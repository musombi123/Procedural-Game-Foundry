"""Approval-gated assembly of the staged movie pipeline into a playable Godot project."""
from __future__ import annotations

import json
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from core.movie_pipeline.models import StageId, StageState
from core.movie_pipeline.service import PipelineStore

APPROVED_INPUTS = (
    StageId.ANALYSIS, StageId.PLAYER, StageId.ENVIRONMENT,
    StageId.ACTORS_PROPS, StageId.AUDIO, StageId.GAMEPLAY,
)


def _inside(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    resolved_root = root.resolve()
    if resolved_root not in candidate.parents or not candidate.is_file():
        raise FileNotFoundError(relative)
    return candidate


def _copy(source: Path, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return str(destination)


def _runtime_main() -> str:
    return r'''extends Node3D

const DIRECTOR_SCRIPT = preload("res://scripts/runtime/GameplayDirector.gd")
const PLAYER_SCRIPT = preload("res://scripts/runtime/PlayerController.gd")
const ACTOR_SCRIPT = preload("res://scripts/runtime/ActorBehaviour.gd")
const PROP_SCRIPT = preload("res://scripts/InteractableProp.gd")

var gameplay: Dictionary = {}
var actor_spec: Dictionary = {}
var audio_manifest: Dictionary = {}
var audio_players: Dictionary = {}
var player: CharacterBody3D
var director: Node

func _ready() -> void:
    gameplay = _read_json("res://gameplay/gameplay.json")
    actor_spec = _read_json("res://gameplay/actors-props.json")
    audio_manifest = _read_json("res://gameplay/audio-manifest.json")
    _configure_input()
    _create_lighting()
    _instance_environment()
    _create_floor_safety_collision()
    _create_director()
    _create_player()
    _instance_actors_and_props()
    _create_audio()
    _create_hud()

func _read_json(path: String) -> Dictionary:
    if not FileAccess.file_exists(path):
        push_error("Required assembled data missing: " + path)
        return {}
    var parsed = JSON.parse_string(FileAccess.get_file_as_string(path))
    return parsed if typeof(parsed) == TYPE_DICTIONARY else {}

func _configure_input() -> void:
    _bind_key("move_forward", KEY_W)
    _bind_key("move_backward", KEY_S)
    _bind_key("move_left", KEY_A)
    _bind_key("move_right", KEY_D)
    _bind_key("jump", KEY_SPACE)
    _bind_key("interact", KEY_E)
    _bind_key("attack", KEY_F)
    _bind_key("save_game", KEY_F5)

func _bind_key(action: String, key: Key) -> void:
    if not InputMap.has_action(action):
        InputMap.add_action(action)
    var event := InputEventKey.new()
    event.physical_keycode = key
    InputMap.action_add_event(action, event)

func _create_lighting() -> void:
    var sun := DirectionalLight3D.new()
    sun.rotation_degrees = Vector3(-48, -28, 0)
    sun.light_energy = 1.2
    add_child(sun)
    var environment := WorldEnvironment.new()
    var settings := Environment.new()
    settings.background_mode = Environment.BG_SKY
    var sky := Sky.new()
    var sky_material := ProceduralSkyMaterial.new()
    sky_material.sky_top_color = Color("#142c49")
    sky_material.sky_horizon_color = Color("#9bb8c4")
    sky.sky_material = sky_material
    settings.sky = sky
    settings.ambient_light_source = Environment.AMBIENT_SOURCE_SKY
    settings.ambient_light_energy = 0.6
    environment.environment = settings
    add_child(environment)

func _instance_environment() -> void:
    var packed := load("res://assets/environment.glb") as PackedScene
    if packed == null:
        push_error("Environment GLB could not be imported")
        return
    var instance := packed.instantiate()
    instance.name = "EnvironmentAsset"
    add_child(instance)

func _create_floor_safety_collision() -> void:
    var floor := StaticBody3D.new()
    floor.name = "WorldSafetyFloor"
    floor.position.y = -2.5
    var shape := CollisionShape3D.new()
    var bounds := BoxShape3D.new()
    bounds.size = Vector3(400, 1, 400)
    shape.shape = bounds
    floor.add_child(shape)
    add_child(floor)

func _create_director() -> void:
    director = Node.new()
    director.name = "GameplayDirector"
    director.set_script(DIRECTOR_SCRIPT)
    add_child(director)
    director.add_to_group("gameplay_director")
    director.configure(gameplay, _read_json("res://gameplay/audio-events.json"))

func _create_player() -> void:
    player = CharacterBody3D.new()
    player.name = "Player"
    player.set_script(PLAYER_SCRIPT)
    var rules: Dictionary = gameplay.get("player", {})
    player.set("move_speed", float(rules.get("move_speed", 5.0)))
    player.set("jump_velocity", float(rules.get("jump_velocity", 4.5)))
    player.set("gravity", float(rules.get("gravity", 9.8)))
    player.position = Vector3(0, 2.0, 12)
    var collider := CollisionShape3D.new()
    var capsule := CapsuleShape3D.new()
    capsule.radius = 0.38
    capsule.height = 1.8
    collider.shape = capsule
    player.add_child(collider)
    var avatar := (load("res://assets/player-avatar.glb") as PackedScene)
    if avatar != null:
        var visual := avatar.instantiate()
        visual.name = "PortraitReferencedAvatar"
        visual.scale = Vector3.ONE * 0.9
        player.add_child(visual)
    var camera := Camera3D.new()
    camera.name = "FollowCamera"
    camera.position = Vector3(0, 2.5, 6.5)
    camera.current = true
    player.add_child(camera)
    add_child(player)
    camera.look_at(player.global_position + Vector3(0, 1.1, 0))
    player.set("director", director)

func _instance_actors_and_props() -> void:
    var packed := load("res://assets/actors-props.glb") as PackedScene
    if packed != null:
        var visuals := packed.instantiate()
        visuals.name = "ActorsAndPropsAsset"
        add_child(visuals)
        _bind_actor_behaviours(visuals)
        _create_actor_hitboxes(visuals)
    _create_interaction_areas()

func _bind_actor_behaviours(visuals: Node) -> void:
    for config in gameplay.get("actor_behaviours", []):
        var actor_id := str(config.get("actor_id", ""))
        var rig := visuals.find_child(actor_id + "_rig", true, false)
        if rig == null:
            rig = visuals.find_child(actor_id + "_mesh", true, false)
        if rig == null:
            push_warning("Actor visual not found for behaviour: " + actor_id)
            continue
        rig.set_script(ACTOR_SCRIPT)
        rig.call("configure", config, player, director)

func _create_actor_hitboxes(visuals: Node) -> void:
    for config in gameplay.get("actor_behaviours", []):
        var actor_id := str(config.get("actor_id", ""))
        var descriptor: Dictionary = {}
        for item in actor_spec.get("actors", []):
            if str(item.get("id", "")) == actor_id:
                descriptor = item
                break
        if descriptor.is_empty():
            continue
        var rig := visuals.find_child(actor_id + "_rig", true, false)
        if rig == null:
            continue
        var area := Area3D.new()
        area.name = "Hitbox_" + actor_id
        area.position = Vector3(descriptor.position[0], descriptor.position[1] + 1.0, descriptor.position[2])
        area.collision_layer = 4
        area.collision_mask = 0
        var collision := CollisionShape3D.new()
        var shape := SphereShape3D.new()
        shape.radius = 1.1 * float(descriptor.get("scale", 1.0))
        collision.shape = shape
        area.add_child(collision)
        area.set_script(load("res://scripts/ActorHitbox.gd"))
        area.call("configure", rig)
        add_child(area)

func _create_interaction_areas() -> void:
    for interaction in gameplay.get("interactions", []):
        var prop_id := str(interaction.get("prop_id", ""))
        var descriptor: Dictionary = {}
        for item in actor_spec.get("props", []):
            if str(item.get("id", "")) == prop_id:
                descriptor = item
                break
        if descriptor.is_empty():
            continue
        var area := Area3D.new()
        area.name = "Interact_" + prop_id
        area.position = Vector3(descriptor.position[0], descriptor.position[1] + 0.8, descriptor.position[2])
        area.collision_layer = 2
        area.collision_mask = 0
        var collision := CollisionShape3D.new()
        var shape := SphereShape3D.new()
        shape.radius = maxf(1.4, float(descriptor.get("scale", 1.0)) * 1.5)
        collision.shape = shape
        area.add_child(collision)
        area.set_script(PROP_SCRIPT)
        area.call("configure", interaction, director)
        add_child(area)

func _create_audio() -> void:
    for effect in audio_manifest.get("effects", []):
        var cue_id := str(effect.get("id", ""))
        var path := "res://assets/audio/" + str(effect.get("file", ""))
        if cue_id.is_empty() or not ResourceLoader.exists(path):
            continue
        var player_node := AudioStreamPlayer.new()
        player_node.name = "SFX_" + cue_id
        player_node.stream = load(path)
        add_child(player_node)
        audio_players[cue_id] = player_node
    director.audio_event.connect(_play_audio_cue)
    var music: Dictionary = audio_manifest.get("music", {})
    if not music.is_empty():
        var music_path := "res://assets/audio/" + str(music.get("file", ""))
        if ResourceLoader.exists(music_path):
            var music_player := AudioStreamPlayer.new()
            music_player.name = "BackgroundMusic"
            music_player.stream = load(music_path)
            add_child(music_player)
            music_player.play()

func _play_audio_cue(cue_id: String) -> void:
    var cue = audio_players.get(cue_id)
    if cue is AudioStreamPlayer:
        cue.play()

func _create_hud() -> void:
    var layer := CanvasLayer.new()
    layer.name = "GameHUD"
    var label := Label.new()
    label.name = "Status"
    label.position = Vector2(18, 18)
    label.add_theme_font_size_override("font_size", 18)
    label.add_theme_color_override("font_color", Color.WHITE)
    label.text = "WASD move · SPACE jump · E interact · F attack · F5 save"
    layer.add_child(label)
    add_child(layer)
    director.objective_updated.connect(func(_id: String, current: int, required: int):
        label.text = "Objective progress: %d / %d   ·   WASD move · E interact · F5 save" % [current, required]
    )
    director.game_won.connect(func(): label.text = "MISSION COMPLETE")
    director.game_lost.connect(func(): label.text = "GAME OVER")

func save_game() -> void:
    director.save_progress()
'''

def _player_script() -> str:
    return r'''extends CharacterBody3D
var move_speed: float = 5.0
var jump_velocity: float = 4.5
var gravity: float = 9.8
var director: Node
func _physics_process(delta: float) -> void:
    if not is_on_floor():
        velocity.y -= gravity * delta
    elif Input.is_action_just_pressed("jump"):
        velocity.y = jump_velocity
        if is_instance_valid(director):
            director.emit_game_event("player_jump")
    var axis := Vector2(Input.get_action_strength("move_right") - Input.get_action_strength("move_left"),
        Input.get_action_strength("move_backward") - Input.get_action_strength("move_forward")).normalized()
    var direction := (global_transform.basis * Vector3(axis.x, 0, axis.y)).normalized()
    velocity.x = direction.x * move_speed
    velocity.z = direction.z * move_speed
    move_and_slide()
    if Input.is_action_just_pressed("interact"):
        _try_interact()
    if Input.is_action_just_pressed("attack"):
        _try_attack()
    if Input.is_action_just_pressed("save_game") and is_instance_valid(director):
        director.save_progress()
func _try_attack() -> void:
    var camera := get_node_or_null("FollowCamera") as Camera3D
    if camera == null:
        return
    var start := camera.global_position
    var finish := start - camera.global_transform.basis.z * 3.0
    var query := PhysicsRayQueryParameters3D.create(start, finish)
    query.collision_mask = 4
    query.collide_with_areas = true
    var hit := get_world_3d().direct_space_state.intersect_ray(query)
    if not hit.is_empty():
        var target = hit.get("collider")
        if target != null and target.has_method("take_damage"):
            target.take_damage(25)
func _try_interact() -> void:
    var camera := get_node_or_null("FollowCamera") as Camera3D
    if camera == null:
        return
    var start := camera.global_position
    var finish := start - camera.global_transform.basis.z * 5.0
    var query := PhysicsRayQueryParameters3D.create(start, finish)
    query.collide_with_areas = true
    var hit := get_world_3d().direct_space_state.intersect_ray(query)
    if not hit.is_empty():
        var target = hit.get("collider")
        if target != null and target.has_method("pgf_interact"):
            target.pgf_interact(self)
'''

def _actor_script() -> str:
    return r'''extends Node3D
var actor_id := ""
var behaviour := "idle"
var move_speed := 2.5
var detection_range := 10.0
var attack_range := 1.8
var damage := 10
var health := 50
var target: Node3D
var director: Node
var patrol_origin := Vector3.ZERO
var attack_cooldown := 0.0
func configure(config: Dictionary, player: Node3D, gameplay_director: Node) -> void:
    actor_id = str(config.get("actor_id", ""))
    behaviour = str(config.get("behaviour", "idle"))
    move_speed = float(config.get("move_speed", 2.5))
    detection_range = float(config.get("detection_range", 10.0))
    attack_range = float(config.get("attack_range", 1.8))
    damage = int(config.get("damage", 10))
    target = player
    director = gameplay_director
    patrol_origin = global_position
func _process(delta: float) -> void:
    if behaviour == "patrol":
        var phase := sin(Time.get_ticks_msec() / 1600.0) * 3.0
        global_position.x = patrol_origin.x + phase
    elif behaviour in ["chase", "attack"] and is_instance_valid(target):
        var offset := target.global_position - global_position
        var distance := offset.length()
        if distance <= detection_range and distance > attack_range:
            offset.y = 0
            global_position += offset.normalized() * move_speed * delta
        elif distance <= attack_range:
            attack_cooldown -= delta
            if attack_cooldown <= 0 and is_instance_valid(director):
                director.damage_player(damage)
                attack_cooldown = 1.2
func take_damage(amount: int) -> void:
    health = maxi(0, health - maxi(amount, 0))
    if health == 0:
        var current_definition: Dictionary = director.get("definition")
        for mission in current_definition.get("missions", []):
            for objective in mission.get("objectives", []):
                if objective.get("kind") == "defeat" and objective.get("target_id") == actor_id:
                    director.advance_objective(str(objective.id))
        queue_free()
'''

def _prop_script() -> str:
    return r'''extends Area3D
var definition: Dictionary = {}
var director: Node
func configure(interaction: Dictionary, gameplay_director: Node) -> void:
    definition = interaction
    director = gameplay_director
func pgf_interact(_player: Node) -> void:
    if not is_instance_valid(director):
        return
    var action := str(definition.get("action", "activate"))
    var item_id := str(definition.get("item_id", definition.get("prop_id", "item")))
    if action == "collect":
        if not director.collect_item(item_id):
            return
    elif action == "damage":
        return
    if not str(definition.get("objective_id", "")).is_empty():
        director.advance_objective(str(definition.objective_id))
    if action == "activate":
        director.set_checkpoint(str(definition.get("prop_id", "checkpoint")))
    queue_free()
'''

def assemble_movie_game(project_folder: Path, pipeline: Any, godot_executable: str) -> dict[str, Any]:
    records = {item.stage: item for item in pipeline.stages}
    if any(records[item].state != StageState.APPROVED for item in APPROVED_INPUTS):
        raise ValueError("All stages through Gameplay must be APPROVED before assembly")
    root = project_folder / "movie_pipeline"
    player_rev = records[StageId.PLAYER].revision
    actors_rev = records[StageId.ACTORS_PROPS].revision
    audio_rev = records[StageId.AUDIO].revision
    gameplay_rev = records[StageId.GAMEPLAY].revision
    player_source = _inside(root, f"player/revision-{player_rev}/player-avatar.glb")
    environment_source = _inside(root, "environment/environment.glb")
    actors_source = _inside(root, f"actors-props/revision-{actors_rev}/actors-props.glb")
    actors_manifest_path = _inside(root, f"actors-props/revision-{actors_rev}/actors-props.manifest.json")
    actors_spec_path = _inside(root, f"actors-props/revision-{actors_rev}/actors-props.json")
    audio_manifest_path = _inside(root, f"audio/revision-{audio_rev}/audio-manifest.json")
    gameplay_root = _inside(root, f"gameplay/revision-{gameplay_rev}/gameplay.json").parent
    gameplay_manifest_path = _inside(root, f"gameplay/revision-{gameplay_rev}/gameplay-manifest.json")
    audio_manifest = json.loads(audio_manifest_path.read_text(encoding="utf-8"))
    actors_manifest = json.loads(actors_manifest_path.read_text(encoding="utf-8"))
    actors_spec = json.loads(actors_spec_path.read_text(encoding="utf-8"))
    gameplay_manifest = json.loads(gameplay_manifest_path.read_text(encoding="utf-8"))
    destination = project_folder / "game"
    if destination.exists():
        shutil.rmtree(destination)
    scripts = destination / "scripts"
    runtime = scripts / "runtime"
    assets = destination / "assets"
    audio_assets = assets / "audio"
    gameplay_assets = destination / "gameplay"
    runtime.mkdir(parents=True)
    audio_assets.mkdir(parents=True)
    gameplay_assets.mkdir(parents=True)
    copied = {}
    copied["player"] = _copy(player_source, assets / "player-avatar.glb")
    copied["environment"] = _copy(environment_source, assets / "environment.glb")
    copied["actors_props"] = _copy(actors_source, assets / "actors-props.glb")
    for name in ("gameplay.json", "audio-events.json"):
        source = _inside(gameplay_root, name)
        copied[name] = _copy(source, gameplay_assets / name)
    for name in gameplay_manifest.get("runtime_files", []):
        source = _inside(gameplay_root, name)
        copied[name] = _copy(source, runtime / Path(name).name)
    copied["actors_props_spec"] = _copy(actors_spec_path, gameplay_assets / "actors-props.json")
    copied["audio_manifest"] = _copy(audio_manifest_path, gameplay_assets / "audio-manifest.json")
    for effect in audio_manifest.get("effects", []):
        source = _inside(audio_manifest_path.parent, str(effect["file"]))
        _copy(source, audio_assets / source.name)
    music = audio_manifest.get("music")
    if music:
        source = _inside(audio_manifest_path.parent, str(music["file"]))
        _copy(source, audio_assets / source.name)
    (scripts / "main.gd").write_text(_runtime_main(), encoding="utf-8")
    (scripts / "PlayerController.gd").write_text(_player_script(), encoding="utf-8")
    (scripts / "ActorBehaviour.gd").write_text(_actor_script(), encoding="utf-8")
    (scripts / "InteractableProp.gd").write_text(_prop_script(), encoding="utf-8")
    (destination / "main.tscn").write_text(
        '[gd_scene load_steps=2 format=3]\n[ext_resource type="Script" path="res://scripts/main.gd" id="1"]\n[node name="PGFPlayableGame" type="Node3D"]\nscript = ExtResource("1")\n',
        encoding="utf-8",
    )
    (destination / "project.godot").write_text(
        'config_version=5\n[application]\nconfig/name="Procedural Game Foundry - Assembled Game"\nrun/main_scene="res://main.tscn"\n[display]\nwindow/size/viewport_width=1280\nwindow/size/viewport_height=720\n[rendering]\nrenderer/rendering_method="gl_compatibility"\nrenderer/rendering_method.mobile="gl_compatibility"\n',
        encoding="utf-8",
    )
    manifest = {
        "schema_version": "1.0", "assembler": "PGF Movie Pipeline Godot Assembler v1",
        "project": "game/project.godot", "main_scene": "game/main.tscn",
        "player_asset": "game/assets/player-avatar.glb",
        "environment_asset": "game/assets/environment.glb",
        "actors_props_asset": "game/assets/actors-props.glb",
        "mission_count": gameplay_manifest["mission_count"],
        "objective_count": gameplay_manifest["objective_count"],
        "actor_count": len(actors_manifest.get("actors", [])),
        "prop_count": len(actors_manifest.get("props", [])),
        "audio_effect_count": len(audio_manifest.get("effects", [])),
        "music_included": bool(music),
        "copied_artifacts": sorted(copied),
        "runtime_bindings": ["player-controller", "actor-behaviours", "prop-interactions", "mission-director", "audio-events", "save-load", "hud"],
        "validation": {"editor_import": "pending", "headless_runtime": "pending"},
        "requires_creator_review": True,
    }
    (destination / "assembly-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    editor = subprocess.run([godot_executable, "--headless", "--path", str(destination), "--editor", "--quit"],
                            capture_output=True, text=True, timeout=240)
    editor_output = editor.stdout + "\n" + editor.stderr
    if editor.returncode != 0 or "SCRIPT ERROR:" in editor_output or "Parse Error" in editor_output:
        raise RuntimeError("Godot editor import/parse validation failed:\n" + editor_output[-5000:])
    runtime_result = subprocess.run([godot_executable, "--headless", "--path", str(destination), "--quit-after", "90"],
                                    capture_output=True, text=True, timeout=180)
    runtime_output = runtime_result.stdout + "\n" + runtime_result.stderr
    if runtime_result.returncode != 0 or "SCRIPT ERROR:" in runtime_output or "Parse Error" in runtime_output:
        raise RuntimeError("Godot headless runtime smoke test failed:\n" + runtime_output[-5000:])
    manifest["validation"] = {"editor_import": "passed", "headless_runtime": "passed"}
    (destination / "assembly-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def register_assembly_routes(app, manager_provider):
    router = APIRouter()

    @router.post("/api/projects/{pid}/movie-pipeline/assembly/build")
    def build_assembly(pid: str):
        manager = manager_provider()
        try:
            folder = manager.path_for(pid)
            manager.load(pid)
            store = PipelineStore(folder)
            pipeline = store.load()
        except FileNotFoundError as exc:
            raise HTTPException(404, "Project or movie pipeline not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        records = {item.stage: item for item in pipeline.stages}
        if any(records[item].state != StageState.APPROVED for item in APPROVED_INPUTS):
            raise HTTPException(409, "Approve analysis, player, environment, actors/props, audio and gameplay before assembly")
        stage = records[StageId.ASSEMBLY]
        if stage.state != StageState.READY:
            raise HTTPException(409, "Assembly stage is not READY; approve gameplay or regenerate upstream stages")
        executable = shutil.which("godot") or shutil.which("godot4")
        if not executable:
            raise HTTPException(503, "Godot 4 is required to import and validate the assembled game")
        stage.state = StageState.RUNNING
        stage.summary = "Assembling approved 3D assets, gameplay systems and audio into Godot"
        store.save(pipeline)
        try:
            manifest = assemble_movie_game(folder, pipeline, executable)
            output = {"project": "game/project.godot", "main_scene": "game/main.tscn",
                      "manifest": "game/assembly-manifest.json", "validation": manifest["validation"],
                      "requires_creator_review": True}
            reviewed = store.mark_review(StageId.ASSEMBLY, output,
                "Godot project assembled and passed editor import plus headless runtime checks; playtest controls, collisions, objectives and audio before approval")
        except Exception as exc:
            current = store.load()
            record = next(item for item in current.stages if item.stage == StageId.ASSEMBLY)
            record.state = StageState.FAILED
            record.error = str(exc)[-3000:]
            record.summary = "Godot assembly or runtime validation failed"
            store.save(current)
            raise HTTPException(500, "Godot assembly failed: " + str(exc)[-2500:]) from exc
        return {"assembled": True,
                "stage": next(item.model_dump(mode="json") for item in reviewed.stages if item.stage == StageId.ASSEMBLY),
                "project": output["project"], "main_scene": output["main_scene"],
                "manifest": output["manifest"], "validation": output["validation"],
                "mission_count": manifest["mission_count"], "objective_count": manifest["objective_count"],
                "actor_count": manifest["actor_count"], "prop_count": manifest["prop_count"],
                "audio_effect_count": manifest["audio_effect_count"], "requires_creator_review": True}


    @router.get("/api/projects/{pid}/movie-pipeline/assembly/download")
    def download_assembly(pid: str):
        manager = manager_provider()
        try:
            folder = manager.path_for(pid)
            manager.load(pid)
            store = PipelineStore(folder)
            pipeline = store.load()
        except FileNotFoundError as exc:
            raise HTTPException(404, "Project or movie pipeline not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        record = next(item for item in pipeline.stages if item.stage == StageId.ASSEMBLY)
        if record.state not in (StageState.REVIEW, StageState.APPROVED):
            raise HTTPException(409, "Assemble and validate the game before downloading it")
        game = folder / "game"
        if not (game / "project.godot").is_file():
            raise HTTPException(404, "Assembled Godot project is missing")
        archive = folder / "assembled-game.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for item in game.rglob("*"):
                if item.is_file():
                    bundle.write(item, Path("ProceduralGameFoundry") / item.relative_to(game))
        from fastapi.responses import FileResponse
        return FileResponse(archive, media_type="application/zip", filename="procedural-game-foundry.zip")

    app.include_router(router)
