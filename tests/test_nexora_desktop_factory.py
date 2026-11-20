from __future__ import annotations

import json
import stat
from pathlib import Path
from zipfile import ZipFile, ZipInfo

import pytest
from fastapi import HTTPException

from core.execution_policy import is_local_compute_only_request
from core.nexora_workspace.local_factory import _archive_project, _safe_extract
from core.nexora_workspace.desktop_api import _resolve_project_path, _restore_archive
from core.project_engine.manager import ProjectManager
from core.project_engine.models import ProjectCreate
from services.worker.local_workspace import load_workspace_root, set_workspace_root


class DummyProjectManager:
    def __init__(self, root: Path):
        self.root = root.resolve()


def test_workspace_root_migration_requires_confirmation_and_preserves_source(tmp_path: Path):
    old_root = tmp_path / "old-projects"
    agent_root = tmp_path / "agent-secrets"
    destination = tmp_path / "new-projects"
    project = old_root / "game-one"
    project.mkdir(parents=True)
    agent_root.mkdir()

    (project / "pgf.json").write_text('{"id":"game-one"}', encoding="utf-8")
    (project / "nexora_owner.json").write_text(
        json.dumps({"user_id": "creator-1"}), encoding="utf-8"
    )
    (project / "game").mkdir()
    (project / "game" / "project.godot").write_text("[application]\n", encoding="utf-8")

    manager = DummyProjectManager(old_root)
    with pytest.raises(HTTPException) as blocked:
        set_workspace_root(manager, agent_root, str(destination), "creator-1")

    assert blocked.value.status_code == 409
    assert blocked.value.detail["code"] == "WORKSPACE_MIGRATION_CONFIRMATION_REQUIRED"
    assert (project / "pgf.json").is_file()

    result = set_workspace_root(
        manager, agent_root, str(destination), "creator-1", confirm_migration=True
    )

    assert result["saved"] is True
    assert result["projects_migrated"] == 1
    assert result["original_workspace_preserved"] is True
    assert manager.root == destination.resolve()
    assert (destination / "game-one" / "game" / "project.godot").is_file()
    assert (old_root / "game-one" / "game" / "project.godot").is_file()
    assert json.loads((destination / ".nexora-workspace.json").read_text())["owner_id"] == "creator-1"
    assert load_workspace_root(agent_root) == destination.resolve()


def test_workspace_root_rejects_filesystem_root_and_agent_secret_directory(tmp_path: Path):
    agent_root = (tmp_path / "agent").resolve()
    agent_root.mkdir()
    manager = DummyProjectManager(tmp_path / "projects")
    manager.root.mkdir()

    with pytest.raises(HTTPException) as root_error:
        set_workspace_root(manager, agent_root, str(Path("/")), "creator-1")
    assert root_error.value.status_code == 422

    with pytest.raises(HTTPException) as secret_error:
        set_workspace_root(manager, agent_root, str(agent_root / "workspace"), "creator-1")
    assert secret_error.value.status_code == 403


def test_backup_archive_excludes_caches_and_agent_workloads(tmp_path: Path):
    project = tmp_path / "MyGame"
    (project / "game").mkdir(parents=True)
    (project / "game" / "project.godot").write_text("[application]\n", encoding="utf-8")
    (project / ".git").mkdir()
    (project / ".git" / "config").write_text("private git metadata", encoding="utf-8")
    (project / "node_modules").mkdir()
    (project / "node_modules" / "junk.js").write_text("cache", encoding="utf-8")
    (project / "workspace_jobs").mkdir()
    (project / "workspace_jobs" / "worker.log").write_text("temporary job log", encoding="utf-8")

    archive_path = tmp_path / "backup.zip"
    report = _archive_project(project, archive_path)

    with ZipFile(archive_path) as archive:
        names = set(archive.namelist())

    assert report["file_count"] == 1
    assert names == {"game/project.godot"}


