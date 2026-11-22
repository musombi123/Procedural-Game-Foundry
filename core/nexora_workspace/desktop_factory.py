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


MONETIZATION_ADDONS = {
    "analytics": {"label": "Game analytics", "provider": "NEXORA local event schema"},
    "rewarded_ads": {"label": "Rewarded ads", "provider": "AdMob SDK integration required"},
    "in_app_purchases": {"label": "In-app purchases", "provider": "Google Play Billing integration required"},
    "premium_content": {"label": "Premium content", "provider": "Game-side entitlement integration required"},
}
AD_PLACEMENTS = {"rewarded_continue", "rewarded_bonus", "interstitial_between_levels", "banner_menu"}


def validate_monetization_manifest(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("A monetization settings object is required.")
    supplied = payload.get("addons", {})
    if not isinstance(supplied, dict) or set(supplied) - set(MONETIZATION_ADDONS):
        raise ValueError("The add-on selection contains an unsupported module.")
    addons = {key: bool(supplied.get(key, False)) for key in MONETIZATION_ADDONS}
    ads = payload.get("ads", {})
    if not isinstance(ads, dict):
        raise ValueError("Ad settings must be an object.")
    placements = ads.get("placements", [])
    if not isinstance(placements, list) or len(placements) > len(AD_PLACEMENTS):
        raise ValueError("Choose valid ad placements.")
    normalized_placements = sorted(set(str(item) for item in placements))
    if any(item not in AD_PLACEMENTS for item in normalized_placements):
        raise ValueError("An ad placement is not supported.")
    provider = str(ads.get("provider") or "none").lower()
    if provider not in {"none", "admob"}:
        raise ValueError("The selected ad provider is unsupported.")
    if normalized_placements and (provider != "admob" or not addons["rewarded_ads"]):
        raise ValueError("Enable the rewarded-ads add-on and select AdMob before configuring ad placements.")
    app_id = str(ads.get("app_id") or "").strip()
    android_unit = str(ads.get("android_unit_id") or "").strip()
    ios_unit = str(ads.get("ios_unit_id") or "").strip()
    if len(app_id) > 160 or len(android_unit) > 160 or len(ios_unit) > 160:
        raise ValueError("AdMob identifiers must be 160 characters or fewer.")
    if provider == "admob" and not re.fullmatch(r"ca-app-pub-[0-9]{4,25}~[0-9]{4,25}", app_id):
        raise ValueError("Enter a valid AdMob app ID before selecting AdMob.")
    return {
        "schema_version": "1.0",
        "addons": addons,
        "ads": {
            "provider": provider,
            "app_id": app_id,
            "android_unit_id": android_unit,
            "ios_unit_id": ios_unit,
            "placements": normalized_placements,
            "test_mode": bool(ads.get("test_mode", True)),
            "consent_required": True,
        },
        "integrations": {
            "analytics": "local_event_schema" if addons["analytics"] else "disabled",
            "rewarded_ads": "sdk_required" if addons["rewarded_ads"] else "disabled",
            "in_app_purchases": "billing_sdk_required" if addons["in_app_purchases"] else "disabled",
            "premium_content": "entitlement_runtime_required" if addons["premium_content"] else "disabled",
        },
        "updated_at": _utc(),
    }


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


def _ensure_starter_godot_project(folder: Path, project_name: str) -> Path:
    """Create a minimal editable Godot 4 project before the first generated build."""
    game = folder / "game"
    game.mkdir(parents=True, exist_ok=True)
    project_file = game / "project.godot"
    if not project_file.is_file():
        safe_name = json.dumps(str(project_name or "Untitled Game")[:80], ensure_ascii=False)
        project_file.write_text(
            "config_version=5\n\n"
            "[application]\n"
            f"config/name={safe_name}\n\n"
            "[display]\n"
            "window/size/viewport_width=1280\n"
            "window/size/viewport_height=720\n\n"
            "[rendering]\n"
            "renderer/rendering_method=\"gl_compatibility\"\n",
            encoding="utf-8",
        )
    for name in ("scenes", "scripts", "assets", "audio", "addons", "tests"):
        (game / name).mkdir(exist_ok=True)
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


def _safe_restore_archive(
    archive: Path,
    folder: Path,
    expected_owner: str | None = None,
) -> dict[str, Any]:
    """Restore all project source/metadata while preserving owner and backup history."""
    staging_root = folder / "restore-staging"
    stage = staging_root / uuid.uuid4().hex
    retired = staging_root / ("retired-" + uuid.uuid4().hex)
    extracted = stage / "project"
    stage.mkdir(parents=True, exist_ok=False)
    extracted.mkdir(parents=True, exist_ok=False)
    count = 0
    total = 0
    moved_current: list[str] = []
    moved_restored: list[str] = []
    keep_names = {"backups", "restore-staging", "nexora_owner.json"}
    try:
        with zipfile.ZipFile(archive, "r") as source:
            entries = source.infolist()
            if len(entries) > BACKUP_FILE_LIMIT + 1:
                raise HTTPException(413, "Backup archive contains too many entries.")
            safe_entries: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
            archive_files: set[str] = set()
            for entry in entries:
                raw_name = str(entry.filename or "")
                normalized = raw_name.replace("\\", "/")
                path = PurePosixPath(normalized)
                mode = (entry.external_attr >> 16) & 0o170000
                if (
                    not normalized
                    or "\x00" in normalized
                    or path.is_absolute()
                    or ":" in normalized
                    or any(part in {"", ".", ".."} for part in path.parts)
                    or any(part.lower() in IGNORED_DIRECTORY_NAMES for part in path.parts)
                ):
                    raise HTTPException(400, "Backup contains an unsafe or excluded path.")
                if mode == 0o120000:
                    raise HTTPException(400, "Backup contains a symbolic link.")
                if mode not in {0, 0o040000, 0o100000}:
                    raise HTTPException(400, "Backup contains an unsupported special file.")
                if normalized == "NEXORA_BACKUP_MANIFEST.json":
                    continue
                count += 1
                total += int(entry.file_size)
                if count > BACKUP_FILE_LIMIT:
                    raise HTTPException(413, "Backup archive contains too many entries.")
                if total > BACKUP_TOTAL_LIMIT:
                    raise HTTPException(413, "Backup expands beyond the 10 GiB restore limit.")
                target = extracted.joinpath(*path.parts).resolve()
                if extracted.resolve() not in target.parents:
                    raise HTTPException(400, "Backup extraction escaped its staging directory.")
                if not entry.is_dir() and not raw_name.endswith(("/", "\\")):
                    archive_files.add(path.as_posix())
                safe_entries.append((entry, path))

            try:
                manifest = json.loads(source.read("NEXORA_BACKUP_MANIFEST.json").decode("utf-8"))
            except (KeyError, ValueError, UnicodeDecodeError) as exc:
                raise HTTPException(422, "Backup archive has no valid NEXORA manifest.") from exc
            if str(manifest.get("project_id") or "") != folder.name:
                raise HTTPException(403, "Backup belongs to a different NEXORA project.")
            manifest_rows = manifest.get("files")
            if not isinstance(manifest_rows, list):
                raise HTTPException(422, "Backup file manifest is invalid.")
            expected_files: set[str] = set()
            checksums: dict[str, tuple[int, str]] = {}
            for row in manifest_rows:
                if not isinstance(row, dict):
                    raise HTTPException(422, "Backup file manifest contains an invalid entry.")
                relative = str(row.get("path") or "").replace("\\", "/")
                pure = PurePosixPath(relative)
                digest = str(row.get("sha256") or "")
                size_bytes = row.get("size_bytes")
                if (
                    not relative
                    or pure.is_absolute()
                    or ":" in relative
                    or any(part in {"", ".", ".."} for part in pure.parts)
                    or any(part.lower() in IGNORED_DIRECTORY_NAMES for part in pure.parts)
                    or not isinstance(size_bytes, int)
                    or size_bytes < 0
                    or not re.fullmatch(r"[a-fA-F0-9]{64}", digest)
                    or pure.as_posix() in expected_files
                ):
                    raise HTTPException(422, "Backup file manifest contains an unsafe, duplicate or invalid entry.")
                normalized_path = pure.as_posix()
                expected_files.add(normalized_path)
                checksums[normalized_path] = (size_bytes, digest.lower())
            if expected_files != archive_files:
                raise HTTPException(422, "Backup archive contents do not match its file manifest.")

            # Extract only after every archive path and manifest entry has passed.
            for entry, relative in safe_entries:
                target = extracted.joinpath(*relative.parts)
                if entry.is_dir() or str(entry.filename).endswith(("/", "\\")):
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    with source.open(entry, "r") as input_stream, target.open("xb") as output_stream:
                        shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)
                except FileExistsError as exc:
                    raise HTTPException(400, "Backup contains duplicate file paths.") from exc

        for relative, (expected_size, expected_digest) in checksums.items():
            staged_file = extracted.joinpath(*PurePosixPath(relative).parts)
            if not staged_file.is_file() or staged_file.is_symlink():
                raise HTTPException(422, "Backup is missing a manifest-listed project file.")
            if staged_file.stat().st_size != expected_size:
                raise HTTPException(409, "A restored project file does not match its manifest size.")
            if _sha256_file(staged_file).lower() != expected_digest:
                raise HTTPException(409, "A restored project file failed its SHA-256 check.")

        if not (extracted / "game" / "project.godot").is_file():
            raise HTTPException(422, "This backup does not contain a restorable Godot project.")
        definition_file = extracted / "pgf.json"
        if not definition_file.is_file():
            raise HTTPException(422, "Backup is missing the Foundry project definition.")
        try:
            definition_id = json.loads(definition_file.read_text(encoding="utf-8")).get("id")
        except (OSError, ValueError, TypeError) as exc:
            raise HTTPException(422, "Backup Foundry project definition is unreadable.") from exc
        if str(definition_id or "") != folder.name:
            raise HTTPException(403, "Backup Foundry project ID does not match the target project.")
        owner_record = extracted / "nexora_owner.json"
        if expected_owner is not None:
            if not owner_record.is_file():
                raise HTTPException(403, "Backup has no NEXORA project owner record.")
            try:
                archived_owner = json.loads(owner_record.read_text(encoding="utf-8")).get("user_id")
            except (OSError, ValueError, TypeError) as exc:
                raise HTTPException(422, "Backup owner record is unreadable.") from exc
            if str(archived_owner) != str(expected_owner):
                raise HTTPException(403, "Backup belongs to a different NEXORA account.")

        # Preserve the live owner marker and all backup history. Replace the
        # rest of the managed project root as a rollback-capable transaction.
        retired.mkdir(parents=True, exist_ok=False)
        try:
            for child in list(folder.iterdir()):
                if child.name.lower() in keep_names:
                    continue
                child.replace(retired / child.name)
                moved_current.append(child.name)

            for child in list(extracted.iterdir()):
                if child.name == "nexora_owner.json":
                    continue
                child.replace(folder / child.name)
                moved_restored.append(child.name)
        except OSError as restore_error:
            rollback_errors = []
            for name in reversed(moved_restored):
                current = folder / name
                try:
                    if current.is_dir() and not current.is_symlink():
                        shutil.rmtree(current)
                    else:
                        current.unlink(missing_ok=True)
                except OSError as exc:
                    rollback_errors.append(str(exc))
            for name in reversed(moved_current):
                old = retired / name
                try:
                    if old.exists() or old.is_symlink():
                        old.replace(folder / name)
                except OSError as exc:
                    rollback_errors.append(str(exc))
            if rollback_errors:
                raise HTTPException(
                    500,
                    "Project restore failed and rollback was incomplete. Recovery files were retained at "
                    + str(retired) + ". Contact NEXORA support before retrying.",
                ) from restore_error
            raise

        shutil.rmtree(retired, ignore_errors=True)
        return {
            "restored": True,
            "files": len(archive_files),
            "size_bytes": total,
            "restored_components": sorted(moved_restored),
            "owner_marker_preserved": True,
            "backup_history_preserved": True,
        }
    finally:
        shutil.rmtree(stage, ignore_errors=True)

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


