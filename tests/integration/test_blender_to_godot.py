"""Real Blender-to-Godot integration coverage for Nexora Foundry.

The image created below is a synthetic, non-identifying image-processing fixture.
It validates Blender's portrait-texture path; it is not a real creator portrait
or evidence of likeness quality. Real creator testing remains consent-gated.
"""
from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import zlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.audio_foundry.synth import generate_audio
from core.gameplay_compiler.compiler import compile_gameplay
from core.movie_pipeline.assembly import assemble_movie_game
from core.movie_pipeline.models import StageId, StageState
from core.movie_pipeline.procedural_world import build_world_spec


ROOT = Path(__file__).resolve().parents[2]


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def _write_synthetic_portrait_fixture(path: Path) -> None:
    """Create a generic color/shape test pattern; it depicts no real person."""
    width, height = 320, 640
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # PNG filter: None
        for x in range(width):
            if 70 <= x < 250 and 35 <= y < 155:
                # Neutral face-texture test patch.
                shade = 168 + ((x + y) % 24)
                pixel = (shade, 126 + ((x * 3) % 18), 102 + ((y * 2) % 16), 255)
            elif 38 <= x < 282 and 190 <= y < 470:
                # Clothing-palette test region.
                pixel = (34 + (y % 25), 82 + (x % 30), 132 + (y % 34), 255)
            elif 105 <= x < 215 and 475 <= y < 625:
                # Lower-body test region.
                pixel = (42, 48, 58, 255)
            else:
                pixel = (42, 48, 58, 255)
            raw.extend(pixel)
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(bytes(raw), level=6))
        + _png_chunk(b"IEND", b"")
    )


