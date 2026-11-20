"""Local device hardware and toolchain discovery for NEXORA.

The probe is intentionally read-only. It never installs drivers, downloads
models, benchmarks the GPU, or launches user-supplied executables.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


GIB = 1024 ** 3


def _memory_total_bytes() -> int | None:
    system = platform.system().lower()
    if system == "windows":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MEMORYSTATUSEX()
            status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullTotalPhys)
        except Exception:
            return None
    if system in {"linux", "darwin"}:
        try:
            return int(os.sysconf("SC_PAGE_SIZE")) * int(os.sysconf("SC_PHYS_PAGES"))
        except (ValueError, OSError, AttributeError):
            pass
    if system == "darwin":
        value = _run_text(["sysctl", "-n", "hw.memsize"], timeout=3)
        try:
            return int(value.strip())
        except (ValueError, AttributeError):
            return None
    return None


def _memory_available_bytes() -> int | None:
    system = platform.system().lower()
    if system == "windows":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MEMORYSTATUSEX()
            status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullAvailPhys)
        except Exception:
            return None
    if system == "linux":
        try:
            values = {}
            for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                key, _, value = line.partition(":")
                if key in {"MemAvailable", "MemFree"}:
                    values[key] = int(value.strip().split()[0]) * 1024
            return values.get("MemAvailable", values.get("MemFree"))
        except (OSError, ValueError, IndexError):
            return None
    if system == "darwin":
        output = _run_text(["vm_stat"], timeout=3)
        page_size = 4096
        match = re.search(r"page size of (\d+) bytes", output)
        if match:
            page_size = int(match.group(1))
        page_counts = {}
        for label in ("Pages free", "Pages inactive", "Pages speculative"):
            found = re.search(rf"{re.escape(label)}:\s+(\d+)", output)
            if found:
                page_counts[label] = int(found.group(1))
        if page_counts:
            return sum(page_counts.values()) * page_size
    return None


def _cpu_model() -> str | None:
    candidates: list[str] = []
    if platform.system().lower() == "windows":
        candidates.extend([os.environ.get("PROCESSOR_IDENTIFIER", ""), platform.processor()])
    elif platform.system().lower() == "darwin":
        value = _run_text(["sysctl", "-n", "machdep.cpu.brand_string"], timeout=3)
        candidates.append(value)
    else:
        try:
            for line in Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.lower().startswith(("model name", "hardware")) and ":" in line:
                    candidates.append(line.split(":", 1)[1].strip())
                    break
        except OSError:
            candidates.append(platform.processor())
    return next((item.strip() for item in candidates if item and item.strip()), None)


def _run_text(command: list[str], timeout: int = 4) -> str:
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, check=False,
            stdin=subprocess.DEVNULL, shell=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _find_tool(env_name: str, candidates: tuple[str, ...]) -> str | None:
    configured = os.environ.get(env_name, "").strip()
    if configured:
        path = Path(configured).expanduser()
        if path.is_file():
            return str(path.resolve())
        located = shutil.which(configured)
        if located:
            return str(Path(located).resolve())
    for candidate in candidates:
        located = shutil.which(candidate)
        if located:
            return str(Path(located).resolve())
    return None


def _tool_version(path: str | None, args: tuple[str, ...] = ("--version",)) -> str | None:
    if not path:
        return None
    text = _run_text([path, *args], timeout=5)
    if not text:
        return "Installed; version could not be read"
    return text.splitlines()[0][:180]


def _gpu_adapters() -> list[dict[str, Any]]:
    executable = _find_tool("NEXORA_NVIDIA_SMI_PATH", ("nvidia-smi", "nvidia-smi.exe"))
    if not executable:
        return []
    output = _run_text(
        [
            executable,
            "--query-gpu=name,memory.total,memory.free,driver_version",
            "--format=csv,noheader,nounits",
        ],
        timeout=8,
    )
    result: list[dict[str, Any]] = []
    for line in output.splitlines():
        parts = [item.strip() for item in line.split(",")]
        if len(parts) < 4:
            continue
        try:
            total_mb = int(float(parts[1]))
            free_mb = int(float(parts[2]))
        except ValueError:
            continue
        result.append(
            {
                "name": parts[0],
                "vendor": "NVIDIA",
                "memory_total_bytes": total_mb * 1024 * 1024,
                "memory_free_bytes": free_mb * 1024 * 1024,
                "driver_version": parts[3],
                "compute_backend": "CUDA",
            }
        )
    return result


def _android_sdk() -> dict[str, Any]:
    roots = [
        os.environ.get("ANDROID_SDK_ROOT", ""),
        os.environ.get("ANDROID_HOME", ""),
    ]
    root = next((Path(item).expanduser() for item in roots if item and Path(item).expanduser().is_dir()), None)
    adb_candidates = [
        str(root / "platform-tools" / ("adb.exe" if os.name == "nt" else "adb")) if root else "",
    ]
    adb_path = _find_tool("NEXORA_ADB_PATH", tuple(item for item in adb_candidates if item) + ("adb", "adb.exe"))
    build_tools = sorted((root / "build-tools").glob("*")) if root and (root / "build-tools").is_dir() else []
    apkanalyzer_candidates = [
        str(root / "cmdline-tools" / "latest" / "bin" / ("apkanalyzer.bat" if os.name == "nt" else "apkanalyzer")) if root else "",
    ]
    apkanalyzer = _find_tool(
        "NEXORA_APKANALYZER_PATH",
        tuple(item for item in apkanalyzer_candidates if item) + ("apkanalyzer", "apkanalyzer.bat"),
    )
    aapt_name = "aapt.exe" if os.name == "nt" else "aapt"
    aapt_candidates = [str(item / aapt_name) for item in build_tools]
    aapt = _find_tool("NEXORA_AAPT_PATH", tuple(aapt_candidates) + ("aapt", "aapt.exe"))
    return {
        "sdk_root": str(root.resolve()) if root else None,
        "adb": adb_path,
        "apkanalyzer": apkanalyzer,
        "aapt": aapt,
        "build_tools_installed": bool(build_tools),
        "ready_for_device_install": bool(adb_path),
        "ready_to_verify_apk": bool(apkanalyzer or aapt),
    }


def _triposr_worker_status() -> dict[str, Any]:
    root_value = os.environ.get("NEXORA_TRIPOSR_ROOT", "").strip()
    root = Path(root_value).expanduser() if root_value else None
    runner = root / "run.py" if root else None
    if not runner or not runner.is_file():
        return {
            "available": False,
            "root_configured": bool(root_value),
            "cuda_available": False,
            "reason": "TripoSR run.py is not configured.",
        }

    python_value = os.environ.get("NEXORA_TRIPOSR_PYTHON", "").strip()
    python_path = str(Path(python_value).expanduser()) if python_value else sys.executable
    located = shutil.which(python_path) if not Path(python_path).is_file() else python_path
    if not located:
        return {
            "available": False,
            "root_configured": True,
            "python_path": python_path,
            "cuda_available": False,
            "reason": "The configured TripoSR Python interpreter was not found.",
        }
    command = [
        located,
        "-c",
        "import json,torch; ok=bool(torch.cuda.is_available()); "
        "print(json.dumps({'torch_version':getattr(torch,'__version__','unknown'),"
        "'cuda_available':ok,'cuda_version':getattr(torch.version,'cuda',None),"
        "'gpu_name':torch.cuda.get_device_name(0) if ok else None}))",
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=25,
            check=False,
            stdin=subprocess.DEVNULL,
            shell=False,
        )
        if result.returncode != 0:
            return {
                "available": False,
                "root_configured": True,
                "python_path": str(Path(located).resolve()),
                "cuda_available": False,
                "reason": (result.stderr or result.stdout or "PyTorch CUDA probe failed")[-900:],
            }
        data = json.loads(result.stdout.strip().splitlines()[-1])
        cuda_available = bool(data.get("cuda_available"))
        return {
            "available": cuda_available,
            "root_configured": True,
            "python_path": str(Path(located).resolve()),
            "torch_version": data.get("torch_version"),
            "cuda_version": data.get("cuda_version"),
            "cuda_available": cuda_available,
            "gpu_name": data.get("gpu_name"),
            "reason": None if cuda_available else "PyTorch is installed but torch.cuda.is_available() returned false.",
        }
    except subprocess.TimeoutExpired:
        return {
            "available": False,
            "root_configured": True,
            "python_path": str(Path(located).resolve()),
            "cuda_available": False,
            "reason": "PyTorch CUDA initialization probe timed out after 25 seconds.",
        }
    except (OSError, ValueError, IndexError) as exc:
        return {
            "available": False,
            "root_configured": True,
            "python_path": str(Path(located).resolve()),
            "cuda_available": False,
            "reason": str(exc)[:900],
        }


def collect_system_profile(data_root: str | Path | None = None) -> dict[str, Any]:
    """Return a bounded, privacy-conscious resource and toolchain inventory."""
    cpu_count = os.cpu_count() or 1
    ram_bytes = _memory_total_bytes()
    ram_available_bytes = _memory_available_bytes()
    root = Path(data_root or os.environ.get("PGF_DATA_DIR") or Path.home()).expanduser()
    try:
        root.mkdir(parents=True, exist_ok=True)
        disk = shutil.disk_usage(root)
        disk_total, disk_free = int(disk.total), int(disk.free)
    except OSError:
        disk_total = disk_free = 0

    tools = {
        "python": {"path": sys.executable, "version": platform.python_version(), "available": True},
        "blender": None,
        "godot": None,
        "ffmpeg": None,
        "ffprobe": None,
        "adb": None,
        "java": None,
        "nvidia_smi": None,
    }
    definitions = {
        "blender": ("NEXORA_BLENDER_PATH", ("blender", "blender.exe"), ("--version",)),
        "godot": ("NEXORA_GODOT_PATH", ("godot", "godot4", "godot.exe", "godot4.exe"), ("--version",)),
        "ffmpeg": ("NEXORA_FFMPEG_PATH", ("ffmpeg", "ffmpeg.exe"), ("-version",)),
        "ffprobe": ("NEXORA_FFPROBE_PATH", ("ffprobe", "ffprobe.exe"), ("-version",)),
        "adb": ("NEXORA_ADB_PATH", ("adb", "adb.exe"), ("version",)),
        "java": ("NEXORA_JAVA_PATH", ("java", "java.exe"), ("-version",)),
        "nvidia_smi": ("NEXORA_NVIDIA_SMI_PATH", ("nvidia-smi", "nvidia-smi.exe"), ("--version",)),
    }
    for name, (env_name, candidates, args) in definitions.items():
        path = _find_tool(env_name, candidates)
        tools[name] = {
            "path": path,
            "available": bool(path),
            "version": _tool_version(path, args),
        }

    gpu_adapters = _gpu_adapters()
    android = _android_sdk()
    return {
        "schema_version": "1.0",
        "machine": {
            "os": platform.system(),
            "os_release": platform.release(),
            "architecture": platform.machine(),
            "cpu_model": _cpu_model(),
            "logical_cpu_count": int(cpu_count),
            "ram_total_bytes": ram_bytes,
            "ram_total_gib": round(ram_bytes / GIB, 2) if ram_bytes else None,
            "ram_available_bytes": ram_available_bytes,
            "ram_available_gib": round(ram_available_bytes / GIB, 2) if ram_available_bytes is not None else None,
            "disk_root": str(root.resolve()),
            "disk_total_bytes": disk_total,
            "disk_free_bytes": disk_free,
            "disk_free_gib": round(disk_free / GIB, 2) if disk_free else None,
        },
        "gpu": {
            "accelerators": gpu_adapters,
            "nvidia_cuda_available": bool(gpu_adapters),
            "primary": gpu_adapters[0] if gpu_adapters else None,
        },
        "tools": tools,
        "android": android,
        "workers": {
            "triposr": _triposr_worker_status(),
        },
        "privacy": {
            "sent_to_cloud": False,
            "note": "This inventory is returned to the local studio only; it is not uploaded to NEXORA cloud.",
        },
    }


PROFILES: dict[str, dict[str, Any]] = {
    "editor_2d": {
        "label": "2D and lightweight projects",
        "min_cpu_cores": 2,
        "min_ram_gib": 8,
        "min_available_ram_gib": 2,
        "min_disk_gib": 10,
        "required_tools": ("godot",),
        "recommended_tools": (),
        "gpu_vram_gib": 0,
        "requires_nvidia": False,
    },
    "procedural_3d": {
        "label": "Procedural 3D production",
        "min_cpu_cores": 4,
        "min_ram_gib": 16,
        "min_available_ram_gib": 4,
        "min_disk_gib": 30,
        "required_tools": ("blender", "godot"),
        "recommended_tools": ("ffmpeg", "ffprobe"),
        "gpu_vram_gib": 0,
        "requires_nvidia": False,
    },
    "movie_processing": {
        "label": "Movie and video processing",
        "min_cpu_cores": 4,
        "min_ram_gib": 8,
        "min_available_ram_gib": 2.5,
        "min_disk_gib": 20,
        "required_tools": ("ffmpeg", "ffprobe"),
        "recommended_tools": ("blender", "godot"),
        "gpu_vram_gib": 0,
        "requires_nvidia": False,
    },
    "image_to_3d": {
        "label": "AI image-to-3D reconstruction (TripoSR baseline)",
        "min_cpu_cores": 6,
        "min_ram_gib": 16,
        "min_available_ram_gib": 6,
        "min_disk_gib": 40,
        "required_tools": ("blender", "python"),
        "recommended_tools": ("godot",),
        "gpu_vram_gib": 6,
        "gpu_free_vram_gib": 4,
        "requires_nvidia": True,
    },
    "android_export": {
        "label": "Android build and device testing",
        "min_cpu_cores": 4,
        "min_ram_gib": 16,
        "min_available_ram_gib": 4,
        "min_disk_gib": 25,
        "required_tools": ("godot", "java", "adb"),
        "recommended_tools": ("ffmpeg",),
        "gpu_vram_gib": 0,
        "requires_nvidia": False,
    },
}


def check_requirements(profile_id: str, profile: dict[str, Any]) -> dict[str, Any]:
    """Evaluate one workload profile; missing optional GPU does not block normal 3D."""
    requirements = PROFILES.get(profile_id)
    if not requirements:
        raise ValueError("Unknown compute profile.")
    machine = profile.get("machine") or {}
    tools = profile.get("tools") or {}
    gpu = profile.get("gpu") or {}
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str, required: bool = True) -> None:
        checks.append({
            "name": name,
            "status": "pass" if ok else ("fail" if required else "warning"),
            "required": required,
            "detail": detail,
        })

    cpu = int(machine.get("logical_cpu_count") or 0)
    add("CPU", cpu >= requirements["min_cpu_cores"], f"{cpu} logical cores detected; {requirements['min_cpu_cores']} recommended minimum.")
    ram = float(machine.get("ram_total_gib") or 0)
    add("Memory", ram >= requirements["min_ram_gib"], f"{ram:g} GiB installed; {requirements['min_ram_gib']} GiB required.")
    available_ram = machine.get("ram_available_gib")
    if available_ram is None:
        add("Available RAM", False, "Current free memory could not be measured on this operating system.", required=False)
    else:
        available_ram = float(available_ram)
        minimum_available = float(requirements.get("min_available_ram_gib", 0))
        add(
            "Available RAM",
            available_ram >= minimum_available,
            f"{available_ram:g} GiB currently available; {minimum_available:g} GiB recommended for this workload.",
        )
    disk = float(machine.get("disk_free_gib") or 0)
    add("Free storage", disk >= requirements["min_disk_gib"], f"{disk:g} GiB free; {requirements['min_disk_gib']} GiB required.")

    for tool in requirements["required_tools"]:
        available = bool(tools.get(tool, {}).get("available"))
        add(tool, available, "Detected." if available else f"{tool} is not installed or not on PATH.")
    for tool in requirements["recommended_tools"]:
        available = bool(tools.get(tool, {}).get("available"))
        add(tool, available, "Detected." if available else f"{tool} is recommended for this workload.", required=False)

    if profile_id == "android_export":
        android = profile.get("android") or {}
        sdk_ready = bool(android.get("sdk_root") and android.get("build_tools_installed"))
        add("Android SDK", sdk_ready, "Android SDK and build-tools detected." if sdk_ready else "Install Android SDK command-line tools and at least one build-tools version.")
        apk_inspector_ready = bool(android.get("ready_to_verify_apk"))
        add("APK inspector", apk_inspector_ready, "apkanalyzer or aapt detected." if apk_inspector_ready else "Install Android SDK command-line tools or build-tools so NEXORA can inspect package IDs before installation.")

    if profile_id == "image_to_3d":
        triposr = profile.get("workers", {}).get("triposr") or {}
        add(
            "TripoSR worker",
            bool(triposr.get("available")),
            f"TripoSR and PyTorch CUDA are ready on {triposr.get('gpu_name') or 'the local GPU'}." if triposr.get("available") else str(triposr.get("reason") or "Install TripoSR and a CUDA-enabled PyTorch environment; set NEXORA_TRIPOSR_ROOT and optionally NEXORA_TRIPOSR_PYTHON."),
        )

    if requirements["requires_nvidia"]:
        primary = gpu.get("primary") or {}
        is_nvidia = bool(primary.get("vendor") == "NVIDIA")
        vram = (float(primary.get("memory_total_bytes") or 0) / GIB)
        free_vram = (float(primary.get("memory_free_bytes") or 0) / GIB)
        add("CUDA GPU", is_nvidia, "NVIDIA CUDA-capable GPU detected." if is_nvidia else "This image-to-3D worker currently requires a supported NVIDIA CUDA GPU.")
        add("GPU memory", vram >= requirements["gpu_vram_gib"], f"{vram:g} GiB total VRAM detected; {requirements['gpu_vram_gib']} GiB minimum for the current TripoSR profile.")
        add("Available GPU memory", free_vram >= requirements["gpu_free_vram_gib"], f"{free_vram:g} GiB free VRAM detected; {requirements['gpu_free_vram_gib']} GiB must be free before starting TripoSR.")
    ready = all(item["status"] != "fail" for item in checks)
    return {
        "profile": profile_id,
        "label": requirements["label"],
        "ready": ready,
        "checks": checks,
        "summary": "This device meets the selected workload requirements." if ready else "This device does not yet meet every required item. Choose a lighter workload or install/upgrade the missing requirements.",
        "execution_location": "creator_device",
    }
