"""Fail-closed local hardware preflight for production jobs."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import HTTPException

from services.worker.system_profile import check_requirements, collect_system_profile


def require_device_profile(profile_id: str) -> dict:
    """Fail closed on hardware readiness and explicit local-device consent."""
    bond = None
    if os.environ.get("NEXORA_LOCAL_AGENT", "").lower() == "true":
        from services.worker.device_bond import load_bond
        data_root = Path(os.environ.get(
            "NEXORA_LOCAL_AGENT_DATA",
            str(Path.home() / ".nexora-local-agent"),
        )).expanduser()
        bond = load_bond(data_root)
        if not bond.get("enabled"):
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "DEVICE_ACCESS_BOND_REQUIRED",
                    "message": "Enable the Device Access Bond on this computer before starting a local production job.",
                },
            )
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
    if bond:
        result["device_access_bond"] = {
            "enabled": True,
            "limits": bond.get("limits", {}),
            "consent_policy": "creator_started_jobs_only",
        }
    return result
