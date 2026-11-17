from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

from core.movie_pipeline.release import (
    TARGETS,
    _deterministic_zip,
    _validate_android_archive,
    export_presets_text,
    sha256_file,
    verify_export,
    write_export_presets,
)


def test_export_presets_define_linux_windows_and_android():
    config = export_presets_text()
    assert 'name="Linux/X11"' in config
    assert 'name="Windows Desktop"' in config
    assert 'name="Android"' in config
    assert 'keystore/release_password=""' not in config
    assert "GODOT_ANDROID_KEYSTORE_RELEASE_PASSWORD" not in config


def test_write_export_presets_requires_a_godot_project(tmp_path):
    with pytest.raises(FileNotFoundError):
        write_export_presets(tmp_path)
    (tmp_path / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    path = write_export_presets(tmp_path)
    assert path.is_file()
    assert 'name="Android"' in path.read_text(encoding="utf-8")


def test_verify_linux_export_checks_elf_header_and_marks_executable(tmp_path):
    path = tmp_path / "game.x86_64"
    path.write_bytes(b"\x7fELF" + b"\0" * 2048)
    info = verify_export(TARGETS["linux"], path)
    assert info["format"] == "ELF"
    assert info["executable"] is True
    assert path.stat().st_mode & 0o111


def test_verify_windows_export_checks_pe_header(tmp_path):
    path = tmp_path / "game.exe"
    path.write_bytes(b"MZ" + b"\0" * 2048)
    info = verify_export(TARGETS["windows"], path)
    assert info["format"] == "PE/COFF"


def test_android_export_must_have_manifest_and_native_libraries(tmp_path):
    path = tmp_path / "game.apk"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("AndroidManifest.xml", b"binary-manifest")
        archive.writestr("lib/arm64-v8a/libgodot.so", b"native-library")
    assert _validate_android_archive(path)["native_libraries"] == ["lib/arm64-v8a/libgodot.so"]


def test_android_export_rejects_missing_native_libraries(tmp_path):
    path = tmp_path / "game.apk"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("AndroidManifest.xml", b"manifest")
    with pytest.raises(ValueError, match="native game libraries"):
        _validate_android_archive(path)


def test_deterministic_release_zip_is_byte_stable(tmp_path):
    artifact = tmp_path / "game"
    artifact.write_bytes(b"game-binary")
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    _deterministic_zip(first, [(artifact, "game")])
    _deterministic_zip(second, [(artifact, "game")])
    assert sha256_file(first) == sha256_file(second)
    with zipfile.ZipFile(first) as archive:
        assert archive.namelist() == ["game"]


def test_sha256_matches_standard_digest(tmp_path):
    path = tmp_path / "file.bin"
    path.write_bytes(b"nexora")
    assert sha256_file(path) == hashlib.sha256(b"nexora").hexdigest()
