"""Frozen Windows entry point for the NEXORA Local Agent.

The installer registers this executable in the current user's Startup folder.
It runs without a console, binds to loopback only, and writes diagnostics under
%LOCALAPPDATA%\\NEXORA\\Agent\\logs.
"""
from __future__ import annotations

import ctypes
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_environment() -> Path:
    local_app_data = Path(
        os.environ.get("LOCALAPPDATA")
        or (Path.home() / "AppData" / "Local")
    )
    root = local_app_data / "NEXORA"
    agent_data = root / "Agent"
    foundry_data = root / "Foundry"
    (agent_data / "logs").mkdir(parents=True, exist_ok=True)
    foundry_data.mkdir(parents=True, exist_ok=True)

    os.environ["NEXORA_LOCAL_AGENT"] = "true"
    os.environ.setdefault("NEXORA_AUTH_REQUIRED", "true")
    os.environ.setdefault("NEXORA_ENV", "local")
    os.environ.setdefault("NEXORA_LOCAL_AGENT_DATA", str(agent_data))
    os.environ.setdefault("PGF_DATA_DIR", str(foundry_data))

    allowed_origins = (
        "https://revelacode.co.ke,"
        "https://www.revelacode.co.ke,"
        "http://localhost:5174,"
        "http://127.0.0.1:5174,"
        "http://localhost:5173,"
        "http://127.0.0.1:5173,"
        "tauri://localhost"
    )
    os.environ.setdefault("NEXORA_LOCAL_ALLOWED_ORIGINS", allowed_origins)
    os.environ.setdefault("NEXORA_CORS_ORIGINS", os.environ["NEXORA_LOCAL_ALLOWED_ORIGINS"])
    return agent_data


def acquire_single_instance_lock(agent_data: Path):
    """Prevent duplicate tray/startup invocations from creating port conflicts."""
    if os.name != "nt":
        return None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, "Local\\NEXORA.LocalAgent.Singleton.v1")
    if not handle:
        raise OSError(ctypes.get_last_error(), "Could not create NEXORA Local Agent instance lock.")
    ERROR_ALREADY_EXISTS = 183
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False
    return (kernel32, handle)


def configure_logging(agent_data: Path) -> None:
    log_file = agent_data / "logs" / "local-agent.log"
    handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=4,
        encoding="utf-8",
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[handler],
        force=True,
    )


def main() -> int:
    agent_data = configure_environment()
    configure_logging(agent_data)

    if "--self-test" in sys.argv:
        from services.worker.local_agent import app
        from services.worker.local_security import PairingAuthority
        assert app.title == "NEXORA Local Compute Agent"
        assert PairingAuthority is not None
        logging.info("NEXORA Local Agent package self-test passed.")
        return 0

    instance_lock = acquire_single_instance_lock(agent_data)
    if instance_lock is False:
        logging.info("NEXORA Local Agent is already running; duplicate startup ignored.")
        return 0

    try:
        import uvicorn
        from services.worker.local_agent import app

        logging.info("NEXORA Local Agent starting on 127.0.0.1:8765.")
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=8765,
            reload=False,
            access_log=False,
            log_config=None,
            log_level="info",
        )
        return 0
    except Exception:
        logging.exception("NEXORA Local Agent stopped unexpectedly.")
        return 1
    finally:
        if instance_lock:
            kernel32, handle = instance_lock
            kernel32.CloseHandle(handle)


if __name__ == "__main__":
    raise SystemExit(main())
