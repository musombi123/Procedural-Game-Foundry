"""Godot and Android SDK detection/configuration for the desktop Build Console."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ANDROID_BUILD_TOOLS_VERSION = "35.0.1"
ANDROID_PLATFORM_VERSION = "35"
ANDROID_NDK_VERSION = "28.1.13356709"
ANDROID_CMAKE_VERSION = "3.10.2.4988404"


def java_home() -> Path | None:
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


def godot_version(godot: str) -> str:
    try:
        result = subprocess.run([godot, "--version"], capture_output=True, text=True,
                                timeout=30, check=False, encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Could not query the installed Godot editor version.") from exc
    if result.returncode != 0:
        raise RuntimeError("Godot did not return its editor version.")
    output = (result.stdout or result.stderr).strip()
    match = re.search(r"(\d+\.\d+(?:\.\d+)?\.(?:stable|dev|beta\d*|rc\d*|alpha\d*))", output, re.I)
    if not match:
        raise RuntimeError("Could not identify the Godot editor version. Install matching Android export templates.")
    return match.group(1)


def template_directory(godot: str) -> Path:
    version = godot_version(godot)
    if os.name == "nt":
        root = Path(os.getenv("APPDATA") or (Path.home() / "AppData" / "Roaming")) / "Godot" / "export_templates"
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support" / "Godot" / "export_templates"
    else:
        root = Path.home() / ".local" / "share" / "godot" / "export_templates"
    return root / version


def template_status(godot: str | None) -> dict[str, Any]:
    if not godot:
        return {"available": False, "version": None, "path": None, "missing": ["Godot editor"]}
    try:
        folder = template_directory(godot)
    except RuntimeError as exc:
        return {"available": False, "version": None, "path": None, "missing": [str(exc)]}
    required = ("android_debug.apk", "android_release.apk", "android_source.zip")
    missing = [item for item in required if not (folder / item).is_file()]
    return {"available": not missing, "version": folder.name, "path": str(folder), "missing": missing}


def sdk_components(sdk: Path | None) -> dict[str, Any]:
    if not sdk:
        return {"available": False, "missing": ["Android SDK root"]}
    expected = {
        "platform-tools / adb": sdk / "platform-tools" / ("adb.exe" if os.name == "nt" else "adb"),
        f"platforms;android-{ANDROID_PLATFORM_VERSION}": sdk / "platforms" / f"android-{ANDROID_PLATFORM_VERSION}",
        f"build-tools;{ANDROID_BUILD_TOOLS_VERSION} / apksigner": sdk / "build-tools" / ANDROID_BUILD_TOOLS_VERSION / ("apksigner.bat" if os.name == "nt" else "apksigner"),
        f"build-tools;{ANDROID_BUILD_TOOLS_VERSION} / aapt": sdk / "build-tools" / ANDROID_BUILD_TOOLS_VERSION / ("aapt.exe" if os.name == "nt" else "aapt"),
        f"ndk;{ANDROID_NDK_VERSION}": sdk / "ndk" / ANDROID_NDK_VERSION,
        f"cmake;{ANDROID_CMAKE_VERSION}": sdk / "cmake" / ANDROID_CMAKE_VERSION,
        "cmdline-tools;latest / sdkmanager": sdk / "cmdline-tools" / "latest" / "bin" / ("sdkmanager.bat" if os.name == "nt" else "sdkmanager"),
    }
    missing = [label for label, path in expected.items() if not path.exists()]
    return {"available": not missing, "missing": missing}


def sdk_tool(sdk: Path | None, name: str) -> str | None:
    if sdk:
        matches = []
        for suffix in ("", ".exe", ".bat"):
            matches.extend(sdk.glob(f"build-tools/*/{name}{suffix}"))
        for candidate in sorted(matches, reverse=True):
            if candidate.is_file():
                return str(candidate)
    return shutil.which(name)


def java_tool(name: str, env: dict[str, str] | None = None) -> str | None:
    environment = env or os.environ
    home = Path(environment.get("JAVA_HOME", "")).expanduser()
    candidate = home / "bin" / (name + (".exe" if os.name == "nt" else ""))
    return str(candidate) if candidate.is_file() else shutil.which(name)


def settings_path(godot: str) -> Path:
    version = godot_version(godot)
    major_minor = ".".join(version.split(".")[:2])
    if os.name == "nt":
        root = Path(os.getenv("APPDATA") or (Path.home() / "AppData" / "Roaming")) / "Godot"
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support" / "Godot"
    else:
        root = Path.home() / ".config" / "godot"
    return root / f"editor_settings-{major_minor}.tres"


def set_editor_resource_value(text: str, key: str, value: str) -> str:
    encoded = json.dumps(value, ensure_ascii=False)
    replacement = f"{key} = {encoded}"
    matcher = re.compile(rf"(?m)^{re.escape(key)}\s*=.*$")
    if matcher.search(text):
        return matcher.sub(lambda _: replacement, text, count=1)
    resource = re.search(r"(?m)^\[resource\]\s*$", text)
    if not resource:
        text = text.rstrip() + "\n\n[resource]\n"
        resource = re.search(r"(?m)^\[resource\]\s*$", text)
    assert resource is not None
    start = resource.end()
    next_section = re.search(r"(?m)^\[[^\]]+\]\s*$", text[start:])
    end = start + next_section.start() if next_section else len(text)
    block = text[start:end].rstrip()
    updated = (block + "\n" if block else "\n") + replacement + "\n"
    return text[:start] + updated + text[end:]


def configure_godot_android(godot: str, sdk: Path | None, env: dict[str, str]) -> dict[str, str]:
    jdk = java_home()
    if not sdk:
        raise RuntimeError("Android SDK not found. Set ANDROID_HOME or ANDROID_SDK_ROOT on this desktop.")
    if not (sdk / "platform-tools" / ("adb.exe" if os.name == "nt" else "adb")).is_file():
        raise RuntimeError("Android SDK platform-tools/adb is missing. Install Android SDK Platform-Tools.")
    if not jdk:
        raise RuntimeError("OpenJDK 17 or a compatible JDK was not found. Set JAVA_HOME and ensure java is on PATH.")
    env["ANDROID_HOME"] = str(sdk)
    env["ANDROID_SDK_ROOT"] = str(sdk)
    env["JAVA_HOME"] = str(jdk)
    target = settings_path(godot)
    target.parent.mkdir(parents=True, exist_ok=True)
    current = target.read_text(encoding="utf-8") if target.is_file() else (
        '[gd_resource type="EditorSettings" format=3]\n\n[resource]\n'
    )
    current = set_editor_resource_value(current, "export/android/android_sdk_path", str(sdk))
    current = set_editor_resource_value(current, "export/android/java_sdk_path", str(jdk))
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(current, encoding="utf-8")
    temp.replace(target)
    return {"android_sdk": str(sdk), "java_home": str(jdk), "godot_settings": str(target)}


def settings_match(godot: str | None, sdk: Path | None, jdk: Path | None) -> bool:
    if not godot or not sdk or not jdk:
        return False
    path = settings_path(godot)
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    sdk_value = re.search(r"(?m)^export/android/android_sdk_path\s*=\s*(.+)", text)
    java_value = re.search(r"(?m)^export/android/java_sdk_path\s*=\s*(.+)", text)
    return bool(
        sdk_value and java_value
        and sdk_value.group(1).strip() == json.dumps(str(sdk))
        and java_value.group(1).strip() == json.dumps(str(jdk))
    )


def set_project_ini_value(project_file: Path, section_name: str, key: str, value: str) -> None:
    text = project_file.read_text(encoding="utf-8") if project_file.is_file() else ""
    section_header = f"[{section_name}]"
    section = re.search(rf"(?m)^\[{re.escape(section_name)}\]\s*$", text)
    if not section:
        text = text.rstrip() + f"\n\n{section_header}\n"
        section = re.search(rf"(?m)^\[{re.escape(section_name)}\]\s*$", text)
    assert section is not None
    start = section.end()
    next_section = re.search(r"(?m)^\[[^\]]+\]\s*$", text[start:])
    end = start + next_section.start() if next_section else len(text)
    block = text[start:end]
    matcher = re.compile(rf"(?m)^{re.escape(key)}\s*=.*$")
    entry = f"{key}={value}"
    if matcher.search(block):
        block = matcher.sub(lambda _: entry, block, count=1)
    else:
        block = block.rstrip() + "\n" + entry + "\n"
    temp = project_file.with_suffix(project_file.suffix + ".tmp")
    temp.write_text(text[:start] + block + text[end:], encoding="utf-8")
    temp.replace(project_file)
