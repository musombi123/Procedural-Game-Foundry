"""Local-first NEXORA factory services.

Mounted only by the loopback Local Agent. These routes never run on Render.
They manage the creator-selected workspace, portable Godot projects, complete
project snapshots, toolchain inventories, and release handoff packages.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import tempfile
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from fastapi import Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from services.worker.local_security import get_pairing_authority
from services.worker.system_profile import check_requirements, collect_system_profile

ROOT_LOCK = threading.RLock()
MAX_IMPORT_BYTES = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_FILES = 50_000
MAX_ARCHIVE_UNPACKED_BYTES = 20 * 1024 * 1024 * 1024
MAX_SINGLE_FILE_BYTES = 4 * 1024 * 1024 * 1024
MAX_COMPRESSION_RATIO = 250
SKIP_DIRS = {".git", ".godot", "__pycache__", "node_modules", ".venv", "venv"}
OFFICIAL_DOWNLOADS = {
    "godot": "https://godotengine.org/download",
    "blender": "https://www.blender.org/download/",
    "ffmpeg": "https://ffmpeg.org/download.html",
    "android_sdk": "https://developer.android.com/tools",
    "java": "https://adoptium.net/temurin/releases/",
    "python": "https://www.python.org/downloads/",
}
PROFILE_TARGETS = {
    "web": ["editor_2d", "procedural_3d"],
    "windows": ["editor_2d", "procedural_3d"],
    "android": ["android_export"],
    "movie": ["movie_processing"],
    "image_to_3d": ["image_to_3d"],
}


class WorkspaceRootRequest(BaseModel):
    path: str = Field(min_length=1, max_length=2048)


class ReleasePrepareRequest(BaseModel):
    project_id: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9_-]+$")
    provider: Literal["google_play", "apple_app_store", "microsoft_store"]
    artifact_path: str = Field(min_length=1, max_length=1024)
    package_id: str = Field(default="", max_length=255)
    version_name: str = Field(default="1.0.0", min_length=1, max_length=64)
    version_code: int = Field(default=1, ge=1, le=2_100_000_000)
    notes: str = Field(default="", max_length=4000)
    confirm_prepare: bool = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _paired_user(authorization: str | None = Header(default=None)) -> str:
    value = (authorization or "").strip()
    if not value.lower().startswith("bearer "):
        raise HTTPException(401, "Pair this browser with the NEXORA Local Agent first.")
    token = value.split(" ", 1)[1].strip()
    principal = get_pairing_authority().resolve(token)
    if not principal:
        raise HTTPException(401, "Local agent token is invalid or expired. Pair again.")
    return str(principal.user_id)


def _manager():
    # Imported after the Foundry app is loaded by local_agent.py.
    from services.api.main import manager
    return manager


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _project_folder(manager: Any, project_id: str, owner_id: str) -> Path:
    try:
        folder = manager.path_for(project_id)
        manager.load(project_id)
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, "Project not found.")
    marker = folder / "nexora_owner.json"
    if not marker.is_file():
        raise HTTPException(403, "This project has no verified NEXORA owner record.")
    try:
        owner = json.loads(marker.read_text(encoding="utf-8")).get("user_id")
    except (OSError, ValueError, TypeError):
        raise HTTPException(500, "Project ownership record is unreadable.")
    if str(owner) != str(owner_id):
        raise HTTPException(404, "Project not found.")
    return folder


def _profile() -> dict[str, Any]:
    return collect_system_profile()


def _tool_rows(profile: dict[str, Any]) -> list[dict[str, Any]]:
    tools = profile.get("tools") or {}
    labels = {
        "godot": ("Godot Engine", "game_engine"),
        "blender": ("Blender", "3d_content"),
        "ffmpeg": ("FFmpeg", "media"),
        "ffprobe": ("FFprobe", "media"),
        "java": ("Java / JDK", "android"),
        "adb": ("Android Debug Bridge", "android"),
        "python": ("Python", "runtime"),
    }
    rows = []
    for tool_id, (label, purpose) in labels.items():
        record = tools.get(tool_id) or {}
        rows.append({
            "id": tool_id,
            "label": label,
            "purpose": purpose,
            "available": bool(record.get("available")),
            "version": record.get("version"),
            "path": record.get("path"),
            "download_url": OFFICIAL_DOWNLOADS.get(tool_id),
            "install_policy": "creator_approved_external_installer",
        })
    android = profile.get("android") or {}
    rows.extend([
        {
            "id": "android_sdk",
            "label": "Android SDK + Build Tools",
            "purpose": "android",
            "available": bool(android.get("sdk_root") and android.get("build_tools_installed")),
            "version": None,
            "path": android.get("sdk_root"),
            "download_url": OFFICIAL_DOWNLOADS["android_sdk"],
            "install_policy": "creator_approved_sdkmanager_setup",
        },
        {
            "id": "android_apk_inspector",
            "label": "APK Inspector (apkanalyzer / aapt)",
            "purpose": "android",
            "available": bool(android.get("ready_to_verify_apk")),
            "version": None,
            "path": android.get("apkanalyzer") or android.get("aapt"),
            "download_url": OFFICIAL_DOWNLOADS["android_sdk"],
            "install_policy": "included_with_android_sdk",
        },
    ])
    return rows


def _ensure_project_metadata(folder: Path, project_id: str, owner_id: str, display_name: str | None = None) -> dict[str, Any]:
    meta_dir = folder / ".nexora"
    meta_path = meta_dir / "project.json"
    if meta_path.is_file():
        try:
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
            if str(metadata.get("owner_id")) != str(owner_id):
                raise HTTPException(404, "Project not found.")
            if metadata.get("project_uuid"):
                return metadata
        except (OSError, ValueError, TypeError):
            raise HTTPException(500, "NEXORA project manifest is unreadable.")
    pgf = json.loads((folder / "pgf.json").read_text(encoding="utf-8"))
    name = display_name or (pgf.get("project") or {}).get("name") or folder.name
    metadata = {
        "schema_version": 1,
        "project_uuid": str(uuid.uuid4()),
        "foundry_project_id": project_id,
        "owner_id": str(owner_id),
        "display_name": str(name)[:80],
        "engine": "Godot",
        "engine_project_path": "source" if (folder / "source" / "project.godot").is_file() else ("game" if (folder / "game" / "project.godot").is_file() else None),
        "created_at": _now(),
        "local_authoritative": True,
        "source_control": "local",
        "cloud_project_copy": False,
    }
    _atomic_json(meta_path, metadata)
    lock_path = meta_dir / "toolchain.lock.json"
    if not lock_path.is_file():
        _atomic_json(lock_path, {
            "schema_version": 1,
            "lock_state": "not_locked",
            "reason": "Run toolchain detection and explicitly lock the versions used by this project.",
            "platform": platform.system().lower(),
            "tools": {},
            "updated_at": _now(),
        })
    return metadata


def _safe_members(archive: zipfile.ZipFile) -> list[tuple[zipfile.ZipInfo, PurePosixPath]]:
    entries = archive.infolist()
    if len(entries) > MAX_ARCHIVE_FILES:
        raise HTTPException(413, "Archive contains too many entries.")
    total = 0
    validated: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
    for info in entries:
        raw = info.filename.replace("\\", "/")
        path = PurePosixPath(raw)
        mode = (info.external_attr >> 16) & 0xFFFF
        if path.is_absolute() or ".." in path.parts or re.match(r"^[A-Za-z]:", raw) or "\x00" in raw:
            raise HTTPException(400, "Archive contains an unsafe file path.")
        if stat.S_ISLNK(mode):
            raise HTTPException(400, "Archive symbolic links are not accepted.")
        if info.file_size > MAX_SINGLE_FILE_BYTES:
            raise HTTPException(413, "Archive contains a file larger than the supported limit.")
        total += info.file_size
        if total > MAX_ARCHIVE_UNPACKED_BYTES:
            raise HTTPException(413, "Archive expands beyond the supported project size.")
        if info.compress_size and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
            raise HTTPException(413, "Archive compression ratio exceeds the safety limit.")
        validated.append((info, path))
    return validated


def _safe_extract(archive: zipfile.ZipFile, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for info, relative in _safe_members(archive):
        output = (target / Path(*relative.parts)).resolve()
        if target.resolve() not in output.parents and output != target.resolve():
            raise HTTPException(400, "Archive attempted to write outside the selected workspace.")
        if info.is_dir():
            output.mkdir(parents=True, exist_ok=True)
            continue
        output.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(info, "r") as source, output.open("wb") as destination:
            shutil.copyfileobj(source, destination, length=1024 * 1024)


def _zip_folder(source: Path, output: Path, exclude_snapshots: bool = True) -> tuple[int, int, str]:
    count = 0
    total = 0
    digest = hashlib.sha256()
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
        for file_path in sorted(source.rglob("*")):
            if not file_path.is_file() or file_path.is_symlink():
                continue
            relative = file_path.relative_to(source)
            if any(part in SKIP_DIRS for part in relative.parts):
                continue
            if exclude_snapshots and len(relative.parts) >= 3 and relative.parts[:2] == (".nexora", "snapshots"):
                continue
            if ".nexora" in relative.parts and "backups" in relative.parts:
                continue
            archive_name = relative.as_posix()
            archive.write(file_path, archive_name)
            count += 1
            total += file_path.stat().st_size
            with file_path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
    return count, total, digest.hexdigest()


def _snapshot_index_path(folder: Path) -> Path:
    return folder / ".nexora" / "snapshots" / "index.json"


def _read_snapshot_index(folder: Path) -> list[dict[str, Any]]:
    path = _snapshot_index_path(folder)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        raise HTTPException(500, "Project snapshot index is unreadable.")


def _create_snapshot(folder: Path, project_id: str, owner_id: str, note: str = "Manual snapshot") -> dict[str, Any]:
    snapshots = folder / ".nexora" / "snapshots"
    snapshots.mkdir(parents=True, exist_ok=True)
    snapshot_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
    archive_path = snapshots / (snapshot_id + ".zip")
    count, total, digest = _zip_folder(folder, archive_path, exclude_snapshots=True)
    record = {
        "id": snapshot_id,
        "project_id": project_id,
        "owner_id": str(owner_id),
        "created_at": _now(),
        "note": (note or "Manual snapshot")[:300],
        "file_count": count,
        "source_bytes": total,
        "archive_bytes": archive_path.stat().st_size,
        "sha256": _sha256(archive_path),
        "content_fingerprint": digest,
        "archive": archive_path.name,
        "restore_supported": True,
    }
    rows = _read_snapshot_index(folder)
    rows.insert(0, record)
    _atomic_json(_snapshot_index_path(folder), rows)
    return record


def _find_snapshot(folder: Path, snapshot_id: str, owner_id: str) -> tuple[dict[str, Any], Path]:
    if not re.fullmatch(r"[A-Za-z0-9T_-]{8,64}", snapshot_id):
        raise HTTPException(422, "Invalid snapshot identifier.")
    row = next((item for item in _read_snapshot_index(folder) if item.get("id") == snapshot_id), None)
    if not row or str(row.get("owner_id")) != str(owner_id):
        raise HTTPException(404, "Snapshot not found.")
    path = (folder / ".nexora" / "snapshots" / str(row.get("archive") or "")).resolve()
    root = (folder / ".nexora" / "snapshots").resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(404, "Snapshot archive is missing.")
    if _sha256(path) != row.get("sha256"):
        raise HTTPException(409, "Snapshot checksum verification failed. Restore is blocked.")
    return row, path


def register_local_factory_routes(app: Any) -> None:
    """Attach local-only factory endpoints to the paired loopback agent."""

    @app.get("/workspace")
    def get_workspace(owner_id: str = Depends(_paired_user)):
        manager = _manager()
        root = Path(manager.root).resolve()
        projects = []
        for definition in manager.list():
            folder = manager.path_for(definition.id)
            marker = folder / "nexora_owner.json"
            try:
                record = json.loads(marker.read_text(encoding="utf-8")) if marker.is_file() else {}
            except (OSError, ValueError):
                continue
            if str(record.get("user_id")) != str(owner_id):
                continue
            metadata = _ensure_project_metadata(folder, definition.id, owner_id)
            projects.append({
                "id": definition.id,
                "project_uuid": metadata["project_uuid"],
                "name": metadata["display_name"],
                "updated_at": datetime.fromtimestamp(folder.stat().st_mtime, timezone.utc).isoformat(),
                "engine_project_path": metadata.get("engine_project_path"),
            })
        try:
            disk = shutil.disk_usage(root)
            free_bytes = int(disk.free)
        except OSError:
            free_bytes = 0
        return {
            "workspace_root": str(root),
            "project_count": len(projects),
            "projects": projects,
            "disk_free_bytes": free_bytes,
            "disk_free_gib": round(free_bytes / (1024 ** 3), 2),
            "authority": "local_filesystem",
        }

    @app.put("/workspace/root")
    def set_workspace_root(payload: WorkspaceRootRequest, owner_id: str = Depends(_paired_user)):
        manager = _manager()
        raw = Path(os.path.expandvars(os.path.expanduser(payload.path.strip())))
        if not raw.is_absolute():
            raise HTTPException(422, "Workspace path must be an absolute path on this computer.")
        try:
            target = raw.resolve()
            target.mkdir(parents=True, exist_ok=True)
            if not target.is_dir():
                raise HTTPException(422, "Selected workspace path is not a directory.")
        except OSError as exc:
            raise HTTPException(400, f"Could not create or access the selected workspace: {exc}") from exc
        if target == Path(target.anchor):
            raise HTTPException(422, "Choose a project folder, not a drive or filesystem root.")
        with ROOT_LOCK:
            current = Path(manager.root).resolve()
            if current != target:
                project_dirs = [item for item in current.iterdir() if item.is_dir() and (item / "pgf.json").is_file()] if current.is_dir() else []
                collisions = [str(target / item.name) for item in project_dirs if (target / item.name).exists()]
                if collisions:
                    raise HTTPException(409, {
                        "code": "WORKSPACE_PROJECT_COLLISION",
                        "message": "The selected folder already contains one or more project IDs. No files were moved.",
                        "conflicts": collisions[:20],
                    })
                for item in project_dirs:
                    shutil.move(str(item), str(target / item.name))
                manager.root = target
        _atomic_json(Path(os.environ.get("NEXORA_LOCAL_AGENT_DATA", str(Path.home() / ".nexora-local-agent"))) / "workspace.json", {
            "workspace_root": str(target),
            "updated_at": _now(),
            "updated_by": str(owner_id),
            "authority": "local_filesystem",
        })
        return {"workspace_root": str(target), "moved_projects": len(project_dirs) if "project_dirs" in locals() else 0, "message": "Workspace location saved. Local project folders remain on this computer."}

    @app.post("/workspace/import")
    async def import_godot_project(file: UploadFile = File(...), owner_id: str = Depends(_paired_user)):
        filename = Path((file.filename or "").replace("\\", "/")).name
        if not filename.lower().endswith(".zip"):
            raise HTTPException(415, "Import a zipped Godot project folder containing project.godot.")
        staging = Path(os.environ.get("NEXORA_LOCAL_AGENT_DATA", str(Path.home() / ".nexora-local-agent"))) / "imports"
        staging.mkdir(parents=True, exist_ok=True)
        uploaded = staging / (uuid.uuid4().hex + ".zip")
        extracted = Path(tempfile.mkdtemp(prefix="nexora-import-", dir=staging))
        total = 0
        try:
            with uploaded.open("wb") as target:
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_IMPORT_BYTES:
                        raise HTTPException(413, "Project archive exceeds the 2 GiB import limit.")
                    target.write(chunk)
            if total == 0:
                raise HTTPException(400, "The selected project archive is empty.")
            try:
                with zipfile.ZipFile(uploaded, "r") as archive:
                    _safe_members(archive)
                    _safe_extract(archive, extracted)
            except zipfile.BadZipFile as exc:
                raise HTTPException(400, "The selected file is not a valid ZIP archive.") from exc
            project_files = list(extracted.rglob("project.godot"))
            project_files = [path for path in project_files if not any(part in SKIP_DIRS for part in path.relative_to(extracted).parts)]
            if len(project_files) != 1:
                raise HTTPException(422, "The archive must contain exactly one Godot project.godot file.")
            source_root = project_files[0].parent
            project_text = project_files[0].read_text(encoding="utf-8", errors="replace")
            found_name = re.search(r'(?m)^config/name\s*=\s*"([^"]{1,80})"', project_text)
            display_name = (found_name.group(1).strip() if found_name else Path(filename).stem)[:80] or "Imported Godot Project"
            from core.project_engine.models import ProjectCreate
            manager = _manager()
            definition = manager.create(ProjectCreate(name=display_name, description="Imported Godot project. Source files remain locally owned.", dimension="3d"))
            folder = manager.path_for(definition.id)
            source_destination = folder / "source"
            shutil.copytree(
                source_root,
                source_destination,
                ignore=shutil.ignore_patterns(*SKIP_DIRS, "*.tmp", "*.bak"),
                symlinks=False,
            )
            owner_marker = {"user_id": str(owner_id), "created_at": _now(), "source": "local_godot_import"}
            _atomic_json(folder / "nexora_owner.json", owner_marker)
            metadata = _ensure_project_metadata(folder, definition.id, owner_id, display_name)
            metadata.update({
                "engine_project_path": "source",
                "imported_from": filename,
                "imported_at": _now(),
                "project_format": "godot",
            })
            _atomic_json(folder / ".nexora" / "project.json", metadata)
            return {
                "imported": True,
                "project_id": definition.id,
                "project_uuid": metadata["project_uuid"],
                "name": display_name,
                "project_path": str(source_destination),
                "message": "Godot project imported into the selected local workspace. Open it in Godot Editor to continue native scene editing.",
            }
        except HTTPException:
            raise
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            raise HTTPException(400, f"Godot project import failed: {exc}") from exc
        finally:
            uploaded.unlink(missing_ok=True)
            shutil.rmtree(extracted, ignore_errors=True)
            await file.close()

    @app.get("/workspace/projects/{project_id}/archive")
    def export_project_archive(project_id: str, owner_id: str = Depends(_paired_user)):
        folder = _project_folder(_manager(), project_id, owner_id)
        _ensure_project_metadata(folder, project_id, owner_id)
        downloads = Path(os.environ.get("NEXORA_LOCAL_AGENT_DATA", str(Path.home() / ".nexora-local-agent"))) / "downloads"
        archive = downloads / f"{project_id}-{uuid.uuid4().hex[:8]}.zip"
        _zip_folder(folder, archive, exclude_snapshots=True)
        return FileResponse(
            archive,
            media_type="application/zip",
            filename=f"nexora-{project_id}.zip",
            background=BackgroundTask(lambda: archive.unlink(missing_ok=True)),
        )

    @app.post("/workspace/projects/{project_id}/open-editor")
    def open_project_in_godot(project_id: str, owner_id: str = Depends(_paired_user)):
        manager = _manager()
        folder = _project_folder(manager, project_id, owner_id)
        metadata = _ensure_project_metadata(folder, project_id, owner_id)
        relative = str(metadata.get("engine_project_path") or "")
        candidate = (folder / relative).resolve() if relative else None
        if not candidate or not (candidate / "project.godot").is_file():
            candidates = [folder / "source", folder / "game", folder]
            candidate = next((path for path in candidates if (path / "project.godot").is_file()), None)
        if not candidate:
            raise HTTPException(409, "Generate or import a Godot project before opening the Godot Editor.")
        root = Path(manager.root).resolve()
        candidate = candidate.resolve()
        if root not in candidate.parents:
            raise HTTPException(403, "Godot project path is outside the selected NEXORA workspace.")
        profile = _profile()
        godot = (profile.get("tools") or {}).get("godot") or {}
        executable = godot.get("path")
        if not executable or not Path(executable).is_file():
            raise HTTPException(503, "Godot 4 is not detected. Install Godot using the official toolchain setup link first.")
        try:
            process = subprocess.Popen(
                [str(executable), "--editor", "--path", str(candidate)],
                cwd=str(candidate),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
                close_fds=True,
            )
        except OSError as exc:
            raise HTTPException(503, f"Could not launch the local Godot Editor: {exc}") from exc
        return {"launched": True, "process_id": process.pid, "project_path": str(candidate), "message": "Godot Editor launched on this computer."}

    @app.get("/toolchains")
    def list_toolchains(owner_id: str = Depends(_paired_user)):
        profile = _profile()
        checks = {}
        for profile_id in ("editor_2d", "procedural_3d", "movie_processing", "android_export", "image_to_3d"):
            try:
                checks[profile_id] = check_requirements(profile_id, profile)
            except ValueError:
                continue
        return {
            "operating_system": platform.system(),
            "architecture": platform.machine(),
            "tools": _tool_rows(profile),
            "workload_profiles": checks,
            "installation_policy": "NEXORA detects tools and provides official setup guidance. Third-party installers and licence prompts remain under creator control.",
            "automatic_installation": False,
        }

    @app.get("/workspace/projects/{project_id}/toolchain-lock")
    def get_toolchain_lock(project_id: str, owner_id: str = Depends(_paired_user)):
        folder = _project_folder(_manager(), project_id, owner_id)
        _ensure_project_metadata(folder, project_id, owner_id)
        path = folder / ".nexora" / "toolchain.lock.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise HTTPException(500, "Project toolchain lock is unreadable.")

    @app.post("/workspace/projects/{project_id}/toolchain-lock")
    def lock_detected_toolchains(project_id: str, owner_id: str = Depends(_paired_user)):
        folder = _project_folder(_manager(), project_id, owner_id)
        _ensure_project_metadata(folder, project_id, owner_id)
        profile = _profile()
        tools = {}
        for item in _tool_rows(profile):
            if not item["available"]:
                continue
            path = Path(item["path"]) if item.get("path") else None
            fingerprint = None
            size = None
            if path and path.is_file() and path.stat().st_size <= 512 * 1024 * 1024:
                size = path.stat().st_size
                fingerprint = _sha256(path)
            tools[item["id"]] = {
                "version": item.get("version"),
                "path": str(path) if path else None,
                "binary_sha256": fingerprint,
                "binary_bytes": size,
                "detected_at": _now(),
            }
        lock = {
            "schema_version": 1,
            "lock_state": "detected_and_recorded",
            "platform": platform.system().lower(),
            "architecture": platform.machine(),
            "tools": tools,
            "integrity_note": "Executable hashes are recorded when a directly accessible tool binary is under 512 MiB. Hashes establish file integrity, not publisher identity or licence rights.",
            "updated_at": _now(),
        }
        _atomic_json(folder / ".nexora" / "toolchain.lock.json", lock)
        return {"saved": True, "lock": lock}

    @app.post("/workspace/projects/{project_id}/snapshots")
    def create_project_snapshot(project_id: str, note: str = Form(default="Manual snapshot"), owner_id: str = Depends(_paired_user)):
        folder = _project_folder(_manager(), project_id, owner_id)
        _ensure_project_metadata(folder, project_id, owner_id)
        return {"snapshot": _create_snapshot(folder, project_id, owner_id, note)}

    @app.get("/workspace/projects/{project_id}/snapshots")
    def list_project_snapshots(project_id: str, owner_id: str = Depends(_paired_user)):
        folder = _project_folder(_manager(), project_id, owner_id)
        rows = [row for row in _read_snapshot_index(folder) if str(row.get("owner_id")) == str(owner_id)]
        return {"snapshots": rows}

    @app.get("/workspace/projects/{project_id}/snapshots/{snapshot_id}/download")
    def download_project_snapshot(project_id: str, snapshot_id: str, owner_id: str = Depends(_paired_user)):
        folder = _project_folder(_manager(), project_id, owner_id)
        row, archive = _find_snapshot(folder, snapshot_id, owner_id)
        return FileResponse(
            archive,
            media_type="application/zip",
            filename=f"nexora-{project_id}-{snapshot_id}.zip",
        )

    @app.post("/workspace/projects/{project_id}/snapshots/{snapshot_id}/restore")
    def restore_project_snapshot(project_id: str, snapshot_id: str, owner_id: str = Depends(_paired_user)):
        folder = _project_folder(_manager(), project_id, owner_id)
        row, archive = _find_snapshot(folder, snapshot_id, owner_id)
        safety_snapshot = _create_snapshot(folder, project_id, owner_id, f"Automatic pre-restore safety point before {snapshot_id}")
        staging_root = Path(os.environ.get("NEXORA_LOCAL_AGENT_DATA", str(Path.home() / ".nexora-local-agent"))) / "restore"
        staging_root.mkdir(parents=True, exist_ok=True)
        extracted = Path(tempfile.mkdtemp(prefix="nexora-restore-", dir=staging_root))
        keep: Path | None = None
        try:
            with zipfile.ZipFile(archive, "r") as source:
                _safe_members(source)
                _safe_extract(source, extracted)
            if not (extracted / "pgf.json").is_file():
                raise HTTPException(409, "Snapshot is missing its Foundry project definition.")
            snapshots_root = folder / ".nexora" / "snapshots"
            keep = staging_root / ("preserved-snapshots-" + uuid.uuid4().hex)
            if snapshots_root.exists():
                shutil.copytree(snapshots_root, keep)
            for child in list(folder.iterdir()):
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink(missing_ok=True)
            for child in extracted.iterdir():
                destination = folder / child.name
                if child.is_dir():
                    shutil.copytree(child, destination)
                else:
                    shutil.copy2(child, destination)
            if keep.exists():
                shutil.rmtree(folder / ".nexora" / "snapshots", ignore_errors=True)
                (folder / ".nexora").mkdir(exist_ok=True)
                shutil.move(str(keep), str(folder / ".nexora" / "snapshots"))
            return {"restored": True, "snapshot_id": snapshot_id, "safety_snapshot_id": safety_snapshot["id"], "message": "Project files restored. A separate safety snapshot was retained before the restore."}
        finally:
            shutil.rmtree(extracted, ignore_errors=True)
            if keep and keep.exists():
                shutil.rmtree(keep, ignore_errors=True)

    @app.get("/publishing/status")
    def publishing_status(owner_id: str = Depends(_paired_user)):
        system = platform.system()
        apple_ready = system == "Darwin" and bool(shutil.which("xcodebuild"))
        google_configured = bool(os.environ.get("NEXORA_GOOGLE_PLAY_SERVICE_ACCOUNT_FILE"))
        apple_configured = bool(os.environ.get("NEXORA_APP_STORE_CONNECT_KEY_ID") and os.environ.get("NEXORA_APP_STORE_CONNECT_ISSUER_ID") and os.environ.get("NEXORA_APP_STORE_CONNECT_PRIVATE_KEY_FILE"))
        microsoft_configured = bool(os.environ.get("NEXORA_MICROSOFT_STORE_CLIENT_ID") and os.environ.get("NEXORA_MICROSOFT_STORE_APP_ID"))
        return {
            "execution_location": "creator_device",
            "publish_actions_require_explicit_confirmation": True,
            "providers": [
                {"id": "google_play", "label": "Google Play", "account_owner": "creator", "platform_ready": True, "credentials_configured": google_configured, "status": "credentials_required" if not google_configured else "connector_configuration_required", "artifact": "Android AAB", "upload_is_not_approval": True},
                {"id": "apple_app_store", "label": "Apple App Store", "account_owner": "creator", "platform_ready": apple_ready, "credentials_configured": apple_configured, "status": "requires_mac_xcode_and_creator_credentials" if not apple_ready or not apple_configured else "connector_configuration_required", "artifact": "Signed IPA", "upload_is_not_approval": True},
                {"id": "microsoft_store", "label": "Microsoft Store", "account_owner": "creator", "platform_ready": system == "Windows", "credentials_configured": microsoft_configured, "status": "creator_partner_center_setup_required", "artifact": "MSIX", "upload_is_not_approval": True},
            ],
            "credential_policy": "Signing keys, service-account files and publisher tokens must remain in the creator's OS credential vault or protected local files. NEXORA does not accept secrets in project manifests or browser storage.",
            "drive_backup": {"available": False, "status": "google_oauth_client_id_and_drive_file_scope_not_configured", "optional": True},
        }

    @app.post("/publishing/prepare")
    def prepare_store_handoff(payload: ReleasePrepareRequest, owner_id: str = Depends(_paired_user)):
        if not payload.confirm_prepare:
            raise HTTPException(403, "Confirm preparation of this release handoff package.")
        manager = _manager()
        # Find and verify ownership through the project ID embedded in an artifact path.
        artifact_rel = PurePosixPath(payload.artifact_path.replace("\\", "/"))
        if artifact_rel.is_absolute() or ".." in artifact_rel.parts:
            raise HTTPException(422, "Artifact path must remain inside the selected project.")
        if len(artifact_rel.parts) < 2:
            raise HTTPException(422, "Select an artifact inside a project folder.")
        project_id = artifact_rel.parts[0]
        folder = _project_folder(manager, project_id, owner_id)
        artifact = (folder / Path(*artifact_rel.parts[1:])).resolve()
        if folder.resolve() not in artifact.parents or not artifact.is_file():
            raise HTTPException(404, "Release artifact not found in this project.")
        expected_suffix = {
            "google_play": {".aab"},
            "apple_app_store": {".ipa"},
            "microsoft_store": {".msix"},
        }[payload.provider]
        if artifact.suffix.lower() not in expected_suffix:
            raise HTTPException(422, f"{payload.provider} requires one of these artifact formats: {', '.join(sorted(expected_suffix))}.")
        if payload.provider == "google_play" and not re.fullmatch(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+", payload.package_id.strip().lower()):
            raise HTTPException(422, "Google Play package ID must use reverse-DNS format.")
        if payload.provider == "apple_app_store" and platform.system() != "Darwin":
            raise HTTPException(409, "Apple signing and final export require a Mac with Xcode. This handoff cannot be prepared as an IPA on the current operating system.")
        release_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
        release_root = folder / ".nexora" / "releases" / release_id
        release_root.mkdir(parents=True, exist_ok=False)
        digest = _sha256(artifact)
        manifest = {
            "schema_version": 1,
            "release_id": release_id,
            "project_id": project_id,
            "project_uuid": _ensure_project_metadata(folder, project_id, owner_id)["project_uuid"],
            "owner_id": str(owner_id),
            "provider": payload.provider,
            "artifact_name": artifact.name,
            "artifact_relative_path": artifact.relative_to(folder).as_posix(),
            "artifact_bytes": artifact.stat().st_size,
            "artifact_sha256": digest,
            "package_id": payload.package_id.strip(),
            "version_name": payload.version_name,
            "version_code": payload.version_code,
            "release_notes": payload.notes,
            "prepared_at": _now(),
            "publication_status": "prepared_not_submitted",
            "creator_confirmation_required_before_upload": True,
            "store_approval_not_guaranteed": True,
        }
        _atomic_json(release_root / "release-manifest.json", manifest)
        handoff = release_root / "nexora-release-handoff.zip"
        with zipfile.ZipFile(handoff, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as package:
            package.write(artifact, artifact.name)
            package.write(release_root / "release-manifest.json", "release-manifest.json")
        manifest["handoff_archive"] = str(handoff.relative_to(folder).as_posix())
        _atomic_json(release_root / "release-manifest.json", manifest)
        return {
            "prepared": True,
            "publication_status": "prepared_not_submitted",
            "release": manifest,
            "handoff_archive": str(handoff),
            "message": "Release handoff package prepared locally. Nothing has been uploaded or published to a store.",
        }
