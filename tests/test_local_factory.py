from __future__ import annotations

from io import BytesIO
from pathlib import Path
import zipfile

import pytest
from fastapi import HTTPException

from services.worker.local_factory import _safe_extract, _safe_members, _zip_folder


def archive_bytes(entries: dict[str, bytes]) -> bytes:
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, body in entries.items():
            archive.writestr(name, body)
    return stream.getvalue()


def test_safe_members_accepts_normal_project_paths(tmp_path: Path) -> None:
    payload = archive_bytes({"game/project.godot": b'config/name="Orbit"', "game/scripts/main.gd": b"extends Node"})
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        members = _safe_members(archive)
        assert len(members) == 2
        _safe_extract(archive, tmp_path)
    assert (tmp_path / "game" / "project.godot").read_bytes() == b'config/name="Orbit"'


@pytest.mark.parametrize("name", ["../escape.txt", "/rooted.txt", "C:/outside.txt", "game/../../outside.txt"])
def test_safe_members_rejects_path_traversal(name: str) -> None:
    payload = archive_bytes({name: b"not allowed"})
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        with pytest.raises(HTTPException) as error:
            _safe_members(archive)
    assert error.value.status_code == 400


def test_project_archive_skips_caches_git_and_snapshot_recursion(tmp_path: Path) -> None:
    source = tmp_path / "project"
    (source / "source" / "scripts").mkdir(parents=True)
    (source / ".git").mkdir()
    (source / ".godot").mkdir()
    (source / ".nexora" / "snapshots").mkdir(parents=True)
    (source / "source" / "project.godot").write_text('config/name="Orbit"', encoding="utf-8")
    (source / "source" / "scripts" / "main.gd").write_text("extends Node", encoding="utf-8")
    (source / ".git" / "secret").write_text("cache", encoding="utf-8")
    (source / ".godot" / "cache").write_text("cache", encoding="utf-8")
    (source / ".nexora" / "snapshots" / "old.zip").write_bytes(b"old snapshot")

    output = tmp_path / "export.zip"
    file_count, source_bytes, digest = _zip_folder(source, output, exclude_snapshots=True)
    assert file_count == 2
    assert source_bytes > 0
    assert len(digest) == 64
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
    assert "source/project.godot" in names
    assert "source/scripts/main.gd" in names
    assert not any(".git/" in item or ".godot/" in item or "snapshots/" in item for item in names)


def test_safe_members_rejects_symbolic_link_entries() -> None:
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        info = zipfile.ZipInfo("project/link")
        info.create_system = 3
        info.external_attr = (0o120777 << 16)
        archive.writestr(info, "target")
    with zipfile.ZipFile(BytesIO(stream.getvalue())) as archive:
        with pytest.raises(HTTPException) as error:
            _safe_members(archive)
    assert error.value.status_code == 400

def test_safe_members_rejects_duplicate_paths_case_insensitively() -> None:
    payload = archive_bytes({"Assets/Player.glb": b"first", "assets/player.glb": b"second"})
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        with pytest.raises(HTTPException) as error:
            _safe_members(archive)
    assert error.value.status_code == 400
