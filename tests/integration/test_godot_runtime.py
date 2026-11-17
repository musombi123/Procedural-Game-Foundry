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


def _write_minimal_glb(path, node_names):
    import json
    import struct

    path.parent.mkdir(parents=True, exist_ok=True)
    nodes = [{"name": name} for name in node_names]
    document = {
        "asset": {"version": "2.0", "generator": "PGF integration fixture"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "FixtureRoot", "children": list(range(1, len(nodes) + 1))}] + nodes,
    }
    payload = json.dumps(document, separators=(",", ":")).encode("utf-8")
    payload += b" " * ((4 - len(payload) % 4) % 4)
    total = 12 + 8 + len(payload)
    path.write_bytes(struct.pack("<III", 0x46546C67, 2, total) +
                     struct.pack("<II", len(payload), 0x4E4F534A) + payload)


def test_movie_pipeline_assembles_and_runs_gameplay_end_to_end(tmp_path):
    """Import real GLB/WAV resources and execute a playable mission in Godot."""
    import json
    import wave
    from types import SimpleNamespace
    from core.movie_pipeline.assembly import assemble_movie_game
    from core.movie_pipeline.models import StageId, StageState
    from core.gameplay_compiler.compiler import compile_gameplay

    godot = shutil.which("godot") or shutil.which("godot4")
    if not godot:
        pytest.skip("Godot 4 editor binary is not installed")

    project = tmp_path / "assembly-project"
    root = project / "movie_pipeline"
    _write_minimal_glb(root / "player/revision-0/player-avatar.glb", ["AvatarRig"])
    _write_minimal_glb(root / "environment/environment.glb", ["Terrain"])
    (root / "environment/world-spec.json").write_text(json.dumps({"dimensions":[48,48,48],"terrain":{"segments":8,"amplitude":1,"frequency":0.03},"landmarks":[],"props":[]}))
    _write_minimal_glb(root / "actors-props/revision-0/actors-props.glb", ["guard-1_rig", "key-1"])
    actors_manifest = {"actors":[{"id":"guard-1","rig":"guard-1_rig"}],"props":[{"id":"key-1"}]}
    actors_spec = {"actors":[{"id":"guard-1","position":[2,0,0],"scale":1}],
                   "props":[{"id":"key-1","position":[1,0,0],"scale":1}]}
    (root / "actors-props/revision-0/actors-props.manifest.json").write_text(json.dumps(actors_manifest))
    (root / "actors-props/revision-0/actors-props.json").write_text(json.dumps(actors_spec))
    audio_dir = root / "audio/revision-0"
    audio_dir.mkdir(parents=True)
    with wave.open(str(audio_dir / "pickup.wav"), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(22050)
        wav.writeframes(b"\x00\x00" * 256)
    audio_manifest = {"effects":[{"id":"pickup-sfx","file":"pickup.wav"}],"music":None}
    (audio_dir / "audio-manifest.json").write_text(json.dumps(audio_manifest))
    spec = {
        "player":{"move_speed":5,"jump_velocity":4.5,"gravity":9.8,"health":100,"inventory_capacity":10},
        "missions":[{"id":"mission-1","title":"Find the key","description":"Collect the key","objectives":[
            {"id":"collect-key","title":"Collect key","description":"Pick up the key","kind":"collect","target_id":"key-1","required_count":1},
            {"id":"defeat-guard","title":"Defeat guard","description":"Defeat the guard","kind":"defeat","target_id":"guard-1","required_count":1}]}],
        "actor_behaviours":[{"actor_id":"guard-1","behaviour":"patrol","move_speed":2.5,"detection_range":10,"attack_range":1.8,"damage":10}],
        "interactions":[{"prop_id":"key-1","action":"collect","objective_id":"collect-key","item_id":"key"}],
        "audio_bindings":[{"event":"objective_complete","cue_id":"pickup-sfx"}],
        "win_condition":"all_objectives_complete","lose_condition":"health_depleted",
    }
    gameplay_dir = root / "gameplay/revision-0"
    compile_gameplay(gameplay_dir, spec, audio_manifest)
    stages = [SimpleNamespace(stage=stage, state=StageState.APPROVED, revision=0) for stage in StageId]
    pipeline = SimpleNamespace(stages=stages)
    manifest = assemble_movie_game(project, pipeline, godot)
    assert manifest["validation"] == {
        "editor_import":"passed", "headless_runtime":"passed", "gameplay_e2e":"passed"
    }
    assert (project / "game/project.godot").is_file()
    assert (project / "game/assets/player-avatar.glb").is_file()
    assert (project / "game/assets/audio/pickup.wav").is_file()
