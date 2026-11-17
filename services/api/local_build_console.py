"""Desktop-local NEXORA runtime, Android export and device-install controls.

These routes are intentionally local-only. They execute Godot, Android SDK and
ADB on the creator's desktop. Production signing credentials are transient
request data and are never written to project metadata, logs or cloud storage.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.game_assembler.godot import assemble_godot_project
from core.orchestration.jobs import Job, JobRegistry, JobState
from core.project_engine.models import WorldDocument
from core.project_engine.manager import ProjectManager


router = APIRouter(tags=["desktop-build-console"])
_RUNS: dict[str, dict[str, Any]] = {}
_RUNS_LOCK = threading.RLock()
_HISTORY_LOCK = threading.RLock()
PACKAGE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
VERSION_PATTERN = re.compile(r"^[0-9]{1,4}(?:\.[0-9]{1,4}){0,3}(?:[-+][A-Za-z0-9.-]+)?$")
DEVICE_SERIAL_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")
ANDROID_BUILD_TOOLS_VERSION = "35.0.1"
ANDROID_PLATFORM_VERSION = "35"
ANDROID_NDK_VERSION = "28.1.13356709"
ANDROID_CMAKE_VERSION = "3.10.2.4988404"


class AndroidPermissions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    internet: bool = True
    access_network_state: bool = True
    camera: bool = False
    record_audio: bool = False
    access_coarse_location: bool = False
    access_fine_location: bool = False
    vibrate: bool = False
    wake_lock: bool = False


class AndroidSigning(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keystore_path: str = Field(min_length=1, max_length=1024)
    key_alias: str = Field(min_length=1, max_length=128)
    key_password: str = Field(min_length=1, max_length=256)


class AndroidBuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    app_name: str = Field(min_length=1, max_length=64)
    package_id: str = Field(min_length=3, max_length=180)
    version_name: str = Field(default="1.0.0", min_length=1, max_length=32)
    version_code: int = Field(default=1, ge=1, le=2100000000)
    build_type: Literal["debug", "release"] = "debug"
    output_format: Literal["apk", "aab"] = "apk"
    orientation: Literal["landscape", "portrait", "sensor"] = "landscape"
    icon_path: str | None = Field(default=None, max_length=1024)
    min_sdk: int = Field(default=23, ge=23, le=35)
    target_sdk: int = Field(default=35, ge=28, le=36)
    arm64: bool = True
    arm32: bool = False
    permissions: AndroidPermissions = Field(default_factory=AndroidPermissions)
    signing: AndroidSigning | None = None

    @field_validator("package_id")
    @classmethod
    def validate_package_id(cls, value: str) -> str:
        value = value.strip()
        if not PACKAGE_PATTERN.fullmatch(value):
            raise ValueError("Package ID must use reverse-DNS format, e.g. com.studio.mygame.")
        if any(len(segment) > 63 for segment in value.split(".")):
            raise ValueError("Each package ID segment must be 63 characters or fewer.")
        return value

    @field_validator("app_name")
    @classmethod
    def clean_app_name(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(ch) < 32 for ch in value):
            raise ValueError("App name must contain printable characters.")
        return value

    @field_validator("version_name")
    @classmethod
    def validate_version_name(cls, value: str) -> str:
        value = value.strip()
        if not VERSION_PATTERN.fullmatch(value):
            raise ValueError("Version name must be a dotted version such as 1.0.0.")
        return value

    @field_validator("permissions")
    @classmethod
    def require_godot_internet_permission(cls, value: AndroidPermissions) -> AndroidPermissions:
        if not value.internet:
            raise ValueError("Godot Android exports always include INTERNET; this permission cannot be disabled.")
        return value

    @field_validator("target_sdk")
    @classmethod
    def target_not_below_minimum(cls, value: int, info):
        minimum = info.data.get("min_sdk", 23)
        if value < minimum:
            raise ValueError("Target SDK cannot be lower than minimum SDK.")
        return value

    @field_validator("output_format")
    @classmethod
    def validate_aab_mode(cls, value: str, info):
        if value == "aab" and info.data.get("build_type", "debug") == "debug":
            raise ValueError("AAB is a release package. Select Release signing to create an AAB.")
        return value


class RuntimeLaunchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["run", "debug", "profile", "editor"] = "run"


class DeviceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    serial: str = Field(min_length=1, max_length=160)

    @field_validator("serial")
    @classmethod
    def validate_serial(cls, value: str) -> str:
        value = value.strip()
        if not DEVICE_SERIAL_PATTERN.fullmatch(value):
            raise ValueError("Invalid ADB device serial.")
        return value


class WirelessEndpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    host: str
    port: int = Field(ge=1, le=65535)


class WirelessPairRequest(WirelessEndpoint):
    pairing_code: str = Field(pattern=r"^[0-9]{6}$")


def _require_desktop() -> None:
    if os.getenv("PGF_REQUIRE_CLOUD_DEPENDENCIES", "false").lower() == "true":
        raise HTTPException(status_code=404, detail="Desktop build and device controls are not exposed by the hosted API.")


def _find_executable(env_names: tuple[str, ...], candidates: tuple[str, ...]) -> str | None:
    for name in env_names:
        value = os.getenv(name, "").strip()
        if value and Path(value).is_file():
            return str(Path(value).resolve())
    for candidate in candidates:
        found = shutil.which(candidate)
        if found:
            return found
    return None


def _godot() -> str | None:
    return _find_executable(("PGF_GODOT_BIN", "GODOT_BIN"), ("godot", "godot4", "Godot"))


def _adb() -> str | None:
    return _find_executable(("ADB_BIN",), ("adb",))


def _android_sdk() -> Path | None:
    candidates = [
        os.getenv("ANDROID_HOME", ""),
        os.getenv("ANDROID_SDK_ROOT", ""),
        str(Path.home() / "Android" / "Sdk"),
        str(Path.home() / "AppData" / "Local" / "Android" / "Sdk"),
        str(Path.home() / "Library" / "Android" / "sdk"),
    ]
    for raw in candidates:
        if raw:
            path = Path(raw).expanduser()
            if path.is_dir():
                return path.resolve()
    return None


def _java_home() -> Path | None:
    configured = os.getenv("JAVA_HOME", "").strip()
    if configured:
        home = Path(configured).expanduser()
        if home.is_dir() and any((home / "bin" / name).is_file() for name in ("java", "java.exe")):
            return home.resolve()
    executable = shutil.which("java")
    if not executable:
        return None
    resolved = Path(executable).resolve()
    return resolved.parent.parent if resolved.parent.name.casefold() == "bin" else None


def _godot_version(godot: str) -> str:
    result = _run([godot, "--version"], timeout=30)
    text = (result["stdout"] or result["stderr"]).strip()
    match = re.search(r"(\d+\.\d+(?:\.\d+)?\.(?:stable|dev|beta\d*|rc\d*|alpha\d*))", text, re.I)
    if not match:
        raise RuntimeError("Could not identify the Godot editor version. Install matching Android export templates.")
    return match.group(1)


def _godot_template_directory(godot: str) -> Path:
    version = _godot_version(godot)
    if os.name == "nt":
        base = Path(os.getenv("APPDATA") or (Path.home() / "AppData" / "Roaming")) / "Godot" / "export_templates"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "Godot" / "export_templates"
    else:
        base = Path.home() / ".local" / "share" / "godot" / "export_templates"
    return base / version


def _android_template_status(godot: str | None) -> dict[str, Any]:
    if not godot:
        return {"available": False, "version": None, "path": None, "missing": ["Godot editor"]}
    try:
        directory = _godot_template_directory(godot)
    except RuntimeError as exc:
        return {"available": False, "version": None, "path": None, "missing": [str(exc)]}
    required = ("android_debug.apk", "android_release.apk", "android_source.zip")
    missing = [name for name in required if not (directory / name).is_file()]
    return {"available": not missing, "version": directory.name, "path": str(directory), "missing": missing}


def _godot_settings_path(godot: str) -> Path:
    version = _godot_version(godot)
    major_minor = ".".join(version.split(".")[:2])
    if os.name == "nt":
        root = Path(os.getenv("APPDATA") or (Path.home() / "AppData" / "Roaming")) / "Godot"
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support" / "Godot"
    else:
        root = Path.home() / ".config" / "godot"
    return root / f"editor_settings-{major_minor}.tres"


def _set_editor_resource_value(text: str, key: str, value: str) -> str:
    encoded = json.dumps(value, ensure_ascii=False)
    line = f"{key} = {encoded}"
    pattern = re.compile(rf"(?m)^{re.escape(key)}\s*=.*$")
    if pattern.search(text):
        return pattern.sub(lambda _: line, text, count=1)
    resource = re.search(r"(?m)^\[resource\]\s*$", text)
    if not resource:
        text = text.rstrip() + "\n\n[resource]\n"
        resource = re.search(r"(?m)^\[resource\]\s*$", text)
    assert resource is not None
    start = resource.end()
    next_section = re.search(r"(?m)^\[[^\]]+\]\s*$", text[start:])
    end = start + next_section.start() if next_section else len(text)
    block = text[start:end].rstrip()
    updated = (block + "\n" if block else "\n") + line + "\n"
    return text[:start] + updated + text[end:]


def _configure_godot_android(godot: str, env: dict[str, str]) -> dict[str, str]:
    sdk = _android_sdk()
    java_home = _java_home()
    if not sdk:
        raise RuntimeError("Android SDK not found. Set ANDROID_HOME or ANDROID_SDK_ROOT on this desktop.")
    if not (sdk / "platform-tools" / ("adb.exe" if os.name == "nt" else "adb")).is_file():
        raise RuntimeError("Android SDK platform-tools/adb is missing. Install Android SDK Platform-Tools.")
    if not java_home:
        raise RuntimeError("OpenJDK 17 or a compatible JDK was not found. Set JAVA_HOME and ensure java is on PATH.")
    env["ANDROID_HOME"] = str(sdk)
    env["ANDROID_SDK_ROOT"] = str(sdk)
    env["JAVA_HOME"] = str(java_home)
    settings = _godot_settings_path(godot)
    settings.parent.mkdir(parents=True, exist_ok=True)
    original = settings.read_text(encoding="utf-8") if settings.is_file() else (
        '[gd_resource type="EditorSettings" format=3]\n\n[resource]\n'
    )
    original = _set_editor_resource_value(original, "export/android/android_sdk_path", str(sdk))
    original = _set_editor_resource_value(original, "export/android/java_sdk_path", str(java_home))
    temporary = settings.with_suffix(settings.suffix + ".tmp")
    temporary.write_text(original, encoding="utf-8")
    temporary.replace(settings)
    return {"android_sdk": str(sdk), "java_home": str(java_home), "godot_settings": str(settings)}


def _android_sdk_components(sdk: Path | None) -> dict[str, Any]:
    if not sdk:
        return {"available": False, "missing": ["Android SDK root"]}
    candidates = {
        "platform-tools / adb": sdk / "platform-tools" / ("adb.exe" if os.name == "nt" else "adb"),
        f"platforms;android-{ANDROID_PLATFORM_VERSION}": sdk / "platforms" / f"android-{ANDROID_PLATFORM_VERSION}",
        f"build-tools;{ANDROID_BUILD_TOOLS_VERSION} / apksigner": sdk / "build-tools" / ANDROID_BUILD_TOOLS_VERSION / ("apksigner.bat" if os.name == "nt" else "apksigner"),
        f"build-tools;{ANDROID_BUILD_TOOLS_VERSION} / aapt": sdk / "build-tools" / ANDROID_BUILD_TOOLS_VERSION / ("aapt.exe" if os.name == "nt" else "aapt"),
        f"ndk;{ANDROID_NDK_VERSION}": sdk / "ndk" / ANDROID_NDK_VERSION,
        f"cmake;{ANDROID_CMAKE_VERSION}": sdk / "cmake" / ANDROID_CMAKE_VERSION,
        "cmdline-tools;latest / sdkmanager": sdk / "cmdline-tools" / "latest" / "bin" / ("sdkmanager.bat" if os.name == "nt" else "sdkmanager"),
    }
    missing = [label for label, path in candidates.items() if not path.exists()]
    return {"available": not missing, "missing": missing}


def _godot_android_settings_match(godot: str | None, sdk: Path | None, java_home: Path | None) -> bool:
    if not godot or not sdk or not java_home:
        return False
    settings = _godot_settings_path(godot)
    if not settings.is_file():
        return False
    text = settings.read_text(encoding="utf-8", errors="replace")
    sdk_setting = re.search(r'(?m)^export/android/android_sdk_path\s*=\s*(.+)
    sdk = _android_sdk()
    if sdk:
        choices = sorted((sdk / "build-tools").glob(f"*/{name}"), reverse=True)
        choices += sorted((sdk / "build-tools").glob(f"*/{name}.exe"), reverse=True)
        choices += sorted((sdk / "build-tools").glob(f"*/{name}.bat"), reverse=True)
        for item in choices:
            if item.is_file():
                return str(item)
    return shutil.which(name)


def _command(executable: str, *arguments: str) -> list[str]:
    if executable.lower().endswith((".bat", ".cmd")) and os.name == "nt":
        return ["cmd.exe", "/d", "/s", "/c", subprocess.list2cmdline([executable, *arguments])]
    return [executable, *arguments]


def _run(command: list[str], timeout: int = 900, env: dict[str, str] | None = None) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout,
            check=False, env=env, encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Command timed out after {timeout} seconds: {' '.join(command[:3])}") from exc
    output = (completed.stdout or "")[-20000:]
    errors = (completed.stderr or "")[-20000:]
    if completed.returncode != 0:
        raise RuntimeError(
            f"Command failed with exit code {completed.returncode}: {' '.join(command[:4])}\n"
            f"{errors or output}"
        )
    return {"returncode": completed.returncode, "stdout": output, "stderr": errors}


def _ensure_game(manager: ProjectManager, project_id: str) -> Path:
    try:
        definition = manager.load(project_id)
        root = manager.path_for(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found.") from exc
    game = root / "game"
    if not (game / "project.godot").is_file():
        world_file = root / "world.json"
        world = WorldDocument.model_validate_json(world_file.read_text(encoding="utf-8")).model_dump(mode="json") if world_file.is_file() else None
        assemble_godot_project(definition, game, world)
    return game.resolve()


def _png_dimensions(path: Path) -> tuple[int, int]:
    try:
        with path.open("rb") as stream:
            header = stream.read(24)
    except OSError as exc:
        raise HTTPException(status_code=400, detail="Could not read the launcher icon.") from exc
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise HTTPException(status_code=415, detail="Launcher icon must be a PNG image.")
    return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")


def _quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _write_android_preset(project: Path, request: AndroidBuildRequest, output: Path) -> None:
    preset_file = project / "export_presets.cfg"
    original = preset_file.read_text(encoding="utf-8") if preset_file.is_file() else ""
    match = re.search(r"(?m)^\[preset\.2\]\s*$", original)
    prefix = original[:match.start()] if match else original.rstrip() + "\n\n"
    icon_ref = ""
    if request.icon_path:
        source = Path(request.icon_path).expanduser().resolve()
        if not source.is_file():
            raise HTTPException(status_code=400, detail="Launcher icon file does not exist on this desktop.")
        width, height = _png_dimensions(source)
        if width < 192 or height < 192 or width != height:
            raise HTTPException(status_code=400, detail="Launcher icon must be a square PNG at least 192×192 pixels.")
        assets = project / "android_assets"
        assets.mkdir(parents=True, exist_ok=True)
        destination = assets / "launcher-icon.png"
        shutil.copy2(source, destination)
        icon_ref = "res://android_assets/launcher-icon.png"

    orientation = {"landscape": 0, "portrait": 1, "sensor": 6}[request.orientation]
    use_gradle = request.output_format == "aab"
    options = request.permissions.model_dump()
    permission_lines = "\n".join(
        f"permissions/{name}={str(enabled).lower()}"
        for name, enabled in options.items()
    )
    export_path = output.relative_to(project).as_posix()
    preset = f'''[preset.2]
name="Android"
platform="Android"
runnable=true
dedicated_server=false
custom_features=""
export_filter="all_resources"
include_filter=""
exclude_filter=""
export_path={_quote(export_path)}
encryption_include_filters=""
encryption_exclude_filters=""
encrypt_pck=false
encrypt_directory=false

[preset.2.options]
custom_template/debug=""
custom_template/release=""
gradle_build/use_gradle_build={str(use_gradle).lower()}
gradle_build/export_format={1 if request.output_format == "aab" else 0}
gradle_build/min_sdk={_quote(str(request.min_sdk))}
gradle_build/target_sdk={_quote(str(request.target_sdk))}
architectures/armeabi-v7a={str(request.arm32).lower()}
architectures/arm64-v8a={str(request.arm64).lower()}
architectures/x86=false
architectures/x86_64=false
package/unique_name={_quote(request.package_id)}
package/name={_quote(request.app_name)}
package/signed=true
version/code={request.version_code}
version/name={_quote(request.version_name)}
screen/immersive_mode=true
screen/orientation={orientation}
launcher_icons/main_192x192={_quote(icon_ref)}
launcher_icons/adaptive_foreground_432x432={_quote(icon_ref)}
{permission_lines}
keystore/release=""
keystore/release_user=""
keystore/release_password=""
'''
    preset_file.write_text(prefix + preset, encoding="utf-8")


def _debug_signing_environment(env: dict[str, str]) -> None:
    keytool = shutil.which("keytool")
    if not keytool:
        raise RuntimeError("Java keytool is required to prepare the desktop debug signing key.")
    key_path = Path.home() / ".android" / "debug.keystore"
    key_path.parent.mkdir(parents=True, exist_ok=True)
    if not key_path.is_file():
        _run(_command(keytool, "-genkeypair", "-v", "-keystore", str(key_path),
                       "-storepass", "android", "-alias", "androiddebugkey",
                       "-keypass", "android", "-dname", "CN=Android Debug,O=Android,C=US",
                       "-keyalg", "RSA", "-keysize", "2048", "-validity", "10000", "-noprompt"), timeout=120)
    env["GODOT_ANDROID_KEYSTORE_DEBUG_PATH"] = str(key_path)
    env["GODOT_ANDROID_KEYSTORE_DEBUG_USER"] = "androiddebugkey"
    env["GODOT_ANDROID_KEYSTORE_DEBUG_PASSWORD"] = "android"


def _signing_environment(request: AndroidBuildRequest) -> dict[str, str]:
    env = os.environ.copy()
    sdk = _android_sdk()
    if sdk:
        env["ANDROID_HOME"] = str(sdk)
        env["ANDROID_SDK_ROOT"] = str(sdk)
    if request.build_type == "debug":
        _debug_signing_environment(env)
        return env
    if not request.signing:
        raise HTTPException(status_code=422, detail="Release builds require a local keystore, alias and key password.")
    key_path = Path(request.signing.keystore_path).expanduser().resolve()
    if not key_path.is_file():
        raise HTTPException(status_code=400, detail="The selected release keystore does not exist on this desktop.")
    env["GODOT_ANDROID_KEYSTORE_RELEASE_PATH"] = str(key_path)
    env["GODOT_ANDROID_KEYSTORE_RELEASE_USER"] = request.signing.key_alias
    env["GODOT_ANDROID_KEYSTORE_RELEASE_PASSWORD"] = request.signing.key_password
    return env


def _validate_export(project: Path, output: Path, request: AndroidBuildRequest, env: dict[str, str]) -> dict[str, Any]:
    if not output.is_file() or output.stat().st_size < 1024:
        raise RuntimeError("Godot completed without creating a non-empty Android package.")
    if not zipfile.is_zipfile(output):
        raise RuntimeError("The Android export is not a valid ZIP-based APK/AAB package.")
    if request.output_format == "apk":
        with zipfile.ZipFile(output) as archive:
            if "AndroidManifest.xml" not in archive.namelist():
                raise RuntimeError("APK validation failed: AndroidManifest.xml is missing.")
        apksigner = _sdk_tool("apksigner") or shutil.which("apksigner")
        if not apksigner:
            raise RuntimeError("Android build-tools apksigner is required to verify the APK signature.")
        verification = _run(_command(apksigner, "verify", "--verbose", str(output)), timeout=180, env=env)
        aapt = _sdk_tool("aapt") or shutil.which("aapt")
        package_validation = None
        if aapt:
            badging = _run(_command(aapt, "dump", "badging", str(output)), timeout=120, env=env)
            package_validation = next((line.strip() for line in badging["stdout"].splitlines() if line.startswith("package:")), None)
            if package_validation and f"name='{request.package_id}'" not in package_validation:
                raise RuntimeError("APK manifest package ID does not match the Build Console configuration.")
        return {"signature_verified": True, "signature_output": verification["stdout"][-3000:], "package_manifest": package_validation}
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        if "base/manifest/AndroidManifest.xml" not in names or "BundleConfig.pb" not in names:
            raise RuntimeError("AAB validation failed: bundle manifest or BundleConfig.pb is missing.")
    jarsigner = shutil.which("jarsigner")
    if not jarsigner:
        raise RuntimeError("Java jarsigner is required to verify the Android App Bundle signature.")
    verification = _run(_command(jarsigner, "-verify", "-verbose", str(output)), timeout=180, env=env)
    return {"signature_verified": True, "signature_output": verification["stdout"][-3000:], "bundle_structure_verified": True}


def _history_file(project_root: Path) -> Path:
    return project_root / "build-history.json"


def _read_history(project_root: Path) -> list[dict[str, Any]]:
    path = _history_file(project_root)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _write_history(project_root: Path, history: list[dict[str, Any]]) -> None:
    target = _history_file(project_root)
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(history[-100:], indent=2), encoding="utf-8")
    temporary.replace(target)


def _build_android(job_id: str, project_id: str, request: AndroidBuildRequest,
                   manager: ProjectManager, jobs: JobRegistry) -> None:
    try:
        jobs.update(job_id, state=JobState.RUNNING, progress=5, message="Preparing Android build environment")
        godot = _godot()
        if not godot:
            raise RuntimeError("Godot 4 editor executable was not found. Set PGF_GODOT_BIN or add Godot to PATH.")
        if not _android_sdk():
            raise RuntimeError("Android SDK not found. Configure ANDROID_HOME or ANDROID_SDK_ROOT on this desktop.")
        if not shutil.which("java"):
            raise RuntimeError("Java is required for Android export. Install a supported JDK and ensure java is on PATH.")
        if request.output_format == "aab" and request.build_type != "release":
            raise RuntimeError("AAB packages must use Release signing.")
        env = _signing_environment(request)
        project = _ensure_game(manager, project_id)
        build_id = uuid4().hex
        extension = request.output_format
        slug = re.sub(r"[^a-z0-9]+", "-", request.app_name.casefold()).strip("-") or "game"
        output = project / "builds" / "android" / f"{slug}-{request.version_name}-{request.version_code}-{build_id[:8]}.{extension}"
        output.parent.mkdir(parents=True, exist_ok=True)
        _write_android_preset(project, request, output)
        jobs.update(job_id, progress=20, message="Importing and validating the Godot project")
        _run([godot, "--headless", "--path", str(project), "--editor", "--quit"], timeout=900, env=env)
        jobs.update(job_id, progress=45, message=f"Exporting signed Android {extension.upper()} package")
        export_mode = "--export-debug" if request.build_type == "debug" else "--export-release"
        export = _run([godot, "--headless", "--path", str(project), export_mode, "Android", str(output)], timeout=3600, env=env)
        jobs.update(job_id, progress=82, message="Verifying package structure, application ID and signature")
        validation = _validate_export(project, output, request, env)
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        record = {
            "id": build_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "app_name": request.app_name,
            "package_id": request.package_id,
            "version_name": request.version_name,
            "version_code": request.version_code,
            "output_format": request.output_format,
            "build_type": request.build_type,
            "orientation": request.orientation,
            "size": output.stat().st_size,
            "sha256": digest,
            "artifact_path": output.relative_to(manager.path_for(project_id)).as_posix(),
            "signature_verified": validation["signature_verified"],
            "package_validation": validation.get("package_manifest"),
        }
        root = manager.path_for(project_id)
        history = _read_history(root)
        history.insert(0, record)
        _write_history(root, history)
        (output.parent / f"{output.stem}.manifest.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        jobs.update(job_id, state=JobState.COMPLETED, progress=100,
                    message=f"{request.output_format.upper()} exported and signature-verified",
                    result={"build": record, "validation": validation,
                            "godot_export": {"stdout": export["stdout"][-6000:], "stderr": export["stderr"][-6000:]}})
    except Exception as exc:
        jobs.update(job_id, state=JobState.FAILED, progress=100, message="Android build failed", error=str(exc)[-12000:])


def _runtime_test(job_id: str, project_id: str, manager: ProjectManager, jobs: JobRegistry) -> None:
    try:
        godot = _godot()
        if not godot:
            raise RuntimeError("Godot 4 was not found on this desktop.")
        project = _ensure_game(manager, project_id)
        root = manager.path_for(project_id)
        log_path = root / "runtime-test.log"
        jobs.update(job_id, state=JobState.RUNNING, progress=10, message="Checking GDScript and importing project resources")
        editor = _run([godot, "--headless", "--path", str(project), "--editor", "--quit"], timeout=900)
        jobs.update(job_id, progress=45, message="Running the generated game headlessly and collecting FPS samples")
        runtime = _run([godot, "--headless", "--path", str(project), "--quit-after", "300",
                        "--print-fps", "--log-file", str(log_path)], timeout=300)
        combined = "\n".join([editor["stdout"], editor["stderr"], runtime["stdout"], runtime["stderr"],
                              log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""])
        errors = [line.strip() for line in combined.splitlines()
                  if re.search(r"(SCRIPT ERROR:|Parse Error|ERROR:|FATAL|Segmentation fault)", line, re.I)]
        fps_samples: list[float] = []
        for line in combined.splitlines():
            if "fps" in line.casefold():
                values = re.findall(r"\d+(?:\.\d+)?", line)
                if values:
                    fps_samples.append(float(values[-1]))
        metrics = {
            "fps_sample_count": len(fps_samples),
            "average_fps": round(sum(fps_samples) / len(fps_samples), 2) if fps_samples else None,
            "minimum_fps": min(fps_samples) if fps_samples else None,
            "maximum_fps": max(fps_samples) if fps_samples else None,
            "test_frames": 300,
            "note": "Headless FPS is a regression signal, not a substitute for GPU profiling on the target desktop or Android device.",
        }
        report = {"passed": not errors, "project_id": project_id, "metrics": metrics,
                  "errors": errors[:100], "log_path": str(log_path)}
        if errors:
            raise RuntimeError("Runtime validation reported errors: " + "\n".join(errors[:20]))
        jobs.update(job_id, state=JobState.COMPLETED, progress=100, message="Godot import and runtime smoke test passed", result=report)
    except Exception as exc:
        jobs.update(job_id, state=JobState.FAILED, progress=100, message="Runtime validation failed", error=str(exc)[-12000:])


def _tail(path: Path, max_bytes: int = 24000) -> str:
    if not path.is_file():
        return ""
    try:
        with path.open("rb") as stream:
            stream.seek(max(0, path.stat().st_size - max_bytes))
            return stream.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _adb_devices() -> list[dict[str, str]]:
    adb = _adb()
    if not adb:
        raise HTTPException(status_code=503, detail="Android platform-tools ADB was not found on this desktop.")
    result = _run(_command(adb, "devices", "-l"), timeout=30)
    devices: list[dict[str, str]] = []
    for line in result["stdout"].splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        serial, state = parts[0], parts[1]
        metadata = {}
        for item in parts[2:]:
            if ":" in item:
                key, value = item.split(":", 1)
                metadata[key] = value
        devices.append({"serial": serial, "state": state,
                        "model": metadata.get("model", ""),
                        "product": metadata.get("product", ""),
                        "transport_id": metadata.get("transport_id", "")})
    return devices


def _ready_device(serial: str) -> tuple[str, str]:
    devices = _adb_devices()
    selected = next((item for item in devices if item["serial"] == serial), None)
    if not selected:
        raise HTTPException(status_code=404, detail="Selected Android device is not connected to this desktop.")
    if selected["state"] != "device":
        raise HTTPException(status_code=409, detail=f"ADB device state is {selected['state']}; authorize USB debugging on the phone.")
    adb = _adb()
    assert adb
    return adb, serial


def register_local_build_routes(app, manager: ProjectManager, jobs: JobRegistry) -> None:
    @app.get("/api/local/build-tools")
    def build_tools():
        _require_desktop()
        godot = _godot()
        adb = _adb()
        sdk = _android_sdk()
        java = shutil.which("java")
        apksigner = _sdk_tool("apksigner") or shutil.which("apksigner")
        aapt = _sdk_tool("aapt") or shutil.which("aapt")
        return {
            "godot": {"available": bool(godot), "path": godot},
            "java": {"available": bool(java), "path": java},
            "android_sdk": {"available": bool(sdk), "path": str(sdk) if sdk else None},
            "adb": {"available": bool(adb), "path": adb},
            "apksigner": {"available": bool(apksigner), "path": apksigner},
            "aapt": {"available": bool(aapt), "path": aapt},
            "android_export_templates": bool(Path.home().joinpath(".local/share/godot/export_templates").is_dir()
                                             or Path.home().joinpath("AppData/Roaming/Godot/export_templates").is_dir()),
            "desktop_local": True,
        }

    @app.post("/api/projects/{project_id}/runtime-test", status_code=202)
    def start_runtime_test(project_id: str, background: BackgroundTasks):
        _require_desktop()
        _ensure_game(manager, project_id)
        job = jobs.add(Job.create(project_id))
        background.add_task(_runtime_test, job.id, project_id, manager, jobs)
        return job.as_dict()

    @app.post("/api/projects/{project_id}/runs", status_code=202)
    def start_game_run(project_id: str, request: RuntimeLaunchRequest):
        _require_desktop()
        godot = _godot()
        if not godot:
            raise HTTPException(status_code=503, detail="Godot 4 was not found on this desktop.")
        project = _ensure_game(manager, project_id)
        run_id = uuid4().hex
        log_path = manager.path_for(project_id) / f"runtime-{run_id}.log"
        command = [godot, "--path", str(project)]
        if request.mode == "editor":
            command.append("--editor")
        elif request.mode == "debug":
            command.extend(["--debug", "--verbose"])
        elif request.mode == "profile":
            command.extend(["--profiling", "--print-fps", "--gpu-profile", "--verbose"])
        with log_path.open("w", encoding="utf-8") as log:
            try:
                process = subprocess.Popen(
                    command, cwd=str(project), stdout=log, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    creationflags=(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0),
                    start_new_session=(os.name != "nt"),
                )
            except OSError as exc:
                raise HTTPException(status_code=503, detail=f"Could not launch Godot: {exc}") from exc
        with _RUNS_LOCK:
            _RUNS[run_id] = {"project_id": project_id, "process": process, "log_path": log_path, "mode": request.mode}
        return {"run_id": run_id, "process_id": process.pid, "mode": request.mode, "state": "running"}

    @app.get("/api/projects/{project_id}/runs/{run_id}")
    def read_game_run(project_id: str, run_id: str):
        _require_desktop()
        with _RUNS_LOCK:
            run = _RUNS.get(run_id)
        if not run or run["project_id"] != project_id:
            raise HTTPException(status_code=404, detail="Runtime session not found.")
        process = run["process"]
        return {"run_id": run_id, "mode": run["mode"], "running": process.poll() is None,
                "exit_code": process.poll(), "log": _tail(run["log_path"])}

    @app.post("/api/projects/{project_id}/runs/{run_id}/stop")
    def stop_game_run(project_id: str, run_id: str):
        _require_desktop()
        with _RUNS_LOCK:
            run = _RUNS.get(run_id)
        if not run or run["project_id"] != project_id:
            raise HTTPException(status_code=404, detail="Runtime session not found.")
        process = run["process"]
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
        return {"run_id": run_id, "running": False, "exit_code": process.poll()}

    @app.get("/api/projects/{project_id}/builds")
    def list_android_builds(project_id: str):
        _require_desktop()
        try:
            root = manager.path_for(project_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid project ID.") from exc
        if not (root / "pgf.json").is_file():
            raise HTTPException(status_code=404, detail="Project not found.")
        return {"builds": _read_history(root)}

    @app.post("/api/projects/{project_id}/android-build", status_code=202)
    def create_android_build(project_id: str, request: AndroidBuildRequest, background: BackgroundTasks):
        _require_desktop()
        _ensure_game(manager, project_id)
        job = jobs.add(Job.create(project_id))
        background.add_task(_build_android, job.id, project_id, request, manager, jobs)
        return job.as_dict()

    @app.get("/api/projects/{project_id}/builds/{build_id}/download")
    def download_android_build(project_id: str, build_id: str):
        _require_desktop()
        root = manager.path_for(project_id)
        record = next((item for item in _read_history(root) if item.get("id") == build_id), None)
        if not record:
            raise HTTPException(status_code=404, detail="Build artifact not found.")
        path = (root / str(record.get("artifact_path") or "")).resolve()
        if root.resolve() not in path.parents or not path.is_file():
            raise HTTPException(status_code=404, detail="Build artifact is unavailable.")
        return FileResponse(path, filename=path.name, media_type="application/octet-stream")

    @app.get("/api/local/android/devices")
    def list_android_devices():
        _require_desktop()
        return {"devices": _adb_devices()}

    @app.post("/api/local/android/connect")
    def connect_wireless_device(request: WirelessEndpoint):
        _require_desktop()
        try:
            ipaddress.ip_address(request.host)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Wireless ADB host must be an IP address.") from exc
        adb = _adb()
        if not adb:
            raise HTTPException(status_code=503, detail="ADB was not found on this desktop.")
        return _run(_command(adb, "connect", f"{request.host}:{request.port}"), timeout=30)

    @app.post("/api/local/android/pair")
    def pair_wireless_device(request: WirelessPairRequest):
        _require_desktop()
        try:
            ipaddress.ip_address(request.host)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Wireless pairing host must be an IP address.") from exc
        adb = _adb()
        if not adb:
            raise HTTPException(status_code=503, detail="ADB was not found on this desktop.")
        return _run(_command(adb, "pair", f"{request.host}:{request.port}", request.pairing_code), timeout=45)

    @app.post("/api/projects/{project_id}/builds/{build_id}/install")
    def install_android_build(project_id: str, build_id: str, request: DeviceSelection):
        _require_desktop()
        root = manager.path_for(project_id)
        record = next((item for item in _read_history(root) if item.get("id") == build_id), None)
        if not record:
            raise HTTPException(status_code=404, detail="Build artifact not found.")
        if record.get("output_format") != "apk":
            raise HTTPException(status_code=409, detail="Android App Bundles cannot be installed directly. Build an APK for device testing.")
        path = (root / str(record.get("artifact_path") or "")).resolve()
        if root.resolve() not in path.parents or not path.is_file():
            raise HTTPException(status_code=404, detail="APK artifact is unavailable.")
        adb, serial = _ready_device(request.serial)
        result = _run(_command(adb, "-s", serial, "install", "-r", str(path)), timeout=300)
        return {"installed": True, "serial": serial, "package_id": record["package_id"], "output": result["stdout"]}

    @app.post("/api/projects/{project_id}/builds/{build_id}/launch")
    def launch_android_build(project_id: str, build_id: str, request: DeviceSelection):
        _require_desktop()
        root = manager.path_for(project_id)
        record = next((item for item in _read_history(root) if item.get("id") == build_id), None)
        if not record:
            raise HTTPException(status_code=404, detail="Build artifact not found.")
        adb, serial = _ready_device(request.serial)
        result = _run(_command(adb, "-s", serial, "shell", "monkey", "-p", str(record["package_id"]), "1"), timeout=60)
        return {"launched": True, "serial": serial, "package_id": record["package_id"], "output": result["stdout"]}

    @app.get("/api/local/android/logs")
    def android_logcat(serial: str, lines: int = 500):
        _require_desktop()
        if not DEVICE_SERIAL_PATTERN.fullmatch(serial):
            raise HTTPException(status_code=422, detail="Invalid ADB device serial.")
        if not 50 <= lines <= 2000:
            raise HTTPException(status_code=422, detail="Log line count must be between 50 and 2000.")
        adb, selected = _ready_device(serial)
        result = _run(_command(adb, "-s", selected, "logcat", "-d", "-t", str(lines)), timeout=60)
        return {"serial": selected, "lines": result["stdout"].splitlines()[-lines:]}
, text)
    java_setting = re.search(r'(?m)^export/android/java_sdk_path\s*=\s*(.+)
    sdk = _android_sdk()
    if sdk:
        choices = sorted((sdk / "build-tools").glob(f"*/{name}"), reverse=True)
        choices += sorted((sdk / "build-tools").glob(f"*/{name}.bat"), reverse=True)
        for item in choices:
            if item.is_file():
                return str(item)
    return shutil.which(name)


def _command(executable: str, *arguments: str) -> list[str]:
    if executable.lower().endswith((".bat", ".cmd")) and os.name == "nt":
        return ["cmd.exe", "/d", "/s", "/c", subprocess.list2cmdline([executable, *arguments])]
    return [executable, *arguments]


def _run(command: list[str], timeout: int = 900, env: dict[str, str] | None = None) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout,
            check=False, env=env, encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Command timed out after {timeout} seconds: {' '.join(command[:3])}") from exc
    output = (completed.stdout or "")[-20000:]
    errors = (completed.stderr or "")[-20000:]
    if completed.returncode != 0:
        raise RuntimeError(
            f"Command failed with exit code {completed.returncode}: {' '.join(command[:4])}\n"
            f"{errors or output}"
        )
    return {"returncode": completed.returncode, "stdout": output, "stderr": errors}


def _ensure_game(manager: ProjectManager, project_id: str) -> Path:
    try:
        definition = manager.load(project_id)
        root = manager.path_for(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found.") from exc
    game = root / "game"
    if not (game / "project.godot").is_file():
        world_file = root / "world.json"
        world = WorldDocument.model_validate_json(world_file.read_text(encoding="utf-8")).model_dump(mode="json") if world_file.is_file() else None
        assemble_godot_project(definition, game, world)
    return game.resolve()


def _png_dimensions(path: Path) -> tuple[int, int]:
    try:
        with path.open("rb") as stream:
            header = stream.read(24)
    except OSError as exc:
        raise HTTPException(status_code=400, detail="Could not read the launcher icon.") from exc
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise HTTPException(status_code=415, detail="Launcher icon must be a PNG image.")
    return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")


def _quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _write_android_preset(project: Path, request: AndroidBuildRequest, output: Path) -> None:
    preset_file = project / "export_presets.cfg"
    original = preset_file.read_text(encoding="utf-8") if preset_file.is_file() else ""
    match = re.search(r"(?m)^\[preset\.2\]\s*$", original)
    prefix = original[:match.start()] if match else original.rstrip() + "\n\n"
    icon_ref = ""
    if request.icon_path:
        source = Path(request.icon_path).expanduser().resolve()
        if not source.is_file():
            raise HTTPException(status_code=400, detail="Launcher icon file does not exist on this desktop.")
        width, height = _png_dimensions(source)
        if width < 192 or height < 192 or width != height:
            raise HTTPException(status_code=400, detail="Launcher icon must be a square PNG at least 192×192 pixels.")
        assets = project / "android_assets"
        assets.mkdir(parents=True, exist_ok=True)
        destination = assets / "launcher-icon.png"
        shutil.copy2(source, destination)
        icon_ref = "res://android_assets/launcher-icon.png"

    orientation = {"landscape": 0, "portrait": 1, "sensor": 6}[request.orientation]
    use_gradle = request.output_format == "aab"
    options = request.permissions.model_dump()
    permission_lines = "\n".join(
        f"permissions/{name}={str(enabled).lower()}"
        for name, enabled in options.items()
    )
    export_path = output.relative_to(project).as_posix()
    preset = f'''[preset.2]
name="Android"
platform="Android"
runnable=true
dedicated_server=false
custom_features=""
export_filter="all_resources"
include_filter=""
exclude_filter=""
export_path={_quote(export_path)}
encryption_include_filters=""
encryption_exclude_filters=""
encrypt_pck=false
encrypt_directory=false

[preset.2.options]
custom_template/debug=""
custom_template/release=""
gradle_build/use_gradle_build={str(use_gradle).lower()}
gradle_build/export_format={1 if request.output_format == "aab" else 0}
gradle_build/min_sdk={_quote(str(request.min_sdk))}
gradle_build/target_sdk={_quote(str(request.target_sdk))}
architectures/armeabi-v7a={str(request.arm32).lower()}
architectures/arm64-v8a={str(request.arm64).lower()}
architectures/x86=false
architectures/x86_64=false
package/unique_name={_quote(request.package_id)}
package/name={_quote(request.app_name)}
package/signed=true
version/code={request.version_code}
version/name={_quote(request.version_name)}
screen/immersive_mode=true
screen/orientation={orientation}
launcher_icons/main_192x192={_quote(icon_ref)}
launcher_icons/adaptive_foreground_432x432={_quote(icon_ref)}
{permission_lines}
keystore/release=""
keystore/release_user=""
keystore/release_password=""
'''
    preset_file.write_text(prefix + preset, encoding="utf-8")


def _debug_signing_environment(env: dict[str, str]) -> None:
    keytool = shutil.which("keytool")
    if not keytool:
        raise RuntimeError("Java keytool is required to prepare the desktop debug signing key.")
    key_path = Path.home() / ".android" / "debug.keystore"
    key_path.parent.mkdir(parents=True, exist_ok=True)
    if not key_path.is_file():
        _run(_command(keytool, "-genkeypair", "-v", "-keystore", str(key_path),
                       "-storepass", "android", "-alias", "androiddebugkey",
                       "-keypass", "android", "-dname", "CN=Android Debug,O=Android,C=US",
                       "-keyalg", "RSA", "-keysize", "2048", "-validity", "10000", "-noprompt"), timeout=120)
    env["GODOT_ANDROID_KEYSTORE_DEBUG_PATH"] = str(key_path)
    env["GODOT_ANDROID_KEYSTORE_DEBUG_USER"] = "androiddebugkey"
    env["GODOT_ANDROID_KEYSTORE_DEBUG_PASSWORD"] = "android"


def _signing_environment(request: AndroidBuildRequest) -> dict[str, str]:
    env = os.environ.copy()
    sdk = _android_sdk()
    if sdk:
        env["ANDROID_HOME"] = str(sdk)
        env["ANDROID_SDK_ROOT"] = str(sdk)
    if request.build_type == "debug":
        _debug_signing_environment(env)
        return env
    if not request.signing:
        raise HTTPException(status_code=422, detail="Release builds require a local keystore, alias and key password.")
    key_path = Path(request.signing.keystore_path).expanduser().resolve()
    if not key_path.is_file():
        raise HTTPException(status_code=400, detail="The selected release keystore does not exist on this desktop.")
    env["GODOT_ANDROID_KEYSTORE_RELEASE_PATH"] = str(key_path)
    env["GODOT_ANDROID_KEYSTORE_RELEASE_USER"] = request.signing.key_alias
    env["GODOT_ANDROID_KEYSTORE_RELEASE_PASSWORD"] = request.signing.key_password
    return env


def _validate_export(project: Path, output: Path, request: AndroidBuildRequest, env: dict[str, str]) -> dict[str, Any]:
    if not output.is_file() or output.stat().st_size < 1024:
        raise RuntimeError("Godot completed without creating a non-empty Android package.")
    if not zipfile.is_zipfile(output):
        raise RuntimeError("The Android export is not a valid ZIP-based APK/AAB package.")
    if request.output_format == "apk":
        with zipfile.ZipFile(output) as archive:
            if "AndroidManifest.xml" not in archive.namelist():
                raise RuntimeError("APK validation failed: AndroidManifest.xml is missing.")
        apksigner = _sdk_tool("apksigner") or shutil.which("apksigner")
        if not apksigner:
            raise RuntimeError("Android build-tools apksigner is required to verify the APK signature.")
        verification = _run(_command(apksigner, "verify", "--verbose", str(output)), timeout=180, env=env)
        aapt = _sdk_tool("aapt") or shutil.which("aapt")
        package_validation = None
        if aapt:
            badging = _run(_command(aapt, "dump", "badging", str(output)), timeout=120, env=env)
            package_validation = next((line.strip() for line in badging["stdout"].splitlines() if line.startswith("package:")), None)
            if package_validation and f"name='{request.package_id}'" not in package_validation:
                raise RuntimeError("APK manifest package ID does not match the Build Console configuration.")
        return {"signature_verified": True, "signature_output": verification["stdout"][-3000:], "package_manifest": package_validation}
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        if "base/manifest/AndroidManifest.xml" not in names or "BundleConfig.pb" not in names:
            raise RuntimeError("AAB validation failed: bundle manifest or BundleConfig.pb is missing.")
    jarsigner = shutil.which("jarsigner")
    if not jarsigner:
        raise RuntimeError("Java jarsigner is required to verify the Android App Bundle signature.")
    verification = _run(_command(jarsigner, "-verify", "-verbose", str(output)), timeout=180, env=env)
    return {"signature_verified": True, "signature_output": verification["stdout"][-3000:], "bundle_structure_verified": True}


def _history_file(project_root: Path) -> Path:
    return project_root / "build-history.json"


def _read_history(project_root: Path) -> list[dict[str, Any]]:
    path = _history_file(project_root)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _write_history(project_root: Path, history: list[dict[str, Any]]) -> None:
    target = _history_file(project_root)
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(history[-100:], indent=2), encoding="utf-8")
    temporary.replace(target)


def _build_android(job_id: str, project_id: str, request: AndroidBuildRequest,
                   manager: ProjectManager, jobs: JobRegistry) -> None:
    try:
        jobs.update(job_id, state=JobState.RUNNING, progress=5, message="Preparing Android build environment")
        godot = _godot()
        if not godot:
            raise RuntimeError("Godot 4 editor executable was not found. Set PGF_GODOT_BIN or add Godot to PATH.")
        if not _android_sdk():
            raise RuntimeError("Android SDK not found. Configure ANDROID_HOME or ANDROID_SDK_ROOT on this desktop.")
        if not shutil.which("java"):
            raise RuntimeError("Java is required for Android export. Install a supported JDK and ensure java is on PATH.")
        if request.output_format == "aab" and request.build_type != "release":
            raise RuntimeError("AAB packages must use Release signing.")
        env = _signing_environment(request)
        project = _ensure_game(manager, project_id)
        build_id = uuid4().hex
        extension = request.output_format
        slug = re.sub(r"[^a-z0-9]+", "-", request.app_name.casefold()).strip("-") or "game"
        output = project / "builds" / "android" / f"{slug}-{request.version_name}-{request.version_code}-{build_id[:8]}.{extension}"
        output.parent.mkdir(parents=True, exist_ok=True)
        _write_android_preset(project, request, output)
        jobs.update(job_id, progress=20, message="Importing and validating the Godot project")
        _run([godot, "--headless", "--path", str(project), "--editor", "--quit"], timeout=900, env=env)
        jobs.update(job_id, progress=45, message=f"Exporting signed Android {extension.upper()} package")
        export_mode = "--export-debug" if request.build_type == "debug" else "--export-release"
        export = _run([godot, "--headless", "--path", str(project), export_mode, "Android", str(output)], timeout=3600, env=env)
        jobs.update(job_id, progress=82, message="Verifying package structure, application ID and signature")
        validation = _validate_export(project, output, request, env)
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        record = {
            "id": build_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "app_name": request.app_name,
            "package_id": request.package_id,
            "version_name": request.version_name,
            "version_code": request.version_code,
            "output_format": request.output_format,
            "build_type": request.build_type,
            "orientation": request.orientation,
            "size": output.stat().st_size,
            "sha256": digest,
            "artifact_path": output.relative_to(manager.path_for(project_id)).as_posix(),
            "signature_verified": validation["signature_verified"],
            "package_validation": validation.get("package_manifest"),
        }
        root = manager.path_for(project_id)
        history = _read_history(root)
        history.insert(0, record)
        _write_history(root, history)
        (output.parent / f"{output.stem}.manifest.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        jobs.update(job_id, state=JobState.COMPLETED, progress=100,
                    message=f"{request.output_format.upper()} exported and signature-verified",
                    result={"build": record, "validation": validation,
                            "godot_export": {"stdout": export["stdout"][-6000:], "stderr": export["stderr"][-6000:]}})
    except Exception as exc:
        jobs.update(job_id, state=JobState.FAILED, progress=100, message="Android build failed", error=str(exc)[-12000:])


def _runtime_test(job_id: str, project_id: str, manager: ProjectManager, jobs: JobRegistry) -> None:
    try:
        godot = _godot()
        if not godot:
            raise RuntimeError("Godot 4 was not found on this desktop.")
        project = _ensure_game(manager, project_id)
        root = manager.path_for(project_id)
        log_path = root / "runtime-test.log"
        jobs.update(job_id, state=JobState.RUNNING, progress=10, message="Checking GDScript and importing project resources")
        editor = _run([godot, "--headless", "--path", str(project), "--editor", "--quit"], timeout=900)
        jobs.update(job_id, progress=45, message="Running the generated game headlessly and collecting FPS samples")
        runtime = _run([godot, "--headless", "--path", str(project), "--quit-after", "300",
                        "--print-fps", "--log-file", str(log_path)], timeout=300)
        combined = "\n".join([editor["stdout"], editor["stderr"], runtime["stdout"], runtime["stderr"],
                              log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""])
        errors = [line.strip() for line in combined.splitlines()
                  if re.search(r"(SCRIPT ERROR:|Parse Error|ERROR:|FATAL|Segmentation fault)", line, re.I)]
        fps_samples: list[float] = []
        for line in combined.splitlines():
            if "fps" in line.casefold():
                values = re.findall(r"\d+(?:\.\d+)?", line)
                if values:
                    fps_samples.append(float(values[-1]))
        metrics = {
            "fps_sample_count": len(fps_samples),
            "average_fps": round(sum(fps_samples) / len(fps_samples), 2) if fps_samples else None,
            "minimum_fps": min(fps_samples) if fps_samples else None,
            "maximum_fps": max(fps_samples) if fps_samples else None,
            "test_frames": 300,
            "note": "Headless FPS is a regression signal, not a substitute for GPU profiling on the target desktop or Android device.",
        }
        report = {"passed": not errors, "project_id": project_id, "metrics": metrics,
                  "errors": errors[:100], "log_path": str(log_path)}
        if errors:
            raise RuntimeError("Runtime validation reported errors: " + "\n".join(errors[:20]))
        jobs.update(job_id, state=JobState.COMPLETED, progress=100, message="Godot import and runtime smoke test passed", result=report)
    except Exception as exc:
        jobs.update(job_id, state=JobState.FAILED, progress=100, message="Runtime validation failed", error=str(exc)[-12000:])


def _tail(path: Path, max_bytes: int = 24000) -> str:
    if not path.is_file():
        return ""
    try:
        with path.open("rb") as stream:
            stream.seek(max(0, path.stat().st_size - max_bytes))
            return stream.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _adb_devices() -> list[dict[str, str]]:
    adb = _adb()
    if not adb:
        raise HTTPException(status_code=503, detail="Android platform-tools ADB was not found on this desktop.")
    result = _run(_command(adb, "devices", "-l"), timeout=30)
    devices: list[dict[str, str]] = []
    for line in result["stdout"].splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        serial, state = parts[0], parts[1]
        metadata = {}
        for item in parts[2:]:
            if ":" in item:
                key, value = item.split(":", 1)
                metadata[key] = value
        devices.append({"serial": serial, "state": state,
                        "model": metadata.get("model", ""),
                        "product": metadata.get("product", ""),
                        "transport_id": metadata.get("transport_id", "")})
    return devices


def _ready_device(serial: str) -> tuple[str, str]:
    devices = _adb_devices()
    selected = next((item for item in devices if item["serial"] == serial), None)
    if not selected:
        raise HTTPException(status_code=404, detail="Selected Android device is not connected to this desktop.")
    if selected["state"] != "device":
        raise HTTPException(status_code=409, detail=f"ADB device state is {selected['state']}; authorize USB debugging on the phone.")
    adb = _adb()
    assert adb
    return adb, serial


def register_local_build_routes(app, manager: ProjectManager, jobs: JobRegistry) -> None:
    @app.get("/api/local/build-tools")
    def build_tools():
        _require_desktop()
        godot = _godot()
        adb = _adb()
        sdk = _android_sdk()
        java = shutil.which("java")
        apksigner = _sdk_tool("apksigner") or shutil.which("apksigner")
        aapt = _sdk_tool("aapt") or shutil.which("aapt")
        return {
            "godot": {"available": bool(godot), "path": godot},
            "java": {"available": bool(java), "path": java},
            "android_sdk": {"available": bool(sdk), "path": str(sdk) if sdk else None},
            "adb": {"available": bool(adb), "path": adb},
            "apksigner": {"available": bool(apksigner), "path": apksigner},
            "aapt": {"available": bool(aapt), "path": aapt},
            "android_export_templates": bool(Path.home().joinpath(".local/share/godot/export_templates").is_dir()
                                             or Path.home().joinpath("AppData/Roaming/Godot/export_templates").is_dir()),
            "desktop_local": True,
        }

    @app.post("/api/projects/{project_id}/runtime-test", status_code=202)
    def start_runtime_test(project_id: str, background: BackgroundTasks):
        _require_desktop()
        _ensure_game(manager, project_id)
        job = jobs.add(Job.create(project_id))
        background.add_task(_runtime_test, job.id, project_id, manager, jobs)
        return job.as_dict()

    @app.post("/api/projects/{project_id}/runs", status_code=202)
    def start_game_run(project_id: str, request: RuntimeLaunchRequest):
        _require_desktop()
        godot = _godot()
        if not godot:
            raise HTTPException(status_code=503, detail="Godot 4 was not found on this desktop.")
        project = _ensure_game(manager, project_id)
        run_id = uuid4().hex
        log_path = manager.path_for(project_id) / f"runtime-{run_id}.log"
        command = [godot, "--path", str(project)]
        if request.mode == "editor":
            command.append("--editor")
        elif request.mode == "debug":
            command.extend(["--debug", "--verbose"])
        elif request.mode == "profile":
            command.extend(["--profiling", "--print-fps", "--gpu-profile", "--verbose"])
        with log_path.open("w", encoding="utf-8") as log:
            try:
                process = subprocess.Popen(
                    command, cwd=str(project), stdout=log, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    creationflags=(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0),
                    start_new_session=(os.name != "nt"),
                )
            except OSError as exc:
                raise HTTPException(status_code=503, detail=f"Could not launch Godot: {exc}") from exc
        with _RUNS_LOCK:
            _RUNS[run_id] = {"project_id": project_id, "process": process, "log_path": log_path, "mode": request.mode}
        return {"run_id": run_id, "process_id": process.pid, "mode": request.mode, "state": "running"}

    @app.get("/api/projects/{project_id}/runs/{run_id}")
    def read_game_run(project_id: str, run_id: str):
        _require_desktop()
        with _RUNS_LOCK:
            run = _RUNS.get(run_id)
        if not run or run["project_id"] != project_id:
            raise HTTPException(status_code=404, detail="Runtime session not found.")
        process = run["process"]
        return {"run_id": run_id, "mode": run["mode"], "running": process.poll() is None,
                "exit_code": process.poll(), "log": _tail(run["log_path"])}

    @app.post("/api/projects/{project_id}/runs/{run_id}/stop")
    def stop_game_run(project_id: str, run_id: str):
        _require_desktop()
        with _RUNS_LOCK:
            run = _RUNS.get(run_id)
        if not run or run["project_id"] != project_id:
            raise HTTPException(status_code=404, detail="Runtime session not found.")
        process = run["process"]
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
        return {"run_id": run_id, "running": False, "exit_code": process.poll()}

    @app.get("/api/projects/{project_id}/builds")
    def list_android_builds(project_id: str):
        _require_desktop()
        try:
            root = manager.path_for(project_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid project ID.") from exc
        if not (root / "pgf.json").is_file():
            raise HTTPException(status_code=404, detail="Project not found.")
        return {"builds": _read_history(root)}

    @app.post("/api/projects/{project_id}/android-build", status_code=202)
    def create_android_build(project_id: str, request: AndroidBuildRequest, background: BackgroundTasks):
        _require_desktop()
        _ensure_game(manager, project_id)
        job = jobs.add(Job.create(project_id))
        background.add_task(_build_android, job.id, project_id, request, manager, jobs)
        return job.as_dict()

    @app.get("/api/projects/{project_id}/builds/{build_id}/download")
    def download_android_build(project_id: str, build_id: str):
        _require_desktop()
        root = manager.path_for(project_id)
        record = next((item for item in _read_history(root) if item.get("id") == build_id), None)
        if not record:
            raise HTTPException(status_code=404, detail="Build artifact not found.")
        path = (root / str(record.get("artifact_path") or "")).resolve()
        if root.resolve() not in path.parents or not path.is_file():
            raise HTTPException(status_code=404, detail="Build artifact is unavailable.")
        return FileResponse(path, filename=path.name, media_type="application/octet-stream")

    @app.get("/api/local/android/devices")
    def list_android_devices():
        _require_desktop()
        return {"devices": _adb_devices()}

    @app.post("/api/local/android/connect")
    def connect_wireless_device(request: WirelessEndpoint):
        _require_desktop()
        try:
            ipaddress.ip_address(request.host)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Wireless ADB host must be an IP address.") from exc
        adb = _adb()
        if not adb:
            raise HTTPException(status_code=503, detail="ADB was not found on this desktop.")
        return _run(_command(adb, "connect", f"{request.host}:{request.port}"), timeout=30)

    @app.post("/api/local/android/pair")
    def pair_wireless_device(request: WirelessPairRequest):
        _require_desktop()
        try:
            ipaddress.ip_address(request.host)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Wireless pairing host must be an IP address.") from exc
        adb = _adb()
        if not adb:
            raise HTTPException(status_code=503, detail="ADB was not found on this desktop.")
        return _run(_command(adb, "pair", f"{request.host}:{request.port}", request.pairing_code), timeout=45)

    @app.post("/api/projects/{project_id}/builds/{build_id}/install")
    def install_android_build(project_id: str, build_id: str, request: DeviceSelection):
        _require_desktop()
        root = manager.path_for(project_id)
        record = next((item for item in _read_history(root) if item.get("id") == build_id), None)
        if not record:
            raise HTTPException(status_code=404, detail="Build artifact not found.")
        if record.get("output_format") != "apk":
            raise HTTPException(status_code=409, detail="Android App Bundles cannot be installed directly. Build an APK for device testing.")
        path = (root / str(record.get("artifact_path") or "")).resolve()
        if root.resolve() not in path.parents or not path.is_file():
            raise HTTPException(status_code=404, detail="APK artifact is unavailable.")
        adb, serial = _ready_device(request.serial)
        result = _run(_command(adb, "-s", serial, "install", "-r", str(path)), timeout=300)
        return {"installed": True, "serial": serial, "package_id": record["package_id"], "output": result["stdout"]}

    @app.post("/api/projects/{project_id}/builds/{build_id}/launch")
    def launch_android_build(project_id: str, build_id: str, request: DeviceSelection):
        _require_desktop()
        root = manager.path_for(project_id)
        record = next((item for item in _read_history(root) if item.get("id") == build_id), None)
        if not record:
            raise HTTPException(status_code=404, detail="Build artifact not found.")
        adb, serial = _ready_device(request.serial)
        result = _run(_command(adb, "-s", serial, "shell", "monkey", "-p", str(record["package_id"]), "1"), timeout=60)
        return {"launched": True, "serial": serial, "package_id": record["package_id"], "output": result["stdout"]}

    @app.get("/api/local/android/logs")
    def android_logcat(serial: str, lines: int = 500):
        _require_desktop()
        if not DEVICE_SERIAL_PATTERN.fullmatch(serial):
            raise HTTPException(status_code=422, detail="Invalid ADB device serial.")
        if not 50 <= lines <= 2000:
            raise HTTPException(status_code=422, detail="Log line count must be between 50 and 2000.")
        adb, selected = _ready_device(serial)
        result = _run(_command(adb, "-s", selected, "logcat", "-d", "-t", str(lines)), timeout=60)
        return {"serial": selected, "lines": result["stdout"].splitlines()[-lines:]}
, text)
    return bool(
        sdk_setting and java_setting
        and sdk_setting.group(1).strip() == json.dumps(str(sdk))
        and java_setting.group(1).strip() == json.dumps(str(java_home))
    )


def _sdk_tool(name: str) -> str | None:
    sdk = _android_sdk()
    if sdk:
        choices = sorted((sdk / "build-tools").glob(f"*/{name}"), reverse=True)
        choices += sorted((sdk / "build-tools").glob(f"*/{name}.bat"), reverse=True)
        for item in choices:
            if item.is_file():
                return str(item)
    return shutil.which(name)


def _command(executable: str, *arguments: str) -> list[str]:
    if executable.lower().endswith((".bat", ".cmd")) and os.name == "nt":
        return ["cmd.exe", "/d", "/s", "/c", subprocess.list2cmdline([executable, *arguments])]
    return [executable, *arguments]


def _run(command: list[str], timeout: int = 900, env: dict[str, str] | None = None) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout,
            check=False, env=env, encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Command timed out after {timeout} seconds: {' '.join(command[:3])}") from exc
    output = (completed.stdout or "")[-20000:]
    errors = (completed.stderr or "")[-20000:]
    if completed.returncode != 0:
        raise RuntimeError(
            f"Command failed with exit code {completed.returncode}: {' '.join(command[:4])}\n"
            f"{errors or output}"
        )
    return {"returncode": completed.returncode, "stdout": output, "stderr": errors}


def _ensure_game(manager: ProjectManager, project_id: str) -> Path:
    try:
        definition = manager.load(project_id)
        root = manager.path_for(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project not found.") from exc
    game = root / "game"
    if not (game / "project.godot").is_file():
        world_file = root / "world.json"
        world = WorldDocument.model_validate_json(world_file.read_text(encoding="utf-8")).model_dump(mode="json") if world_file.is_file() else None
        assemble_godot_project(definition, game, world)
    return game.resolve()


def _png_dimensions(path: Path) -> tuple[int, int]:
    try:
        with path.open("rb") as stream:
            header = stream.read(24)
    except OSError as exc:
        raise HTTPException(status_code=400, detail="Could not read the launcher icon.") from exc
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise HTTPException(status_code=415, detail="Launcher icon must be a PNG image.")
    return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")


def _quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _write_android_preset(project: Path, request: AndroidBuildRequest, output: Path) -> None:
    preset_file = project / "export_presets.cfg"
    original = preset_file.read_text(encoding="utf-8") if preset_file.is_file() else ""
    match = re.search(r"(?m)^\[preset\.2\]\s*$", original)
    prefix = original[:match.start()] if match else original.rstrip() + "\n\n"
    icon_ref = ""
    if request.icon_path:
        source = Path(request.icon_path).expanduser().resolve()
        if not source.is_file():
            raise HTTPException(status_code=400, detail="Launcher icon file does not exist on this desktop.")
        width, height = _png_dimensions(source)
        if width < 192 or height < 192 or width != height:
            raise HTTPException(status_code=400, detail="Launcher icon must be a square PNG at least 192×192 pixels.")
        assets = project / "android_assets"
        assets.mkdir(parents=True, exist_ok=True)
        destination = assets / "launcher-icon.png"
        shutil.copy2(source, destination)
        icon_ref = "res://android_assets/launcher-icon.png"

    orientation = {"landscape": 0, "portrait": 1, "sensor": 6}[request.orientation]
    use_gradle = request.output_format == "aab"
    options = request.permissions.model_dump()
    permission_lines = "\n".join(
        f"permissions/{name}={str(enabled).lower()}"
        for name, enabled in options.items()
    )
    export_path = output.relative_to(project).as_posix()
    preset = f'''[preset.2]
name="Android"
platform="Android"
runnable=true
dedicated_server=false
custom_features=""
export_filter="all_resources"
include_filter=""
exclude_filter=""
export_path={_quote(export_path)}
encryption_include_filters=""
encryption_exclude_filters=""
encrypt_pck=false
encrypt_directory=false

[preset.2.options]
custom_template/debug=""
custom_template/release=""
gradle_build/use_gradle_build={str(use_gradle).lower()}
gradle_build/export_format={1 if request.output_format == "aab" else 0}
gradle_build/min_sdk={_quote(str(request.min_sdk))}
gradle_build/target_sdk={_quote(str(request.target_sdk))}
architectures/armeabi-v7a={str(request.arm32).lower()}
architectures/arm64-v8a={str(request.arm64).lower()}
architectures/x86=false
architectures/x86_64=false
package/unique_name={_quote(request.package_id)}
package/name={_quote(request.app_name)}
package/signed=true
version/code={request.version_code}
version/name={_quote(request.version_name)}
screen/immersive_mode=true
screen/orientation={orientation}
launcher_icons/main_192x192={_quote(icon_ref)}
launcher_icons/adaptive_foreground_432x432={_quote(icon_ref)}
{permission_lines}
keystore/release=""
keystore/release_user=""
keystore/release_password=""
'''
    preset_file.write_text(prefix + preset, encoding="utf-8")


def _debug_signing_environment(env: dict[str, str]) -> None:
    keytool = shutil.which("keytool")
    if not keytool:
        raise RuntimeError("Java keytool is required to prepare the desktop debug signing key.")
    key_path = Path.home() / ".android" / "debug.keystore"
    key_path.parent.mkdir(parents=True, exist_ok=True)
    if not key_path.is_file():
        _run(_command(keytool, "-genkeypair", "-v", "-keystore", str(key_path),
                       "-storepass", "android", "-alias", "androiddebugkey",
                       "-keypass", "android", "-dname", "CN=Android Debug,O=Android,C=US",
                       "-keyalg", "RSA", "-keysize", "2048", "-validity", "10000", "-noprompt"), timeout=120)
    env["GODOT_ANDROID_KEYSTORE_DEBUG_PATH"] = str(key_path)
    env["GODOT_ANDROID_KEYSTORE_DEBUG_USER"] = "androiddebugkey"
    env["GODOT_ANDROID_KEYSTORE_DEBUG_PASSWORD"] = "android"


def _signing_environment(request: AndroidBuildRequest) -> dict[str, str]:
    env = os.environ.copy()
    sdk = _android_sdk()
    if sdk:
        env["ANDROID_HOME"] = str(sdk)
        env["ANDROID_SDK_ROOT"] = str(sdk)
    if request.build_type == "debug":
        _debug_signing_environment(env)
        return env
    if not request.signing:
        raise HTTPException(status_code=422, detail="Release builds require a local keystore, alias and key password.")
    key_path = Path(request.signing.keystore_path).expanduser().resolve()
    if not key_path.is_file():
        raise HTTPException(status_code=400, detail="The selected release keystore does not exist on this desktop.")
    env["GODOT_ANDROID_KEYSTORE_RELEASE_PATH"] = str(key_path)
    env["GODOT_ANDROID_KEYSTORE_RELEASE_USER"] = request.signing.key_alias
    env["GODOT_ANDROID_KEYSTORE_RELEASE_PASSWORD"] = request.signing.key_password
    return env


def _validate_export(project: Path, output: Path, request: AndroidBuildRequest, env: dict[str, str]) -> dict[str, Any]:
    if not output.is_file() or output.stat().st_size < 1024:
        raise RuntimeError("Godot completed without creating a non-empty Android package.")
    if not zipfile.is_zipfile(output):
        raise RuntimeError("The Android export is not a valid ZIP-based APK/AAB package.")
    if request.output_format == "apk":
        with zipfile.ZipFile(output) as archive:
            if "AndroidManifest.xml" not in archive.namelist():
                raise RuntimeError("APK validation failed: AndroidManifest.xml is missing.")
        apksigner = _sdk_tool("apksigner") or shutil.which("apksigner")
        if not apksigner:
            raise RuntimeError("Android build-tools apksigner is required to verify the APK signature.")
        verification = _run(_command(apksigner, "verify", "--verbose", str(output)), timeout=180, env=env)
        aapt = _sdk_tool("aapt") or shutil.which("aapt")
        package_validation = None
        if aapt:
            badging = _run(_command(aapt, "dump", "badging", str(output)), timeout=120, env=env)
            package_validation = next((line.strip() for line in badging["stdout"].splitlines() if line.startswith("package:")), None)
            if package_validation and f"name='{request.package_id}'" not in package_validation:
                raise RuntimeError("APK manifest package ID does not match the Build Console configuration.")
        return {"signature_verified": True, "signature_output": verification["stdout"][-3000:], "package_manifest": package_validation}
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        if "base/manifest/AndroidManifest.xml" not in names or "BundleConfig.pb" not in names:
            raise RuntimeError("AAB validation failed: bundle manifest or BundleConfig.pb is missing.")
    jarsigner = shutil.which("jarsigner")
    if not jarsigner:
        raise RuntimeError("Java jarsigner is required to verify the Android App Bundle signature.")
    verification = _run(_command(jarsigner, "-verify", "-verbose", str(output)), timeout=180, env=env)
    return {"signature_verified": True, "signature_output": verification["stdout"][-3000:], "bundle_structure_verified": True}


def _history_file(project_root: Path) -> Path:
    return project_root / "build-history.json"


def _read_history(project_root: Path) -> list[dict[str, Any]]:
    path = _history_file(project_root)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _write_history(project_root: Path, history: list[dict[str, Any]]) -> None:
    target = _history_file(project_root)
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(history[-100:], indent=2), encoding="utf-8")
    temporary.replace(target)


def _build_android(job_id: str, project_id: str, request: AndroidBuildRequest,
                   manager: ProjectManager, jobs: JobRegistry) -> None:
    try:
        jobs.update(job_id, state=JobState.RUNNING, progress=5, message="Preparing Android build environment")
        godot = _godot()
        if not godot:
            raise RuntimeError("Godot 4 editor executable was not found. Set PGF_GODOT_BIN or add Godot to PATH.")
        if not _android_sdk():
            raise RuntimeError("Android SDK not found. Configure ANDROID_HOME or ANDROID_SDK_ROOT on this desktop.")
        if not shutil.which("java"):
            raise RuntimeError("Java is required for Android export. Install a supported JDK and ensure java is on PATH.")
        if request.output_format == "aab" and request.build_type != "release":
            raise RuntimeError("AAB packages must use Release signing.")
        env = _signing_environment(request)
        project = _ensure_game(manager, project_id)
        build_id = uuid4().hex
        extension = request.output_format
        slug = re.sub(r"[^a-z0-9]+", "-", request.app_name.casefold()).strip("-") or "game"
        output = project / "builds" / "android" / f"{slug}-{request.version_name}-{request.version_code}-{build_id[:8]}.{extension}"
        output.parent.mkdir(parents=True, exist_ok=True)
        _write_android_preset(project, request, output)
        jobs.update(job_id, progress=20, message="Importing and validating the Godot project")
        _run([godot, "--headless", "--path", str(project), "--editor", "--quit"], timeout=900, env=env)
        jobs.update(job_id, progress=45, message=f"Exporting signed Android {extension.upper()} package")
        export_mode = "--export-debug" if request.build_type == "debug" else "--export-release"
        export = _run([godot, "--headless", "--path", str(project), export_mode, "Android", str(output)], timeout=3600, env=env)
        jobs.update(job_id, progress=82, message="Verifying package structure, application ID and signature")
        validation = _validate_export(project, output, request, env)
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        record = {
            "id": build_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "app_name": request.app_name,
            "package_id": request.package_id,
            "version_name": request.version_name,
            "version_code": request.version_code,
            "output_format": request.output_format,
            "build_type": request.build_type,
            "orientation": request.orientation,
            "size": output.stat().st_size,
            "sha256": digest,
            "artifact_path": output.relative_to(manager.path_for(project_id)).as_posix(),
            "signature_verified": validation["signature_verified"],
            "package_validation": validation.get("package_manifest"),
        }
        root = manager.path_for(project_id)
        history = _read_history(root)
        history.insert(0, record)
        _write_history(root, history)
        (output.parent / f"{output.stem}.manifest.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        jobs.update(job_id, state=JobState.COMPLETED, progress=100,
                    message=f"{request.output_format.upper()} exported and signature-verified",
                    result={"build": record, "validation": validation,
                            "godot_export": {"stdout": export["stdout"][-6000:], "stderr": export["stderr"][-6000:]}})
    except Exception as exc:
        jobs.update(job_id, state=JobState.FAILED, progress=100, message="Android build failed", error=str(exc)[-12000:])


def _runtime_test(job_id: str, project_id: str, manager: ProjectManager, jobs: JobRegistry) -> None:
    try:
        godot = _godot()
        if not godot:
            raise RuntimeError("Godot 4 was not found on this desktop.")
        project = _ensure_game(manager, project_id)
        root = manager.path_for(project_id)
        log_path = root / "runtime-test.log"
        jobs.update(job_id, state=JobState.RUNNING, progress=10, message="Checking GDScript and importing project resources")
        editor = _run([godot, "--headless", "--path", str(project), "--editor", "--quit"], timeout=900)
        jobs.update(job_id, progress=45, message="Running the generated game headlessly and collecting FPS samples")
        runtime = _run([godot, "--headless", "--path", str(project), "--quit-after", "300",
                        "--print-fps", "--log-file", str(log_path)], timeout=300)
        combined = "\n".join([editor["stdout"], editor["stderr"], runtime["stdout"], runtime["stderr"],
                              log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""])
        errors = [line.strip() for line in combined.splitlines()
                  if re.search(r"(SCRIPT ERROR:|Parse Error|ERROR:|FATAL|Segmentation fault)", line, re.I)]
        fps_samples: list[float] = []
        for line in combined.splitlines():
            if "fps" in line.casefold():
                values = re.findall(r"\d+(?:\.\d+)?", line)
                if values:
                    fps_samples.append(float(values[-1]))
        metrics = {
            "fps_sample_count": len(fps_samples),
            "average_fps": round(sum(fps_samples) / len(fps_samples), 2) if fps_samples else None,
            "minimum_fps": min(fps_samples) if fps_samples else None,
            "maximum_fps": max(fps_samples) if fps_samples else None,
            "test_frames": 300,
            "note": "Headless FPS is a regression signal, not a substitute for GPU profiling on the target desktop or Android device.",
        }
        report = {"passed": not errors, "project_id": project_id, "metrics": metrics,
                  "errors": errors[:100], "log_path": str(log_path)}
        if errors:
            raise RuntimeError("Runtime validation reported errors: " + "\n".join(errors[:20]))
        jobs.update(job_id, state=JobState.COMPLETED, progress=100, message="Godot import and runtime smoke test passed", result=report)
    except Exception as exc:
        jobs.update(job_id, state=JobState.FAILED, progress=100, message="Runtime validation failed", error=str(exc)[-12000:])


def _tail(path: Path, max_bytes: int = 24000) -> str:
    if not path.is_file():
        return ""
    try:
        with path.open("rb") as stream:
            stream.seek(max(0, path.stat().st_size - max_bytes))
            return stream.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _adb_devices() -> list[dict[str, str]]:
    adb = _adb()
    if not adb:
        raise HTTPException(status_code=503, detail="Android platform-tools ADB was not found on this desktop.")
    result = _run(_command(adb, "devices", "-l"), timeout=30)
    devices: list[dict[str, str]] = []
    for line in result["stdout"].splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        serial, state = parts[0], parts[1]
        metadata = {}
        for item in parts[2:]:
            if ":" in item:
                key, value = item.split(":", 1)
                metadata[key] = value
        devices.append({"serial": serial, "state": state,
                        "model": metadata.get("model", ""),
                        "product": metadata.get("product", ""),
                        "transport_id": metadata.get("transport_id", "")})
    return devices


def _ready_device(serial: str) -> tuple[str, str]:
    devices = _adb_devices()
    selected = next((item for item in devices if item["serial"] == serial), None)
    if not selected:
        raise HTTPException(status_code=404, detail="Selected Android device is not connected to this desktop.")
    if selected["state"] != "device":
        raise HTTPException(status_code=409, detail=f"ADB device state is {selected['state']}; authorize USB debugging on the phone.")
    adb = _adb()
    assert adb
    return adb, serial


def register_local_build_routes(app, manager: ProjectManager, jobs: JobRegistry) -> None:
    @app.get("/api/local/build-tools")
    def build_tools():
        _require_desktop()
        godot = _godot()
        adb = _adb()
        sdk = _android_sdk()
        java = shutil.which("java")
        apksigner = _sdk_tool("apksigner") or shutil.which("apksigner")
        aapt = _sdk_tool("aapt") or shutil.which("aapt")
        return {
            "godot": {"available": bool(godot), "path": godot},
            "java": {"available": bool(java), "path": java},
            "android_sdk": {"available": bool(sdk), "path": str(sdk) if sdk else None},
            "adb": {"available": bool(adb), "path": adb},
            "apksigner": {"available": bool(apksigner), "path": apksigner},
            "aapt": {"available": bool(aapt), "path": aapt},
            "android_export_templates": bool(Path.home().joinpath(".local/share/godot/export_templates").is_dir()
                                             or Path.home().joinpath("AppData/Roaming/Godot/export_templates").is_dir()),
            "desktop_local": True,
        }

    @app.post("/api/projects/{project_id}/runtime-test", status_code=202)
    def start_runtime_test(project_id: str, background: BackgroundTasks):
        _require_desktop()
        _ensure_game(manager, project_id)
        job = jobs.add(Job.create(project_id))
        background.add_task(_runtime_test, job.id, project_id, manager, jobs)
        return job.as_dict()

    @app.post("/api/projects/{project_id}/runs", status_code=202)
    def start_game_run(project_id: str, request: RuntimeLaunchRequest):
        _require_desktop()
        godot = _godot()
        if not godot:
            raise HTTPException(status_code=503, detail="Godot 4 was not found on this desktop.")
        project = _ensure_game(manager, project_id)
        run_id = uuid4().hex
        log_path = manager.path_for(project_id) / f"runtime-{run_id}.log"
        command = [godot, "--path", str(project)]
        if request.mode == "editor":
            command.append("--editor")
        elif request.mode == "debug":
            command.extend(["--debug", "--verbose"])
        elif request.mode == "profile":
            command.extend(["--profiling", "--print-fps", "--gpu-profile", "--verbose"])
        with log_path.open("w", encoding="utf-8") as log:
            try:
                process = subprocess.Popen(
                    command, cwd=str(project), stdout=log, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    creationflags=(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0),
                    start_new_session=(os.name != "nt"),
                )
            except OSError as exc:
                raise HTTPException(status_code=503, detail=f"Could not launch Godot: {exc}") from exc
        with _RUNS_LOCK:
            _RUNS[run_id] = {"project_id": project_id, "process": process, "log_path": log_path, "mode": request.mode}
        return {"run_id": run_id, "process_id": process.pid, "mode": request.mode, "state": "running"}

    @app.get("/api/projects/{project_id}/runs/{run_id}")
    def read_game_run(project_id: str, run_id: str):
        _require_desktop()
        with _RUNS_LOCK:
            run = _RUNS.get(run_id)
        if not run or run["project_id"] != project_id:
            raise HTTPException(status_code=404, detail="Runtime session not found.")
        process = run["process"]
        return {"run_id": run_id, "mode": run["mode"], "running": process.poll() is None,
                "exit_code": process.poll(), "log": _tail(run["log_path"])}

    @app.post("/api/projects/{project_id}/runs/{run_id}/stop")
    def stop_game_run(project_id: str, run_id: str):
        _require_desktop()
        with _RUNS_LOCK:
            run = _RUNS.get(run_id)
        if not run or run["project_id"] != project_id:
            raise HTTPException(status_code=404, detail="Runtime session not found.")
        process = run["process"]
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
        return {"run_id": run_id, "running": False, "exit_code": process.poll()}

    @app.get("/api/projects/{project_id}/builds")
    def list_android_builds(project_id: str):
        _require_desktop()
        try:
            root = manager.path_for(project_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid project ID.") from exc
        if not (root / "pgf.json").is_file():
            raise HTTPException(status_code=404, detail="Project not found.")
        return {"builds": _read_history(root)}

    @app.post("/api/projects/{project_id}/android-build", status_code=202)
    def create_android_build(project_id: str, request: AndroidBuildRequest, background: BackgroundTasks):
        _require_desktop()
        _ensure_game(manager, project_id)
        job = jobs.add(Job.create(project_id))
        background.add_task(_build_android, job.id, project_id, request, manager, jobs)
        return job.as_dict()

    @app.get("/api/projects/{project_id}/builds/{build_id}/download")
    def download_android_build(project_id: str, build_id: str):
        _require_desktop()
        root = manager.path_for(project_id)
        record = next((item for item in _read_history(root) if item.get("id") == build_id), None)
        if not record:
            raise HTTPException(status_code=404, detail="Build artifact not found.")
        path = (root / str(record.get("artifact_path") or "")).resolve()
        if root.resolve() not in path.parents or not path.is_file():
            raise HTTPException(status_code=404, detail="Build artifact is unavailable.")
        return FileResponse(path, filename=path.name, media_type="application/octet-stream")

    @app.get("/api/local/android/devices")
    def list_android_devices():
        _require_desktop()
        return {"devices": _adb_devices()}

    @app.post("/api/local/android/connect")
    def connect_wireless_device(request: WirelessEndpoint):
        _require_desktop()
        try:
            ipaddress.ip_address(request.host)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Wireless ADB host must be an IP address.") from exc
        adb = _adb()
        if not adb:
            raise HTTPException(status_code=503, detail="ADB was not found on this desktop.")
        return _run(_command(adb, "connect", f"{request.host}:{request.port}"), timeout=30)

    @app.post("/api/local/android/pair")
    def pair_wireless_device(request: WirelessPairRequest):
        _require_desktop()
        try:
            ipaddress.ip_address(request.host)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Wireless pairing host must be an IP address.") from exc
        adb = _adb()
        if not adb:
            raise HTTPException(status_code=503, detail="ADB was not found on this desktop.")
        return _run(_command(adb, "pair", f"{request.host}:{request.port}", request.pairing_code), timeout=45)

    @app.post("/api/projects/{project_id}/builds/{build_id}/install")
    def install_android_build(project_id: str, build_id: str, request: DeviceSelection):
        _require_desktop()
        root = manager.path_for(project_id)
        record = next((item for item in _read_history(root) if item.get("id") == build_id), None)
        if not record:
            raise HTTPException(status_code=404, detail="Build artifact not found.")
        if record.get("output_format") != "apk":
            raise HTTPException(status_code=409, detail="Android App Bundles cannot be installed directly. Build an APK for device testing.")
        path = (root / str(record.get("artifact_path") or "")).resolve()
        if root.resolve() not in path.parents or not path.is_file():
            raise HTTPException(status_code=404, detail="APK artifact is unavailable.")
        adb, serial = _ready_device(request.serial)
        result = _run(_command(adb, "-s", serial, "install", "-r", str(path)), timeout=300)
        return {"installed": True, "serial": serial, "package_id": record["package_id"], "output": result["stdout"]}

    @app.post("/api/projects/{project_id}/builds/{build_id}/launch")
    def launch_android_build(project_id: str, build_id: str, request: DeviceSelection):
        _require_desktop()
        root = manager.path_for(project_id)
        record = next((item for item in _read_history(root) if item.get("id") == build_id), None)
        if not record:
            raise HTTPException(status_code=404, detail="Build artifact not found.")
        adb, serial = _ready_device(request.serial)
        result = _run(_command(adb, "-s", serial, "shell", "monkey", "-p", str(record["package_id"]), "1"), timeout=60)
        return {"launched": True, "serial": serial, "package_id": record["package_id"], "output": result["stdout"]}

    @app.get("/api/local/android/logs")
    def android_logcat(serial: str, lines: int = 500):
        _require_desktop()
        if not DEVICE_SERIAL_PATTERN.fullmatch(serial):
            raise HTTPException(status_code=422, detail="Invalid ADB device serial.")
        if not 50 <= lines <= 2000:
            raise HTTPException(status_code=422, detail="Log line count must be between 50 and 2000.")
        adb, selected = _ready_device(serial)
        result = _run(_command(adb, "-s", selected, "logcat", "-d", "-t", str(lines)), timeout=60)
        return {"serial": selected, "lines": result["stdout"].splitlines()[-lines:]}
