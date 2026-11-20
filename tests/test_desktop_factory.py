import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi import HTTPException

from core.nexora_workspace.desktop_factory import (
    TOOL_CATALOG,
    _backup_project,
    _copy_godot_project,
    _ensure_starter_godot_project,
    _relative_project_path,
    _safe_restore_archive,
)


def test_project_path_rejects_traversal(tmp_path: Path):
    base = tmp_path / "game"
    base.mkdir()
    with pytest.raises(HTTPException) as error:
        _relative_project_path(base, "../outside.txt")
    assert error.value.status_code == 400


def test_project_path_rejects_symlinks(tmp_path: Path):
    base = tmp_path / "game"
    base.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.gd").write_text("not project data", encoding="utf-8")
    link = base / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable on this runner.")
    with pytest.raises(HTTPException) as error:
        _relative_project_path(base, "linked/secret.gd")
    assert error.value.status_code == 403


def test_import_copies_godot_source_and_skips_runtime_caches(tmp_path: Path):
    source = tmp_path / "source-game"
    source.mkdir()
    (source / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    (source / "player.gd").write_text("extends Node\n", encoding="utf-8")
    (source / ".godot").mkdir()
    (source / ".godot" / "editor_layout.cfg").write_text("cache", encoding="utf-8")
    destination = tmp_path / "workspace" / "Imported" / "game"
    result = _copy_godot_project(source, destination)
    assert result["files"] == 2
    assert (destination / "project.godot").is_file()
    assert (destination / "player.gd").is_file()
    assert not (destination / ".godot").exists()


def test_snapshot_integrity_and_restore_round_trip(tmp_path: Path):
    project = tmp_path / "project"
    game = project / "game"
    game.mkdir(parents=True)
    (game / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    script = game / "player.gd"
    script.write_text("extends Node\n", encoding="utf-8")
    owner_file = project / "nexora_owner.json"
    owner_file.write_text(json.dumps({"user_id": "creator-1"}), encoding="utf-8")
    workspace_file = project / "nexora_workspace.json"
    workspace_file.write_text('{"scene":"original"}', encoding="utf-8")
    snapshot = _backup_project(project, "snapshot-20261120T172100-1234abcd")
    script.write_text("changed\n", encoding="utf-8")
    workspace_file.write_text('{"scene":"modified"}', encoding="utf-8")
    result = _safe_restore_archive(
        project / "backups" / (snapshot["id"] + ".zip"),
        project,
        expected_owner="creator-1",
    )
    assert result["restored"] is True
    assert script.read_text(encoding="utf-8") == "extends Node\n"
    assert workspace_file.read_text(encoding="utf-8") == '{"scene":"original"}'
    assert json.loads(owner_file.read_text(encoding="utf-8"))["user_id"] == "creator-1"
    assert (project / "backups" / (snapshot["id"] + ".zip")).is_file()



def test_restore_rejects_zip_path_traversal(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    archive = project / "unsafe.zip"
    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as output:
        output.writestr(r"..\escaped.txt", "Windows path traversal must not escape")
        output.writestr("game/project.godot", "config_version=5\n")
    with pytest.raises(HTTPException):
        _safe_restore_archive(archive, project)
    assert not (tmp_path / "escaped.txt").exists()


def test_tool_installer_exposes_only_fixed_package_ids():
    assert set(TOOL_CATALOG) == {
        "godot", "blender", "ffmpeg", "java17", "android_studio"
    }
    assert all(item["winget_id"] for item in TOOL_CATALOG.values())



def test_starter_project_is_created_and_existing_project_is_preserved(tmp_path: Path):
    folder = tmp_path / "new-project"
    folder.mkdir()
    game = _ensure_starter_godot_project(folder, "Starter Game")
    project_file = game / "project.godot"
    assert project_file.is_file()
    text = project_file.read_text(encoding="utf-8")
    assert 'config/name="Starter Game"' in text
    script = game / "scripts" / "custom.gd"
    script.write_text("extends Node\\n", encoding="utf-8")
    _ensure_starter_godot_project(folder, "Renamed Game")
    assert script.read_text(encoding="utf-8") == "extends Node\\n"
    assert "Starter Game" in project_file.read_text(encoding="utf-8")


def test_google_desktop_oauth_redirect_is_loopback_root_only(monkeypatch):
    from core.nexora_workspace.drive_backup import _redirect_uri

    monkeypatch.delenv("NEXORA_GOOGLE_DRIVE_REDIRECT_URI", raising=False)
    assert _redirect_uri() == "http://127.0.0.1:8765"
    monkeypatch.setenv("NEXORA_GOOGLE_DRIVE_REDIRECT_URI", "http://127.0.0.1:8765/engine/callback")
    with pytest.raises(HTTPException) as error:
        _redirect_uri()
    assert error.value.status_code == 503


def test_snapshot_restore_rejects_another_account_owner(tmp_path: Path):
    project = tmp_path / "project"
    game = project / "game"
    game.mkdir(parents=True)
    (game / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    (project / "nexora_owner.json").write_text(json.dumps({"user_id": "creator-1"}), encoding="utf-8")
    snapshot = _backup_project(project, "snapshot-20261120T172102-1234abcd")
    before = (game / "project.godot").read_text(encoding="utf-8")
    with pytest.raises(HTTPException) as error:
        _safe_restore_archive(
            project / "backups" / (snapshot["id"] + ".zip"),
            project,
            expected_owner="creator-2",
        )
    assert error.value.status_code == 403
    assert (game / "project.godot").read_text(encoding="utf-8") == before
