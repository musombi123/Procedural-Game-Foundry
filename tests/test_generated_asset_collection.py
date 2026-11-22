from core.asset_registry.registry import AssetRegistry
from core.nexora_workspace.api import _asset_rows


def test_generated_movie_pipeline_assets_are_in_shared_collection(tmp_path):
    project = tmp_path / "project"
    generated = project / "movie_pipeline" / "player" / "revision-1" / "player-avatar.glb"
    generated.parent.mkdir(parents=True)
    generated.write_bytes(b"glTF-generated-avatar")

    rows = _asset_rows(project)

    assert len(rows) == 1
    asset = rows[0]
    assert asset["origin"] == "movie-pipeline"
    assert asset["kind"] == "character"
    assert asset["filename"] == "player-avatar.glb"
    assert asset["metadata"]["relative_path"] == "movie_pipeline/player/revision-1/player-avatar.glb"
    assert asset["status"] == "ready"


def test_registered_and_generated_assets_share_one_collection(tmp_path):
    project = tmp_path / "project"
    asset_root = project / "assets"
    asset_root.mkdir(parents=True)
    uploaded = asset_root / "outpost.glb"
    uploaded.write_bytes(b"glTF-uploaded")
    AssetRegistry(asset_root).register(
        asset_id="outpost-1234",
        relative_path="outpost.glb",
        kind="environment",
        license_name="Creator-owned",
    )

    generated = project / "movie_pipeline" / "environment" / "environment.glb"
    generated.parent.mkdir(parents=True)
    generated.write_bytes(b"glTF-generated-world")

    rows = _asset_rows(project)

    assert {row["id"] for row in rows} == {"outpost-1234", rows[1]["id"] if rows[0]["id"] == "outpost-1234" else rows[0]["id"]}
    assert len(rows) == 2
    assert {row["origin"] for row in rows} == {"project-library", "movie-pipeline"}
