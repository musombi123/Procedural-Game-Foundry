"""User-authorized local project-root selection for NEXORA Local Agent."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Callable, Any

from fastapi import Depends, HTTPException, Request
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
        return candidate.resolve()
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
    # Avoid well-known operating-system and application installation roots.
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


def register_local_workspace_routes(app: Any, manager: Any, agent_data: str | Path, paired_dependency: Callable):
    agent_root = Path(agent_data).expanduser().resolve()

    @app.get("/workspace")
    def get_workspace(user_id: str = Depends(paired_dependency)):
        root = Path(manager.root).resolve()
        marker = root / ".nexora-workspace.json"
        return {
            "workspace_root": str(root),
            "projects_directory": str(root),
            "paired_user": user_id,
            "marker_present": marker.is_file(),
            "storage": shutil.disk_usage(root).__dict__ if hasattr(shutil.disk_usage(root), "__dict__") else {
                "total": shutil.disk_usage(root).total,
                "used": shutil.disk_usage(root).used,
                "free": shutil.disk_usage(root).free,
            },
        }

    @app.put("/workspace/root")
    def set_workspace_root(payload: WorkspaceRootRequest, user_id: str = Depends(paired_dependency)):
        target = _safe_target(payload.path, agent_root)
        current = Path(manager.root).resolve()
        marker = target / ".nexora-workspace.json"

        if target.exists() and target != current:
            if marker.is_file():
                try:
                    recorded = json.loads(marker.read_text(encoding="utf-8")).get("owner_id")
                except (OSError, ValueError):
                    raise HTTPException(409, "Selected folder has an invalid NEXORA workspace marker.")
                if str(recorded) != str(user_id):
                    raise HTTPException(404, "Workspace not found.")
            else:
                meaningful = [item for item in target.iterdir()]
                if meaningful:
                    raise HTTPException(409, "The selected folder is not empty and is not already a NEXORA workspace. Choose an empty folder or select its verified NEXORA workspace root.")
        target.mkdir(parents=True, exist_ok=True)

        # Copy (never move) existing projects so a root change cannot destroy
        # the creator's previous workspace. Only projects owned by this account
        # are migrated, and conflicts stop the operation.
        migrated = 0
        if current != target and current.is_dir() and current != agent_root:
            source_projects = []
            for owner_file in current.glob("*/nexora_owner.json"):
                folder = owner_file.parent
                try:
                    record = json.loads(owner_file.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if str(record.get("user_id")) == str(user_id) and (folder / "pgf.json").is_file():
                    source_projects.append(folder)
            for folder in source_projects:
                destination = target / folder.name
                if destination.exists():
                    raise HTTPException(409, f"Cannot migrate project '{folder.name}': a folder with that ID already exists at the destination.")
            if source_projects and not payload.confirm_migration:
                raise HTTPException(409, {
                    "code": "WORKSPACE_MIGRATION_CONFIRMATION_REQUIRED",
                    "message": f"{len(source_projects)} existing project(s) will be copied to the selected folder. The original files will remain untouched.",
                    "projects_to_copy": [folder.name for folder in source_projects],
                })
            for folder in source_projects:
                shutil.copytree(folder, target / folder.name, symlinks=False)
                migrated += 1

        marker_payload = {"schema_version": 1, "owner_id": str(user_id), "created_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()}
        temporary = marker.with_name(marker.name + ".tmp")
        temporary.write_text(json.dumps(marker_payload, indent=2), encoding="utf-8")
        temporary.replace(marker)
        config = _config_path(agent_root)
        config.parent.mkdir(parents=True, exist_ok=True)
        config_tmp = config.with_name(config.name + ".tmp")
        config_tmp.write_text(json.dumps({"path": str(target)}, indent=2), encoding="utf-8")
        config_tmp.replace(config)

        manager.root = target
        manager.root.mkdir(parents=True, exist_ok=True)
        return {
            "saved": True,
            "workspace_root": str(target),
            "projects_directory": str(target),
            "projects_migrated": migrated,
            "original_workspace_preserved": True,
        }
