"""Build a creator workspace project through the real Blender -> Godot gameplay pipeline.

Workspace scene data is translated into the same bounded manifests used by the
staged movie pipeline. Creator files remain local to the worker while the build
runs; only final artifacts are uploaded to the private object store.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from core.audio_foundry.synth import generate_audio
from core.gameplay_compiler.compiler import compile_gameplay
from core.movie_pipeline.assembly import assemble_movie_game
from core.movie_pipeline.models import StageId, StageState
from core.movie_pipeline.procedural_world import build_world_spec


ROOT = Path(__file__).resolve().parents[2]
ALLOWED_BEHAVIOURS = {"idle", "patrol", "guard", "chase", "attack"}
ALLOWED_OBJECTIVES = {"collect", "defeat", "reach", "survive"}


def _safe_id(value: Any, fallback: str) -> str:
    candidate = re.sub(r"[^A-Za-z0-9_-]", "_", str(value or fallback))[:48]
    return candidate or fallback


def _vector(value: Any, fallback: tuple[float, float, float]) -> list[float]:
    if not isinstance(value, (list, tuple)):
        return list(fallback)
    result = []
    for index in range(3):
        try:
            number = float(value[index])
            if not (-1e6 < number < 1e6):
                raise ValueError
            result.append(max(-512.0, min(512.0, number)))
        except (IndexError, TypeError, ValueError):
            result.append(float(fallback[index]))
    return result


def _scale(value: Any) -> float:
    if isinstance(value, (list, tuple)) and value:
        values = value[:3]
    else:
        values = [value if value is not None else 1.0]
    parsed = []
    for item in values:
        try:
            parsed.append(abs(float(item)))
        except (TypeError, ValueError):
            parsed.append(1.0)
    return max(0.25, min(4.0, sum(parsed) / max(1, len(parsed))))


def build_workspace_specs(
    project: dict[str, Any],
    asset_files: dict[str, Path] | None = None,
) -> dict[str, Any]:
    """Translate the browser workspace document into safe runtime manifests."""
    asset_files = asset_files or {}
    document = project.get("document") if isinstance(project.get("document"), dict) else {}
    scene = document.get("scene") if isinstance(document.get("scene"), dict) else {}
    settings = document.get("settings") if isinstance(document.get("settings"), dict) else {}
    gameplay = document.get("gameplay") if isinstance(document.get("gameplay"), dict) else {}
    raw_objects = scene.get("objects") if isinstance(scene.get("objects"), list) else []
    raw_enemies = gameplay.get("enemies") if isinstance(gameplay.get("enemies"), list) else []
    raw_objectives = gameplay.get("objectives") if isinstance(gameplay.get("objectives"), list) else []

    name = str(project.get("name") or document.get("name") or "NEXORA Game")[:80]
    description = str(project.get("description") or document.get("description") or "A creator-authored science-fiction exploration game.")[:2000]
    try:
        seed = max(0, min(4294967295, int(document.get("seed", 784215))))
    except (TypeError, ValueError):
        seed = 784215

    world_scale = str(settings.get("world_scale", "small")).lower()
    if world_scale not in {"small", "medium", "large"}:
        world_scale = "small"
    world_spec = build_world_spec(
        {"title": name, "setting": description, "world_scale": world_scale},
        seed=seed,
    )
    world_spec["source_product"] = "NEXORA Foundry workspace"

    # A creator may explicitly assign a GLB to a scene node named Player,
    # Avatar or Character. Otherwise the build uses a neutral procedural avatar.
    player_asset_id = ""
    for raw in raw_objects:
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("name", "")).casefold()
        asset_id = str(raw.get("asset_id") or "")
        if asset_id in asset_files and any(word in label for word in ("player", "avatar", "character")):
            player_asset_id = asset_id
            break
    if not player_asset_id:
        for asset_id, file_path in asset_files.items():
            if any(word in file_path.name.casefold() for word in ("player", "avatar", "character")):
                player_asset_id = asset_id
                break

    actors: list[dict[str, Any]] = []
    actor_behaviours: list[dict[str, Any]] = []
    enemy_ids: list[str] = []
    for index, raw in enumerate(raw_enemies[:64]):
        if not isinstance(raw, dict):
            continue
        actor_id = _safe_id(raw.get("id"), f"enemy_{index + 1}")
        if actor_id in enemy_ids:
            actor_id = f"{actor_id}_{index + 1}"
        behaviour = str(raw.get("behavior") or raw.get("behaviour") or "patrol").lower()
        if behaviour not in ALLOWED_BEHAVIOURS:
            behaviour = "patrol"
        position = _vector(raw.get("position"), (6.0 + index * 4.0, 0.0, -6.0))
        actors.append({
            "id": actor_id,
            "name": str(raw.get("name") or f"Enemy {index + 1}")[:80],
            "kind": "enemy",
            "behavior": behaviour,
            "scale": _scale(raw.get("scale", 1.0)),
            "position": position,
        })
        actor_behaviours.append({
            "actor_id": actor_id,
            "behaviour": behaviour,
            "move_speed": 2.5,
            "detection_range": 12.0,
            "attack_range": 1.8,
            "damage": 8,
        })
        enemy_ids.append(actor_id)

    props: list[dict[str, Any]] = []
    prop_ids: set[str] = set()
    used_asset_ids: set[str] = set()
    for index, raw in enumerate(raw_objects):
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("name") or f"Scene prop {index + 1}")
        lowered = f"{label} {raw.get('type', '')}".casefold()
        if any(word in lowered for word in ("world root", "player start", "directional light", "camera")):
            continue
        object_id = _safe_id(raw.get("id"), f"scene_prop_{index + 1}")
        if object_id in prop_ids:
            object_id = f"{object_id}_{index + 1}"
        asset_id = str(raw.get("asset_id") or "")
        if asset_id == player_asset_id:
            continue
        asset_path = asset_files.get(asset_id)
        if asset_path and asset_path.is_file():
            used_asset_ids.add(asset_id)
        kind = "weapon" if "weapon" in lowered else "vehicle" if "vehicle" in lowered else "tool" if "tool" in lowered else "item"
        interaction = "collect" if any(word in lowered for word in ("key", "item", "pickup", "supply")) else "activate"
        props.append({
            "id": object_id,
            "name": label[:80],
            "kind": kind,
            "interaction": interaction,
            "scale": _scale(raw.get("scale", 1.0)),
            "position": _vector(raw.get("position"), (float(index % 5) * 3.0, 0.0, -8.0 - float(index // 5) * 3.0)),
            **({"asset_path": str(asset_path.resolve())} if asset_path and asset_path.is_file() else {}),
        })
        prop_ids.add(object_id)

    # Preserve GLB uploads that have not yet been assigned to a scene node.
    for index, (asset_id, file_path) in enumerate(asset_files.items()):
        if asset_id == player_asset_id or asset_id in used_asset_ids or not file_path.is_file():
            continue
        object_id = _safe_id(f"creator_asset_{asset_id}", f"creator_asset_{index + 1}")
        if object_id in prop_ids:
            continue
        props.append({
            "id": object_id,
            "name": file_path.name[:80],
            "kind": "item",
            "interaction": "activate",
            "scale": 1.0,
            "position": [float(index % 4) * 4.0 - 6.0, 0.0, -10.0 - float(index // 4) * 4.0],
            "asset_path": str(file_path.resolve()),
        })
        prop_ids.add(object_id)

    mission_objectives: list[dict[str, Any]] = []
    interactions: list[dict[str, Any]] = []
    if not raw_objectives:
        if enemy_ids:
            for index, enemy_id in enumerate(enemy_ids):
                mission_objectives.append({
                    "id": f"defeat_{index + 1}",
                    "title": f"Defeat {actors[index]['name']}",
                    "description": "Defeat the hostile actor.",
                    "kind": "defeat",
                    "target_id": enemy_id,
                    "required_count": 1,
                })
        else:
            props.append({
                "id": "nexora_exit",
                "name": "Mission Exit",
                "kind": "item",
                "interaction": "activate",
                "scale": 1.0,
                "position": [0.0, 0.0, -18.0],
            })
            prop_ids.add("nexora_exit")
            mission_objectives.append({
                "id": "reach_exit",
                "title": "Reach the mission exit",
                "description": "Travel through the world and reach the marked exit.",
                "kind": "reach",
                "target_id": "nexora_exit",
                "required_count": 1,
            })
    else:
        for index, raw in enumerate(raw_objectives[:64]):
            if not isinstance(raw, dict):
                continue
            objective_id = _safe_id(raw.get("id"), f"objective_{index + 1}")
            kind = str(raw.get("kind") or "reach").lower()
            if kind not in ALLOWED_OBJECTIVES:
                kind = "reach"
            target_id = _safe_id(raw.get("target_id"), "")
            if kind == "defeat":
                if target_id not in enemy_ids:
                    target_id = enemy_ids[0] if enemy_ids else ""
                if not target_id:
                    kind = "reach"
            if kind in {"collect", "reach"} and (not target_id or target_id not in prop_ids):
                target_id = f"objective_target_{objective_id}"
                position = [float((index % 4) * 5 - 7), 0.0, -14.0 - float(index // 4) * 5.0]
                props.append({
                    "id": target_id,
                    "name": str(raw.get("name") or f"Objective {index + 1}")[:80],
                    "kind": "item",
                    "interaction": "collect" if kind == "collect" else "activate",
                    "scale": 1.0,
                    "position": position,
                })
                prop_ids.add(target_id)
            required = raw.get("required_count", 10 if kind == "survive" else 1)
            try:
                required = max(1, min(3600 if kind == "survive" else 100, int(required)))
            except (TypeError, ValueError):
                required = 10 if kind == "survive" else 1
            mission_objectives.append({
                "id": objective_id,
                "title": str(raw.get("name") or f"Objective {index + 1}")[:100],
                "description": str(raw.get("description") or raw.get("name") or "Complete the objective.")[:500],
                "kind": kind,
                "target_id": target_id,
                "required_count": required,
            })
            if kind == "collect":
                interactions.append({
                    "prop_id": target_id,
                    "action": "collect",
                    "objective_id": objective_id,
                    "item_id": target_id,
                })

    if not mission_objectives:
        raise ValueError("The NEXORA project has no valid gameplay objectives.")
    gameplay_spec = {
        "player": {
            "move_speed": 5.5,
            "jump_velocity": 4.5,
            "gravity": 9.8,
            "health": 100,
            "inventory_capacity": 20,
        },
        "missions": [{
            "id": "nexora_main_mission",
            "title": f"{name} — Main Mission",
            "description": description,
            "objectives": mission_objectives,
        }],
        "actor_behaviours": actor_behaviours,
        "interactions": interactions,
        "audio_bindings": [
            {"event": "objective_complete", "cue_id": "nexora_objective"},
            {"event": "player_damaged", "cue_id": "nexora_damage"},
            {"event": "victory", "cue_id": "nexora_victory"},
            {"event": "defeat", "cue_id": "nexora_defeat"},
        ],
        "win_condition": "all_objectives_complete",
        "lose_condition": "health_depleted",
        "creator_mechanics": [
            str(item.get("name") or "")[:100]
            for item in gameplay.get("mechanics", [])[:64]
            if isinstance(item, dict)
        ],
    }
    actors_spec = {"actors": actors, "props": props}
    audio_cues = [
        {"id": "nexora_objective", "label": "Objective completed", "kind": "tone", "frequency": 660, "duration": 0.22, "seed": seed + 1, "trigger": "objective_complete"},
        {"id": "nexora_damage", "label": "Player damaged", "kind": "impact", "frequency": 180, "duration": 0.18, "seed": seed + 2, "trigger": "player_damaged"},
        {"id": "nexora_victory", "label": "Mission victory", "kind": "sweep", "frequency": 440, "duration": 0.8, "seed": seed + 3, "trigger": "victory"},
        {"id": "nexora_defeat", "label": "Mission defeat", "kind": "alarm", "frequency": 220, "duration": 0.7, "seed": seed + 4, "trigger": "defeat"},
    ]
    return {
        "world_spec": world_spec,
        "actors_spec": actors_spec,
        "gameplay_spec": gameplay_spec,
        "audio_cues": audio_cues,
        "player_asset_id": player_asset_id,
        "creator_asset_count": len(asset_files),
        "scene_object_count": len(raw_objects),
        "enemy_count": len(actors),
        "objective_count": len(mission_objectives),
    }


def _run_blender(executable: str, script_name: str, *arguments: str) -> str:
    script = ROOT / "blender" / "scripts" / script_name
    environment = os.environ.copy()
    system_packages = Path("/usr/lib/python3/dist-packages")
    if system_packages.is_dir():
        current = environment.get("PYTHONPATH", "")
        environment["PYTHONPATH"] = str(system_packages) + (os.pathsep + current if current else "")
    result = subprocess.run(
        [executable, "--background", "--factory-startup", "--python", str(script), "--", *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=900,
        env=environment,
    )
    output = (result.stdout or "") + "\n" + (result.stderr or "")
    if result.returncode != 0 or "Traceback (most recent call last)" in output or "Error: Python:" in output:
        raise RuntimeError(f"Blender {script_name} failed (exit={result.returncode}): {output[-8000:]}")
    return output


def assemble_workspace_game(
    project: dict[str, Any],
    asset_files: dict[str, Path],
    destination: Path,
    blender_executable: str,
    godot_executable: str,
) -> tuple[Path, dict[str, Any]]:
    """Run Blender asset creation and the tested Godot gameplay assembler."""
    if not blender_executable or not godot_executable:
        raise RuntimeError("Both Blender and Godot 4 are required for workspace game assembly.")
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    pipeline_root = destination / "movie_pipeline"
    player_dir = pipeline_root / "player" / "revision-0"
    environment_dir = pipeline_root / "environment"
    actors_dir = pipeline_root / "actors-props" / "revision-0"
    audio_dir = pipeline_root / "audio" / "revision-0"
    gameplay_dir = pipeline_root / "gameplay" / "revision-0"
    for folder in (player_dir, environment_dir, actors_dir, audio_dir, gameplay_dir):
        folder.mkdir(parents=True, exist_ok=True)

    specs = build_workspace_specs(project, asset_files)
    player_asset = asset_files.get(specs["player_asset_id"])
    player_output = player_dir / "player-avatar.glb"
    if player_asset and player_asset.is_file():
        shutil.copy2(player_asset, player_output)
    else:
        _run_blender(blender_executable, "build_default_player.py", "--output", str(player_output))

    world_spec_path = environment_dir / "world-spec.json"
    world_spec_path.write_text(json.dumps(specs["world_spec"], indent=2), encoding="utf-8")
    _run_blender(
        blender_executable,
        "build_movie_world.py",
        "--spec", str(world_spec_path),
        "--output", str(environment_dir / "environment.glb"),
    )

    actors_spec_path = actors_dir / "actors-props.json"
    actors_spec_path.write_text(json.dumps(specs["actors_spec"], indent=2), encoding="utf-8")
    _run_blender(
        blender_executable,
        "build_actors_props.py",
        "--spec", str(actors_spec_path),
        "--output", str(actors_dir / "actors-props.glb"),
    )

    audio_manifest = generate_audio(audio_dir, specs["audio_cues"], {"duration": 16, "seed": 42, "mood": "adventure", "loop": True})
    compile_gameplay(gameplay_dir, specs["gameplay_spec"], audio_manifest)

    stages = [
        SimpleNamespace(stage=stage, state=StageState.APPROVED, revision=0)
        for stage in StageId
    ]
    pipeline = SimpleNamespace(stages=stages)
    manifest = assemble_movie_game(destination, pipeline, godot_executable)
    manifest["workspace_source"] = {
        "project_id": str(project.get("id") or ""),
        "creator_asset_count": specs["creator_asset_count"],
        "scene_object_count": specs["scene_object_count"],
        "enemy_count": specs["enemy_count"],
        "objective_count": specs["objective_count"],
        "player_avatar": "creator_glb" if player_asset and player_asset.is_file() else "procedural_default",
        "requires_creator_review": True,
    }
    game_dir = destination / "game"
    (game_dir / "nexora-workspace-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return game_dir, manifest
