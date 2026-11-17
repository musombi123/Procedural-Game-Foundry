from __future__ import annotations
import hashlib, os, re, shutil, subprocess, tempfile, zipfile
from pathlib import Path
from typing import Any
from .security import validate_package_id, validate_private_pair_address, validate_serial

MAX_APK_BYTES = 1024 * 1024 * 1024

class AdbError(RuntimeError):
    pass

def adb_path() -> str:
    configured = os.getenv("NEXORA_ADB_PATH", "").strip()
    candidate = configured or shutil.which("adb")
    if not candidate or not Path(candidate).is_file():
        raise AdbError("Android SDK Platform Tools are not installed or adb is not on PATH.")
    return candidate

def run_adb(args: list[str], timeout: int = 30) -> str:
    try:
        result = subprocess.run([adb_path(), *args], capture_output=True, text=True, timeout=timeout, check=False, shell=False)
    except subprocess.TimeoutExpired as exc:
        raise AdbError("ADB command timed out.") from exc
    except OSError as exc:
        raise AdbError("Could not start Android Debug Bridge.") from exc
    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0:
        raise AdbError(output[-3000:] or "ADB command failed.")
    return output.strip()

def list_devices() -> list[dict[str, str]]:
    output = run_adb(["devices", "-l"])
    devices = []
    for line in output.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2 or parts[1] not in {"device", "unauthorized", "offline"}:
            continue
        devices.append({"serial": parts[0], "state": parts[1],
            "model": next((p.split(":", 1)[1] for p in parts[2:] if p.startswith("model:")), ""),
            "product": next((p.split(":", 1)[1] for p in parts[2:] if p.startswith("product:")), "")})
    return devices

def pair_wireless(host: str, pairing_port: int, pairing_code: str, connect_port: int) -> dict[str, str]:
    host, pairing_port = validate_private_pair_address(host, pairing_port)
    if not 1024 <= int(connect_port) <= 65535:
        raise ValueError("ADB connection port must be between 1024 and 65535.")
    code = str(pairing_code).strip()
    if not re.fullmatch(r"\\d{6}", code):
        raise ValueError("Android Wireless Debugging pairing code must contain six digits.")
    paired = run_adb(["pair", f"{host}:{pairing_port}", code], timeout=30)
    connected = run_adb(["connect", f"{host}:{int(connect_port)}"], timeout=20)
    return {"pairing": paired[-500:], "connection": connected[-500:]}

def _apk_metadata_tool() -> str:
    configured = os.getenv("NEXORA_APKANALYZER_PATH", "").strip()
    candidate = configured or shutil.which("apkanalyzer") or shutil.which("aapt")
    if not candidate or not Path(candidate).is_file():
        raise AdbError("Android SDK Build Tools are required to inspect APK package metadata.")
    return candidate

def inspect_apk(path: Path) -> dict[str, str]:
    if not zipfile.is_zipfile(path):
        raise AdbError("Uploaded file is not a valid APK archive.")
    tool = _apk_metadata_tool()
    if Path(tool).name.lower().startswith("aapt"):
        command, pattern = [tool, "dump", "badging", str(path)], re.compile(r"^package: name='([^']+)'")
    else:
        command, pattern = [tool, "manifest", "application-id", str(path)], re.compile(r"^([A-Za-z][A-Za-z0-9_.]+)$")
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False, shell=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AdbError("Could not inspect the APK manifest.") from exc
    if result.returncode != 0:
        raise AdbError((result.stderr or result.stdout or "APK manifest inspection failed.")[-2000:])
    match = next((m for line in result.stdout.splitlines() if (m := pattern.search(line.strip()))), None)
    if not match:
        raise AdbError("Could not read the Android application ID from the APK.")
    return {"package_id": validate_package_id(match.group(1))}

def verify_apk_signature(path: Path) -> None:
    configured = os.getenv("NEXORA_APKSIGNER_PATH", "").strip()
    signer = configured or shutil.which("apksigner")
    if not signer or not Path(signer).is_file():
        raise AdbError("Android SDK Build Tools apksigner is required to verify APK signatures before installation.")
    try:
        result = subprocess.run([signer, "verify", "--verbose", str(path)], capture_output=True, text=True, timeout=45, check=False, shell=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AdbError("Could not verify the APK signature.") from exc
    if result.returncode != 0:
        raise AdbError((result.stderr or result.stdout or "APK signature verification failed.")[-2000:])

def install_apk_file(serial: str, package_id: str, path: Path) -> dict[str, Any]:
    serial, package_id = validate_serial(serial), validate_package_id(package_id)
    if not path.is_file() or path.stat().st_size <= 0 or path.stat().st_size > MAX_APK_BYTES:
        raise AdbError("APK file is empty or exceeds the 1 GB transfer limit.")
    metadata = inspect_apk(path)
    if metadata["package_id"] != package_id:
        raise AdbError(f"APK package ID mismatch: expected {package_id}, found {metadata['package_id']}.")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    output = run_adb(["-s", serial, "install", "-r", "-t", str(path)], timeout=180)
    return {"serial": serial, "package_id": package_id, "sha256": digest.hexdigest(), "install_output": output[-1000:]}

def launch_app(serial: str, package_id: str) -> dict[str, str]:
    serial, package_id = validate_serial(serial), validate_package_id(package_id)
    output = run_adb(["-s", serial, "shell", "monkey", "-p", package_id, "-c", "android.intent.category.LAUNCHER", "1"], timeout=45)
    return {"serial": serial, "package_id": package_id, "launch_output": output[-1000:]}

def read_logcat(serial: str, package_id: str, lines: int = 300) -> dict[str, str]:
    serial, package_id = validate_serial(serial), validate_package_id(package_id)
    pid_output = run_adb(["-s", serial, "shell", "pidof", "-s", package_id], timeout=15)
    pid = pid_output.split()[0] if pid_output.strip() else ""
    if not pid.isdigit():
        raise AdbError("The game process is not running; launch the game before collecting its logs.")
    output = run_adb(["-s", serial, "logcat", "-d", "-t", str(min(max(int(lines), 1), 500)), "--pid", pid], timeout=30)
    return {"serial": serial, "package_id": package_id, "pid": pid, "logcat": output[-50000:]}
