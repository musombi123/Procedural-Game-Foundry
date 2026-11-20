"""Local-only NEXORA project lifecycle, toolchain lock, backup and release APIs.

These routes are mounted in the Foundry engine and are blocked by the hosted
execution policy. They operate only on the creator's paired local machine.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile, BadZipFile

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

MAX_BACKUP_BYTES = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_EXPANDED_BYTES = 5 * 1024 * 1024 * 1024
MAX_ARCHIVE_FILES = 30000
EXCLUDED_DIRS = {
    ".git", ".godot", ".venv", "venv", "node_modules", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "cache", "tmp", "temp",
    "build-cache", ".idea", ".vscode",
}
EXCLUDED_TOP_LEVEL = {"workspace_jobs", "device-staging"}
SAFE_PROJECT_ID = re.compile(r"^[A-Za-z0-9_-]{1,100}$")


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _owner(request: Request) -> str:
    value = getattr(request.state, "nexora_user_id", None)
    if not value:
        raise HTTPException(401, "Pair this local computer and sign in to NEXORA.")
    return str(value)


def _project(manager: Any, pid: str, request: Request) -> tuple[Path, Any, str]:
    if not SAFE_PROJECT_ID.fullmatch(pid):
        raise HTTPException(400, "Invalid project identifier.")
    try:
        folder = manager.path_for(pid)
        definition = manager.load(pid)
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, "Project not found.")
    user_id = _owner(request)
    marker = folder / "nexora_owner.json"
    try:
        record = json.loads(marker.read_text(encoding="utf-8")) if marker.is_file() else {}
    except (OSError, ValueError):
        raise HTTPException(500, "Project ownership record is unreadable.")
    if str(record.get("user_id") or "") != user_id:
        raise HTTPException(404, "Project not found.")
    return folder, definition, user_id


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _ensure_project_layout(folder: Path, definition: Any, owner_id: str) -> dict:
    meta = folder / ".nexora"
    for name in ("provenance", "build-manifests", "backups"):
        (meta / name).mkdir(parents=True, exist_ok=True)
    manifest_path = meta / "project.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise HTTPException(500, "NEXORA project manifest is corrupt; restore a known-good backup.")
        if str(manifest.get("owner_id") or "") != owner_id:
            raise HTTPException(404, "Project not found.")
    else:
        manifest = {
            "schema_version": 1,
            "project_id": definition.id,
            "owner_id": owner_id,
            "name": definition.project.name,
            "description": definition.project.description,
            "engine": "Godot 4",
            "engine_project_path": "game/project.godot",
            "created_at": getattr(definition, "created_at", _utc()),
            "updated_at": _utc(),
            "targets": ["web", "android", "windows"],
        }
        _atomic_json(manifest_path, manifest)
    lock_path = meta / "toolchain.lock.json"
    if not lock_path.exists():
        _atomic_json(lock_path, {"schema_version": 1, "locked_at": None, "tools": {}})
    return manifest


def _archive_project(folder: Path, output: Path) -> dict:
    digest = hashlib.sha256()
    total = 0
    count = 0
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
        for current, dirs, filenames in os.walk(folder):
            current_path = Path(current)
            relative_dir = current_path.relative_to(folder)
            dirs[:] = [
                name for name in dirs
                if name not in EXCLUDED_DIRS
                and not (relative_dir == Path(".") and name in EXCLUDED_TOP_LEVEL)
            ]
            for filename in filenames:
                source = current_path / filename
                relative = source.relative_to(folder)
                if any(part in EXCLUDED_DIRS for part in relative.parts):
                    continue
                if relative.parts and relative.parts[0] in EXCLUDED_TOP_LEVEL:
                    continue
                if source.is_symlink() or not source.is_file():
                    continue
                size = source.stat().st_size
                total += size
                count += 1
                if total > MAX_BACKUP_BYTES or count > MAX_ARCHIVE_FILES:
                    raise HTTPException(413, "Project exceeds the local backup limit (2 GiB / 30,000 files).")
                archive.write(source, arcname=relative.as_posix())
                with source.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
    return {"file_count": count, "source_bytes": total, "sha256": digest.hexdigest(), "archive_bytes": output.stat().st_size}


def _safe_extract(archive_path: Path, destination: Path) -> dict:
    expanded = 0
    count = 0
    seen: set[str] = set()
    try:
        with ZipFile(archive_path, "r") as archive:
            for info in archive.infolist():
                raw = info.filename.replace("\\", "/")
                relative = PurePosixPath(raw)
                if relative.is_absolute() or not raw or any(part in {"", ".", ".."} for part in relative.parts):
                    raise HTTPException(422, "Backup archive contains an unsafe file path.")
                if ":" in relative.parts[0] or raw.startswith("//"):
                    raise HTTPException(422, "Backup archive contains an absolute or drive-qualified path.")
                normalized = relative.as_posix()
                if normalized in seen:
                    raise HTTPException(422, "Backup archive contains duplicate paths.")
                seen.add(normalized)
                mode = (info.external_attr >> 16) & 0o170000
                if mode == 0o120000:
                    raise HTTPException(422, "Symbolic links are not accepted in NEXORA project backups.")
                count += 1
                expanded += int(info.file_size)
                if count > MAX_ARCHIVE_FILES or expanded > MAX_ARCHIVE_EXPANDED_BYTES:
                    raise HTTPException(413, "Backup archive exceeds the extraction safety limits.")
                target = (destination / Path(*relative.parts)).resolve()
                if destination.resolve() not in target.parents and target != destination.resolve():
                    raise HTTPException(422, "Backup archive attempts to write outside the project folder.")
            archive.extractall(destination)
    except BadZipFile as exc:
        raise HTTPException(422, "The selected backup is not a valid ZIP archive.") from exc
    return {"file_count": count, "expanded_bytes": expanded}


class ReleaseManifestPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    target: str = Field(pattern=r"^(web|android|windows|linux)$")
    version: str = Field(min_length=1, max_length=40, pattern=r"^[0-9A-Za-z][0-9A-Za-z.+_-]*$")
    release_notes: str = Field(default="", max_length=5000)
    rights_confirmed: bool = False


class PublisherPreparePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str = Field(pattern=r"^(google_play|apple_app_store|microsoft_store)$")
    release_manifest_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")


def register_local_factory_routes(app: Any, manager: Any) -> None:
    router = APIRouter()

    @router.get("/api/v1/factory/projects/{pid}/manifest")
    def get_project_manifest(pid: str, request: Request):
        folder, definition, owner_id = _project(manager, pid, request)
        return _ensure_project_layout(folder, definition, owner_id)

    @router.put("/api/v1/factory/projects/{pid}/manifest")
    def update_project_manifest(pid: str, payload: dict, request: Request):
        folder, definition, owner_id = _project(manager, pid, request)
        current = _ensure_project_layout(folder, definition, owner_id)
        allowed = {"name", "description", "targets", "engine", "engine_project_path"}
        updates = {key: value for key, value in payload.items() if key in allowed}
        if "name" in updates:
            name = str(updates["name"]).strip()
            if not name or len(name) > 80:
                raise HTTPException(422, "Project name must contain 1–80 characters.")
            updates["name"] = name
        if "description" in updates:
            updates["description"] = str(updates["description"])[:2000]
        if "targets" in updates:
            targets = updates["targets"]
            if not isinstance(targets, list) or not targets or any(v not in {"web", "android", "windows", "linux", "macos", "ios"} for v in targets):
                raise HTTPException(422, "Choose one or more supported export targets.")
            updates["targets"] = sorted(set(targets))
        current.update(updates)
        current["updated_at"] = _utc()
        _atomic_json(folder / ".nexora" / "project.json", current)
        return current

    @router.get("/api/v1/factory/toolchains/catalog")
    def toolchain_catalog(request: Request):
        _owner(request)
        from services.worker.system_profile import collect_system_profile
        profile = collect_system_profile(manager.root)
        return {
            "execution_location": "creator_device",
            "catalog": [
                {"id":"godot","name":"Godot Engine 4.x","purpose":"Game editor, runtime and exports","required_for":["web","android","windows"],"url":"https://godotengine.org/download/","install_mode":"official_installer"},
                {"id":"godot_templates","name":"Godot Export Templates","purpose":"Platform export templates matching the installed Godot version","required_for":["web","android","windows"],"url":"https://docs.godotengine.org/en/stable/tutorials/export/exporting_projects.html","install_mode":"godot_editor"},
                {"id":"blender","name":"Blender","purpose":"Procedural 3D assets, characters and environments","required_for":["3d_assets"],"url":"https://www.blender.org/download/","install_mode":"official_installer"},
                {"id":"ffmpeg","name":"FFmpeg + FFprobe","purpose":"Local media inspection and audio/video processing","required_for":["media"],"url":"https://ffmpeg.org/download.html","install_mode":"official_build"},
                {"id":"java","name":"Java JDK 17","purpose":"Android Gradle/export tooling","required_for":["android"],"url":"https://adoptium.net/temurin/releases/?version=17","install_mode":"official_installer"},
                {"id":"android_sdk","name":"Android SDK Command-line Tools","purpose":"Android platform/build tools and ADB","required_for":["android"],"url":"https://developer.android.com/tools","install_mode":"sdkmanager"},
            ],
            "inventory": profile,
            "workspace_root": str(Path(manager.root).resolve()),
            "notice": "Downloads and installers are launched by the creator. NEXORA never silently installs third-party tools."
        }

    @router.post("/api/v1/factory/toolchains/lock")
    def lock_toolchains(payload: dict, request: Request):
        owner_id = _owner(request)
        from services.worker.system_profile import collect_system_profile
        profile = collect_system_profile(manager.root)
        lock = {
            "schema_version": 1,
            "owner_id": owner_id,
            "locked_at": _utc(),
            "host": {
                "system": profile.get("machine", {}).get("system"),
                "architecture": profile.get("machine", {}).get("architecture"),
            },
            "tools": profile.get("tools", {}),
            "android": profile.get("android", {}),
            "gpu": profile.get("gpu", {}),
            "targets": payload.get("targets", ["web", "android", "windows"]),
        }
        if not isinstance(lock["targets"], list) or any(item not in {"web", "android", "windows", "linux", "macos", "ios"} for item in lock["targets"]):
            raise HTTPException(422, "Toolchain targets are invalid.")
        if payload.get("project_id"):
            folder, definition, _ = _project(manager, str(payload["project_id"]), request)
            _ensure_project_layout(folder, definition, owner_id)
            destination = folder / ".nexora" / "toolchain.lock.json"
        else:
            destination = Path(manager.root) / ".nexora" / "toolchain.lock.json"
        _atomic_json(destination, lock)
        return {"saved": True, "path": str(destination), "lock": lock}

    @router.get("/api/v1/workspace/projects/{pid}/backup/export")
    def export_project_backup(pid: str, request: Request):
        folder, definition, owner_id = _project(manager, pid, request)
        manifest = _ensure_project_layout(folder, definition, owner_id)
        backup_root = Path(manager.root) / ".nexora-backups"
        backup_root.mkdir(parents=True, exist_ok=True)
        output = backup_root / f"{pid}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.zip"
        report = _archive_project(folder, output)
        record = {
            "schema_version": 1,
            "backup_id": uuid4().hex,
            "project_id": pid,
            "owner_id": owner_id,
            "project_name": manifest.get("name") or definition.project.name,
            "created_at": _utc(),
            **report,
        }
        _atomic_json(folder / ".nexora" / "backups" / f"{record['backup_id']}.json", record)
        return FileResponse(output, media_type="application/zip", filename=f"NEXORA-{pid}-backup.zip", headers={"X-NEXORA-Backup-SHA256": report["sha256"]})

    @router.post("/api/v1/workspace/projects/import", status_code=201)
    async def import_project_backup(request: Request, file: UploadFile = File(...), name: str = Form(default="")):
        owner_id = _owner(request)
        if not (file.filename or "").lower().endswith(".zip"):
            raise HTTPException(415, "Import a NEXORA project ZIP or a Godot project ZIP.")
        staging_root = Path(manager.root) / ".nexora-import-staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        temporary = staging_root / f"{uuid4().hex}.zip"
        extracted = staging_root / temporary.stem
        size = 0
        try:
            with temporary.open("xb") as stream:
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_BACKUP_BYTES:
                        raise HTTPException(413, "Import archive exceeds the 2 GiB upload limit.")
                    stream.write(chunk)
            extracted.mkdir(parents=True, exist_ok=False)
            _safe_extract(temporary, extracted)
            candidates = [extracted / "game", extracted]
            candidates.extend(path for path in extracted.iterdir() if path.is_dir())
            game_root = next((path for path in candidates if (path / "project.godot").is_file()), None)
            if game_root is None:
                raise HTTPException(422, "The ZIP must contain a Godot project with project.godot at its root or in a game/ folder.")
            project_name = (name.strip() or game_root.name or "Imported Game")[:80]
            from core.project_engine.models import ProjectCreate
            definition = manager.create(ProjectCreate(name=project_name, description="Imported into NEXORA Desktop Studio"))
            folder = manager.path_for(definition.id)
            game_destination = folder / "game"
            if game_destination.exists():
                shutil.rmtree(game_destination)
            shutil.copytree(game_root, game_destination, ignore=shutil.ignore_patterns(*EXCLUDED_DIRS))
            (folder / "nexora_owner.json").write_text(json.dumps({"user_id": owner_id, "created_at": _utc()}, indent=2), encoding="utf-8")
            state = {
                "id": definition.id, "name": project_name, "description": "Imported Godot project",
                "schemaVersion": 1, "engine": "Godot 4", "external_godot_project": True,
                "settings": {"target": "Desktop", "orientation": "Landscape", "renderPipeline": "Forward+"},
                "scene": {"id": uuid4().hex, "name": "Imported Project", "objects": []},
                "assets": [], "gameplay": {"enemies": [], "mechanics": [], "objectives": []},
                "createdAt": _utc(), "updatedAt": _utc(), "version": 1,
            }
            _atomic_json(folder / "nexora_workspace.json", state)
            manifest = _ensure_project_layout(folder, definition, owner_id)
            manifest.update({"name": project_name, "engine_project_path": "game/project.godot", "imported_at": _utc()})
            _atomic_json(folder / ".nexora" / "project.json", manifest)
            # Preserve project-level NEXORA metadata and non-engine support files from a NEXORA backup.
            source_meta = extracted / ".nexora"
            if source_meta.is_dir():
                for source in source_meta.iterdir():
                    target = folder / ".nexora" / source.name
                    if source.is_file() and source.name in {"project.json", "toolchain.lock.json"}:
                        # The new owner and ID must remain authoritative.
                        continue
                    if source.is_dir() and source.name in {"provenance", "build-manifests"}:
                        shutil.copytree(source, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns(*EXCLUDED_DIRS))
            return {"imported": True, "project": {"id": definition.id, "name": project_name, "engine_project_path": "game/project.godot"}}
        finally:
            temporary.unlink(missing_ok=True)
            if extracted.exists():
                shutil.rmtree(extracted, ignore_errors=True)
            await file.close()

    @router.post("/api/v1/factory/projects/{pid}/releases")
    def create_release_manifest(pid: str, payload: ReleaseManifestPayload, request: Request):
        folder, definition, owner_id = _project(manager, pid, request)
        manifest = _ensure_project_layout(folder, definition, owner_id)
        if not payload.rights_confirmed:
            raise HTTPException(403, "Confirm that you have the rights to distribute every included source file and asset.")
        job_metadata = folder / "workspace_jobs" / f"{payload.job_id}.owner.json"
        try:
            job_owner = json.loads(job_metadata.read_text(encoding="utf-8")).get("user_id")
        except (OSError, ValueError):
            raise HTTPException(404, "Build job not found for this project.")
        if str(job_owner) != owner_id:
            raise HTTPException(404, "Build job not found for this project.")
        artifact_path = folder / "workspace_jobs" / f"{payload.job_id}.json"
        try:
            artifacts = json.loads(artifact_path.read_text(encoding="utf-8")).get("artifacts", [])
        except (OSError, ValueError):
            raise HTTPException(409, "Build artifact manifest is missing or unreadable.")
        selected = [item for item in artifacts if item.get("id") == payload.target or item.get("platform") == payload.target]
        if not selected:
            # Build workers use the platform code as artifact ID; fail closed if absent.
            raise HTTPException(409, f"No {payload.target} artifact exists in the selected build.")
        verified = []
        for item in selected:
            relative = Path(str(item.get("path") or ""))
            if relative.is_absolute() or ".." in relative.parts:
                raise HTTPException(500, "Build artifact path is invalid.")
            target = (folder / relative).resolve()
            if folder.resolve() not in target.parents or not target.is_file():
                raise HTTPException(404, "Build artifact file is missing.")
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            verified.append({
                "id": str(item.get("id")),
                "filename": target.name,
                "path": relative.as_posix(),
                "content_type": item.get("content_type") or mimetypes.guess_type(target.name)[0] or "application/octet-stream",
                "size_bytes": target.stat().st_size,
                "sha256": digest,
            })
        release_id = f"rel_{uuid4().hex[:20]}"
        release = {
            "schema_version": 1, "id": release_id, "project_id": pid, "owner_id": owner_id,
            "project_name": manifest.get("name") or definition.project.name,
            "provider_status": "prepared_not_submitted", "target": payload.target,
            "version": payload.version, "release_notes": payload.release_notes,
            "created_at": _utc(), "artifacts": verified,
            "rights_confirmed": True,
        }
        destination = folder / ".nexora" / "build-manifests" / f"{release_id}.json"
        _atomic_json(destination, release)
        return release

    @router.get("/api/v1/factory/projects/{pid}/releases")
    def list_release_manifests(pid: str, request: Request):
        folder, definition, owner_id = _project(manager, pid, request)
        root = folder / ".nexora" / "build-manifests"
        rows = []
        if root.is_dir():
            for path in sorted(root.glob("rel_*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
                try:
                    item = json.loads(path.read_text(encoding="utf-8"))
                    if item.get("owner_id") == owner_id:
                        rows.append(item)
                except (OSError, ValueError):
                    continue
        return {"releases": rows}

    @router.post("/api/v1/factory/projects/{pid}/publishers/prepare")
    def prepare_publisher_package(pid: str, payload: PublisherPreparePayload, request: Request):
        folder, definition, owner_id = _project(manager, pid, request)
        release_path = folder / ".nexora" / "build-manifests" / f"{payload.release_manifest_id}.json"
        try:
            release = json.loads(release_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise HTTPException(404, "Release manifest not found.")
        if release.get("owner_id") != owner_id:
            raise HTTPException(404, "Release manifest not found.")
        target = release.get("target")
        requirements = {
            "google_play": {"target": "android", "artifact": ".aab", "account": "Creator-owned Google Play Console developer account and existing app record", "next": "Run scripts/nexora-publish-google-play.py from this desktop after configuring the local service-account credential."},
            "apple_app_store": {"target": "ios", "artifact": ".ipa", "account": "Creator-owned Apple Developer Program and App Store Connect app record; a Mac with Xcode is required", "next": "Open the Xcode archive on your Mac, sign it with your Apple team and upload through Transporter or App Store Connect."},
            "microsoft_store": {"target": "windows", "artifact": ".msix", "account": "Creator-owned Microsoft Partner Center developer account and app identity", "next": "Complete the first Partner Center submission manually; subsequent submission automation is a separately authenticated integration."},
        }
        selected = requirements[payload.provider]
        if target != selected["target"]:
            raise HTTPException(409, f"{payload.provider} requires a {selected['target']} release; selected release is {target}.")
        suffix = selected["artifact"]
        if not any(item["filename"].lower().endswith(suffix) for item in release.get("artifacts", [])):
            raise HTTPException(409, f"The release does not contain the required {suffix} artifact.")
        return {
            "provider": payload.provider,
            "release_id": release["id"],
            "state": "prepared_not_submitted",
            "account_requirement": selected["account"],
            "next_step": selected["next"],
            "artifacts": release["artifacts"],
            "warning": "Preparation is not submission or store approval. The creator must review the package and confirm every final publish action in their own publisher account."
        }

    app.include_router(router)
