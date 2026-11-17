"""Headless Godot 4 smoke test for an assembled playable world."""
import shutil
import subprocess

import pytest

from core.game_assembler.godot import assemble_godot_project
from core.project_engine.models import ProjectCreate, ProjectDefinition, WorldDocument


def test_generated_godot_world_parses_and_runs(tmp_path):
    godot = shutil.which("godot") or shutil.which("godot4")
    if not godot:
        pytest.skip("Godot 4 editor binary is not installed")

    definition = ProjectDefinition(
        id="godot-smoke",
        project=ProjectCreate(name="Godot Runtime Smoke", seed=20261116),
    )
    world = WorldDocument.model_validate({
        "seed": 20261116,
        "world": {
            "width": 64, "depth": 64, "resolution": 24,
            "amplitude": 8, "frequency": 0.055,
        },
        "objects": [
            {"id": "outpost-1", "name": "Smoke Outpost", "kind": "outpost", "x": -8, "z": 0},
            {"id": "beacon-1", "name": "Smoke Beacon", "kind": "beacon", "x": 8, "z": -8},
            {"id": "tree-1", "name": "Smoke Tree", "kind": "tree", "x": 12, "z": 10},
            {"id": "rock-1", "name": "Smoke Rock", "kind": "rock", "x": -12, "z": -10},
            {"id": "crate-1", "name": "Smoke Crate", "kind": "crate", "x": 0, "z": -12},
        ],
    })
    project = tmp_path / "game"
    assemble_godot_project(definition, project, world.model_dump(mode="json"))

    editor = subprocess.run(
        [godot, "--headless", "--path", str(project), "--editor", "--quit"],
        capture_output=True, text=True, timeout=180,
    )
    editor_output = editor.stdout + "\n" + editor.stderr
    assert editor.returncode == 0, editor_output
    assert "SCRIPT ERROR:" not in editor_output, editor_output
    assert "Parse Error" not in editor_output, editor_output

    runtime = subprocess.run(
        [godot, "--headless", "--path", str(project), "--quit-after", "12"],
        capture_output=True, text=True, timeout=180,
    )
    runtime_output = runtime.stdout + "\n" + runtime.stderr
    assert runtime.returncode == 0, runtime_output
    assert "SCRIPT ERROR:" not in runtime_output, runtime_output
    assert "Parse Error" not in runtime_output, runtime_output


def test_compiled_gameplay_scripts_parse_in_godot(tmp_path):
    """Compile every emitted runtime script with the real Godot parser."""
    import json
    from core.gameplay_compiler.compiler import RUNTIME_FILES

    godot = shutil.which("godot") or shutil.which("godot4")
    if not godot:
        pytest.skip("Godot 4 editor binary is not installed")

    project = tmp_path / "gameplay-runtime"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    (project / "project.godot").write_text(
        '[application]\nconfig/name="PGF Gameplay Runtime Test"\nconfig/features=PackedStringArray("4.6")\n',
        encoding="utf-8",
    )
    for name, source in RUNTIME_FILES.items():
        (scripts / name).write_text(source, encoding="utf-8")

    parsed = subprocess.run(
        [godot, "--headless", "--path", str(project), "--editor", "--quit"],
        capture_output=True, text=True, timeout=180,
    )
    output = parsed.stdout + "\n" + parsed.stderr
    assert parsed.returncode == 0, output
    assert "SCRIPT ERROR:" not in output, output
    assert "Parse Error" not in output, output
