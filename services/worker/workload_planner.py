"""Resource-aware NEXORA workload placement.

Keep lightweight work on the paired creator device. Fall back to the managed
server only when its measured toolchain and capacity satisfy the workload.
This module plans placement; it does not start jobs or transfer project data.
"""
from __future__ import annotations

from typing import Any


POLICIES: dict[str, dict[str, Any]] = {
    "workspace_editing": {
        "label": "Workspace editing and lightweight scene updates",
        "local": {"cpu": 1, "ram_total": 4, "ram_available": 0.75, "disk": 1, "tools": ()},
        "server": {"cpu": 1, "ram_total": 2, "ram_available": 1, "disk": 1, "tools": ()},
        "remote_preferred": False,
    },
    "procedural_3d": {
        "label": "Procedural 3D assets and Godot scene production",
        "local": {"cpu": 2, "ram_total": 8, "ram_available": 4, "disk": 15, "tools": ("blender", "godot")},
        "server": {"cpu": 4, "ram_total": 16, "ram_available": 4, "disk": 15, "tools": ("blender", "godot")},
        "remote_preferred": False,
    },
    "movie_processing": {
        "label": "Video inspection, keyframes and audio/video processing",
        "local": {"cpu": 2, "ram_total": 6, "ram_available": 2.5, "disk": 10, "tools": ("ffmpeg", "ffprobe")},
        "server": {"cpu": 2, "ram_total": 8, "ram_available": 2.5, "disk": 10, "tools": ("ffmpeg", "ffprobe")},
        "remote_preferred": False,
    },
    "android_export": {
        "label": "Android export and package validation",
        "local": {"cpu": 2, "ram_total": 8, "ram_available": 4, "disk": 25, "tools": ("godot", "java"), "android_sdk": True},
        "server": {"cpu": 2, "ram_total": 8, "ram_available": 4, "disk": 25, "tools": ("godot", "java"), "android_sdk": True},
        "remote_preferred": False,
    },
    "heavy_3d_render": {
        "label": "High-resolution 3D rendering and large scene compilation",
        "local": {"cpu": 8, "ram_total": 24, "ram_available": 10, "disk": 40, "tools": ("blender", "godot")},
        "server": {"cpu": 8, "ram_total": 32, "ram_available": 12, "disk": 40, "tools": ("blender", "godot")},
        "remote_preferred": True,
    },
    "image_to_3d": {
        "label": "GPU image-to-3D reconstruction",
        "local": {"cpu": 6, "ram_total": 16, "ram_available": 6, "disk": 40, "tools": ("blender", "python"), "gpu_vram": 6, "gpu_free_vram": 4},
        "server": {"cpu": 8, "ram_total": 32, "ram_available": 12, "disk": 40, "tools": ("blender", "python"), "gpu_vram": 6, "gpu_free_vram": 4},
        "remote_preferred": False,
    },
}


def _tool_available(profile: dict[str, Any], name: str) -> bool:
    tools = profile.get("tools") or {}
    return bool((tools.get(name) or {}).get("available"))


def assess_capacity(profile: dict[str, Any], requirement: dict[str, Any]) -> dict[str, Any]:
    """Assess a device/worker from live inventory; unknown values fail closed."""
    machine = profile.get("machine") or {}
    gpu = profile.get("gpu") or {}
    failures: list[str] = []

    cpu = machine.get("logical_cpu_count")
    cpu_available = machine.get("cpu_available_cores")
    if cpu_available is None:
        cpu_available = cpu
    if cpu is None or float(cpu) < requirement["cpu"]:
        failures.append(f"CPU: {cpu or 'unknown'} logical cores; {requirement['cpu']} required.")
    elif cpu_available is None or float(cpu_available) < max(1.0, requirement["cpu"] * 0.45):
        failures.append(f"CPU is currently busy; about {cpu_available or 0:g} cores are available.")

    ram_total = machine.get("ram_total_gib")
    if ram_total is None or float(ram_total) < requirement["ram_total"]:
        failures.append(f"Installed RAM: {ram_total or 'unknown'} GiB; {requirement['ram_total']} GiB required.")
    ram_available = machine.get("ram_available_gib")
    if ram_available is None or float(ram_available) < requirement["ram_available"]:
        failures.append(f"Available RAM: {ram_available or 'unknown'} GiB; {requirement['ram_available']} GiB required.")

    disk_free = machine.get("disk_free_gib")
    if disk_free is None or float(disk_free) < requirement["disk"]:
        failures.append(f"Free storage: {disk_free or 'unknown'} GiB; {requirement['disk']} GiB required.")

    for tool in requirement.get("tools", ()):
        if not _tool_available(profile, tool):
            failures.append(f"Required tool is missing: {tool}.")

    if requirement.get("android_sdk"):
        android = profile.get("android") or {}
        if not (android.get("sdk_root") and android.get("build_tools_installed")):
            failures.append("Android SDK platform and build-tools are not ready.")

    if requirement.get("gpu_vram"):
        primary = gpu.get("primary") or {}
        total = float(primary.get("memory_total_bytes") or 0) / (1024 ** 3)
        free = float(primary.get("memory_free_bytes") or 0) / (1024 ** 3)
        if primary.get("vendor") != "NVIDIA":
            failures.append("A supported NVIDIA CUDA GPU is required.")
        if total < requirement["gpu_vram"]:
            failures.append(f"GPU VRAM: {total:g} GiB; {requirement['gpu_vram']} GiB required.")
        if free < requirement["gpu_free_vram"]:
            failures.append(f"Free GPU VRAM: {free:g} GiB; {requirement['gpu_free_vram']} GiB required.")

    return {
        "ready": not failures,
        "failures": failures,
        "measured": {
            "logical_cpu_count": cpu,
            "cpu_available_cores": cpu_available,
            "ram_total_gib": ram_total,
            "ram_available_gib": ram_available,
            "disk_free_gib": disk_free,
        },
    }


def plan_execution(
    workload: str,
    local_profile: dict[str, Any],
    managed_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    """Choose local, managed-server candidate, or unavailable without running work."""
    policy = POLICIES.get(str(workload or "").strip())
    if not policy:
        raise ValueError("Unknown NEXORA workload profile.")

    local = assess_capacity(local_profile or {}, policy["local"])
    server_present = bool(managed_profile and managed_profile.get("available"))
    server = assess_capacity(managed_profile or {}, policy["server"]) if server_present else {
        "ready": False,
        "failures": ["Managed compute worker is not configured or reachable."],
        "measured": {},
    }

    if local["ready"] and not policy["remote_preferred"]:
        location = "creator_device"
        decision = "run_locally"
        reason = "The creator computer has sufficient measured CPU, RAM, storage and tools. Keep this workload local."
    elif server["ready"]:
        location = "managed_server"
        decision = "managed_server_candidate"
        reason = "The creator computer is not a safe fit or this workload is marked for managed compute. The managed worker has the required tools and capacity."
    elif local["ready"]:
        location = "creator_device"
        decision = "run_locally"
        reason = "The managed worker cannot satisfy this workload, but the creator computer can. Keep it local."
    else:
        location = "unavailable"
        decision = "wait_for_capacity"
        reason = "Neither the creator computer nor the configured managed worker meets this workload's requirements."

    return {
        "workload": workload,
        "label": policy["label"],
        "decision": decision,
        "execution_location": location,
        "reason": reason,
        "local": local,
        "managed_server": server,
        "requires_remote_project_transfer": location == "managed_server",
        "requires_remote_upload_confirmation": location == "managed_server",
        "job_submission_enabled": False,
        "note": "This is a placement preflight only. It does not upload project files or start a production job.",
    }