def test_safe_extract_rejects_parent_traversal(tmp_path: Path):
    archive_path = tmp_path / "traversal.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("../escape.txt", "should not be extracted")

    destination = tmp_path / "restore"
    destination.mkdir()
    with pytest.raises(HTTPException) as error:
        _safe_extract(archive_path, destination)

    assert error.value.status_code == 422
    assert not (tmp_path / "escape.txt").exists()


def test_safe_extract_rejects_symbolic_links(tmp_path: Path):
    archive_path = tmp_path / "symlink.zip"
    link = ZipInfo("linked-file")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with ZipFile(archive_path, "w") as archive:
        archive.writestr(link, "../../outside.txt")

    destination = tmp_path / "restore"
    destination.mkdir()
    with pytest.raises(HTTPException) as error:
        _safe_extract(archive_path, destination)

    assert error.value.status_code == 422
    assert not (tmp_path / "outside.txt").exists()


def test_cloud_policy_blocks_all_desktop_factory_routes_but_not_billing():
    assert is_local_compute_only_request("GET", "/api/v1/desktop/toolchains")
    assert is_local_compute_only_request("POST", "/api/v1/desktop/toolchains/lock")
    assert is_local_compute_only_request("GET", "/api/v1/factory/toolchains/catalog")
    assert is_local_compute_only_request("POST", "/api/v1/workspace/projects/import")
    assert not is_local_compute_only_request("GET", "/api/v1/creator-flow/plans")
    assert not is_local_compute_only_request("POST", "/api/v1/creator-flow/checkout")



def test_workspace_root_same_path_rejects_foreign_project_ownership(tmp_path: Path):
    root = tmp_path / "projects"
    agent_root = tmp_path / "agent"
    project = root / "foreign-project"
    project.mkdir(parents=True)
    agent_root.mkdir()
    (project / "pgf.json").write_text('{"id":"foreign-project"}', encoding="utf-8")
    (project / "nexora_owner.json").write_text(json.dumps({"user_id":"other-account"}), encoding="utf-8")

    manager = DummyProjectManager(root)
    with pytest.raises(HTTPException) as blocked:
        set_workspace_root(manager, agent_root, str(root), "creator-1")

    assert blocked.value.status_code == 403
    assert not (root / ".nexora-workspace.json").exists()


def test_project_file_resolver_rejects_internal_symlinks(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "safe.txt").write_text("safe", encoding="utf-8")
    try:
        (project / "alias.txt").symlink_to(project / "safe.txt")
    except OSError:
        pytest.skip("The current operating system does not allow creating a symlink in this test environment.")

    with pytest.raises(HTTPException) as blocked:
        _resolve_project_path(project, "alias.txt")

    assert blocked.value.status_code == 403


def test_snapshot_restore_is_atomic_and_preserves_owner_record(tmp_path: Path):
    root = tmp_path / "projects"
    root.mkdir()
    manager = ProjectManager(root)
    definition = manager.create(ProjectCreate(name="Restore Test"))
    folder = manager.path_for(definition.id)
    owner_record = {"user_id":"creator-1","created_at":"2026-11-20T00:00:00+00:00"}
    (folder / "nexora_owner.json").write_text(json.dumps(owner_record), encoding="utf-8")
    game = folder / "game"
    game.mkdir()
    scene = game / "main.gd"
    scene.write_text("print('original')\\n", encoding="utf-8")

    archive = tmp_path / "snapshot.zip"
    _archive_project(folder, archive)
    scene.write_text("print('damaged')\\n", encoding="utf-8")

    result = _restore_archive(manager, folder, definition, "creator-1", archive)

    assert result["restored"] is True
    assert (folder / "game" / "main.gd").read_text(encoding="utf-8") == "print('original')\\n"
    assert json.loads((folder / "nexora_owner.json").read_text(encoding="utf-8")) == owner_record
    assert manager.load(definition.id).id == definition.id
    assert not list(root.glob(f".{definition.id}.rollback-*"))
