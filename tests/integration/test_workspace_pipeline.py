from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from core.game_assembler.workspace_pipeline import assemble_workspace_game, build_workspace_specs


def _project():
    return {
        "id": "workspace-pipeline-test",
        "name": "NEXORA Workspace Integration",
        "description": "A compact science-fiction outpost with a supply cache and a hostile patrol.",
        "document": {
            "seed": 20261117,
            "settings": {"world_scale": "small"},
            "scene": {
                "objects": [
                    {"id": "world-root", "name": "World", "type": "Node3D", "position": [0, 0, 0]},
                    {"id": "player-start", "name": "Player Start", "type": "Marker3D", "position": [0, 1, 12]},
                    {"id": "outpost", "name": "Outpost", "type": "StaticBody3D", "position": [0, 0, -12], "scale": [2, 2, 2]},
                    {"id": "supply-crate", "name": "Supply Crate", "type": "MeshInstance3D", "position": [4, 0, 3]},
                ]
            },
            "gameplay": {
                "enemies": [{"id": "patrol-guard", "name": "Patrol Guard", "behavior": "patrol"}],
                "mechanics": [{"id": "interact", "name": "Interact with mission props", "status": "proposed"}],
                "objectives": [
                    {"id": "reach-outpost", "name": "Reach the outpost", "kind": "reach", "target_id": "outpost", "status": "draft"}
                ],
            },
        },
    }


def test_workspace_specs_compile_safe_default_mission_and_creator_data():
    specs = build_workspace_specs(_project())
    gameplay = specs["gameplay_spec"]
    assert gameplay["missions"][0]["objectives"][0]["kind"] == "collect"
    assert gameplay["missions"][0]["objectives"][1]["kind"] == "defeat"
    assert any(item["actor_id"] == "patrol_guard" for item in gameplay["actor_behaviours"])
    assert any(item["id"] == "outpost" for item in specs["actors_spec"]["props"])
    assert any(item["kind"] == "reach" and item["target_id"] == "outpost" for item in gameplay["missions"][0]["objectives"])
    assert specs["objective_count"] == 3


def test_workspace_specs_assign_creator_avatar_and_imported_prop(tmp_path: Path):
    avatar = tmp_path / "creator-avatar.glb"
    prop = tmp_path / "creator-crate.glb"
    avatar.write_bytes(b"glTF-avatar")
    prop.write_bytes(b"glTF-prop")
    project = _project()
    project["document"]["scene"]["objects"].extend([
        {"id": "player-avatar", "name": "Player Avatar", "type": "MeshInstance3D", "asset_id": "avatar-asset", "position": [0, 0, 0]},
        {"id": "custom-crate", "name": "Custom Crate", "type": "MeshInstance3D", "asset_id": "prop-asset", "position": [5, 0, 5]},
    ])
    specs = build_workspace_specs(project, {"avatar-asset": avatar, "prop-asset": prop})
    assert specs["player_asset_id"] == "avatar-asset"
    imported = next(item for item in specs["actors_spec"]["props"] if item["id"] == "custom-crate")
    assert imported["asset_path"] == str(prop.resolve())


def test_workspace_build_runs_real_blender_godot_and_gameplay_checks(tmp_path: Path):
    blender = shutil.which("blender")
    godot = shutil.which("godot") or shutil.which("godot4")
    if not blender:
        pytest.skip("Blender is not installed")
    if not godot:
        pytest.skip("Godot 4 is not installed")

    game, manifest = assemble_workspace_game(
        _project(),
        {},
        tmp_path / "nexora-workspace-build",
        blender,
        godot,
    )
    assert manifest["validation"] == {
        "editor_import": "passed",
        "headless_runtime": "passed",
        "gameplay_e2e": "passed",
    }
    assert manifest["workspace_source"]["player_avatar"] == "procedural_default"
    assert manifest["workspace_source"]["enemy_count"] == 1
    assert (game / "project.godot").is_file()
    assert (game / "main.tscn").is_file()
    assert (game / "assets" / "player-avatar.glb").is_file()
    assert (game / "assets" / "environment.glb").is_file()
    assert (game / "assets" / "actors-props.glb").is_file()
    assert (game / "gameplay" / "gameplay.json").is_file()
    assert (game / "scripts" / "assembly_smoke.gd").is_file()
    assert 'package/unique_name="com.nexora.foundry"' in (game / "export_presets.cfg").read_text(encoding="utf-8")

    # Native export and Android emulator jobs consume this exact workspace game,
    # not a separate fixture build.
    export_project = os.environ.get("NEXORA_EXPORT_PROJECT_DIR")
    if export_project:
        destination = Path(export_project)
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(game, destination)
        assert (destination / "project.godot").is_file()
        assert (destination / "nexora-workspace-manifest.json").is_file()
