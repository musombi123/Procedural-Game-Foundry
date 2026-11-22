from pathlib import Path

from core.asset_registry.registry import AssetRegistry
from core.nexora_workspace.api import _asset_rows


def test_asset_rows_includes_registered_and_generated_pipeline_files(tmp_path: Path) -> None:
    project = tmp_path / "project"
    asset_root = project / "assets"
    asset_root.mkdir(parents=True)

    uploaded = asset_root / "creator-character.glb"
    uploaded.write_bytes(b"registered glb")
    AssetRegistry(asset_root).register(
        "creator-character",
        uploaded.name,
        "character",
        "Creator confirms usage rights",
        source="creator-upload",
        metadata={"format": "glb", "validation": {"valid": True}},
    )

    generated = project / "movie_pipeline" / "player" / "hero.glb"
    generated.parent.mkdir(parents=True)
    generated.write_bytes(b"generated glb")

    rows = _asset_rows(project)
    by_id = {row["id"]: row for row in rows}

    assert "creator-character" in by_id
    assert by_id["creator-character"]["origin"] == "project-library"
    assert by_id["creator-character"]["kind"] == "character"

    generated_rows = [row for row in rows if row["origin"] == "movie-pipeline"]
    assert len(generated_rows) == 1
    row = generated_rows[0]
    assert row["filename"] == "hero.glb"
    assert row["kind"] == "character"
    assert row["metadata"]["relative_path"] == "movie_pipeline/player/hero.glb"
    assert row["status"] == "ready"


def test_asset_rows_ignores_empty_and_unsupported_pipeline_files(tmp_path: Path) -> None:
    project = tmp_path / "project"
    unsupported = project / "movie_pipeline" / "player" / "notes.txt"
    empty = project / "movie_pipeline" / "environment" / "empty.glb"
    unsupported.parent.mkdir(parents=True)
    empty.parent.mkdir(parents=True)
    unsupported.write_text("not an asset", encoding="utf-8")
    empty.write_bytes(b"")

    rows = _asset_rows(project)
    assert len(rows) == 1
    assert rows[0]["filename"] == "empty.glb"
    assert rows[0]["status"] == "failed"
