"""Desktop-only NEXORA factory endpoints consumed by the static Studio UI.

All handlers execute inside the paired loopback Foundry engine. The cloud
execution policy rejects /api/v1/desktop/* requests before these handlers run.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from http.client import HTTPSConnection
from zipfile import ZipFile

from fastapi import APIRouter, File, Form, HTTPException, Request as FastAPIRequest, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from core.asset_registry.registry import AssetRegistry
from core.nexora_workspace.desktop_factory import _levels_path, validate_level_manifest, validate_monetization_manifest
from core.nexora_workspace.local_factory import (
    _archive_project, _atomic_json, _ensure_project_layout, _project, _safe_extract,
    EXCLUDED_DIRS, MAX_BACKUP_BYTES,
)
from core.project_engine.models import ProjectCreate
from services.worker.system_profile import collect_system_profile
from services.worker.local_workspace import set_workspace_root
from core.nexora_workspace.drive_oauth import (
    begin_drive_oauth, drive_access_token, drive_status, disconnect_drive,
)
from core.nexora_workspace.default_assets import (
    catalog as default_asset_catalog,
    install_pack as install_default_asset_pack,
)
from core.nexora_workspace.polyhaven_assets import (
    PolyHavenError,
    download_model as download_polyhaven_model,
    search_models as search_polyhaven_models,
)

TEXT_EXTENSIONS = {
    ".gd", ".tscn", ".tres", ".godot", ".cfg", ".ini", ".json", ".md", ".txt",
    ".yml", ".yaml", ".toml", ".xml", ".csv", ".shader", ".gdshader", ".cs",
    ".js", ".ts", ".html", ".css", ".py", ".ps1", ".sh", ".bat", ".sql",
}
MAX_EDIT_BYTES = 2 * 1024 * 1024
WINGET_PACKAGES = {
    "godot": "GodotEngine.GodotEngine",
    "blender": "BlenderFoundation.Blender",
    "ffmpeg": "Gyan.FFmpeg",
    "java17": "EclipseAdoptium.Temurin.17.JDK",
}
SNAPSHOT_SCHEMA = 1


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _owner(request: FastAPIRequest) -> str:
    value = getattr(request.state, "nexora_user_id", None)
    if not value:
        raise HTTPException(401, "Sign in to your NEXORA account.")
    return str(value)


def _safe_relative(raw: str) -> Path:
    raw_value = str(raw or "").replace("\\", "/")
    # Check absolute syntax before trimming separators; trimming first would
    # turn "/outside.gd" into a seemingly harmless relative filename.
    if raw_value.startswith("/") or (
        len(raw_value) >= 3 and raw_value[1] == ":" and raw_value[2] == "/"
    ):
        raise HTTPException(400, "Invalid project-relative path.")
    value = raw_value.strip("/")
    candidate = Path(value)
    if not value:
        return Path(".")
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        raise HTTPException(400, "Invalid project-relative path.")
    return candidate


def _resolve_project_path(folder: Path, raw: str) -> Path:
    relative = _safe_relative(raw)
    root = folder.resolve()
    candidate = root
    for part in relative.parts:
        candidate = candidate / part
        # Check each lexical component before resolve() follows any symlink.
        if candidate.is_symlink():
            raise HTTPException(403, "Symbolic links are not editable through NEXORA Studio.")
    target = candidate.resolve()
    if root not in target.parents and target != root:
        raise HTTPException(403, "Project path escapes the selected project.")
    return target


def _create_project_text_file(folder: Path, raw_path: str, content: str) -> dict:
    """Create a new, bounded text source file inside an existing project directory."""
    relative = _safe_relative(raw_path)
    if relative == Path(".") or relative.name == "nexora_owner.json" or relative.suffix.lower() not in TEXT_EXTENSIONS:
        raise HTTPException(415, "Choose a supported text source-file extension.")
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_EDIT_BYTES:
        raise HTTPException(413, "New source file exceeds the 2 MiB editor limit.")
    target = _resolve_project_path(folder, raw_path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        # Re-resolve after directory creation and re-check the project boundary.
        target = _resolve_project_path(folder, raw_path)
        with target.open("xb") as stream:
            stream.write(encoded)
    except FileExistsError as exc:
        raise HTTPException(409, "A file already exists at this path. Open it instead of overwriting it.") from exc
    except OSError as exc:
        raise HTTPException(400, "The source file could not be created in this project folder.") from exc
    return {
        "created": True,
        "path": target.relative_to(folder.resolve()).as_posix(),
        "size_bytes": len(encoded),
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }


def _snapshot_dir(manager: Any, pid: str) -> Path:
    root = Path(manager.root) / ".nexora-snapshots" / pid
    root.mkdir(parents=True, exist_ok=True)
    return root


def _snapshot_records(manager: Any, pid: str) -> list[dict]:
    root = _snapshot_dir(manager, pid)
    records = []
    for path in sorted(root.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("project_id") == pid:
                records.append(record)
        except (OSError, ValueError):
            continue
    return records


def _create_snapshot(manager: Any, folder: Path, definition: Any, owner_id: str) -> dict:
    snapshot_id = "snap_" + uuid.uuid4().hex[:20]
    root = _snapshot_dir(manager, definition.id)
    archive = root / f"{snapshot_id}.zip"
    report = _archive_project(folder, archive)
    archive_hash = hashlib.sha256()
    with archive.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            archive_hash.update(chunk)
    record = {
        "schema_version": SNAPSHOT_SCHEMA,
        "id": snapshot_id,
        "project_id": definition.id,
        "owner_id": owner_id,
        "created_at": _utc(),
        "archive_path": str(archive),
        **report,
        "sha256": archive_hash.hexdigest(),
    }
    _atomic_json(root / f"{snapshot_id}.json", record)
    return record


def _restore_archive(manager: Any, folder: Path, definition: Any, owner_id: str, archive: Path) -> dict:
    stage_root = Path(manager.root) / ".nexora-restore-staging"
    stage_root.mkdir(parents=True, exist_ok=True)
    stage = stage_root / uuid.uuid4().hex
    replacement = folder.parent / f".{folder.name}.restore-{uuid.uuid4().hex}"
    rollback = folder.parent / f".{folder.name}.rollback-{uuid.uuid4().hex}"
    stage.mkdir()
    try:
        report = _safe_extract(archive, stage)
        pgf_path = stage / "pgf.json"
        if not pgf_path.is_file():
            raise HTTPException(422, "Backup does not contain a NEXORA project definition.")
        try:
            pgf = json.loads(pgf_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise HTTPException(422, "Backup project definition is corrupt.")
        if str(pgf.get("id")) != str(definition.id):
            raise HTTPException(409, "Backup belongs to a different project ID.")
        try:
            from core.project_engine.models import ProjectDefinition
            ProjectDefinition.model_validate(pgf)
        except Exception as exc:
            raise HTTPException(422, "Backup project definition does not match the current NEXORA project schema.") from exc

        owner_file = stage / "nexora_owner.json"
        if owner_file.is_file():
            try:
                backup_owner = json.loads(owner_file.read_text(encoding="utf-8")).get("user_id")
            except (OSError, ValueError):
                raise HTTPException(422, "Backup ownership metadata is invalid.")
            if str(backup_owner) != owner_id:
                raise HTTPException(404, "Backup not found.")

        # NEXORA's project manifest is independently owner-bound. Reject a
        # backup whose project ID or account ownership contradicts its marker.
        manifest_path = stage / ".nexora" / "project.json"
        if manifest_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raise HTTPException(422, "Backup NEXORA project manifest is invalid.")
            if str(manifest.get("project_id") or "") != str(definition.id):
                raise HTTPException(409, "Backup manifest belongs to a different project ID.")
            if str(manifest.get("owner_id") or "") != owner_id:
                raise HTTPException(404, "Backup not found.")

        # Construct a complete replacement beside the existing project. The
        # live project is not touched until extraction, schema and ownership
        # checks and all copies have succeeded.
        replacement.mkdir(parents=True, exist_ok=False)
        for item in stage.iterdir():
            if item.name == "nexora_owner.json":
                continue
            destination = replacement / item.name
            if item.is_dir():
                shutil.copytree(item, destination, symlinks=False)
            else:
                shutil.copy2(item, destination, follow_symlinks=False)

        # Preserve the currently authenticated owner marker, not an archive
        # supplied marker. Snapshot history lives outside this project folder.
        current_owner = folder / "nexora_owner.json"
        if not current_owner.is_file():
            raise HTTPException(500, "The current project owner marker is missing.")
        replacement_owner = replacement / "nexora_owner.json"
        shutil.copy2(current_owner, replacement_owner, follow_symlinks=False)

        original_moved = False
        try:
            folder.rename(rollback)
            original_moved = True
            replacement.rename(folder)
            manager.load(definition.id)
        except Exception as exc:
            # Never delete the live folder unless the original has definitely
            # been moved to the rollback path. A failed first rename leaves it
            # untouched and this branch must not remove it.
            if original_moved:
                if folder.exists():
                    shutil.rmtree(folder, ignore_errors=True)
                if rollback.exists() and not folder.exists():
                    rollback.rename(folder)
            raise HTTPException(500, "Project restore failed validation; the previous project was restored unchanged.") from exc

        shutil.rmtree(rollback, ignore_errors=True)
        return {"restored": True, "files": report["file_count"], "expanded_bytes": report["expanded_bytes"]}
    finally:
        shutil.rmtree(stage, ignore_errors=True)
        shutil.rmtree(replacement, ignore_errors=True)


def _drive_request(user_id: str, method: str, url: str, body: bytes | None = None, headers: dict | None = None) -> dict:
    token = drive_access_token(user_id)
    request_headers = {"Authorization": "Bearer " + token, "Accept": "application/json", **(headers or {})}
    request = Request(url, data=body, headers=request_headers, method=method)
    try:
        with urlopen(request, timeout=45) as response:
            raw = response.read(2 * 1024 * 1024)
            return json.loads(raw.decode("utf-8")) if raw else {}
    except HTTPError as exc:
        detail = exc.read(4096).decode("utf-8", "replace")
        raise HTTPException(exc.code, "Google Drive request failed: " + detail[:800]) from exc
    except (URLError, OSError, ValueError) as exc:
        raise HTTPException(503, "Could not connect to Google Drive.") from exc


def _drive_list_project_backups(user_id: str, pid: str) -> list[dict]:
    escaped = pid.replace("\\", "\\\\").replace("'", "\\'")
    query = "trashed=false and appProperties has { key='nexoraProjectId' and value='" + escaped + "' }"
    url = "https://www.googleapis.com/drive/v3/files?" + urlencode({
        "q": query,
        "spaces": "drive",
        "pageSize": "100",
        "orderBy": "modifiedTime desc",
        "fields": "files(id,name,size,modifiedTime,appProperties,mimeType)",
    })
    result = _drive_request(user_id, "GET", url)
    return result.get("files", [])


def _drive_upload_file(user_id: str, source: Path, metadata: dict) -> dict:
    token = drive_access_token(user_id)
    size = source.stat().st_size
    if size <= 0 or size > MAX_BACKUP_BYTES:
        raise HTTPException(413, "Google Drive accepts non-empty project backups up to 2 GiB.")
    start_url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable"
    headers = {
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": "application/zip",
        "X-Upload-Content-Length": str(size),
    }
    request = Request(start_url, data=json.dumps(metadata).encode("utf-8"), headers=headers, method="POST")
    try:
        with urlopen(request, timeout=30) as response:
            location = response.headers.get("Location")
    except (HTTPError, URLError, OSError) as exc:
        raise HTTPException(503, "Google Drive could not start a resumable backup upload.") from exc
    if not location:
        raise HTTPException(502, "Google Drive did not return a resumable upload URL.")
    parsed = urlsplit(location)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"www.googleapis.com", "upload.googleapis.com"}
        or parsed.username
        or parsed.password
    ):
        raise HTTPException(502, "Google Drive returned an untrusted resumable-upload endpoint.")
    connection = HTTPSConnection(parsed.hostname, parsed.port or 443, timeout=120)
    chunk_size = 8 * 1024 * 1024  # Multiple of Google's 256 KiB resumable-upload granularity.
    sent = 0
    retries_without_progress = 0
    try:
        with source.open("rb") as stream:
            while sent < size:
                stream.seek(sent)
                chunk = stream.read(min(chunk_size, size - sent))
                if not chunk:
                    raise HTTPException(500, "Local backup ended before the expected upload size.")
                start_byte = sent
                end_byte = sent + len(chunk) - 1
                connection.putrequest("PUT", parsed.path + (("?" + parsed.query) if parsed.query else ""))
                connection.putheader("Authorization", "Bearer " + token)
                connection.putheader("Content-Type", "application/zip")
                connection.putheader("Content-Length", str(len(chunk)))
                connection.putheader("Content-Range", f"bytes {start_byte}-{end_byte}/{size}")
                connection.endheaders()
                connection.send(chunk)
                response = connection.getresponse()
                raw = response.read(1024 * 1024)
                if response.status in {200, 201}:
                    try:
                        return json.loads(raw.decode("utf-8")) if raw else {}
                    except ValueError as exc:
                        raise HTTPException(502, "Google Drive returned an invalid upload response.") from exc
                if response.status != 308:
                    raise HTTPException(502, "Google Drive resumable upload failed: " + raw.decode("utf-8", "replace")[:800])
                acknowledged = response.getheader("Range")
                if acknowledged:
                    match = re.fullmatch(r"bytes=0-(\d+)", acknowledged.strip())
                    if not match:
                        raise HTTPException(502, "Google Drive returned an invalid resumable-upload Range header.")
                    next_sent = int(match.group(1)) + 1
                else:
                    next_sent = 0
                if next_sent <= sent:
                    retries_without_progress += 1
                    if retries_without_progress > 3:
                        raise HTTPException(503, "Google Drive upload made no forward progress after three retries.")
                else:
                    retries_without_progress = 0
                if next_sent > size:
                    raise HTTPException(502, "Google Drive acknowledged bytes beyond the local backup size.")
                sent = next_sent
        raise HTTPException(502, "Google Drive ended the resumable session without completing the backup.")
    except OSError as exc:
        raise HTTPException(503, "The Google Drive upload connection was interrupted.") from exc
    finally:
        connection.close()


def _drive_download_file(user_id: str, file_id: str, destination: Path) -> None:
    token = drive_access_token(user_id)
    url = "https://www.googleapis.com/drive/v3/files/" + file_id + "?alt=media"
    request = Request(url, headers={"Authorization": "Bearer " + token}, method="GET")
    total = 0
    try:
        with urlopen(request, timeout=90) as response, destination.open("xb") as stream:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_BACKUP_BYTES:
                    raise HTTPException(413, "Google Drive backup exceeds the 2 GiB restore limit.")
                stream.write(chunk)
    except HTTPError as exc:
        raise HTTPException(exc.code, "Google Drive backup could not be downloaded.") from exc
    except (URLError, OSError) as exc:
        raise HTTPException(503, "Could not download the backup from Google Drive.") from exc


class WorkspaceFileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=1024)
    content: str = Field(max_length=2 * 1024 * 1024)
    expected_sha256: str = Field(min_length=64, max_length=64)


class WorkspaceFileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=1024)
    content: str = Field(default="", max_length=2 * 1024 * 1024)


class DesktopWorkspaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=3, max_length=2048)
    confirm_migration: bool = False


class DesktopImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=3, max_length=2048)
    name: str | None = Field(default=None, max_length=80)


class ToolchainInstallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tools: list[str] = Field(min_length=1, max_length=10)
    confirm_install: bool = False


class PublishPrepareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platform: str = Field(pattern=r"^(android|web|windows|linux)$")
    artifact_id: str = Field(min_length=1, max_length=100)
    version: str = Field(default="1.0.0", min_length=1, max_length=40, pattern=r"^[0-9A-Za-z][0-9A-Za-z.+_-]*$")
    release_notes: str = Field(default="", max_length=5000)
    rights_confirmed: bool = False


class ToolchainLockRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str | None = None
    targets: list[str] = Field(default_factory=lambda: ["web", "android", "windows"])


class DefaultAssetPackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pack_id: str = Field(pattern=r"^(adventure|fantasy|sci_fi|modern)$")
    overwrite_existing: bool = False


class PolyHavenModelDownloadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9_]+$")
    resolution: str = Field(default="2k", pattern=r"^(1k|2k|4k)$")


def register_desktop_factory_routes(app: Any, manager: Any) -> None:
    router = APIRouter()

    @router.get("/api/v1/desktop/status")
    def desktop_status(request: FastAPIRequest):
        owner_id = _owner(request)
        profile = collect_system_profile(manager.root)
        projects = []
        for definition in manager.list():
            folder = manager.path_for(definition.id)
            owner_file = folder / "nexora_owner.json"
            try:
                if json.loads(owner_file.read_text(encoding="utf-8")).get("user_id") == owner_id:
                    projects.append(definition.id)
            except (OSError, ValueError):
                continue
        disk = shutil.disk_usage(manager.root)
        return {
            "machine": profile.get("machine", {}),
            "gpu": profile.get("gpu", {}),
            "tools": profile.get("tools", {}),
            "android": profile.get("android", {}),
            "workspace_root": str(Path(manager.root).resolve()),
            "projects": len(projects),
            "execution_location": "creator_device",
            "cloud_compute_enabled": False,
            "disk": {"total": disk.total, "used": disk.used, "free": disk.free},
        }

    @router.put("/api/v1/desktop/workspace")
    def change_workspace(payload: DesktopWorkspaceRequest, request: FastAPIRequest):
        owner_id = _owner(request)
        agent_root = Path(os.environ.get("NEXORA_LOCAL_AGENT_DATA", str(Path.home() / ".nexora-local-agent"))).expanduser().resolve()
        return set_workspace_root(manager, agent_root, payload.path, owner_id, payload.confirm_migration)

    @router.get("/api/v1/desktop/projects/{pid}/monetization")
    def get_project_monetization(pid: str, request: FastAPIRequest):
        folder, definition, _ = _project(manager, pid, request)
        path = folder / ".nexora" / "monetization.json"
        if not path.is_file():
            return validate_monetization_manifest({})
        try:
            return validate_monetization_manifest(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError) as exc:
            raise HTTPException(500, "The local monetization settings are unreadable or invalid.") from exc

    @router.put("/api/v1/desktop/projects/{pid}/monetization")
    def save_project_monetization(pid: str, payload: dict, request: FastAPIRequest):
        folder, definition, _ = _project(manager, pid, request)
        try:
            manifest = validate_monetization_manifest(payload)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        path = folder / ".nexora" / "monetization.json"
        _atomic_json(path, manifest)
        game_folder = folder / "game"
        if game_folder.is_dir():
            # This public runtime manifest contains IDs and feature flags only;
            # credentials and private purchase data never belong in game files.
            _atomic_json(game_folder / "nexora_monetization.json", manifest)
        return {"saved": True, "manifest": manifest, "runtime_manifest_written": game_folder.is_dir(), "execution": "configuration_only"}

    @router.get("/api/v1/desktop/projects/{pid}/levels")
    def list_project_levels(pid: str, request: FastAPIRequest):
        folder, _, _ = _project(manager, pid, request)
        path = _levels_path(folder)
        if not path.is_file():
            return validate_level_manifest({"levels": [{
                "id": "level-1", "title": "Level 1", "difficulty": "normal",
                "state": "draft", "shared_asset_ids": [],
            }]})
        try:
            return validate_level_manifest(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError) as exc:
            raise HTTPException(500, "The local level manifest is unreadable or invalid.") from exc

    @router.put("/api/v1/desktop/projects/{pid}/levels")
    def save_project_levels(pid: str, payload: dict, request: FastAPIRequest):
        folder, _, _ = _project(manager, pid, request)
        try:
            manifest = validate_level_manifest(payload)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        path = _levels_path(folder)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        os.replace(temporary, path)
        return {"saved": True, **manifest}

    @router.post("/api/v1/desktop/projects/{pid}/initialize")
    def initialize_project(pid: str, request: FastAPIRequest):
        folder, definition, owner_id = _project(manager, pid, request)
        return {"initialized": True, "manifest": _ensure_project_layout(folder, definition, owner_id)}

    @router.get("/api/v1/desktop/assets/default-packs")
    def list_default_asset_packs(request: FastAPIRequest):
        _owner(request)
        return default_asset_catalog()

    @router.post("/api/v1/desktop/projects/{pid}/assets/default-pack")
    def apply_default_asset_pack(pid: str, payload: DefaultAssetPackRequest, request: FastAPIRequest):
        folder, definition, owner_id = _project(manager, pid, request)
        project_root = folder.resolve()
        if project_root == folder.resolve().parent:
            raise HTTPException(403, "Invalid project asset directory.")
        project_root.mkdir(parents=True, exist_ok=True)
        try:
            result = install_default_asset_pack(
                project_root, payload.pack_id, overwrite=payload.overwrite_existing
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {
            **result,
            "project_id": definition.id,
            "project_name": definition.project.name,
            "owner_id": owner_id,
        }

    @router.get("/api/v1/desktop/projects/{pid}/assets/library")
    def list_desktop_project_asset_library(pid: str, request: FastAPIRequest):
        folder, definition, owner_id = _project(manager, pid, request)
        registry = AssetRegistry((folder / "assets").resolve())
        assets = []
        for record in registry.list():
            relative_path = str(record.get("path") or "")
            file_path = (registry.root / relative_path).resolve()
            if registry.root not in file_path.parents or not file_path.is_file():
                continue
            assets.append({
                **record,
                "name": file_path.stem,
                "type": file_path.suffix.lower().lstrip("."),
                "size_bytes": file_path.stat().st_size,
            })
        return {"project_id": definition.id, "project_name": definition.project.name,
                "owner_id": owner_id, "assets": assets, "count": len(assets)}

    @router.get("/api/v1/desktop/assets/3d/search")
    def search_3d_assets(request: FastAPIRequest, q: str = "", limit: int = 40):
        _owner(request)
        try:
            return search_polyhaven_models(q, limit)
        except PolyHavenError as exc:
            raise HTTPException(502, str(exc)) from exc

    @router.post("/api/v1/desktop/projects/{pid}/assets/3d/download")
    def download_3d_asset(pid: str, payload: PolyHavenModelDownloadRequest, request: FastAPIRequest):
        folder, definition, owner_id = _project(manager, pid, request)
        project_root = (folder / "game").resolve()
        if folder.resolve() not in project_root.parents:
            raise HTTPException(403, "Invalid Godot project directory.")
        project_root.mkdir(parents=True, exist_ok=True)
        try:
            result = download_polyhaven_model(folder, payload.asset_id, payload.resolution)
        except PolyHavenError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {
            **result,
            "project_id": definition.id,
            "project_name": definition.project.name,
            "owner_id": owner_id,
        }

    @router.get("/api/v1/desktop/projects/{pid}/assets/3d/{asset_id}/file")
    def serve_downloaded_3d_model(pid: str, asset_id: str, request: FastAPIRequest):
        folder, definition, owner_id = _project(manager, pid, request)
        if not re.fullmatch(r"[a-z0-9_]{2,100}", asset_id):
            raise HTTPException(422, "Invalid Poly Haven asset identifier.")
        project_root = folder.resolve()
        asset_root = (project_root / "assets" / "3d" / "polyhaven" / asset_id).resolve()
        if project_root not in asset_root.parents:
            raise HTTPException(403, "Invalid 3D asset directory.")
        if not asset_root.is_dir():
            raise HTTPException(404, "Downloaded 3D model was not found in this project.")
        models = sorted(asset_root.rglob("*.glb"))
        if not models:
            raise HTTPException(415, "This asset is available as glTF with dependencies. Open it from the Godot FileSystem dock.")
        return FileResponse(
            models[0], media_type="model/gltf-binary", filename=models[0].name,
            headers={"Cache-Control": "no-store", "X-NEXORA-Asset-Provider": "Poly Haven"},
        )

    @router.post("/api/v1/desktop/projects/import", status_code=201)
    def import_godot_folder(payload: DesktopImportRequest, request: FastAPIRequest):
        owner_id = _owner(request)
        source = Path(payload.path).expanduser()
        try:
            source = source.resolve(strict=True)
        except (OSError, RuntimeError):
            raise HTTPException(404, "The selected Godot project folder does not exist.")
        if not source.is_dir() or not (source / "project.godot").is_file():
            raise HTTPException(422, "Choose the folder that contains the Godot project.godot file.")
        if source == Path(source.anchor) or any(part in EXCLUDED_DIRS for part in source.parts):
            raise HTTPException(403, "The selected folder cannot be imported.")
        total_bytes = 0
        file_count = 0
        for current, dirs, files in os.walk(source):
            current_path = Path(current)
            for directory in list(dirs):
                item = current_path / directory
                if item.is_symlink():
                    raise HTTPException(422, "Project imports containing symbolic links are not supported.")
            dirs[:] = [directory for directory in dirs if directory not in EXCLUDED_DIRS]
            for filename in files:
                item = current_path / filename
                if item.is_symlink():
                    raise HTTPException(422, "Project imports containing symbolic links are not supported.")
                if filename == ".DS_Store" or filename.endswith(".tmp"):
                    continue
                file_count += 1
                total_bytes += item.stat().st_size
                if total_bytes > MAX_BACKUP_BYTES or file_count > 30000:
                    raise HTTPException(413, "The existing Godot project exceeds the 2 GiB / 30,000-file import limit.")
        name = (payload.name or source.name or "Imported Godot Game").strip()[:80]
        if not name:
            raise HTTPException(422, "Enter a project name.")
        definition = manager.create(ProjectCreate(name=name, description="Imported local Godot project"))
        folder = manager.path_for(definition.id)
        destination = folder / "game"
        shutil.copytree(
            source, destination,
            ignore=shutil.ignore_patterns(*EXCLUDED_DIRS, "*.tmp", ".DS_Store"),
            symlinks=False,
        )
        (folder / "nexora_owner.json").write_text(json.dumps({"user_id": owner_id, "created_at": _utc()}, indent=2), encoding="utf-8")
        _atomic_json(folder / "nexora_workspace.json", {
            "id": definition.id, "name": name, "description": "Imported Godot project",
            "schemaVersion": 1, "engine": "Godot 4", "external_godot_project": True,
            "engine_project_path": "game/project.godot",
            "settings": {"target": "Desktop", "orientation": "Landscape", "renderPipeline": "Forward+"},
            "scene": {"id": uuid.uuid4().hex, "name": "Imported project", "objects": []},
            "assets": [], "gameplay": {"enemies": [], "mechanics": [], "objectives": []},
            "createdAt": _utc(), "updatedAt": _utc(), "version": 1,
        })
        manifest = _ensure_project_layout(folder, definition, owner_id)
        manifest.update({"name": name, "engine_project_path": "game/project.godot", "imported_at": _utc()})
        _atomic_json(folder / ".nexora" / "project.json", manifest)
        return {"imported": True, "project": {"id": definition.id, "name": name}}

    @router.get("/api/v1/desktop/projects/{pid}/files")
    def list_project_files(pid: str, request: FastAPIRequest, path: str = ""):
        folder, definition, _ = _project(manager, pid, request)
        target = _resolve_project_path(folder, path)
        if not target.exists() or not target.is_dir():
            raise HTTPException(404, "Project folder not found.")
        entries = []
        for item in sorted(target.iterdir(), key=lambda value: (not value.is_dir(), value.name.lower())):
            if item.is_symlink() or item.name in EXCLUDED_DIRS or item.name.endswith(".tmp"):
                continue
            if item.name == "nexora_owner.json":
                continue
            try:
                relative = item.relative_to(folder).as_posix()
                entries.append({
                    "name": item.name,
                    "path": relative,
                    "kind": "directory" if item.is_dir() else "file",
                    "size_bytes": item.stat().st_size if item.is_file() else 0,
                    "editable": item.is_file() and item.suffix.lower() in TEXT_EXTENSIONS and item.stat().st_size <= MAX_EDIT_BYTES,
                })
            except OSError:
                continue
        return {"entries": entries, "path": str(path or "")}

    @router.get("/api/v1/desktop/projects/{pid}/file")
    def read_project_file(pid: str, request: FastAPIRequest, path: str):
        folder, definition, _ = _project(manager, pid, request)
        target = _resolve_project_path(folder, path)
        if target.name == "nexora_owner.json" or target.suffix.lower() not in TEXT_EXTENSIONS:
            raise HTTPException(415, "This file type is not editable in NEXORA.")
        if not target.is_file() or target.stat().st_size > MAX_EDIT_BYTES:
            raise HTTPException(404, "Text file was not found or exceeds the 2 MiB editor limit.")
        data = target.read_bytes()
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(415, "This file is not valid UTF-8 text.")
        return {"path": target.relative_to(folder).as_posix(), "content": content, "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}

    @router.put("/api/v1/desktop/projects/{pid}/file")
    def save_project_file(pid: str, payload: WorkspaceFileUpdate, request: FastAPIRequest):
        folder, definition, _ = _project(manager, pid, request)
        target = _resolve_project_path(folder, payload.path)
        if target.name == "nexora_owner.json" or target.suffix.lower() not in TEXT_EXTENSIONS:
            raise HTTPException(415, "This file type is not editable in NEXORA.")
        if not target.is_file():
            raise HTTPException(404, "Project file not found.")
        old = target.read_bytes()
        old_hash = hashlib.sha256(old).hexdigest()
        if old_hash != payload.expected_sha256:
            raise HTTPException(409, "This file changed since it was opened. Reload before saving.")
        encoded = payload.content.encode("utf-8")
        if len(encoded) > MAX_EDIT_BYTES:
            raise HTTPException(413, "Text file exceeds the 2 MiB editor limit.")
        temporary = target.with_name(target.name + ".nexora-tmp")
        temporary.write_bytes(encoded)
        temporary.replace(target)
        digest = hashlib.sha256(encoded).hexdigest()
        return {"saved": True, "sha256": digest, "size_bytes": len(encoded)}

    @router.post("/api/v1/desktop/projects/{pid}/file", status_code=201)
    def create_project_file(pid: str, payload: WorkspaceFileCreate, request: FastAPIRequest):
        folder, definition, _ = _project(manager, pid, request)
        return _create_project_text_file(folder, payload.path, payload.content)

    @router.get("/api/v1/desktop/projects/{pid}/snapshots")
    def list_project_snapshots(pid: str, request: FastAPIRequest):
        folder, definition, owner_id = _project(manager, pid, request)
        rows = [item for item in _snapshot_records(manager, pid) if item.get("owner_id") == owner_id]
        return {"snapshots": rows}

    @router.post("/api/v1/desktop/projects/{pid}/snapshots")
    def create_project_snapshot(pid: str, request: FastAPIRequest):
        folder, definition, owner_id = _project(manager, pid, request)
        snapshot = _create_snapshot(manager, folder, definition, owner_id)
        return {"snapshot": snapshot, **snapshot}

    @router.post("/api/v1/desktop/projects/{pid}/snapshots/{snapshot_id}/restore")
    def restore_project_snapshot(pid: str, snapshot_id: str, request: FastAPIRequest):
        folder, definition, owner_id = _project(manager, pid, request)
        if not snapshot_id.startswith("snap_") or "/" in snapshot_id or "\\" in snapshot_id:
            raise HTTPException(404, "Snapshot not found.")
        root = _snapshot_dir(manager, pid)
        metadata_path = root / f"{snapshot_id}.json"
        try:
            snapshot = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise HTTPException(404, "Snapshot not found.")
        if snapshot.get("owner_id") != owner_id or snapshot.get("project_id") != pid:
            raise HTTPException(404, "Snapshot not found.")
        archive = root / f"{snapshot_id}.zip"
        if not archive.is_file():
            raise HTTPException(404, "Snapshot archive is missing.")
        actual = _sha256_path(archive)
        if actual != snapshot.get("sha256"):
            raise HTTPException(409, "Snapshot integrity check failed. The archive may have changed.")
        result = _restore_archive(manager, folder, definition, owner_id, archive)
        return {**result, "snapshot_id": snapshot_id}

    @router.get("/api/v1/desktop/toolchains")
    def get_toolchains(request: FastAPIRequest, project_id: str | None = None):
        owner_id = _owner(request)
        profile = collect_system_profile(manager.root)
        machine = profile.get("machine", {})
        tools = profile.get("tools", {})
        android = profile.get("android", {})
        godot = tools.get("godot") or {}
        godot_version = str(godot.get("version") or "")
        version_parts = godot_version.split(".")
        version_prefix = (
            ".".join(version_parts[:3]) + ".stable"
            if len(version_parts) >= 4 and version_parts[3] == "stable"
            else ""
        )
        template_roots = []
        if os.name == "nt" and os.environ.get("APPDATA"):
            template_roots.append(Path(os.environ["APPDATA"]) / "Godot" / "export_templates")
        elif __import__("platform").system() == "Darwin":
            template_roots.append(Path.home() / "Library" / "Application Support" / "Godot" / "export_templates")
        else:
            template_roots.extend([
                Path.home() / ".local" / "share" / "godot" / "export_templates",
                Path.home() / ".var" / "app" / "org.godotengine.Godot" / "data" / "godot" / "export_templates",
            ])
        template_match = None
        if version_prefix:
            for root in template_roots:
                if root.is_dir():
                    template_match = next(
                        (item for item in root.iterdir() if item.is_dir() and item.name.startswith(version_prefix)),
                        None,
                    )
                    if template_match:
                        break
        toolchain_tools = {
            **tools,
            "godot_templates": {
                "available": bool(template_match),
                "path": str(template_match.resolve()) if template_match else None,
                "version": template_match.name if template_match else None,
            },
        }
        catalog = [
            {"id":"godot","label":"Godot Engine 4.x","purpose":"Engine, editor, runtime and platform export.","url":"https://godotengine.org/download/","winget_id":WINGET_PACKAGES["godot"]},
            {"id":"godot_templates","label":"Godot Export Templates","purpose":"Templates matching your exact Godot version. Install from Godot Editor > Manage Export Templates.","url":"https://docs.godotengine.org/en/stable/tutorials/export/exporting_projects.html","winget_id":None},
            {"id":"blender","label":"Blender","purpose":"Local procedural 3D modelling and asset generation.","url":"https://www.blender.org/download/","winget_id":WINGET_PACKAGES["blender"]},
            {"id":"ffmpeg","label":"FFmpeg + FFprobe","purpose":"Local video/audio processing and inspection.","url":"https://ffmpeg.org/download.html","winget_id":WINGET_PACKAGES["ffmpeg"]},
            {"id":"java17","label":"Java JDK 17","purpose":"Android Gradle/export toolchain.","url":"https://adoptium.net/temurin/releases/?version=17","winget_id":WINGET_PACKAGES["java17"]},
            {"id":"android_sdk","label":"Android SDK Command-line Tools","purpose":"Android platform/build-tools and ADB. Install with Google's sdkmanager; Android Studio is not required.","url":"https://developer.android.com/tools","winget_id":None},
        ]
        lock = None
        if project_id:
            folder, definition, _ = _project(manager, project_id, request)
            lock_path = folder / ".nexora" / "toolchain.lock.json"
            if lock_path.is_file():
                try: lock = json.loads(lock_path.read_text(encoding="utf-8"))
                except (OSError, ValueError): lock = None
        return {
            "machine": {**machine, "system": machine.get("os")},
            "tools": {**toolchain_tools, "android_sdk": {"available": bool(android.get("sdk_root") and android.get("build_tools_installed")), "path": android.get("sdk_root"), "version": None}},
            "android": android,
            "catalog": catalog,
            "lock": lock,
            "install_provider": "winget" if os.name == "nt" and shutil.which("winget") else "manual_setup",
            "execution_location": "creator_device",
        }

    @router.post("/api/v1/desktop/toolchains/install")
    def install_toolchains(payload: ToolchainInstallRequest, request: FastAPIRequest):
        _owner(request)
        if not payload.confirm_install:
            raise HTTPException(403, "Confirm that you want to start the selected installers.")
        allowed = set(WINGET_PACKAGES) | {"android_sdk", "godot_templates"}
        unknown = set(payload.tools) - allowed
        if unknown:
            raise HTTPException(422, "One or more requested tools are not in the approved NEXORA catalogue.")
        manual = [item for item in payload.tools if item in {"android_sdk", "godot_templates"}]
        installed = [item for item in payload.tools if item in WINGET_PACKAGES]
        if not installed:
            return {
                "started": False,
                "manual_setup": [{"id":item,"message":"Open the official tool documentation and complete its installer or SDK manager with your own licence acceptance."} for item in manual],
                "message": "The selected components require their official installer or sdkmanager. No installation was started."
            }
        if os.name != "nt" or not shutil.which("winget"):
            manual_ids = payload.tools
            return {
                "started": False,
                "installers": [],
                "manual_setup": [{
                    "id": item,
                    "message": "Install from the official download link in Toolchain Manager, then select Detect tools."
                } for item in manual_ids],
                "message": "Automatic installation is currently supported only on Windows with winget. No installer was started; use the official links shown for each selected tool."
            }
        started = []
        for item in installed:
            package = WINGET_PACKAGES[item]
            command = ["winget", "install", "--id", package, "--exact", "--source", "winget", "--interactive"]
            creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
            try:
                process = subprocess.Popen(command, cwd=str(manager.root), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=False, creationflags=creationflags)
            except OSError as exc:
                raise HTTPException(503, f"Could not start the approved {item} installer: {exc}") from exc
            started.append({"id": item, "package_id": package, "process_id": process.pid, "state": "installer_started"})
        return {
            "started": True,
            "installers": started,
            "manual_setup": [{"id":item,"message":"Use the official installer or sdkmanager; complete Google licence prompts yourself."} for item in manual],
            "message": "Installer windows have been started. Complete each installer and accept vendor licences yourself. Restart NEXORA Local Agent so updated PATH values are detected, then select Detect tools. Installation is not marked complete until detection succeeds."
        }

    @router.post("/api/v1/desktop/toolchains/lock")
    def pin_toolchain_versions(payload: ToolchainLockRequest, request: FastAPIRequest):
        owner_id = _owner(request)
        allowed_targets = {"web", "android", "windows", "linux", "macos", "ios"}
        if not payload.targets or any(item not in allowed_targets for item in payload.targets):
            raise HTTPException(422, "Select one or more supported export targets.")
        profile = collect_system_profile(manager.root)
        lock = {
            "schema_version": 1,
            "owner_id": owner_id,
            "locked_at": _utc(),
            "host": {
                "os": profile.get("machine", {}).get("os"),
                "architecture": profile.get("machine", {}).get("architecture"),
            },
            "tools": profile.get("tools", {}),
            "android": profile.get("android", {}),
            "gpu": profile.get("gpu", {}),
            "targets": sorted(set(payload.targets)),
        }
        if payload.project_id:
            folder, definition, _ = _project(manager, payload.project_id, request)
            _ensure_project_layout(folder, definition, owner_id)
            destination = folder / ".nexora" / "toolchain.lock.json"
        else:
            destination = Path(manager.root) / ".nexora" / "toolchain.lock.json"
        _atomic_json(destination, lock)
        return {"saved": True, "lock": lock, "path": str(destination)}

    @router.get("/api/v1/desktop/publish/readiness")
    def publisher_readiness(request: FastAPIRequest):
        _owner(request)
        import platform
        is_mac = platform.system() == "Darwin"
        play_file = os.environ.get("NEXORA_PLAY_SERVICE_ACCOUNT_FILE", "").strip()
        play_package = os.environ.get("NEXORA_PLAY_PACKAGE_NAME", "").strip()
        apple_key = os.environ.get("NEXORA_APPLE_API_KEY_PATH", "").strip()
        apple_bundle = os.environ.get("NEXORA_APPLE_BUNDLE_ID", "").strip()
        apple_ready = bool(
            is_mac and shutil.which("xcodebuild") and apple_key and Path(apple_key).is_file()
            and os.environ.get("NEXORA_APPLE_ISSUER_ID") and os.environ.get("NEXORA_APPLE_KEY_ID")
            and apple_bundle
        )
        microsoft_msix = os.environ.get("NEXORA_MS_STORE_MSIX_PATH", "").strip()
        # The first Partner Center listing is creator-managed; this codebase
        # does not yet implement the Microsoft Store submission API connector.
        microsoft_ready = False
        providers = [
            {"id":"google_play","name":"Google Play Console","ready":bool(play_file and Path(play_file).is_file() and play_package), "missing":[item for item,ok in [
                ("Creator-owned Play Console account and existing app record", bool(play_package)),
                ("NEXORA_PLAY_SERVICE_ACCOUNT_FILE pointing to a local least-privilege service-account JSON file", bool(play_file and Path(play_file).is_file())),
                ("Signed Android App Bundle (.aab) generated in NEXORA", True),
            ] if not ok]},
            {"id":"apple_app_store","name":"Apple App Store Connect","ready":apple_ready,"missing":[item for item,ok in [
                ("A Mac with Xcode command-line tools", is_mac and bool(shutil.which("xcodebuild"))),
                ("App Store Connect API key file stored locally", bool(apple_key and Path(apple_key).is_file())),
                ("App Store Connect issuer ID and key ID", bool(os.environ.get("NEXORA_APPLE_ISSUER_ID") and os.environ.get("NEXORA_APPLE_KEY_ID"))),
                ("Creator-owned App Store Connect app record / bundle ID", bool(apple_bundle)),
            ] if not ok]},
            {"id":"microsoft_store","name":"Microsoft Store / Partner Center","ready":microsoft_ready,"missing":[item for item,ok in [
                ("Creator-owned Partner Center developer account and app identity", bool(os.environ.get("NEXORA_MS_STORE_APP_ID"))),
                ("Authorized Microsoft Store submission access token", bool(os.environ.get("NEXORA_MS_STORE_ACCESS_TOKEN"))),
                ("Signed MSIX package path", bool(microsoft_msix and Path(microsoft_msix).is_file())),
                ("NEXORA Microsoft Store submission connector (not yet implemented)", False),
            ] if not ok]},
        ]
        return {"providers": providers, "final_submission_requires_creator_confirmation": True}

    @router.post("/api/v1/desktop/projects/{pid}/publish/prepare")
    def prepare_project_publish(pid: str, payload: PublishPrepareRequest, request: FastAPIRequest):
        folder, definition, owner_id = _project(manager, pid, request)
        if not payload.rights_confirmed:
            raise HTTPException(403, "Confirm that you own or have distribution rights to the game and every included asset before preparing a release.")
        job_root = folder / "workspace_jobs"
        matched = None
        job_id = None
        for metadata in job_root.glob("*.json"):
            if metadata.name.endswith(".owner.json"):
                continue
            try:
                record = json.loads(metadata.read_text(encoding="utf-8"))
                item = next((row for row in record.get("artifacts", []) if row.get("id") == payload.artifact_id), None)
                owner_path = job_root / (metadata.stem + ".owner.json")
                job_owner = json.loads(owner_path.read_text(encoding="utf-8")).get("user_id") if owner_path.is_file() else None
                if item and str(job_owner) == owner_id:
                    matched, job_id = item, metadata.stem
                    break
            except (OSError, ValueError):
                continue
        if not matched:
            raise HTTPException(404, "Build artifact is not available in the selected project.")
        target = payload.platform
        if target not in {"android", "web", "windows", "linux"}:
            raise HTTPException(422, "Unsupported release target.")
        if payload.artifact_id != target:
            raise HTTPException(409, "Choose an artifact generated for the selected release platform.")
        relative = Path(str(matched.get("path") or ""))
        if relative.is_absolute() or ".." in relative.parts:
            raise HTTPException(500, "Build output path is invalid.")
        artifact_path = (folder / relative).resolve()
        if folder.resolve() not in artifact_path.parents or not artifact_path.is_file():
            raise HTTPException(404, "The selected build artifact is missing.")
        if target == "android" and artifact_path.suffix.lower() != ".aab":
            raise HTTPException(409, "Google Play release preparation requires a signed Android App Bundle (.aab), not a debug APK.")
        digest = hashlib.sha256()
        with artifact_path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        release_id = "rel_" + uuid.uuid4().hex[:20]
        record = {
            "schema_version": 1, "id": release_id, "project_id": pid, "owner_id": owner_id,
            "project_name": definition.project.name, "provider_status": "prepared_not_submitted",
            "target": target, "version": payload.version, "release_notes": payload.release_notes,
            "created_at": _utc(), "rights_confirmed": True,
            "job_id": job_id,
            "artifacts": [{
                "id": payload.artifact_id, "filename": artifact_path.name,
                "path": relative.as_posix(), "size_bytes": artifact_path.stat().st_size,
                "sha256": digest.hexdigest(),
                "content_type": matched.get("content_type") or mimetypes.guess_type(artifact_path.name)[0] or "application/octet-stream",
                **({
                    key: matched[key]
                    for key in ("artifact_format", "package_id", "version_name", "version_code", "build_type")
                    if key in matched
                }),
            }],
            "warning": "Preparation only. A creator rights review and publisher-side final approval are still required.",
        }
        destination = folder / ".nexora" / "build-manifests" / f"{release_id}.json"
        _atomic_json(destination, record)
        return {"prepared": True, "release": record, "submitted": False}

    @router.get("/api/v1/desktop/drive/status")
    def google_drive_status(request: FastAPIRequest):
        return drive_status(_owner(request))

    @router.post("/api/v1/desktop/drive/authorize")
    def authorize_google_drive(request: FastAPIRequest):
        try:
            url = begin_drive_oauth(_owner(request))
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"authorization_url": url, "scope": "drive.file", "token_storage": "operating_system_credential_vault"}

    @router.post("/api/v1/desktop/drive/disconnect")
    def disconnect_google_drive(request: FastAPIRequest):
        try:
            disconnect_drive(_owner(request))
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc
        return {"disconnected": True}

    @router.get("/api/v1/desktop/drive/projects/{pid}/backups")
    def list_google_drive_backups(pid: str, request: FastAPIRequest):
        _, _, owner_id = _project(manager, pid, request)
        return {"files": _drive_list_project_backups(owner_id, pid)}

    @router.post("/api/v1/desktop/drive/projects/{pid}/snapshots/{snapshot_id}/upload")
    def upload_snapshot_to_drive(pid: str, snapshot_id: str, request: FastAPIRequest):
        folder, definition, owner_id = _project(manager, pid, request)
        if not snapshot_id.startswith("snap_") or "/" in snapshot_id:
            raise HTTPException(404, "Snapshot not found.")
        root = _snapshot_dir(manager, pid)
        try:
            record = json.loads((root / f"{snapshot_id}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise HTTPException(404, "Snapshot not found.")
        if record.get("owner_id") != owner_id:
            raise HTTPException(404, "Snapshot not found.")
        archive = root / f"{snapshot_id}.zip"
        if not archive.is_file() or _sha256_path(archive) != record.get("sha256"):
            raise HTTPException(409, "Snapshot archive failed its integrity check.")
        metadata = {
            "name": f"NEXORA-{definition.project.name}-{snapshot_id}.zip",
            "mimeType": "application/zip",
            "appProperties": {"nexoraProjectId": pid, "nexoraSnapshotId": snapshot_id, "nexoraOwnerId": owner_id},
        }
        result = _drive_upload_file(owner_id, archive, metadata)
        return {"uploaded": True, "file": result}

    @router.post("/api/v1/desktop/drive/projects/{pid}/backups/{file_id}/restore")
    def restore_google_drive_backup(pid: str, file_id: str, request: FastAPIRequest):
        folder, definition, owner_id = _project(manager, pid, request)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", file_id or ""):
            raise HTTPException(400, "Invalid Drive file identifier.")
        # Confirm file ownership and project metadata before downloading.
        files = _drive_list_project_backups(owner_id, pid)
        selected = next((item for item in files if item.get("id") == file_id), None)
        if not selected:
            raise HTTPException(404, "NEXORA project backup not found in Google Drive.")
        temp_root = Path(manager.root) / ".nexora-drive-restore"
        temp_root.mkdir(parents=True, exist_ok=True)
        temporary = temp_root / (uuid.uuid4().hex + ".zip")
        try:
            _drive_download_file(owner_id, file_id, temporary)
            result = _restore_archive(manager, folder, definition, owner_id, temporary)
            return {**result, "drive_file_id": file_id}
        finally:
            temporary.unlink(missing_ok=True)

    app.include_router(router)
