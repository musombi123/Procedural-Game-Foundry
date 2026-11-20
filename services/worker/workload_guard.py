"""Fail-closed local hardware preflight for production jobs."""
from __future__ import annotations

from fastapi import HTTPException

from services.worker.system_profile import check_requirements, collect_system_profile


def require_device_profile(profile_id: str) -> dict:
    """Raise before a production job is queued when this device is underpowered."""
    profile = collect_system_profile()
    result = check_requirements(profile_id, profile)
    if not result.get("ready"):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "DEVICE_REQUIREMENTS_NOT_MET",
                "message": result.get("summary") or "This device does not meet the workload requirements.",
                **result,
            },
        )
    return result
