"""Private NEXORA managed-compute toolchain service.

This service is deployed as a private Render service from the dedicated Docker
image. It only reports its installed toolchain and resource capacity. Job
submission remains disabled until the queue, artifact store and data-transfer
contract are configured.
"""
from __future__ import annotations

import hmac
import math
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from services.worker.system_profile import collect_system_profile
from services.worker.workload_planner import plan_execution


DATA_ROOT = Path(os.environ.get("NEXORA_COMPUTE_WORKSPACE_ROOT", "/tmp/nexora-compute"))
SERVICE_KEY = os.environ.get("NEXORA_MANAGED_COMPUTE_SECRET", "").strip()
GIB = 1024 ** 3

app = FastAPI(
    title="NEXORA Managed Compute Runtime",
    version="1.0.0",
    description="Private server-side toolchain inventory and workload placement preflight.",
)


def _read_text(path: str) -> str:
    try:
        return Path(path).read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        return ""


def _apply_container_limits(profile: dict[str, Any]) -> dict[str, Any]:
    """Use cgroup quotas rather than host totals when measuring container capacity."""
    machine = profile.setdefault("machine", {})
    cpu_limits = _read_text("/sys/fs/cgroup/cpu.max").split()
    if len(cpu_limits) == 2 and cpu_limits[0] != "max":
        try:
            quota, period = int(cpu_limits[0]), int(cpu_limits[1])
            if quota > 0 and period > 0:
                cpu_limit = max(1, math.floor(quota / period))
                machine["logical_cpu_count"] = min(int(machine.get("logical_cpu_count") or cpu_limit), cpu_limit)
                utilization = machine.get("cpu_utilization_percent")
                if utilization is not None:
                    machine["cpu_available_cores"] = round(
                        machine["logical_cpu_count"] * (1.0 - min(100.0, max(0.0, float(utilization))) / 100.0),
                        2,
                    )
        except ValueError:
            pass

    memory_limit_text = _read_text("/sys/fs/cgroup/memory.max")
    memory_current_text = _read_text("/sys/fs/cgroup/memory.current")
    if memory_limit_text and memory_limit_text != "max":
        try:
            memory_limit = int(memory_limit_text)
            memory_current = int(memory_current_text or 0)
            if memory_limit > 0:
                available = max(0, memory_limit - memory_current)
                machine["ram_total_bytes"] = memory_limit
                machine["ram_total_gib"] = round(memory_limit / GIB, 2)
                machine["ram_available_bytes"] = available
                machine["ram_available_gib"] = round(available / GIB, 2)
        except ValueError:
            pass

    # Job scratch is ephemeral. Customer projects and long-lived artifacts are
    # never persisted to the container image layer.
    try:
        DATA_ROOT.mkdir(parents=True, exist_ok=True)
        disk = os.statvfs(DATA_ROOT)
        free = int(disk.f_bavail * disk.f_frsize)
        machine["disk_root"] = str(DATA_ROOT)
        machine["disk_free_bytes"] = free
        machine["disk_free_gib"] = round(free / GIB, 2)
    except OSError:
        machine["disk_free_bytes"] = 0
        machine["disk_free_gib"] = 0
    return profile


def _profile() -> dict[str, Any]:
    return _apply_container_limits(collect_system_profile(DATA_ROOT))


def _required_tool_state(profile: dict[str, Any]) -> dict[str, bool]:
    tools = profile.get("tools") or {}
    android = profile.get("android") or {}
    return {
        "blender": bool((tools.get("blender") or {}).get("available")),
        "godot": bool((tools.get("godot") or {}).get("available")),
        "ffmpeg": bool((tools.get("ffmpeg") or {}).get("available")),
        "ffprobe": bool((tools.get("ffprobe") or {}).get("available")),
        "java": bool((tools.get("java") or {}).get("available")),
        "adb": bool(android.get("adb") or (tools.get("adb") or {}).get("available")),
        "android_sdk": bool(android.get("sdk_root") and android.get("build_tools_installed")),
        "android_apk_inspector": bool(android.get("ready_to_verify_apk")),
    }


def _public_profile(profile: dict[str, Any]) -> dict[str, Any]:
    machine = profile.get("machine") or {}
    return {
        "schema_version": profile.get("schema_version"),
        "machine": {
            "os": machine.get("os"),
            "architecture": machine.get("architecture"),
            "logical_cpu_count": machine.get("logical_cpu_count"),
            "cpu_available_cores": machine.get("cpu_available_cores"),
            "ram_total_gib": machine.get("ram_total_gib"),
            "ram_available_gib": machine.get("ram_available_gib"),
            "disk_free_gib": machine.get("disk_free_gib"),
        },
        "gpu": {
            "nvidia_cuda_available": bool((profile.get("gpu") or {}).get("nvidia_cuda_available")),
            "primary": (profile.get("gpu") or {}).get("primary"),
        },
        "tools": {
            key: {
                "available": bool((value or {}).get("available")),
                "version": (value or {}).get("version"),
            }
            for key, value in (profile.get("tools") or {}).items()
        },
        "android": {
            "sdk_root": (profile.get("android") or {}).get("sdk_root"),
            "build_tools_installed": bool((profile.get("android") or {}).get("build_tools_installed")),
            "ready_to_verify_apk": bool((profile.get("android") or {}).get("ready_to_verify_apk")),
        },
    }


def _authorize(x_nexora_compute_key: str | None) -> None:
    if not SERVICE_KEY:
        raise HTTPException(503, "Managed compute service secret is not configured.")
    if not x_nexora_compute_key or not hmac.compare_digest(x_nexora_compute_key, SERVICE_KEY):
        raise HTTPException(401, "Managed compute service authentication failed.")


class PlanRequest(BaseModel):
    workload: str = Field(min_length=1, max_length=40)
    local_profile: dict[str, Any]


@app.get("/health")
def health():
    profile = _profile()
    required = _required_tool_state(profile)
    return {
        "status": "ready" if all(required.values()) else "degraded",
        "service": "NEXORA Managed Compute Runtime",
        "toolchain": required,
        "toolchain_ready": all(required.values()),
        "execution_location": "managed_server",
        "job_submission_enabled": False,
    }


@app.get("/internal/capabilities")
def capabilities(x_nexora_compute_key: str | None = Header(default=None)):
    _authorize(x_nexora_compute_key)
    profile = _profile()
    required = _required_tool_state(profile)
    return {
        "available": True,
        "service": "NEXORA Managed Compute Runtime",
        "toolchain_ready": all(required.values()),
        "toolchain": required,
        "profile": _public_profile(profile),
        "execution_location": "managed_server",
        "job_submission_enabled": False,
        "note": "Server-side toolchain is installed. Job transfer/queue execution is not enabled by this runtime-only service.",
    }


@app.post("/internal/plan")
def plan(payload: PlanRequest, x_nexora_compute_key: str | None = Header(default=None)):
    _authorize(x_nexora_compute_key)
    server_profile = _profile()
    required = _required_tool_state(server_profile)
    managed = {
        **server_profile,
        "available": all(required.values()),
    }
    return plan_execution(payload.workload, payload.local_profile, managed)