def _run_blender(executable: str, script_name: str, *arguments: str) -> str:
    script = ROOT / "blender" / "scripts" / script_name
    environment = os.environ.copy()
    # Ubuntu's Blender package uses bundled Python 3.12. Expose the matching
    # system package directory so its glTF exporter can import python3-numpy.
    blender_system_packages = Path("/usr/lib/python3/dist-packages")
    if blender_system_packages.is_dir():
        existing_pythonpath = environment.get("PYTHONPATH", "")
        environment["PYTHONPATH"] = (
            str(blender_system_packages)
            + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
        )
    result = subprocess.run(
        [
            executable,
            "--background",
            "--factory-startup",
            "--python",
            str(script),
            "--",
            *arguments,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=900,
        env=environment,
    )
    output = (result.stdout or "") + "\\n" + (result.stderr or "")
    # Blender may exit 0 even after a Python operator traceback; reject that.
    if result.returncode != 0 or "Traceback (most recent call last)" in output or "Error: Python:" in output:
        raise AssertionError(
            f"{script_name} failed (exit={result.returncode}):\\n{output[-12000:]}"
        )
    return output

def _read_glb_json(path: Path) -> dict:
    data = path.read_bytes()
    assert len(data) >= 20, f"{path.name} is too small to be a GLB"
    magic, version, declared_length = struct.unpack_from("<III", data, 0)
    assert magic == 0x46546C67, f"{path.name} has an invalid GLB magic header"
    assert version == 2, f"{path.name} is not GLB 2.0"
    assert declared_length == len(data), f"{path.name} has an invalid GLB length"
    json_length, chunk_type = struct.unpack_from("<II", data, 12)
    assert chunk_type == 0x4E4F534A, f"{path.name} has no leading JSON chunk"
    return json.loads(data[20 : 20 + json_length].decode("utf-8").rstrip(" \t\r\n\0"))


def test_real_blender_assets_import_and_run_in_godot(tmp_path: Path) -> None:
    blender = shutil.which("blender")
    godot = shutil.which("godot") or shutil.which("godot4")
    if not blender:
        pytest.skip("Blender is not installed")
    if not godot:
        pytest.skip("Godot 4 is not installed")

    pipeline_root = tmp_path / "creator-project" / "movie_pipeline"
    avatar_dir = pipeline_root / "player" / "revision-0"
    environment_dir = pipeline_root / "environment"
    actors_dir = pipeline_root / "actors-props" / "revision-0"
    audio_dir = pipeline_root / "audio" / "revision-0"
    gameplay_dir = pipeline_root / "gameplay" / "revision-0"
    for folder in (avatar_dir, environment_dir, actors_dir, audio_dir, gameplay_dir):
        folder.mkdir(parents=True, exist_ok=True)

    # CI-only synthetic image. It proves the local Blender input path works,
    # but never substitutes for the founder/player's actual consented portrait.
    portrait = tmp_path / "synthetic-portrait-test-fixture.png"
    _write_synthetic_portrait_fixture(portrait)

    avatar_spec = {
        "proportions": {
            "height": 1.78,
            "shoulder_width": 0.46,
            "hip_width": 0.34,
            "leg_ratio": 0.52,
            "build": 1.0,
        },
        "face_crop": {
            "center_x": 0.5,
            "top": 0.035,
            "width": 0.56,
            "height": 0.19,
        },
        "identity_source": "synthetic_ci_fixture",
        "creator_review_required": True,
    }
    avatar_spec_path = avatar_dir / "avatar.json"
    avatar_spec_path.write_text(json.dumps(avatar_spec, indent=2), encoding="utf-8")
    avatar_glb = avatar_dir / "player-avatar.glb"
    _run_blender(
        blender,
        "build_player_avatar.py",
        "--portrait",
        str(portrait),
        "--output",
        str(avatar_glb),
        "--spec",
        str(avatar_spec_path),
    )

    world_spec = build_world_spec(
        {
            "title": "Blender-to-Godot Integration Fixture",
            "setting": "abandoned science outpost",
            "world_scale": "small",
        },
        seed=20261117,
    )
    world_spec_path = environment_dir / "world-spec.json"
    world_spec_path.write_text(json.dumps(world_spec, indent=2), encoding="utf-8")
    environment_glb = environment_dir / "environment.glb"
    _run_blender(
        blender,
        "build_movie_world.py",
        "--spec",
        str(world_spec_path),
        "--output",
        str(environment_glb),
    )

    actors_spec = {
        "actors": [
            {
                "id": "guard-1",
                "name": "Integration Guard",
                "kind": "enemy",
                "behavior": "patrol",
                "scale": 1.0,
                "position": [2.0, 0.0, 0.0],
            }
        ],
        "props": [
            {
                "id": "key-1",
                "name": "Integration Supply Key",
                "kind": "item",
                "interaction": "collect",
                "scale": 1.0,
                "position": [1.0, 0.0, 0.0],
            }
        ],
    }
    actors_spec_path = actors_dir / "actors-props.json"
    actors_spec_path.write_text(json.dumps(actors_spec, indent=2), encoding="utf-8")
    actors_glb = actors_dir / "actors-props.glb"
    actors_output = _run_blender(
        blender,
        "build_actors_props.py",
        "--spec",
        str(actors_spec_path),
        "--output",
        str(actors_glb),
    )
    assert actors_glb.is_file(), (
        "Blender did not emit the actors/props GLB. Generator output:\\n"
        + actors_output[-12000:]
    )
    actors_manifest_path = actors_glb.with_suffix(".manifest.json")
    assert actors_manifest_path.is_file(), (
        "Blender did not emit the actor/prop manifest. Generator output:\\n"
        + actors_output[-12000:]
        + "\\nDirectory files: "
        + repr(sorted(item.name for item in actors_dir.iterdir()))
    )

    audio_manifest = generate_audio(
        audio_dir,
        [
            {
                "id": "pickup-sfx",
                "label": "Supply collected",
                "kind": "tone",
                "frequency": 660,
                "duration": 0.22,
                "seed": 17,
                "trigger": "objective_complete",
            }
        ],
        None,
    )

    gameplay_spec = {
        "player": {
            "move_speed": 5,
            "jump_velocity": 4.5,
            "gravity": 9.8,
            "health": 100,
            "inventory_capacity": 10,
        },
        "missions": [
            {
                "id": "mission-1",
                "title": "Secure the outpost",
                "description": "Collect the key and defeat the guard.",
                "objectives": [
                    {
                        "id": "collect-key",
                        "title": "Collect the key",
                        "description": "Pick up the supply key.",
                        "kind": "collect",
                        "target_id": "key-1",
                        "required_count": 1,
                    },
                    {
                        "id": "defeat-guard",
                        "title": "Defeat the guard",
                        "description": "Defeat the outpost guard.",
                        "kind": "defeat",
                        "target_id": "guard-1",
                        "required_count": 1,
                    },
                ],
            }
        ],
        "actor_behaviours": [
            {
                "actor_id": "guard-1",
                "behaviour": "patrol",
                "move_speed": 2.5,
                "detection_range": 10,
                "attack_range": 1.8,
                "damage": 10,
            }
        ],
        "interactions": [
            {
                "prop_id": "key-1",
                "action": "collect",
                "objective_id": "collect-key",
                "item_id": "supply-key",
            }
        ],
        "audio_bindings": [
            {"event": "objective_complete", "cue_id": "pickup-sfx"}
        ],
        "win_condition": "all_objectives_complete",
        "lose_condition": "health_depleted",
    }
    compile_gameplay(gameplay_dir, gameplay_spec, audio_manifest)

    # Validate that Blender produced actual geometry, a skinned avatar and an
    # actor armature rather than only empty fixture scene nodes.
    avatar_doc = _read_glb_json(avatar_glb)
    environment_doc = _read_glb_json(environment_glb)
    actors_doc = _read_glb_json(actors_glb)
    assert avatar_doc.get("meshes"), "Avatar GLB contains no mesh geometry"
    assert avatar_doc.get("skins"), "Avatar GLB contains no skin/armature"
    assert avatar_doc.get("images"), "Avatar GLB does not contain its face texture"
    assert environment_doc.get("meshes"), "Environment GLB contains no mesh geometry"
    assert actors_doc.get("meshes"), "Actors/props GLB contains no mesh geometry"
    assert actors_doc.get("skins"), "Actor GLB contains no skin/armature"

    stages = [
        SimpleNamespace(stage=stage, state=StageState.APPROVED, revision=0)
        for stage in StageId
    ]
    manifest = assemble_movie_game(
        tmp_path / "creator-project",
        SimpleNamespace(stages=stages),
        godot,
    )
    assert manifest["validation"] == {
        "editor_import": "passed",
        "headless_runtime": "passed",
        "gameplay_e2e": "passed",
    }
    assert (tmp_path / "creator-project" / "game" / "assets" / "player-avatar.glb").is_file()
    assert (tmp_path / "creator-project" / "game" / "assets" / "environment.glb").is_file()
    assert (tmp_path / "creator-project" / "game" / "assets" / "actors-props.glb").is_file()
    assert (tmp_path / "creator-project" / "game" / "assets" / "audio" / "pickup-sfx.wav").is_file()

    # Optional CI hand-off: export the exact assembled game tested above.
    export_fixture_dir = os.environ.get("NEXORA_EXPORT_FIXTURE_DIR")
    if export_fixture_dir:
        destination = Path(export_fixture_dir)
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(tmp_path / "creator-project" / "game", destination)
