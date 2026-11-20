from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi import HTTPException

from core.nexora_workspace.desktop_factory import (
    TOOL_CATALOG,
    _backup_project,
    _copy_godot_project,
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
    snapshot = _backup_project(project, "snapshot-20261120T172100-1234abcd")
    script.write_text("changed\n", encoding="utf-8")
    result = _safe_restore_archive(project / "backups" / (snapshot["id"] + ".zip"), project)
    assert result["restored"] is True
    assert script.read_text(encoding="utf-8") == "extends Node\n"


def test_restore_rejects_zip_path_traversal(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    archive = project / "unsafe.zip"
    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as output:
        output.writestr("../escaped.txt", "must not escape")
        output.writestr("game/project.godot", "config_version=5\n")
    with pytest.raises(HTTPException):
        _safe_restore_archive(archive, project)
    assert not (tmp_path / "escaped.txt").exists()


def test_tool_installer_exposes_only_fixed_package_ids():
    assert set(TOOL_CATALOG) == {
        "godot", "blender", "ffmpeg", "java17", "android_studio"
    }
    assert all(item["winget_id"] for item in TOOL_CATALOG.values())
