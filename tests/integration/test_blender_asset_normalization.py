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
