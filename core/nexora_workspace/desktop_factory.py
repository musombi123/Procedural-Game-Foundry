"""NEXORA desktop-first project, toolchain, backup and release services.

All routes in this module are mounted only inside the paired local Foundry
agent. They never run on the hosted control plane. The project directory on
the creator's computer remains the source of truth.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from core.project_engine.models import ProjectCreate
from services.worker.system_profile import collect_system_profile

WRITE_LIMIT = 2 * 1024 * 1024
BACKUP_FILE_LIMIT = 25_000
BACKUP_TOTAL_LIMIT = 10 * 1024 * 1024 * 1024
TEXT_EXTENSIONS = {
    ".gd", ".tscn", ".tres", ".godot", ".json", ".cfg", ".ini", ".md",
    ".txt", ".shader", ".gdshader", ".cs", ".xml", ".yml", ".yaml",
    ".toml", ".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css",
    ".svg", ".gitignore", ".gdignore", ".csv", ".po", ".pot",
}
IGNORED_DIRECTORY_NAMES = {
    ".git", ".godot", ".import", "node_modules", ".venv", "venv",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "backups", "restore-staging", ".cache",
}
TOOL_CATALOG: dict[str, dict[str, str]] = {
    "godot": {
        "label": "Godot Engine 4",
        "winget_id": "GodotEngine.GodotEngine",
        "purpose": "Game editor, runtime, headless validation and export",
    },
    "blender": {
        "label": "Blender",
        "winget_id": "BlenderFoundation.Blender",
        "purpose": "Procedural 3D assets, characters and environments",
    },
    "ffmpeg": {
        "label": "FFmpeg",
        "winget_id": "Gyan.FFmpeg",
        "purpose": "Video/audio inspection and media conversion",
    },
    "java17": {
        "label": "Eclipse Temurin JDK 17",
        "winget_id": "EclipseAdoptium.Temurin.17.JDK",
        "purpose": "Android export toolchain runtime",
    },
    "android_studio": {
        "label": "Android Studio",
        "winget_id": "Google.AndroidStudio",
        "purpose": "Android SDK, platform tools, build-tools and emulator manager",
    },
}
SAFE_TOOL_IDS = frozenset(TOOL_CATALOG)
PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,96}$")
SNAPSHOT_ID_RE = re.compile(r"^snapshot-[0-9T_-]+-[a-f0-9]{8}$")


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _settings_file() -> Path:
    root = Path(os.environ.get(
        "NEXORA_LOCAL_AGENT_DATA",
        str(Path.home() / ".nexora-local-agent"),
    )).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root / "desktop-factory.json"


def restore_workspace_root(manager: Any) -> None:
    """Restore the last creator-selected projects directory on agent startup."""
    path = _settings_file()
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
        selected = Path(str(settings.get("workspace_root") or "")).expanduser()
        if selected.is_absolute() and selected.is_dir():
            manager.root = selected.resolve()
            manager.root.mkdir(parents=True, exist_ok=True)
    except (OSError, ValueError, TypeError):
        # A damaged optional preference must never prevent the Local Agent
        # from starting; the previous/default local project root stays active.
        return


def _owner_id(request: Request) -> str:
    owner = getattr(request.state, "nexora_user_id", None)
    if not owner:
        raise HTTPException(401, "Sign in and pair this computer with your NEXORA account.")
    return str(owner)


def _project_folder(manager: Any, pid: str, request: Request) -> Path:
    if not PROJECT_ID_RE.fullmatch(str(pid or "")):
        raise HTTPException(400, "Invalid NEXORA project ID.")
    try:
        folder = manager.path_for(pid)
        manager.load(pid)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Project not found.") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    marker = folder / "nexora_owner.json"
    if not marker.is_file():
        raise HTTPException(403, "This project has no verified NEXORA owner record.")
    try:
        recorded = json.loads(marker.read_text(encoding="utf-8")).get("user_id")
    except (OSError, ValueError, TypeError) as exc:
        raise HTTPException(500, "Project ownership record is unreadable.") from exc
    if str(recorded) != _owner_id(request):
        raise HTTPException(404, "Project not found.")
    return folder


def _editor_root(folder: Path) -> Path:
    game = folder / "game"
    if (game / "project.godot").is_file():
        return game
    if (folder / "project.godot").is_file():
        return folder
    return game


def _manifest(folder: Path, owner: str, name: str | None = None) -> dict[str, Any]:
    nexora = folder / ".nexora"
    nexora.mkdir(parents=True, exist_ok=True)
    manifest_path = nexora / "project.json"
    try:
        existing = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    except (OSError, ValueError, TypeError):
        existing = {}
    manifest = {
        "schema_version": 1,
        "project_id": folder.name,
        "project_uuid": existing.get("project_uuid") or str(uuid.uuid4()),
        "owner_account_id": owner,
        "name": (name or existing.get("name") or folder.name)[:80],
        "engine": "godot",
        "engine_version": existing.get("engine_version"),
        "created_at": existing.get("created_at") or _utc(),
        "updated_at": _utc(),
        "local_first": True,
        "cloud_is_source_of_truth": False,
    }
    _atomic_json(manifest_path, manifest)
    lock_path = nexora / "toolchain.lock.json"
    if not lock_path.is_file():
        _atomic_json(lock_path, {
            "schema_version": 1,
            "engine": {"name": "Godot", "version": None, "export_templates": None},
            "tools": {},
            "updated_at": _utc(),
        })
    return manifest


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _relative_project_path(base: Path, relative: str, *, allow_root: bool = False) -> Path:
    value = str(relative or "").replace("\\", "/")
    pure = PurePosixPath(value)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        if allow_root and value in {"", "."}:
            return base.resolve()
        raise HTTPException(400, "Project paths must be relative and cannot contain traversal segments.")
    if any(part.lower() in IGNORED_DIRECTORY_NAMES for part in pure.parts):
        raise HTTPException(403, "This generated/cache directory is not exposed by the NEXORA file workspace.")
    candidate = base.joinpath(*pure.parts)
    current = base
    for part in pure.parts:
        current = current / part
        if current.is_symlink():
            raise HTTPException(403, "Symbolic links are not followed by the NEXORA project file API.")
    resolved = candidate.resolve()
    if resolved != base.resolve() and base.resolve() not in resolved.parents:
        raise HTTPException(403, "Project path escapes the selected project directory.")
    return resolved


def _toolchain_summary(profile: dict[str, Any]) -> dict[str, Any]:
    tools = profile.get("tools") or {}
    android = profile.get("android") or {}
    mapping = {
        "python": tools.get("python"),
        "godot": tools.get("godot"),
        "blender": tools.get("blender"),
        "ffmpeg": tools.get("ffmpeg"),
        "ffprobe": tools.get("ffprobe"),
        "java": tools.get("java"),
        "adb": tools.get("adb") or ({"path": android.get("adb"), "available": bool(android.get("adb"))}),
        "apkanalyzer": {"path": android.get("apkanalyzer"), "available": bool(android.get("apkanalyzer"))},
        "aapt": {"path": android.get("aapt"), "available": bool(android.get("aapt"))},
    }
    return {
        key: {
            "available": bool(value and value.get("available", value.get("path"))),
            "path": value.get("path") if isinstance(value, dict) else None,
            "version": value.get("version") if isinstance(value, dict) else None,
        }
        for key, value in mapping.items()
    }


def _project_lock(folder: Path, profile: dict[str, Any]) -> dict[str, Any]:
    lock_path = folder / ".nexora" / "toolchain.lock.json"
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8")) if lock_path.is_file() else {}
    except (OSError, ValueError):
        lock = {}
    detected = _toolchain_summary(profile)
    tools = dict(lock.get("tools") or {})
    for key, value in detected.items():
        if value["available"]:
            tools[key] = {
                "path": value["path"],
                "version": value["version"],
                "detected_at": _utc(),
            }
    lock.update({
        "schema_version": 1,
        "engine": {
            "name": "Godot",
            "version": detected["godot"]["version"],
            "export_templates": lock.get("engine", {}).get("export_templates"),
        },
        "tools": tools,
        "updated_at": _utc(),
    })
    _atomic_json(lock_path, lock)
    return lock


def _copy_godot_project(source: Path, destination: Path) -> dict[str, Any]:
    source = source.resolve()
    destination = destination.resolve()
    if not source.is_dir() or not (source / "project.godot").is_file():
        raise HTTPException(422, "Select a folder containing a Godot project.godot file.")
    if source == destination or source in destination.parents or destination in source.parents:
        raise HTTPException(400, "The import source and NEXORA destination cannot contain one another.")
    destination.mkdir(parents=True, exist_ok=False)
    files = 0
    total_bytes = 0
    for current, directories, filenames in os.walk(source, followlinks=False):
        current_path = Path(current)
        directories[:] = [
            name for name in directories
            if name.lower() not in IGNORED_DIRECTORY_NAMES
            and not (current_path / name).is_symlink()
        ]
        relative = current_path.relative_to(source)
        target_dir = destination / relative
        target_dir.mkdir(parents=True, exist_ok=True)
        for filename in filenames:
            source_file = current_path / filename
            if source_file.is_symlink():
                continue
            try:
                size = source_file.stat().st_size
            except OSError:
                continue
            files += 1
            total_bytes += size
            if files > BACKUP_FILE_LIMIT:
                raise HTTPException(413, "The project contains too many files to import safely.")
            if total_bytes > BACKUP_TOTAL_LIMIT:
                raise HTTPException(413, "The project exceeds the 10 GiB local import limit.")
            target_file = target_dir / filename
            shutil.copy2(source_file, target_file)
    if not (destination / "project.godot").is_file():
        raise HTTPException(422, "The selected folder did not contain a copyable project.godot file.")
    return {"files": files, "size_bytes": total_bytes}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_excluded(relative: Path) -> bool:
    return any(part.lower() in IGNORED_DIRECTORY_NAMES for part in relative.parts)


def _backup_project(folder: Path, snapshot_id: str) -> dict[str, Any]:
    backups = folder / "backups"
    backups.mkdir(exist_ok=True)
    archive = backups / f"{snapshot_id}.zip"
    manifest_rows: list[dict[str, Any]] = []
    total = 0
    count = 0
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for current, directories, filenames in os.walk(folder, followlinks=False):
            current_path = Path(current)
            directories[:] = [
                name for name in directories
                if name.lower() not in IGNORED_DIRECTORY_NAMES
                and not (current_path / name).is_symlink()
            ]
            for filename in filenames:
                source = current_path / filename
                if source.is_symlink() or source.resolve() == archive.resolve():
                    continue
                relative = source.relative_to(folder)
                if _snapshot_excluded(relative):
                    continue
                size = source.stat().st_size
                count += 1
                total += size
                if count > BACKUP_FILE_LIMIT:
                    raise HTTPException(413, "Snapshot exceeds the 25,000-file safety limit.")
                if total > BACKUP_TOTAL_LIMIT:
                    raise HTTPException(413, "Snapshot exceeds the 10 GiB safety limit.")
                checksum = _sha256_file(source)
                output.write(source, arcname=relative.as_posix())
                manifest_rows.append({
                    "path": relative.as_posix(),
                    "size_bytes": size,
                    "sha256": checksum,
                })
        output.writestr("NEXORA_BACKUP_MANIFEST.json", json.dumps({
            "schema_version": 1,
            "project_id": folder.name,
            "created_at": _utc(),
            "files": manifest_rows,
        }, indent=2))
    record = {
        "id": snapshot_id,
        "created_at": _utc(),
        "file_count": count,
        "source_bytes": total,
        "archive_bytes": archive.stat().st_size,
        "sha256": _sha256_file(archive),
        "filename": archive.name,
    }
    _atomic_json(backups / f"{snapshot_id}.json", record)
    return record


def _safe_restore_archive(archive: Path, folder: Path) -> dict[str, Any]:
    stage = folder / "restore-staging" / uuid.uuid4().hex
    stage.mkdir(parents=True, exist_ok=False)
    count = 0
    total = 0
    try:
        with zipfile.ZipFile(archive, "r") as source:
            entries = source.infolist()
            if len(entries) > BACKUP_FILE_LIMIT + 1:
                raise HTTPException(413, "Backup archive contains too many entries.")
            for entry in entries:
                path = PurePosixPath(entry.filename)
                mode = (entry.external_attr >> 16) & 0o170000
                if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
                    raise HTTPException(400, "Backup contains an unsafe path.")
                if mode == 0o120000:
                    raise HTTPException(400, "Backup contains a symbolic link.")
                if entry.filename == "NEXORA_BACKUP_MANIFEST.json":
                    continue
                count += 1
                total += int(entry.file_size)
                if total > BACKUP_TOTAL_LIMIT:
                    raise HTTPException(413, "Backup expands beyond the 10 GiB restore limit.")
                target = stage.joinpath(*path.parts).resolve()
                if stage.resolve() not in target.parents:
                    raise HTTPException(400, "Backup extraction escaped its staging directory.")
            source.extractall(stage)
        replacement = stage / "game"
        if not (replacement / "project.godot").is_file():
            raise HTTPException(422, "This backup does not contain a restorable Godot project.")
        live_game = folder / "game"
        retired = folder / f".game-before-restore-{uuid.uuid4().hex[:8]}"
        if live_game.exists():
            live_game.replace(retired)
        replacement.replace(live_game)
        if retired.exists():
            shutil.rmtree(retired, ignore_errors=True)
        return {"restored": True, "files": count, "size_bytes": total}
    finally:
        shutil.rmtree(stage.parent, ignore_errors=True)


def _publisher_readiness(profile: dict[str, Any]) -> list[dict[str, Any]]:
    tools = _toolchain_summary(profile)
    android = profile.get("android") or {}
    is_mac = platform.system().lower() == "darwin"
    xcode = shutil.which("xcodebuild")
    play_service_account = os.environ.get("NEXORA_PLAY_SERVICE_ACCOUNT_FILE", "").strip()
    apple_key = os.environ.get("NEXORA_APP_STORE_CONNECT_KEY_FILE", "").strip()
    microsoft_values = (
        "NEXORA_MSSTORE_TENANT_ID", "NEXORA_MSSTORE_CLIENT_ID",
        "NEXORA_MSSTORE_CLIENT_SECRET", "NEXORA_MSSTORE_PRODUCT_ID",
    )
    signing_path = os.environ.get("GODOT_ANDROID_KEYSTORE_RELEASE_PATH", "").strip()
    release_signing_ready = (
        bool(signing_path) and Path(signing_path).is_file()
        and bool(os.environ.get("GODOT_ANDROID_KEYSTORE_RELEASE_USER"))
        and bool(os.environ.get("GODOT_ANDROID_KEYSTORE_RELEASE_PASSWORD"))
    )
    play_ready = (
        bool(play_service_account)
        and Path(play_service_account).is_file()
        and bool(android.get("sdk_root"))
        and bool(tools["java"]["available"])
        and release_signing_ready
    )
    apple_ready = (
        False and is_mac and bool(xcode)
        and all(os.environ.get(key) for key in (
            "NEXORA_APP_STORE_CONNECT_ISSUER_ID",
            "NEXORA_APP_STORE_CONNECT_KEY_ID",
        ))
        and bool(apple_key) and Path(apple_key).is_file()
    )
    microsoft_packager = bool(shutil.which("makeappx") or shutil.which("makeappx.exe"))
    microsoft_ready = all(os.environ.get(key) for key in microsoft_values) and microsoft_packager
    return [
        {
            "id": "google_play",
            "name": "Google Play",
            "ready": play_ready,
            "requirements": [
                "Your Google Play developer account and app listing",
                "Local Android SDK, Java and a signed AAB",
                "A service-account JSON file authorized in Play Console",
            ],
            "missing": [
                label for label, ok in (
                    ("Play service-account JSON file", bool(play_service_account and Path(play_service_account).is_file())),
                    ("Android SDK", bool(android.get("sdk_root"))),
                    ("Java", bool(tools["java"]["available"])),
                    ("Protected Android release signing", release_signing_ready),
                ) if not ok
            ],
            "publish_requires_confirmation": True,
            "first_submission_may_require_console_setup": True,
        },
        {
            "id": "apple_app_store",
            "name": "Apple App Store",
            "ready": apple_ready,
            "requirements": [
                "A Mac with Xcode and the required signing identities",
                "Your Apple Developer and App Store Connect accounts",
                "App Store Connect API issuer ID, key ID and private key file",
            ],
            "missing": [
                label for label, ok in (
                    ("NEXORA macOS build target (not implemented)", False),
                ("macOS and Xcode", is_mac and bool(xcode)),
                    ("App Store Connect issuer and key IDs", bool(os.environ.get("NEXORA_APP_STORE_CONNECT_ISSUER_ID") and os.environ.get("NEXORA_APP_STORE_CONNECT_KEY_ID"))),
                    ("App Store Connect private key file", bool(apple_key and Path(apple_key).is_file())),
                ) if not ok
            ],
            "publish_requires_confirmation": True,
            "first_submission_may_require_console_setup": True,
        },
        {
            "id": "microsoft_store",
            "name": "Microsoft Store",
            "ready": microsoft_ready,
            "requirements": [
                "Your Partner Center developer account and product identity",
                "A signed MSIX package and configured publisher identity",
                "An authorized Microsoft Entra application",
            ],
            "missing": [key for key in microsoft_values if not os.environ.get(key)] + ([] if microsoft_packager else ["Windows SDK makeappx MSIX packager"]),
            "publish_requires_confirmation": True,
            "first_submission_may_require_console_setup": True,
        },
    ]


def register_desktop_factory_routes(app: Any, manager: Any) -> None:
    """Register local-only NEXORA desktop factory routes on the local Foundry app."""
    router = APIRouter(prefix="/api/v1/desktop", tags=["NEXORA Desktop Factory"])
    restore_workspace_root(manager)

    @router.get("/status")
    def desktop_status(request: Request):
        owner = _owner_id(request)
        profile = collect_system_profile(manager.root)
        return {
            "product": "NEXORA Desktop Factory",
            "execution_location": "creator_device",
            "cloud_compute_enabled": False,
            "owner_account_id": owner,
            "workspace_root": str(manager.root),
            "workspace_exists": manager.root.is_dir(),
            "projects": len(manager.list()),
            "machine": profile.get("machine", {}),
            "gpu": profile.get("gpu", {}),
            "tools": _toolchain_summary(profile),
            "android": profile.get("android", {}),
            "supported_targets": ["web", "android", "windows"],
            "apple_export": {
                "available_on_this_machine": platform.system().lower() == "darwin",
                "requires_macos_xcode": True,
            },
        }

    @router.put("/workspace")
    def choose_workspace(payload: dict, request: Request):
        _owner_id(request)
        raw = str(payload.get("path") or "").strip()
        if not raw or len(raw) > 2048:
            raise HTTPException(422, "Enter a valid projects directory path.")
        selected = Path(raw).expanduser()
        if not selected.is_absolute():
            raise HTTPException(422, "The projects directory must be an absolute path.")
        try:
            resolved = selected.resolve()
            protected = [Path(resolved.anchor), Path.home().resolve()]
            for key in ("WINDIR", "SystemRoot", "ProgramFiles", "ProgramFiles(x86)"):
                value = os.environ.get(key)
                if value:
                    protected.append(Path(value).resolve())
            if platform.system().lower() != "windows":
                protected.extend(Path(item) for item in ("/etc", "/usr", "/bin", "/sbin", "/var", "/System", "/Library"))
            if any(resolved == item or item in resolved.parents for item in protected):
                raise HTTPException(403, "Choose a dedicated NEXORA projects folder, not a system, program, drive-root or home directory.")
            resolved.mkdir(parents=True, exist_ok=True)
            if not resolved.is_dir():
                raise HTTPException(422, "The selected workspace path is not a directory.")
            probe = resolved / f".nexora-write-test-{uuid.uuid4().hex[:8]}"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except HTTPException:
            raise
        except OSError as exc:
            raise HTTPException(400, f"NEXORA cannot use that directory: {exc}") from exc
        previous = str(manager.root)
        manager.root = resolved
        _atomic_json(_settings_file(), {
            "workspace_root": str(resolved),
            "updated_at": _utc(),
            "owner_account_id": _owner_id(request),
        })
        return {"saved": True, "workspace_root": str(resolved), "previous_root": previous}

    @router.post("/projects/{pid}/initialize")
    def initialize_project(pid: str, request: Request):
        folder = _project_folder(manager, pid, request)
        definition = manager.load(pid)
        manifest = _manifest(folder, _owner_id(request), definition.project.name)
        profile = collect_system_profile(manager.root)
        lock = _project_lock(folder, profile)
        game = _editor_root(folder)
        if game.is_dir():
            _manifest(game, _owner_id(request), definition.project.name)
            _atomic_json(game / ".nexora" / "toolchain.lock.json", lock)
        return {"initialized": True, "manifest": manifest, "toolchain_lock": lock}

    @router.post("/projects/import")
    def import_godot_project(payload: dict, request: Request):
        owner = _owner_id(request)
        raw = str(payload.get("path") or "").strip()
        if not raw or len(raw) > 2048:
            raise HTTPException(422, "Enter the absolute folder path of an existing Godot project.")
        source = Path(raw).expanduser()
        if not source.is_absolute():
            raise HTTPException(422, "The imported project path must be absolute.")
        if not source.is_dir() or not (source / "project.godot").is_file():
            raise HTTPException(422, "The selected directory must contain project.godot.")
        name = str(payload.get("name") or source.name or "Imported Godot Project").strip()[:80]
        definition = manager.create(ProjectCreate(
            name=name or "Imported Godot Project",
            description="Imported existing Godot project",
            genre="science-fiction",
            dimension="3d",
        ))
        folder = manager.path_for(definition.id)
        try:
            _atomic_json(folder / "nexora_owner.json", {"user_id": owner, "created_at": _utc()})
            copied = _copy_godot_project(source, folder / "game")
            manifest = _manifest(folder, owner, name)
            _manifest(folder / "game", owner, name)
            return {
                "imported": True,
                "id": definition.id,
                "name": name,
                "source_path": str(source.resolve()),
                "destination": str(folder / "game"),
                "files": copied["files"],
                "size_bytes": copied["size_bytes"],
                "manifest": manifest,
            }
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise

    @router.get("/projects/{pid}/files")
    def list_project_files(pid: str, request: Request, path: str = ""):
        folder = _project_folder(manager, pid, request)
        base = _editor_root(folder)
        if not base.is_dir():
            raise HTTPException(404, "The Godot project folder has not been created yet.")
        directory = _relative_project_path(base, path, allow_root=True)
        if not directory.is_dir():
            raise HTTPException(404, "Project directory not found.")
        rows = []
        for child in sorted(directory.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
            if child.is_symlink() or child.name.lower() in IGNORED_DIRECTORY_NAMES:
                continue
            if child.name.startswith(".") and child.name != ".nexora":
                continue
            try:
                size = child.stat().st_size if child.is_file() else None
            except OSError:
                size = None
            rows.append({
                "name": child.name,
                "path": child.relative_to(base).as_posix(),
                "kind": "directory" if child.is_dir() else "file",
                "size_bytes": size,
                "editable": child.is_file() and child.suffix.lower() in TEXT_EXTENSIONS,
            })
            if len(rows) >= 500:
                break
        return {"path": path, "entries": rows, "root": str(base)}

    @router.get("/projects/{pid}/file")
    def read_project_file(pid: str, request: Request, path: str):
        folder = _project_folder(manager, pid, request)
        base = _editor_root(folder)
        target = _relative_project_path(base, path)
        if not target.is_file():
            raise HTTPException(404, "Project file not found.")
        if target.suffix.lower() not in TEXT_EXTENSIONS:
            raise HTTPException(415, "This file type is not exposed in the text editor. Use the asset workspace for binary files.")
        if target.stat().st_size > WRITE_LIMIT:
            raise HTTPException(413, "Files larger than 2 MiB cannot be opened in the embedded text editor.")
        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(415, "This file is not valid UTF-8 text.") from exc
        return {
            "path": path,
            "content": content,
            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "size_bytes": target.stat().st_size,
        }

    @router.put("/projects/{pid}/file")
    def write_project_file(pid: str, payload: dict, request: Request):
        folder = _project_folder(manager, pid, request)
        base = _editor_root(folder)
        path = str(payload.get("path") or "")
        content = payload.get("content")
        if not isinstance(content, str):
            raise HTTPException(422, "File content must be text.")
        encoded = content.encode("utf-8")
        if len(encoded) > WRITE_LIMIT:
            raise HTTPException(413, "Files larger than 2 MiB cannot be saved through the embedded text editor.")
        if Path(path).suffix.lower() not in TEXT_EXTENSIONS:
            raise HTTPException(415, "This file extension is not editable in the embedded text editor.")
        target = _relative_project_path(base, path)
        if target.exists() and target.is_dir():
            raise HTTPException(400, "The selected path is a directory.")
        expected = payload.get("expected_sha256")
        if target.exists() and expected:
            actual = _sha256_file(target)
            if actual != str(expected):
                raise HTTPException(409, "This file changed after it was opened. Reload it before saving to avoid overwriting newer edits.")
        elif target.exists() and not expected:
            raise HTTPException(409, "Reload the file before overwriting it so NEXORA can verify its current version.")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".nexora-tmp")
        temporary.write_bytes(encoded)
        temporary.replace(target)
        return {
            "saved": True,
            "path": path,
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "size_bytes": len(encoded),
        }

    @router.post("/projects/{pid}/snapshots")
    def create_snapshot(pid: str, request: Request):
        folder = _project_folder(manager, pid, request)
        snapshot_id = "snapshot-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
        return _backup_project(folder, snapshot_id)

    @router.get("/projects/{pid}/snapshots")
    def list_snapshots(pid: str, request: Request):
        folder = _project_folder(manager, pid, request)
        backups = folder / "backups"
        records = []
        if backups.is_dir():
            for metadata in sorted(backups.glob("snapshot-*.json"), reverse=True):
                try:
                    item = json.loads(metadata.read_text(encoding="utf-8"))
                    archive = backups / (str(item.get("id")) + ".zip")
                    if archive.is_file():
                        records.append(item)
                except (OSError, ValueError, TypeError):
                    continue
        return {"snapshots": records}

    @router.post("/projects/{pid}/snapshots/{snapshot_id}/restore")
    def restore_snapshot(pid: str, snapshot_id: str, request: Request):
        folder = _project_folder(manager, pid, request)
        if not SNAPSHOT_ID_RE.fullmatch(snapshot_id):
            raise HTTPException(400, "Invalid snapshot ID.")
        archive = folder / "backups" / f"{snapshot_id}.zip"
        if not archive.is_file():
            raise HTTPException(404, "Snapshot not found.")
        metadata_path = folder / "backups" / f"{snapshot_id}.json"
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise HTTPException(500, "Snapshot metadata is unavailable.") from exc
        if _sha256_file(archive) != metadata.get("sha256"):
            raise HTTPException(409, "Snapshot integrity check failed. The archive was changed or damaged.")
        return _safe_restore_archive(archive, folder)

    @router.get("/toolchains")
    def toolchains(request: Request, project_id: str | None = None):
        _owner_id(request)
        profile = collect_system_profile(manager.root)
        lock = None
        if project_id:
            folder = _project_folder(manager, project_id, request)
            _manifest(folder, _owner_id(request), manager.load(project_id).project.name)
            lock = _project_lock(folder, profile)
        return {
            "machine": profile.get("machine", {}),
            "gpu": profile.get("gpu", {}),
            "tools": _toolchain_summary(profile),
            "android": profile.get("android", {}),
            "catalog": [
                {"id": key, **value, "supported_on_windows": True}
                for key, value in TOOL_CATALOG.items()
            ],
            "lock": lock,
            "install_provider": "winget" if platform.system().lower() == "windows" and shutil.which("winget") else None,
        }

    @router.post("/toolchains/install")
    def install_toolchains(payload: dict, request: Request):
        _owner_id(request)
        selected = payload.get("tools")
        if not isinstance(selected, list) or not selected or len(selected) > len(SAFE_TOOL_IDS):
            raise HTTPException(422, "Select one or more supported toolchains.")
        if any(item not in SAFE_TOOL_IDS for item in selected):
            raise HTTPException(422, "The toolchain selection contains an unsupported package.")
        if payload.get("confirm_install") is not True:
            raise HTTPException(403, "Confirm the selected software installation before continuing.")
        if platform.system().lower() != "windows":
            raise HTTPException(501, "Guided package installation currently supports Windows with WinGet. macOS and Linux tools can be detected and configured, but are not installed automatically.")
        winget = shutil.which("winget")
        if not winget:
            raise HTTPException(503, "WinGet is not available. Install or update Microsoft App Installer, then retry.")
        results = []
        for tool_id in selected:
            entry = TOOL_CATALOG[tool_id]
            command = [
                winget, "install", "--id", entry["winget_id"], "--exact",
                "--source", "winget", "--accept-source-agreements",
                "--accept-package-agreements", "--silent",
            ]
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=3600,
                    stdin=subprocess.DEVNULL,
                    shell=False,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                results.append({"id": tool_id, "installed": False, "error": "Installation timed out after 60 minutes."})
                continue
            except OSError as exc:
                results.append({"id": tool_id, "installed": False, "error": str(exc)[:500]})
                continue
            results.append({
                "id": tool_id,
                "installed": completed.returncode == 0,
                "exit_code": completed.returncode,
                "output": (completed.stdout or completed.stderr or "")[-1800:],
            })
        profile = collect_system_profile(manager.root)
        inventory_path = _settings_file().with_name("toolchain-inventory.json")
        _atomic_json(inventory_path, {
            "updated_at": _utc(),
            "tools": _toolchain_summary(profile),
        })
        return {"results": results, "tools": _toolchain_summary(profile)}

    @router.get("/publish/readiness")
    def publish_readiness(request: Request):
        _owner_id(request)
        profile = collect_system_profile(manager.root)
        return {
            "execution_location": "creator_device",
            "providers": _publisher_readiness(profile),
            "supported_local_build_targets": ["web", "android_apk", "android_aab", "windows"],
            "apple_requires_mac_relay": platform.system().lower() != "darwin",
            "note": "Readiness checks do not submit or publish an app. You must own the relevant developer account, app record, legal agreements and credentials.",
        }

    @router.post("/projects/{pid}/publish/prepare")
    def prepare_release(pid: str, payload: dict, request: Request):
        folder = _project_folder(manager, pid, request)
        platform_id = str(payload.get("platform") or "")
        artifact_id = str(payload.get("artifact_id") or "")
        if platform_id not in {"web", "android", "windows", "linux"}:
            raise HTTPException(422, "Unsupported release platform.")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", artifact_id):
            raise HTTPException(422, "Invalid build artifact ID.")
        artifact = None
        for job_file in (folder / "workspace_jobs").glob("*.json"):
            try:
                items = json.loads(job_file.read_text(encoding="utf-8")).get("artifacts", [])
            except (OSError, ValueError, TypeError):
                continue
            artifact = next((row for row in items if str(row.get("id")) == artifact_id), None)
            if artifact:
                break
        if not artifact:
            raise HTTPException(404, "The selected build artifact was not found.")
        relative = Path(str(artifact.get("path") or ""))
        if relative.is_absolute() or ".." in relative.parts:
            raise HTTPException(400, "Build artifact path is unsafe.")
        source = (folder / relative).resolve()
        if folder.resolve() not in source.parents or not source.is_file():
            raise HTTPException(404, "The build artifact is missing from the local project.")
        if artifact_id != platform_id:
            raise HTTPException(422, "Select the build artifact whose platform matches this release.")
        release_dir = folder / "releases"
        release_dir.mkdir(exist_ok=True)
        release_source = source
        if platform_id == "web":
            web_directory = source.parent
            bundle = release_dir / ("web-bundle-" + uuid.uuid4().hex[:8] + ".zip")
            with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                for item in web_directory.rglob("*"):
                    if item.is_file() and not item.is_symlink():
                        archive.write(item, arcname=item.relative_to(web_directory).as_posix())
            release_source = bundle
        manifest = {
            "schema_version": 1,
            "project_id": pid,
            "owner_account_id": _owner_id(request),
            "platform": platform_id,
            "artifact": {
                "id": artifact_id,
                "filename": release_source.name,
                "relative_path": release_source.relative_to(folder).as_posix(),
                "size_bytes": release_source.stat().st_size,
                "sha256": _sha256_file(release_source),
            },
            "prepared_at": _utc(),
            "publishing_status": "prepared_locally_not_submitted",
            "publisher_account_owner": _owner_id(request),
        }
        output = release_dir / f"{platform_id}-{artifact_id}-release-manifest.json"
        _atomic_json(output, manifest)
        return {"prepared": True, "manifest": manifest, "manifest_path": str(output)}

    app.include_router(router)