LEVEL_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
LEVEL_DIFFICULTIES = {"story", "easy", "normal", "hard", "expert"}
LEVEL_STATES = {"draft", "testing", "approved"}


def _levels_path(folder: Path) -> Path:
    return folder / ".nexora" / "levels.json"


def validate_level_manifest(payload: Any) -> dict[str, Any]:
    """Validate an ordered, project-local multi-level manifest without touching assets."""
    if not isinstance(payload, dict) or not isinstance(payload.get("levels"), list):
        raise ValueError("A levels array is required.")
    supplied = payload["levels"]
    if not supplied or len(supplied) > 100:
        raise ValueError("A project must contain between 1 and 100 levels.")
    normalized = []
    seen: set[str] = set()
    for index, raw in enumerate(supplied, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"Level {index} must be an object.")
        level_id = str(raw.get("id") or "").strip()
        title = str(raw.get("title") or "").strip()
        if not LEVEL_ID_RE.fullmatch(level_id):
            raise ValueError(f"Level {index} has an invalid ID.")
        if level_id in seen:
            raise ValueError("Level IDs must be unique.")
        seen.add(level_id)
        if not title or len(title) > 80:
            raise ValueError(f"Level {index} title must contain 1–80 characters.")
        difficulty = str(raw.get("difficulty") or "normal").lower()
        state = str(raw.get("state") or "draft").lower()
        if difficulty not in LEVEL_DIFFICULTIES:
            raise ValueError(f"Level {index} has an unsupported difficulty.")
        if state not in LEVEL_STATES:
            raise ValueError(f"Level {index} has an unsupported state.")
        asset_ids = raw.get("shared_asset_ids", [])
        if not isinstance(asset_ids, list) or len(asset_ids) > 200:
            raise ValueError(f"Level {index} shared_asset_ids must be a list of at most 200 IDs.")
        clean_assets = []
        for asset_id in asset_ids:
            value = str(asset_id).strip()
            if not LEVEL_ID_RE.fullmatch(value):
                raise ValueError(f"Level {index} contains an invalid shared asset ID.")
            if value not in clean_assets:
                clean_assets.append(value)
        normalized.append({
            "id": level_id,
            "title": title,
            "order": index,
            "difficulty": difficulty,
            "state": state,
            "shared_asset_ids": clean_assets,
        })
    return {"schema_version": "1.0", "levels": normalized, "level_count": len(normalized)}


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
            protected = [Path(resolved.anchor)]
            for key in ("WINDIR", "SystemRoot", "ProgramFiles", "ProgramFiles(x86)"):
                value = os.environ.get(key)
                if value:
                    protected.append(Path(value).resolve())
            if platform.system().lower() != "windows":
                protected.extend(Path(item) for item in ("/etc", "/usr", "/bin", "/sbin", "/var", "/System", "/Library"))
            home = Path.home().resolve()
            if resolved == home or any(resolved == item or item in resolved.parents for item in protected):
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

    @router.get("/projects/{pid}/monetization")
    def get_project_monetization(pid: str, request: Request):
        folder = _project_folder(manager, pid, request)
        path = folder / ".nexora" / "monetization.json"
        if not path.is_file():
            return validate_monetization_manifest({})
        try:
            return validate_monetization_manifest(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError) as exc:
            raise HTTPException(500, "The local monetization settings are unreadable or invalid.") from exc

    @router.put("/projects/{pid}/monetization")
    def save_project_monetization(pid: str, payload: dict, request: Request):
        folder = _project_folder(manager, pid, request)
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

    @router.get("/projects/{pid}/levels")
    def list_project_levels(pid: str, request: Request):
        folder = _project_folder(manager, pid, request)
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

    @router.put("/projects/{pid}/levels")
    def save_project_levels(pid: str, payload: dict, request: Request):
        folder = _project_folder(manager, pid, request)
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

    @router.post("/projects/{pid}/initialize")
    def initialize_project(pid: str, request: Request):
        folder = _project_folder(manager, pid, request)
        definition = manager.load(pid)
        game = _ensure_starter_godot_project(folder, definition.project.name)
        manifest = _manifest(folder, _owner_id(request), definition.project.name)
        profile = collect_system_profile(manager.root)
        lock = _project_lock(folder, profile)
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

    @router.post("/projects/{pid}/file", status_code=201)
    def create_project_file(pid: str, payload: dict, request: Request):
        folder = _project_folder(manager, pid, request)
        base = _editor_root(folder)
        path = str(payload.get("path") or "")
        content = payload.get("content", "")
        if not isinstance(content, str):
            raise HTTPException(422, "File content must be text.")
        encoded = content.encode("utf-8")
        if len(encoded) > WRITE_LIMIT:
            raise HTTPException(413, "New source files are limited to 2 MiB.")
        if Path(path).suffix.lower() not in TEXT_EXTENSIONS:
            raise HTTPException(415, "This file extension is not editable in the embedded text editor.")
        target = _relative_project_path(base, path)
        if not target.parent.is_dir():
            raise HTTPException(404, "The destination folder must already exist.")
        try:
            with target.open("xb") as stream:
                stream.write(encoded)
        except FileExistsError as exc:
            raise HTTPException(409, "A file already exists at this path. Open it instead of overwriting it.") from exc
        except OSError as exc:
            raise HTTPException(400, "The source file could not be created.") from exc
        return {"created": True, "path": path, "size_bytes": len(encoded), "sha256": hashlib.sha256(encoded).hexdigest()}

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
        return _safe_restore_archive(archive, folder, expected_owner=_owner_id(request))

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

    # Google Drive OAuth and resumable backup are local-agent-only extensions.
    from core.nexora_workspace.drive_backup import register_drive_backup_routes
    register_drive_backup_routes(app, manager)
