"""Repeatable Nexora Foundry exports, validation and release packaging."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ExportTarget:
    key: str
    preset: str
    filename: str
    platform: str


TARGETS = {
    "linux": ExportTarget("linux", "Linux/X11", "NexoraFoundry.x86_64", "Linux x86_64"),
    "windows": ExportTarget("windows", "Windows Desktop", "NexoraFoundry.exe", "Windows x86_64"),
    "android": ExportTarget("android", "Android", "NexoraFoundry.apk", "Android arm64-v8a + armeabi-v7a"),
}


def export_presets_text() -> str:
    """Public export configuration only; signing secrets stay in user env/config."""
    return '''[preset.0]
name="Linux/X11"
platform="Linux/X11"
runnable=true
dedicated_server=false
custom_features=""
export_filter="all_resources"
include_filter=""
exclude_filter=""
export_path=""

[preset.0.options]
custom_template/debug=""
custom_template/release=""
debug/export_console_wrapper=1
binary_format/64_bits=true
binary_format/embed_pck=true
texture_format/s3tc_bptc=true
texture_format/etc2_astc=false

[preset.1]
name="Windows Desktop"
platform="Windows Desktop"
runnable=true
dedicated_server=false
custom_features=""
export_filter="all_resources"
include_filter=""
exclude_filter=""
export_path=""

[preset.1.options]
custom_template/debug=""
custom_template/release=""
debug/export_console_wrapper=false
binary_format/64_bits=true
binary_format/embed_pck=true
texture_format/bptc=false
texture_format/s3tc=true
application/modify_resources=true
application/product_name="Nexora Foundry"
application/file_description="Nexora Foundry generated game"
application/company_name="Nexora Foundry"

[preset.2]
name="Android"
platform="Android"
runnable=true
dedicated_server=false
custom_features=""
export_filter="all_resources"
include_filter=""
exclude_filter=""
export_path=""

[preset.2.options]
custom_template/debug=""
custom_template/release=""
gradle_build/use_gradle_build=false
gradle_build/export_format=0
architectures/armeabi-v7a=true
architectures/arm64-v8a=true
architectures/x86=false
architectures/x86_64=false
package/unique_name="com.nexora.foundry"
package/name="Nexora Foundry"
package/signed=true
package/retain_data_on_uninstall=false
package/version="0.1.0"
package/version_code=1
package/app_category=2
screen/immersive_mode=true
screen/support_small=true
'''


def write_export_presets(project_dir: Path) -> Path:
    """Write the three supported presets to an assembled Godot project."""
    if not (project_dir / "project.godot").is_file():
        raise FileNotFoundError(f"Not a Godot project: {project_dir}")
    path = project_dir / "export_presets.cfg"
    path.write_text(export_presets_text(), encoding="utf-8")
    return path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_android_archive(path: Path) -> dict[str, Any]:
    if not zipfile.is_zipfile(path):
        raise ValueError("Android export is not a valid APK/ZIP archive")
    with zipfile.ZipFile(path) as archive:
        damaged = archive.testzip()
        if damaged:
            raise ValueError(f"Android APK contains a corrupt entry: {damaged}")
        names = set(archive.namelist())
    if "AndroidManifest.xml" not in names:
        raise ValueError("Android APK is missing AndroidManifest.xml")
    native_libs = sorted(name for name in names if name.startswith("lib/") and name.endswith(".so"))
    if not native_libs:
        raise ValueError("Android APK contains no native game libraries")
    return {"archive_entries": len(names), "native_libraries": native_libs}


def verify_export(target: ExportTarget, artifact: Path) -> dict[str, Any]:
    if not artifact.is_file() or artifact.stat().st_size < 1024:
        raise ValueError(f"Export artifact is missing or unexpectedly small: {artifact}")
    if target.key == "linux":
        with artifact.open("rb") as stream:
            if stream.read(4) != b"\x7fELF":
                raise ValueError("Linux export does not have an ELF executable header")
        artifact.chmod(artifact.stat().st_mode | 0o111)
        return {"format": "ELF", "bytes": artifact.stat().st_size, "executable": True}
    if target.key == "windows":
        with artifact.open("rb") as stream:
            if stream.read(2) != b"MZ":
                raise ValueError("Windows export does not have an MZ executable header")
        return {"format": "PE/COFF", "bytes": artifact.stat().st_size}
    if target.key == "android":
        info = _validate_android_archive(artifact)
        return {"format": "APK", "bytes": artifact.stat().st_size, **info}
    raise ValueError(f"Unsupported export target: {target.key}")


def _deterministic_zip(output: Path, files: list[tuple[Path, str]]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for source, archive_name in sorted(files, key=lambda item: item[1]):
            info = zipfile.ZipInfo(archive_name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            mode = 0o100755 if source.stat().st_mode & 0o111 else 0o100644
            info.external_attr = mode << 16
            bundle.writestr(info, source.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def _configure_android_editor_settings(env: dict[str, str]) -> None:
    sdk = env.get("ANDROID_SDK_ROOT") or env.get("ANDROID_HOME")
    java = env.get("JAVA_HOME")
    if not sdk or not Path(sdk).is_dir():
        raise RuntimeError("Android SDK unavailable: set ANDROID_SDK_ROOT or ANDROID_HOME")
    if not java or not Path(java).is_dir():
        raise RuntimeError("Java SDK unavailable: set JAVA_HOME (OpenJDK 17 is recommended)")
    adb_name = "adb.exe" if os.name == "nt" else "adb"
    if not (Path(sdk) / "platform-tools" / adb_name).exists():
        raise RuntimeError("Android SDK platform-tools/adb is missing")
    config_root = Path(env.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "godot"
    config_root.mkdir(parents=True, exist_ok=True)
    settings = config_root / "editor_settings-4.tres"

    def quote(value: str) -> str:
        return json.dumps(str(Path(value).resolve()).replace("\\", "/"))

    settings.write_text(
        '[gd_resource type="EditorSettings" format=3]\n\n[resource]\n'
        f'export/android/android_sdk_path = {quote(sdk)}\n'
        f'export/android/java_sdk_path = {quote(java)}\n',
        encoding="utf-8",
    )


def _require_release_signing(target: ExportTarget, env: dict[str, str]) -> None:
    if target.key == "android":
        required = (
            "GODOT_ANDROID_KEYSTORE_RELEASE_PATH",
            "GODOT_ANDROID_KEYSTORE_RELEASE_USER",
            "GODOT_ANDROID_KEYSTORE_RELEASE_PASSWORD",
        )
        missing = [key for key in required if not env.get(key)]
        if missing:
            raise RuntimeError(
                "Android production release signing is not configured. Missing: "
                + ", ".join(missing)
            )
        if not Path(env[required[0]]).is_file():
            raise RuntimeError("Android release keystore file does not exist")
    if target.key == "windows" and not env.get("GODOT_WINDOWS_CODESIGN_IDENTITY"):
        raise RuntimeError(
            "Windows production signing is not configured. Set GODOT_WINDOWS_CODESIGN_IDENTITY "
            "and the matching signing tool."
        )


def export_game(
    project_dir: Path,
    target_key: str,
    output_dir: Path,
    godot_executable: str = "godot",
    mode: str = "debug",
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    if target_key not in TARGETS:
        raise ValueError(f"Unsupported target '{target_key}'. Choose: {', '.join(TARGETS)}")
    if mode not in ("debug", "release"):
        raise ValueError("mode must be 'debug' or 'release'")
    project_dir = project_dir.resolve()
    output_dir = output_dir.resolve()
    target = TARGETS[target_key]
    environment = dict(os.environ if env is None else env)
    if not (project_dir / "project.godot").is_file():
        raise FileNotFoundError(f"Godot project not found: {project_dir}")
    write_export_presets(project_dir)
    if mode == "release":
        _require_release_signing(target, environment)
    if target.key == "android":
        _configure_android_editor_settings(environment)
    version = subprocess.run(
        [godot_executable, "--version"], capture_output=True, text=True, timeout=30, env=environment
    )
    if version.returncode != 0:
        raise RuntimeError("Godot editor executable could not run: " + (version.stderr or version.stdout))
    version_text = (version.stdout or version.stderr).strip()
    if not version_text.startswith("4.6"):
        raise RuntimeError(f"Godot 4.6 is required for this release pipeline; found {version_text}")
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact = output_dir / target.filename
    export_flag = "--export-release" if mode == "release" else "--export-debug"
    command = [
        godot_executable, "--headless", "--path", str(project_dir),
        export_flag, target.preset, str(artifact),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=1800, env=environment)
    export_output = (result.stdout or "") + "\n" + (result.stderr or "")
    if result.returncode != 0 or not artifact.is_file():
        raise RuntimeError(
            f"{target.platform} export failed (exit={result.returncode}). "
            "Check Godot export templates and platform SDK configuration.\n"
            + export_output[-12000:]
        )
    artifact_info = verify_export(target, artifact)
    project_manifest = project_dir / "assembly-manifest.json"
    manifest = {
        "schema_version": "1.0",
        "product": "Nexora Foundry",
        "target": target.key,
        "platform": target.platform,
        "mode": mode,
        "godot_version": version_text,
        "source_commit": environment.get("GITHUB_SHA") or environment.get("NEXORA_SOURCE_COMMIT") or "local",
        "artifact": artifact.name,
        "artifact_bytes": artifact.stat().st_size,
        "artifact_sha256": sha256_file(artifact),
        "artifact_validation": artifact_info,
        "assembly_manifest_sha256": sha256_file(project_manifest) if project_manifest.is_file() else None,
        "signing": (
            "release-keystore"
            if target.key == "android" and mode == "release"
            else "windows-code-signing"
            if target.key == "windows" and mode == "release"
            else "development/debug signing" if target.key == "android"
            else "unsigned" if target.key in ("linux", "windows")
            else "not-applicable"
        ),
        "quality_gates": {
            "godot_export": "passed",
            "artifact_integrity": "passed",
            "platform_structure": "passed",
            "creator_playtest": "required",
            "store_or_public_release": "not_authorized_by_this_build",
        },
    }
    manifest_path = output_dir / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    package_path = None
    if target.key in ("linux", "windows"):
        package_path = output_dir / f"NexoraFoundry-{target.key}.zip"
        _deterministic_zip(package_path, [
            (artifact, artifact.name),
            (manifest_path, "release-manifest.json"),
        ])
    checksums = [f"{sha256_file(artifact)}  {artifact.name}"]
    if package_path:
        checksums.append(f"{sha256_file(package_path)}  {package_path.name}")
    checksums.append(f"{sha256_file(manifest_path)}  release-manifest.json")
    checksum_path = output_dir / "checksums.sha256"
    checksum_path.write_text("\n".join(checksums) + "\n", encoding="utf-8")
    return {
        "target": target.key,
        "artifact": str(artifact),
        "manifest": str(manifest_path),
        "checksums": str(checksum_path),
        "package": str(package_path) if package_path else None,
        "validation": artifact_info,
    }
