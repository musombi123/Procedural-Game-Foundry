"""User-authorized local project-root selection for NEXORA Local Agent."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Callable

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field


class WorkspaceRootRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=3, max_length=2048)
    confirm_migration: bool = False


def _config_path(agent_data: Path) -> Path:
    return agent_data / "workspace-root.json"


def load_workspace_root(agent_data: str | Path) -> Path | None:
    config = _config_path(Path(agent_data).expanduser().resolve())
    try:
        value = json.loads(config.read_text(encoding="utf-8")).get("path")
        candidate = Path(str(value)).expanduser()
        if not candidate.is_absolute():
            return None
        resolved = candidate.resolve()
        # A removable drive may be disconnected when the agent starts. Fall
        # back to the installer default so the agent can still be paired and
        # the creator can select another workspace from Studio.
        return resolved if resolved.is_dir() else None
    except (OSError, ValueError, TypeError):
        return None


def _safe_target(raw_path: str, agent_data: Path) -> Path:
    candidate = Path(raw_path.strip()).expanduser()
    if not candidate.is_absolute():
        raise HTTPException(422, "Choose an absolute folder path on this computer.")
    target = candidate.resolve()
    if target == Path(target.anchor) or len(target.parts) < 3:
        raise HTTPException(422, "Choose a project folder, not a drive or filesystem root.")
    if target == agent_data or agent_data in target.parents:
        raise HTTPException(403, "The project workspace cannot be inside NEXORA Local Agent credentials or staging data.")
    if target.exists() and not target.is_dir():
        raise HTTPException(422, "The selected workspace path is not a folder.")
    protected = []
    if os.name == "nt":
        for key in ("WINDIR", "SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData"):
            value = os.environ.get(key)
            if value:
                protected.append(Path(value).resolve())
    else:
        protected.extend(Path(value).resolve() for value in ("/etc", "/usr", "/bin", "/sbin", "/proc", "/sys", "/dev"))
    for path in protected:
        if target == path or path in target.parents:
            raise HTTPException(403, "The selected folder is a protected operating-system location.")
    return target


def set_workspace_root(manager: Any, agent_data: str | Path, raw_path: str, user_id: str, confirm_migration: bool = False) -> dict:
    agent_root = Path(agent_data).expanduser().resolve()
    target = _safe_target(raw_path, agent_root)
    current = Path(manager.root).resolve()
    marker = target / ".nexora-workspace.json"
    if marker.is_symlink():
        raise HTTPException(403, "A NEXORA workspace marker cannot be a symbolic link.")
    marker_preexisted = marker.is_file()

    # A selected existing workspace is account-bound, even when it is already
    # the active root. Never relabel another account's root as the caller's.
    if target.exists():
        if marker_preexisted:
            try:
                recorded = json.loads(marker.read_text(encoding="utf-8")).get("owner_id")
            except (OSError, ValueError):
                raise HTTPException(409, "Selected folder has an invalid NEXORA workspace marker.")
            if str(recorded) != str(user_id):
                raise HTTPException(404, "Workspace not found.")
        elif target != current and list(target.iterdir()):
            raise HTTPException(409, "The selected folder is not empty and is not already a verified NEXORA workspace. Choose an empty folder or select its verified NEXORA workspace root.")
        elif target == current:
            # A legacy current root can be initialized only after every project
            # folder that has a project definition proves the current owner.
            for child in target.iterdir():
                if child.is_symlink():
                    raise HTTPException(403, "The current workspace contains a symbolic link. Remove it or migrate its target explicitly.")
                if not child.is_dir() or not (child / "pgf.json").is_file():
                    continue
                owner_file = child / "nexora_owner.json"
                if owner_file.is_symlink():
                    raise HTTPException(403, "A project ownership marker cannot be a symbolic link.")
                try:
                    child_owner = json.loads(owner_file.read_text(encoding="utf-8")).get("user_id") if owner_file.is_file() else None
                except (OSError, ValueError):
                    raise HTTPException(409, "A project in this workspace has unreadable ownership metadata.")
                if str(child_owner or "") != str(user_id):
                    raise HTTPException(403, "The current workspace contains a project that is not verified as owned by this NEXORA account.")
    target.mkdir(parents=True, exist_ok=True)

    # Copy, never move, account-owned projects. Reject symlinks rather than
    # following them outside the project root during migration.
    source_projects: list[Path] = []
    if current != target and current.is_dir() and current != agent_root:
        for owner_file in current.glob("*/nexora_owner.json"):
            folder = owner_file.parent
            if folder.is_symlink() or owner_file.is_symlink():
                raise HTTPException(422, "A project selected for migration contains a symbolic-link ownership path.")
            try:
                record = json.loads(owner_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if str(record.get("user_id")) != str(user_id) or not (folder / "pgf.json").is_file():
                continue
            for current_dir, directories, files in os.walk(folder, followlinks=False):
                base = Path(current_dir)
                if base.is_symlink():
                    raise HTTPException(422, f"Project '{folder.name}' contains a symbolic link and cannot be migrated safely.")
                for entry in directories + files:
                    if (base / entry).is_symlink():
                        raise HTTPException(422, f"Project '{folder.name}' contains a symbolic link and cannot be migrated safely.")
            source_projects.append(folder)

    copy_projects: list[Path] = []
    for folder in source_projects:
        destination = target / folder.name
        if destination.exists():
            destination_owner = destination / "nexora_owner.json"
            if destination_owner.is_symlink():
                raise HTTPException(409, f"Destination project '{folder.name}' has a symbolic-link ownership marker.")
            try:
                existing_owner = json.loads(destination_owner.read_text(encoding="utf-8")).get("user_id") if destination_owner.is_file() else None
            except (OSError, ValueError):
                raise HTTPException(409, f"Destination project '{folder.name}' has unreadable ownership metadata.")
            if str(existing_owner or "") == str(user_id) and (destination / "pgf.json").is_file():
                # A prior interrupted migration may already have copied this
                # project. Treat that verified destination as completed.
                continue
            raise HTTPException(409, f"Cannot migrate project '{folder.name}': a folder with that ID already exists at the destination.")
        copy_projects.append(folder)

    if copy_projects and not confirm_migration:
        raise HTTPException(409, {
            "code": "WORKSPACE_MIGRATION_CONFIRMATION_REQUIRED",
            "message": f"{len(copy_projects)} existing project(s) will be copied to the selected folder. The original files will remain untouched.",
            "projects_to_copy": [folder.name for folder in copy_projects],
        })

    staging_root = target / ".nexora-migration-staging"
    if staging_root.is_symlink():
        raise HTTPException(403, "NEXORA migration staging cannot be a symbolic link.")
    staging = staging_root / __import__("uuid").uuid4().hex
    promoted: list[Path] = []
    marker_created = False
    config = _config_path(agent_root)
    previous_config = config.read_bytes() if config.is_file() else None
    try:
        if copy_projects:
            staging.mkdir(parents=True, exist_ok=False)
            for folder in copy_projects:
                shutil.copytree(folder, staging / folder.name, symlinks=False)
            # Promote only complete copies. The original project folders stay
            # untouched in the previous workspace.
            for staged_project in sorted(staging.iterdir()):
                destination = target / staged_project.name
                if destination.exists():
                    raise HTTPException(409, f"Destination project '{staged_project.name}' appeared during migration.")
                staged_project.rename(destination)
                promoted.append(destination)

        if not marker_preexisted:
            import datetime
            marker_payload = {
                "schema_version": 1,
                "owner_id": str(user_id),
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            temporary = marker.with_name(marker.name + ".tmp")
            temporary.write_text(json.dumps(marker_payload, indent=2), encoding="utf-8")
            temporary.replace(marker)
            marker_created = True

        config.parent.mkdir(parents=True, exist_ok=True)
        config_tmp = config.with_name(config.name + ".tmp")
        config_tmp.write_text(json.dumps({"path": str(target)}, indent=2), encoding="utf-8")
        config_tmp.replace(config)

        manager.root = target
        manager.root.mkdir(parents=True, exist_ok=True)
        runtime_root = target / ".nexora-runtime"
        if runtime_root.is_symlink():
            raise HTTPException(403, "NEXORA runtime data cannot be a symbolic link.")
        runtime_root.mkdir(parents=True, exist_ok=True)
        os.environ["PGF_DATA_DIR"] = str(runtime_root)
    except Exception:
        # Roll back only folders created by this attempt. A workspace that was
        # already valid before this request is never removed or relabelled.
        for destination in reversed(promoted):
            if destination.exists():
                shutil.rmtree(destination, ignore_errors=True)
        if marker_created:
            marker.unlink(missing_ok=True)
        if previous_config is None:
            config.unlink(missing_ok=True)
        else:
            temporary = config.with_name(config.name + ".restore.tmp")
            temporary.write_bytes(previous_config)
            temporary.replace(config)
        manager.root = current
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        try:
            staging_root.rmdir()
        except OSError:
            pass

    return {
        "saved": True,
        "workspace_root": str(target),
        "projects_directory": str(target),
        "projects_migrated": len(promoted),
        "original_workspace_preserved": True,
    }


def register_local_workspace_routes(app: Any, manager: Any, agent_data: str | Path, paired_dependency: Callable):
    agent_root = Path(agent_data).expanduser().resolve()

    @app.get("/workspace")
    def get_workspace(user_id: str = Depends(paired_dependency)):
        root = Path(manager.root).resolve()
        marker = root / ".nexora-workspace.json"
        disk = shutil.disk_usage(root)
        return {
            "workspace_root": str(root),
            "projects_directory": str(root),
            "paired_user": user_id,
            "marker_present": marker.is_file(),
            "storage": {"total": disk.total, "used": disk.used, "free": disk.free},
        }

    @app.put("/workspace/root")
    def update_workspace_root(payload: WorkspaceRootRequest, user_id: str = Depends(paired_dependency)):
        return set_workspace_root(manager, agent_root, payload.path, user_id, payload.confirm_migration)

    @app.get("/drive/oauth/callback")
    def google_drive_oauth_callback(code: str = "", state: str = "", error: str = ""):
        from fastapi.responses import HTMLResponse
        from core.nexora_workspace.drive_oauth import finish_drive_oauth
        if error:
            message = "Google authorization was not completed. Return to NEXORA and try again."
        else:
            try:
                finish_drive_oauth(code, state)
                message = "Google Drive is connected. You may close this window and return to NEXORA."
            except Exception as exc:
                message = "Google Drive connection failed: " + str(exc)
        escaped = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return HTMLResponse(
            "<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>NEXORA Drive</title></head>"
            "<body style='font-family:system-ui;background:#07111f;color:#e2e8f0;padding:3rem;max-width:40rem;margin:auto'>"
            "<h1 style='color:#67e8f9'>NEXORA · Google Drive</h1><p>" + escaped + "</p>"
            "<p>You can close this tab.</p><script>setTimeout(()=>{try{window.close()}catch{}},1800)</script></body></html>"
        )
