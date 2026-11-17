from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


def test_blender_normalizes_a_creator_glb(tmp_path):
    blender = shutil.which("blender")
    if not blender:
        pytest.skip("Blender is not installed in this test environment.")

    root = Path(__file__).resolve().parents[2]
    source = tmp_path / "creator-crate.glb"
    normalized = tmp_path / "normalized-crate.glb"
    report = tmp_path / "asset-report.json"

    generate = root / "blender" / "scripts" / "generate_scifi_crate.py"
    process = root / "blender" / "scripts" / "process_creator_asset.py"
    subprocess.run(
        [blender, "--background", "--python", str(generate), "--", "--output", str(source)],
        capture_output=True, text=True, timeout=240, check=True,
    )
    subprocess.run(
        [blender, "--background", "--python", str(process), "--",
         "--input", str(source), "--output", str(normalized), "--report", str(report)],
        capture_output=True, text=True, timeout=240, check=True,
    )

    result = json.loads(report.read_text(encoding="utf-8"))
    assert normalized.is_file() and normalized.stat().st_size > 1024
    assert result["status"] == "normalized"
    assert result["processor"] == "Blender"
    assert result["mesh_objects"] >= 1
    assert result["triangles"] > 0
    assert result["creator_review_required"] is True

    # Reuse the real normalized Blender output as a project-bound creator asset.
    # The resulting Godot script must load and instantiate the imported GLB.
    godot = shutil.which("godot") or shutil.which("godot4")
    if not godot:
        pytest.skip("Godot 4 is not installed; Blender normalization passed.")

    from core.game_assembler.godot import assemble_godot_project
    from core.game_assembler.workspace_adapter import build_documents

    asset_id = "22222222-2222-4222-8222-222222222222"
    creator_project = {
        "name": "Blender GLB Scene Binding",
        "description": "Real Blender-created GLB imported into generated Godot scene",
        "document": {
            "seed": 20261117,
            "scene": {
                "objects": [{
                    "id": "creator-crate",
                    "name": "Creator Cargo Crate",
                    "type": "MeshInstance3D",
                    "position": [2, 0, -2],
                    "rotation": [0, 0, 0],
                    "scale": [1, 1, 1],
                    "asset_id": asset_id,
                }]
            },
        },
    }
    definition, world = build_documents(
        "11111111-1111-4111-8111-111111111111",
        creator_project,
        {asset_id: f"res://assets/{asset_id}.glb"},
    )
    godot_project = tmp_path / "godot-project"
    asset_directory = godot_project / "assets"
    asset_directory.mkdir(parents=True, exist_ok=True)
    shutil.copy2(normalized, asset_directory / f"{asset_id}.glb")
    assemble_godot_project(definition, godot_project, world.model_dump(mode="json"))

    editor = subprocess.run(
        [godot, "--headless", "--path", str(godot_project), "--editor", "--quit"],
        capture_output=True, text=True, timeout=240,
    )
    editor_output = editor.stdout + "\\n" + editor.stderr
    assert editor.returncode == 0, editor_output
    assert "SCRIPT ERROR:" not in editor_output, editor_output
    runtime = subprocess.run(
        [godot, "--headless", "--path", str(godot_project), "--quit-after", "12"],
        capture_output=True, text=True, timeout=240,
    )
    runtime_output = runtime.stdout + "\\n" + runtime.stderr
    assert runtime.returncode == 0, runtime_output
    assert "SCRIPT ERROR:" not in runtime_output, runtime_output
