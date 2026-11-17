"""Deterministic gameplay manifest compiler and safe Godot runtime emitters."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

RUNTIME_FILES = {
"GameplayDirector.gd": r'''extends Node
class_name GameplayDirector
signal objective_updated(objective_id: String, current: int, required: int)
signal mission_completed(mission_id: String)
signal game_won
signal game_lost
signal audio_event(event_id: String)
var definition: Dictionary = {}
var progress: Dictionary = {}
var health: int = 100
var inventory: Dictionary = {}
var checkpoints: Array[String] = []
var finished: bool = false
var _audio_events: Dictionary = {}
func configure(gameplay: Dictionary, audio_events: Dictionary = {}) -> void:
    definition = gameplay
    _audio_events = audio_events
    health = int(definition.get("player", {}).get("health", 100))
    for mission in definition.get("missions", []):
        for objective in mission.get("objectives", []):
            progress[objective.id] = 0
func emit_game_event(event_id: String) -> void:
    if _audio_events.has(event_id):
        audio_event.emit(String(_audio_events[event_id]))
func advance_objective(objective_id: String, amount: int = 1) -> void:
    if finished:
        return
    var found: Dictionary = {}
    for mission in definition.get("missions", []):
        for objective in mission.get("objectives", []):
            if objective.id == objective_id:
                found = objective
                break
    if found.is_empty():
        return
    var required := int(found.get("required_count", 1))
    var current := mini(int(progress.get(objective_id, 0)) + maxi(amount, 0), required)
    progress[objective_id] = current
    objective_updated.emit(objective_id, current, required)
    emit_game_event("objective_progress")
    if current >= required:
        emit_game_event("objective_complete")
        _check_missions()
func _check_missions() -> void:
    for mission in definition.get("missions", []):
        var complete := true
        for objective in mission.get("objectives", []):
            if int(progress.get(objective.id, 0)) < int(objective.get("required_count", 1)):
                complete = false
                break
        if complete:
            mission_completed.emit(String(mission.id))
    var all_complete := true
    for mission in definition.get("missions", []):
        for objective in mission.get("objectives", []):
            if int(progress.get(objective.id, 0)) < int(objective.get("required_count", 1)):
                all_complete = false
    if all_complete and not definition.get("missions", []).is_empty():
        win_game()
func collect_item(item_id: String, amount: int = 1) -> bool:
    var capacity := int(definition.get("player", {}).get("inventory_capacity", 20))
    var count := 0
    for value in inventory.values():
        count += int(value)
    if count + amount > capacity or amount < 1:
        return false
    inventory[item_id] = int(inventory.get(item_id, 0)) + amount
    emit_game_event("item_collected")
    return true
func damage_player(amount: int) -> void:
    if finished:
        return
    health = maxi(0, health - maxi(amount, 0))
    emit_game_event("player_damaged")
    if health == 0:
        lose_game()
func set_checkpoint(checkpoint_id: String) -> void:
    if not checkpoints.has(checkpoint_id):
        checkpoints.append(checkpoint_id)
    emit_game_event("checkpoint_reached")
func win_game() -> void:
    if finished:
        return
    finished = true
    emit_game_event("victory")
    game_won.emit()
func lose_game() -> void:
    if finished:
        return
    finished = true
    emit_game_event("defeat")
    game_lost.emit()
func save_progress(path: String = "user://savegame.json") -> bool:
    var data := {"health": health, "inventory": inventory, "progress": progress, "checkpoints": checkpoints, "finished": finished}
    var file := FileAccess.open(path, FileAccess.WRITE)
    if file == null:
        return false
    file.store_string(JSON.stringify(data))
    return true
func load_progress(path: String = "user://savegame.json") -> bool:
    if not FileAccess.file_exists(path):
        return false
    var file := FileAccess.open(path, FileAccess.READ)
    if file == null:
        return false
    var parsed = JSON.parse_string(file.get_as_text())
    if typeof(parsed) != TYPE_DICTIONARY:
        return false
    health = int(parsed.get("health", health))
    inventory = parsed.get("inventory", {})
    progress = parsed.get("progress", progress)
    checkpoints.clear()
    for checkpoint in parsed.get("checkpoints", []):
        checkpoints.append(str(checkpoint))
    finished = bool(parsed.get("finished", false))
    return true
''',
"PlayerController.gd": r'''extends CharacterBody3D
class_name PGFPlayerController
@export var move_speed: float = 5.0
@export var jump_velocity: float = 4.5
@export var gravity: float = 9.8
@export var director_path: NodePath
var director: Node
func _ready() -> void:
    if not director_path.is_empty():
        director = get_node_or_null(director_path)
func _physics_process(delta: float) -> void:
    var input_vector := Vector2(Input.get_action_strength("move_right") - Input.get_action_strength("move_left"), Input.get_action_strength("move_backward") - Input.get_action_strength("move_forward")).normalized()
    var direction := (global_transform.basis * Vector3(input_vector.x, 0.0, input_vector.y)).normalized()
    velocity.x = direction.x * move_speed
    velocity.z = direction.z * move_speed
    if not is_on_floor():
        velocity.y -= gravity * delta
    elif Input.is_action_just_pressed("jump"):
        velocity.y = jump_velocity
        if is_instance_valid(director):
            director.emit_game_event("player_jump")
    move_and_slide()
func interact_with(target: Node) -> void:
    if target != null and target.has_method("pgf_interact"):
        target.pgf_interact(self)
''',
"ActorBehaviour.gd": r'''extends Node
class_name PGFActorBehaviour
enum Mode { IDLE, PATROL, GUARD, CHASE, ATTACK }
@export var mode: Mode = Mode.IDLE
@export var move_speed: float = 2.5
@export var detection_range: float = 10.0
@export var attack_range: float = 1.8
@export var damage: int = 10
@export var patrol_points: Array[Vector3] = []
var _patrol_index: int = 0
var _target: Node3D
var _body: CharacterBody3D
func _ready() -> void:
    _body = get_parent() as CharacterBody3D
func set_target(target: Node3D) -> void:
    _target = target
func _physics_process(delta: float) -> void:
    if _body == null:
        return
    if mode == Mode.IDLE or mode == Mode.GUARD:
        _body.velocity.x = move_toward(_body.velocity.x, 0.0, move_speed * delta)
        _body.velocity.z = move_toward(_body.velocity.z, 0.0, move_speed * delta)
    elif mode == Mode.PATROL:
        _patrol(delta)
    elif mode == Mode.CHASE or mode == Mode.ATTACK:
        _pursue(delta)
    _body.move_and_slide()
func _patrol(delta: float) -> void:
    if patrol_points.is_empty():
        return
    var destination: Vector3 = patrol_points[_patrol_index]
    var direction := destination - _body.global_position
    if direction.length() < 0.5:
        _patrol_index = (_patrol_index + 1) % patrol_points.size()
        return
    direction.y = 0.0
    direction = direction.normalized()
    _body.velocity.x = direction.x * move_speed
    _body.velocity.z = direction.z * move_speed
func _pursue(delta: float) -> void:
    if not is_instance_valid(_target):
        return
    var offset := _target.global_position - _body.global_position
    var distance := offset.length()
    if distance <= attack_range:
        if _target.has_method("take_damage"):
            _target.take_damage(damage)
        return
    if distance <= detection_range:
        offset.y = 0.0
        var direction := offset.normalized()
        _body.velocity.x = direction.x * move_speed
        _body.velocity.z = direction.z * move_speed
''',
"AudioEventRouter.gd": r'''extends Node
class_name PGFAudioEventRouter
@export var director_path: NodePath
@export var cue_players: Dictionary = {}
var director: Node
func _ready() -> void:
    director = get_node_or_null(director_path)
    if is_instance_valid(director) and director.has_signal("audio_event"):
        director.audio_event.connect(_play_cue)
func _play_cue(cue_id: String) -> void:
    var player = cue_players.get(cue_id)
    if player is AudioStreamPlayer or player is AudioStreamPlayer3D:
        player.play()
'''
}

def compile_gameplay(output_dir: Path, spec: dict[str, Any], audio_manifest: dict[str, Any]) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "gameplay.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
    audio_events = {item["event"]: item["cue_id"] for item in spec.get("audio_bindings", [])}
    (output_dir / "audio-events.json").write_text(json.dumps(audio_events, indent=2), encoding="utf-8")
    runtime_dir = output_dir / "runtime"
    runtime_dir.mkdir(exist_ok=True)
    for name, source in RUNTIME_FILES.items():
        (runtime_dir / name).write_text(source, encoding="utf-8")
    manifest = {"schema_version":"1.0","compiler":"PGF Deterministic Gameplay Compiler v1","creator_authored":True,
      "gameplay_spec":"gameplay.json","audio_events":"audio-events.json",
      "runtime_files":[f"runtime/{name}" for name in RUNTIME_FILES],
      "mission_count":len(spec["missions"]),
      "objective_count":sum(len(m["objectives"]) for m in spec["missions"]),
      "actor_behaviour_count":len(spec.get("actor_behaviours",[])),
      "interaction_count":len(spec.get("interactions",[])),
      "audio_binding_count":len(audio_events),
      "available_audio_cues":[item["id"] for item in audio_manifest.get("effects",[])],
      "requires_creator_review":True,
      "runtime_integration":"Generated Godot scripts and data are ready for assembly; scene-node binding remains an explicit assembly step."}
    (output_dir / "gameplay-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest
