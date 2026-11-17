from __future__ import annotations
import os, shutil
from typing import Annotated
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from . import adb
from .security import PairingState, validate_package_id, validate_serial

HOST = "127.0.0.1"
PORT = int(os.getenv("NEXORA_BRIDGE_PORT", "8765"))
ALLOWED_ORIGINS = {v.strip().rstrip("/") for v in os.getenv("NEXORA_BRIDGE_ALLOWED_ORIGINS", "https://revelacode.co.ke,https://www.revelacode.co.ke").split(",") if v.strip()}
pairing = PairingState()
app = FastAPI(title="NEXORA Desktop Device Bridge", version="0.1.0", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(CORSMiddleware, allow_origins=sorted(ALLOWED_ORIGINS), allow_credentials=False,
                   allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["Authorization", "Content-Type"], max_age=300)

@app.middleware("http")
async def loopback_only(request: Request, call_next):
    client = request.client.host if request.client else ""
    if client not in {"127.0.0.1", "::1"}:
        raise HTTPException(status_code=403, detail="The device bridge only accepts loopback connections.")
    host = request.headers.get("host", "").split(":", 1)[0].strip("[]").lower()
    if host not in {"127.0.0.1", "localhost"}:
        raise HTTPException(status_code=403, detail="Invalid local bridge host header.")
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") not in ALLOWED_ORIGINS:
        raise HTTPException(status_code=403, detail="This origin is not allowed to control the local device bridge.")
    return await call_next(request)

def require_pairing(authorization: Annotated[str | None, Header()] = None) -> None:
    scheme, _, token = str(authorization or "").partition(" ")
    if scheme.casefold() != "bearer" or not pairing.authorize(token.strip()):
        raise HTTPException(status_code=401, detail="Pair this desktop bridge before using device operations.")

class PairRequest(BaseModel):
    code: str = Field(min_length=8, max_length=8, pattern=r"^\\d{8}$")

class WirelessPairRequest(BaseModel):
    host: str
    pairing_port: int = Field(ge=1024, le=65535)
    connect_port: int = Field(ge=1024, le=65535)
    pairing_code: str = Field(min_length=6, max_length=6, pattern=r"^\\d{6}$")

class AppRequest(BaseModel):
    serial: str
    package_id: str

@app.get("/health")
def health():
    return {"status": "ready", "product": "NEXORA Desktop Device Bridge", "paired": pairing.paired,
            "adb_available": bool(os.getenv("NEXORA_ADB_PATH") or shutil.which("adb"))}

@app.post("/pair")
def pair(request: PairRequest):
    token = pairing.pair(request.code)
    if not token:
        raise HTTPException(status_code=401, detail="Pairing code is invalid, expired or locked. Restart the desktop bridge to generate a new code.")
    return {"paired": True, "access_token": token}

@app.get("/devices", dependencies=[Depends(require_pairing)])
def devices():
    try:
        return {"devices": adb.list_devices()}
    except adb.AdbError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

@app.post("/wireless/pair", dependencies=[Depends(require_pairing)])
def wireless_pair(request: WirelessPairRequest):
    try:
        return adb.pair_wireless(request.host, request.pairing_port, request.pairing_code, request.connect_port)
    except (adb.AdbError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@app.post("/install", dependencies=[Depends(require_pairing)])
async def install(file: UploadFile = File(...), serial: str = Form(...), package_id: str = Form(...), confirm_install: bool = Form(...)):
    if confirm_install is not True:
        raise HTTPException(status_code=400, detail="Explicit installation confirmation is required.")
    try:
        validate_serial(serial)
        validate_package_id(package_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not (file.filename or "").lower().endswith(".apk"):
        raise HTTPException(status_code=415, detail="Only APK files can be installed. AAB files are not directly installable.")
    import tempfile
    from pathlib import Path
    try:
        with tempfile.TemporaryDirectory(prefix="nexora-apk-") as directory:
            apk_path = Path(directory) / "creator-build.apk"
            total = 0
            with apk_path.open("wb") as destination:
                while chunk := await file.read(1024 * 1024):
                    total += len(chunk)
                    if total > adb.MAX_APK_BYTES:
                        raise HTTPException(status_code=413, detail="APK exceeds the 1 GB transfer limit.")
                    destination.write(chunk)
            if total == 0:
                raise HTTPException(status_code=400, detail="APK file is empty.")
            result = adb.install_apk_file(serial, package_id, apk_path)
            return {"installed": True, **result}
    except (adb.AdbError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await file.close()

@app.post("/launch", dependencies=[Depends(require_pairing)])
def launch(request: AppRequest):
    try:
        return {"launched": True, **adb.launch_app(request.serial, request.package_id)}
    except (adb.AdbError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@app.get("/logcat", dependencies=[Depends(require_pairing)])
def logcat(serial: str, package_id: str, lines: int = 300):
    try:
        return adb.read_logcat(serial, package_id, lines)
    except (adb.AdbError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
