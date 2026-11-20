"""NEXORA Local Compute Agent.

This service is installed and run on the creator's computer. It binds to
127.0.0.1 only, pairs by a one-time terminal code, reports device capability,
and provides a narrowly allow-listed Android device bridge.

The Foundry API is mounted under /engine and is enabled only when
NEXORA_LOCAL_AGENT=true. It runs on this same user's machine, not on Render.
"""
from __future__ import annotations

import hashlib
import ipaddress
import os
import re
import shutil
import subprocess
import tempfile
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request as UrlRequest, urlopen
from pathlib import Path
from typing import Any
from datetime import datetime, timezone

# Set these before importing the Foundry application. The cloud Render process
# never imports this module.
os.environ["NEXORA_LOCAL_AGENT"] = "true"
os.environ.setdefault("NEXORA_AUTH_REQUIRED", "true")
if not os.environ.get("PGF_DATA_DIR"):
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        os.environ["PGF_DATA_DIR"] = str(Path(os.environ["LOCALAPPDATA"]) / "NEXORA" / "Foundry")
    else:
        os.environ["PGF_DATA_DIR"] = str(Path.home() / ".local" / "share" / "nexora" / "foundry")

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from services.worker.local_security import PairingAuthority, get_pairing_authority
from services.worker.system_profile import check_requirements, collect_system_profile
from services.worker.local_workspace import load_workspace_root, register_local_workspace_routes

VERSION = "1.0.0"
PORT = 8765
MAX_APK_BYTES = 1024 * 1024 * 1024
SERIAL_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
PACKAGE_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
PAIR_CODE_RE = re.compile(r"^[0-9]{8}$")
ORIGINS = {
    item.strip()
    for item in os.environ.get(
        "NEXORA_LOCAL_ALLOWED_ORIGINS",
        "https://revelacode.co.ke,http://localhost:5174,http://127.0.0.1:5174,http://localhost:5173,http://127.0.0.1:5173,tauri://localhost",
    ).split(",")
    if item.strip()
}
DATA_ROOT = Path(os.environ.get("NEXORA_LOCAL_AGENT_DATA", str(Path.home() / ".nexora-local-agent"))).expanduser().resolve()

# Restore the creator-selected projects folder before the Foundry engine is imported.
_SAVED_WORKSPACE_ROOT = load_workspace_root(DATA_ROOT)
if _SAVED_WORKSPACE_ROOT:
    # Keep runtime state outside the creator's source projects. The shared
    # ProjectManager root is reassigned to the selected workspace after import.
    os.environ["PGF_DATA_DIR"] = str(_SAVED_WORKSPACE_ROOT / ".nexora-runtime")

STAGING_ROOT = DATA_ROOT / "device-staging"
STAGING_ROOT.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="NEXORA Local Compute Agent",
    version=VERSION,
    description="Loopback-only local hardware preflight and Android device bridge.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(ORIGINS),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)


@app.middleware("http")
async def loopback_and_origin_guard(request: Request, call_next):
    """Defend the local service against remote access and browser-based CSRF."""
    client_host = (request.client.host if request.client else "") or ""
    if client_host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        return JSONResponse({"detail": "NEXORA Local Agent accepts loopback connections only."}, status_code=403)
    host = (request.headers.get("host") or "").lower()
    allowed_hosts = {
        "127.0.0.1:8765", "localhost:8765", "[::1]:8765",
        "127.0.0.1", "localhost", "[::1]",
    }
    if host and host not in allowed_hosts:
        return JSONResponse({"detail": "Invalid local agent Host header."}, status_code=403)
    origin = request.headers.get("origin")
    if origin and origin not in ORIGINS:
        return JSONResponse({"detail": "This website is not allowed to connect to NEXORA Local Agent."}, status_code=403)
    return await call_next(request)


class PairRequest(BaseModel):
    code: str = Field(min_length=8, max_length=8, pattern=r"^[0-9]{8}$")
    account_access_token: str = Field(min_length=20, max_length=4096)


class RequirementsRequest(BaseModel):
    profile: str = Field(min_length=1, max_length=40)


class WirelessPairRequest(BaseModel):
    host: str = Field(min_length=7, max_length=64)
    pairing_port: int = Field(ge=1, le=65535)
    connect_port: int = Field(ge=1, le=65535)
    pairing_code: str = Field(min_length=6, max_length=6, pattern=r"^[0-9]{6}$")


def _authority() -> PairingAuthority:
    return get_pairing_authority()


