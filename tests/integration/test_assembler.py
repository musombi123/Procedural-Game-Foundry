import json

from core.project_engine.models import ProjectCreate, ProjectDefinition, WorldDocument
from core.game_assembler.godot import assemble_godot_project
from core.validation.validator import validate_project

def test_assembly(tmp_path):
    definition = ProjectDefinition(id="test-world", project=ProjectCreate(name="Test World", seed=10))
    folder = tmp_path / "test-world"
    folder.mkdir()
    (folder / "pgf.json").write_text(definition.model_dump_json())
    assemble_godot_project(definition, folder / "game")
    assert validate_project(folder)["valid"]

def test_assembly_includes_saved_scene_objects(tmp_path):
    definition = ProjectDefinition(id="scene-world", project=ProjectCreate(name="Scene World", seed=10))
    folder = tmp_path / "scene-world"
    folder.mkdir()
    state = WorldDocument.model_validate({
        "seed": 91,
        "world": {"width": 112, "depth": 96, "resolution": 32, "amplitude": 12, "frequency": 0.06},
        "objects": [{
            "id": "beacon-1", "name": "North Beacon", "kind": "beacon",
            "x": 8, "y": 0, "z": -5, "rotation": 35, "scale": 1.2, "color": "#5b8da8"
        }],
        "sun_angle": 24, "fog": True, "water_level": -2
    })
    assemble_godot_project(definition, folder / "game", state.model_dump(mode="json"))
    terrain = json.loads((folder / "game" / "pgf_world.json").read_text())
    scene = json.loads((folder / "game" / "pgf_scene.json").read_text())
    assert terrain["seed"] == 91
    assert terrain["width"] == 112
    assert scene["objects"][0]["name"] == "North Beacon"
    assert scene["objects"][0]["y"] != 0
    player = (folder / "game" / "scripts" / "player.gd").read_text()
    assert "CapsuleShape3D.new()" in player
    assert "move_and_slide()" in player
    assert "ui_accept" in player