def _bearer(authorization: str | None = Header(default=None)) -> str:
    value = (authorization or "").strip()
    if not value.lower().startswith("bearer "):
        raise HTTPException(401, "Pair this browser with the NEXORA Local Agent first.")
    token = value.split(" ", 1)[1].strip()
    principal = _authority().resolve(token)
    if not principal:
        raise HTTPException(401, "Local agent token is invalid or expired. Pair again.")
    return token


def _require_paired(token: str = Depends(_bearer)) -> str:
    principal = _authority().resolve(token)
    if not principal:
        raise HTTPException(401, "Local agent token is invalid or expired. Pair again.")
    return principal.user_id


def _adb_path() -> str:
    path = shutil.which("adb") or shutil.which("adb.exe")
    if path:
        return path
    profile = collect_system_profile(DATA_ROOT)
    value = ((profile.get("android") or {}).get("adb"))
    if value and Path(value).is_file():
        return str(value)
    raise HTTPException(503, "Android Platform Tools (adb) are not installed or configured on this computer.")


def _run(command: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            stdin=subprocess.DEVNULL,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(504, "The local device command timed out.") from exc
    except OSError as exc:
        raise HTTPException(503, "A required local command could not be started.") from exc


def _validate_serial(serial: str) -> str:
    value = str(serial or "").strip()
    if not SERIAL_RE.fullmatch(value):
        raise HTTPException(422, "Invalid Android device identifier.")
    return value


def _validate_package_id(package_id: str) -> str:
    value = str(package_id or "").strip()
    if not PACKAGE_RE.fullmatch(value):
        raise HTTPException(422, "Invalid Android package ID.")
    return value


def _parse_devices(output: str) -> list[dict[str, str]]:
    devices = []
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith("List of devices") or line.startswith("*"):
            continue
        parts = line.split()
        if len(parts) < 2 or not SERIAL_RE.fullmatch(parts[0]):
            continue
        props: dict[str, str] = {}
        for item in parts[2:]:
            if ":" in item:
                key, value = item.split(":", 1)
                props[key] = value
        devices.append({
            "serial": parts[0],
            "state": parts[1],
            "model": props.get("model", "").replace("_", " ") or parts[0],
            "product": props.get("product", ""),
            "device": props.get("device", ""),
        })
    return devices


def _apk_tools() -> tuple[str | None, str | None]:
    profile = collect_system_profile(DATA_ROOT)
    android = profile.get("android") or {}
    return android.get("apkanalyzer"), android.get("aapt")


def _apk_package_id(path: Path) -> str:
    apkanalyzer, aapt = _apk_tools()
    if apkanalyzer:
        result = _run([apkanalyzer, "manifest", "application-id", str(path)], timeout=20)
        if result.returncode == 0:
            return result.stdout.strip()
    if aapt:
        result = _run([aapt, "dump", "badging", str(path)], timeout=20)
        if result.returncode == 0:
            match = re.search(r"^package: name='([^']+)'", result.stdout, re.MULTILINE)
            if match:
                return match.group(1)
    raise HTTPException(
        503,
        "Android SDK APK inspection is unavailable. Install Android SDK build-tools (aapt) or command-line tools (apkanalyzer).",
    )


@app.on_event("startup")
async def print_pairing_code() -> None:
    authority = _authority()
    code = authority.pairing_code_for_terminal
    if code:
        print("\n" + "=" * 64)
        print("NEXORA LOCAL COMPUTE AGENT")
        print(f"One-time browser pairing code: {code}")
        print("Enter this code in NEXORA Studio. It expires after 15 minutes.")
        print("Agent binding: 127.0.0.1:8765 (loopback only)")
        print("=" * 64 + "\n")


@app.get("/health")
def health():
    return {
        "status": "ready",
        "service": "NEXORA Local Compute Agent",
        "version": VERSION,
        "bound_to_loopback": True,
        "execution_location": "creator_device",
        "pairing_required": True,
    }


def _verify_cloud_account(token: str) -> dict[str, Any]:
    base = os.environ.get("NEXORA_CLOUD_API_URL", "https://nexora-foundry-api.onrender.com").rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1"}:
        raise HTTPException(503, "NEXORA cloud API must use HTTPS for local-agent account pairing.")
    request = UrlRequest(
        base + "/api/v1/auth/me",
        headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=10) as response:
            payload = json.loads(response.read(256 * 1024).decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 401:
            raise HTTPException(401, "Your NEXORA account session expired. Sign in again before pairing this computer.") from exc
        raise HTTPException(503, f"NEXORA account verification failed (HTTP {exc.code}).") from exc
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise HTTPException(503, "Could not verify your NEXORA account with the cloud service. Check your internet connection.") from exc
    user = payload.get("user") if isinstance(payload, dict) else None
    if not isinstance(user, dict) or not user.get("id"):
        raise HTTPException(401, "The cloud service did not return a valid NEXORA account.")
    return user


@app.post("/pair")
def pair(payload: PairRequest):
    account = _verify_cloud_account(payload.account_access_token)
    try:
        token, expires_at = _authority().exchange(
            payload.code,
            user_id=str(account["id"]),
            cloud_access_token=payload.account_access_token,
        )
    except ValueError as exc:
        raise HTTPException(401, str(exc)) from exc
    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_at_epoch": expires_at,
        "expires_in_seconds": 12 * 60 * 60,
        "storage_policy": "memory_only_until_agent_restart_or_expiry",
    }


@app.post("/disconnect")
def disconnect(user_id: str = Depends(_require_paired), authorization: str | None = Header(default=None)):
    token = (authorization or "").split(" ", 1)[-1].strip()
    _authority().revoke(token)
    return {"disconnected": True}


@app.get("/system/capabilities")
def capabilities(user_id: str = Depends(_require_paired)):
    profile = collect_system_profile(DATA_ROOT)
    return {
        **profile,
        "agent": {"version": VERSION, "paired_user": user_id, "execution_location": "creator_device"},
    }


@app.post("/requirements/check")
def requirements(payload: RequirementsRequest, user_id: str = Depends(_require_paired)):
    profile = collect_system_profile(DATA_ROOT)
    try:
        result = check_requirements(payload.profile, profile)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {**result, "checked_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()}


@app.get("/devices")
def devices(user_id: str = Depends(_require_paired)):
    adb = _adb_path()
    result = _run([adb, "devices", "-l"], timeout=15)
    if result.returncode != 0:
        raise HTTPException(503, result.stderr[-1200:] or "ADB could not list connected devices.")
    return {"devices": _parse_devices(result.stdout)}


@app.post("/wireless/pair")
def wireless_pair(payload: WirelessPairRequest, user_id: str = Depends(_require_paired)):
    try:
        address = ipaddress.ip_address(payload.host.strip())
    except ValueError as exc:
        raise HTTPException(422, "Enter a valid private IPv4 or IPv6 address.") from exc
    if not address.is_private or address.is_loopback or address.is_link_local or address.is_multicast:
        raise HTTPException(403, "Wireless pairing is restricted to a private LAN address.")
    adb = _adb_path()
    pair_target = f"{address.compressed}:{payload.pairing_port}"
    connect_target = f"{address.compressed}:{payload.connect_port}"
    paired = _run([adb, "pair", pair_target, payload.pairing_code], timeout=30)
    if paired.returncode != 0:
        raise HTTPException(400, paired.stderr[-1200:] or paired.stdout[-1200:] or "ADB wireless pairing failed.")
    connected = _run([adb, "connect", connect_target], timeout=20)
    if connected.returncode != 0:
        raise HTTPException(400, connected.stderr[-1200:] or connected.stdout[-1200:] or "ADB wireless connection failed.")
    return {"paired": True, "connected": True, "target": connect_target}


@app.post("/install")
async def install_apk(
    file: UploadFile = File(...),
    serial: str = Form(...),
    package_id: str = Form(...),
    confirm_install: bool = Form(...),
    user_id: str = Depends(_require_paired),
):
    if not confirm_install:
        raise HTTPException(403, "Confirm the installation on this computer before proceeding.")
    target_serial = _validate_serial(serial)
    expected_package = _validate_package_id(package_id)
    filename = Path((file.filename or "").replace("\\", "/")).name
    if not filename.lower().endswith(".apk"):
        raise HTTPException(415, "Only APK files can be installed directly. AAB files must be converted through a signed release workflow.")
    temp_path: Path | None = None
    digest = hashlib.sha256()
    total = 0
    try:
        with tempfile.NamedTemporaryFile(prefix="nexora-", suffix=".apk", dir=STAGING_ROOT, delete=False) as stream:
            temp_path = Path(stream.name)
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_APK_BYTES:
                    raise HTTPException(413, "APK exceeds the local 1 GiB installation limit.")
                digest.update(chunk)
                stream.write(chunk)
        if total == 0:
            raise HTTPException(400, "The selected APK is empty.")
        actual_package = _apk_package_id(temp_path)
        if actual_package != expected_package:
            raise HTTPException(
                422,
                f"Package ID mismatch. The APK contains '{actual_package}', but NEXORA expected '{expected_package}'.",
            )
        adb = _adb_path()
        result = _run([adb, "-s", target_serial, "install", "-r", str(temp_path)], timeout=900)
        if result.returncode != 0:
            raise HTTPException(400, result.stderr[-2000:] or result.stdout[-2000:] or "Android installation failed.")
        return {
            "installed": True,
            "serial": target_serial,
            "package_id": actual_package,
            "size_bytes": total,
            "sha256": digest.hexdigest(),
            "message": result.stdout.strip()[-1200:] or "APK installed.",
        }
    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)
        await file.close()


@app.post("/launch")
def launch_game(payload: dict[str, Any], user_id: str = Depends(_require_paired)):
    serial = _validate_serial(str(payload.get("serial") or ""))
    package_id = _validate_package_id(str(payload.get("package_id") or ""))
    adb = _adb_path()
    result = _run([adb, "-s", serial, "shell", "monkey", "-p", package_id, "1"], timeout=30)
    if result.returncode != 0:
        raise HTTPException(400, result.stderr[-1500:] or result.stdout[-1500:] or "Android could not launch the selected package.")
    return {"launched": True, "serial": serial, "package_id": package_id, "output": result.stdout.strip()[-1000:]}


@app.get("/logcat")
def logcat(
    serial: str,
    package_id: str,
    lines: int = 300,
    user_id: str = Depends(_require_paired),
):
    target_serial = _validate_serial(serial)
    package = _validate_package_id(package_id)
    line_count = max(50, min(int(lines), 2000))
    adb = _adb_path()
    pid_result = _run([adb, "-s", target_serial, "shell", "pidof", package], timeout=15)
    pid = pid_result.stdout.strip().split()
    if pid_result.returncode != 0 or not pid or not pid[0].isdigit():
        raise HTTPException(409, "The selected game is not currently running on this device.")
    result = _run([adb, "-s", target_serial, "logcat", "--pid", pid[0], "-d", "-t", str(line_count)], timeout=20)
    if result.returncode != 0:
        raise HTTPException(400, result.stderr[-1000:] or "Could not read the selected app's logcat.")
    return {"logcat": result.stdout[-250_000:], "package_id": package, "pid": pid[0]}


@app.get("/capabilities")
def short_capabilities(user_id: str = Depends(_require_paired)):
    profile = collect_system_profile(DATA_ROOT)
    return {
        "cpu": profile["machine"]["logical_cpu_count"],
        "ram_gib": profile["machine"]["ram_total_gib"],
        "disk_free_gib": profile["machine"]["disk_free_gib"],
        "gpu": profile["gpu"]["primary"],
        "tools": profile["tools"],
        "android": profile["android"],
    }


# Desktop factory APIs are mounted only inside this loopback agent. They are
# deliberately absent from the hosted cloud application.
from services.worker.desktop_factory import register_desktop_factory_routes

register_desktop_factory_routes(app, _require_paired, DATA_ROOT)


# The complete Foundry application is available locally under /engine. Its
# generation endpoints are blocked on the cloud host by execution_policy.py.
# The agent process runs with NEXORA_LOCAL_AGENT=true, so those operations run
# on this machine's CPU/GPU and write to this machine's project directory.
from services.api import main as foundry_main
foundry_app = foundry_main.app
if _SAVED_WORKSPACE_ROOT:
    foundry_main.manager.root = _SAVED_WORKSPACE_ROOT
    foundry_main.manager.root.mkdir(parents=True, exist_ok=True)

app.mount("/engine", foundry_app)
register_local_workspace_routes(app, foundry_main.manager, DATA_ROOT, _require_paired)

# Google Desktop OAuth redirects must target a bare loopback IP:port URI.
# The outer Local Agent therefore receives the callback at http://127.0.0.1:8765,
# while all authenticated NEXORA factory APIs remain mounted under /engine.
from core.nexora_workspace.drive_backup import handle_drive_callback


@app.get("/")
def google_drive_oauth_callback(request: Request):
    return handle_drive_callback(request)



# Desktop factory services: workspace root, portable projects, snapshots,
# toolchain inventory and local store-handoff preparation.
from services.worker.local_factory import register_local_factory_routes
register_local_factory_routes(app)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("services.worker.local_agent:app", host="127.0.0.1", port=PORT, reload=False)
