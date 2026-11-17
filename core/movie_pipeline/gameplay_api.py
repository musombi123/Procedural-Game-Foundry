"""Approval-gated creator-authored Gameplay Compiler API."""
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from core.movie_pipeline.models import StageId, StageState
from core.movie_pipeline.service import PipelineStore
from core.gameplay_compiler.compiler import compile_gameplay
import json

class ObjectiveSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$")
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=500)
    kind: Literal["collect", "interact", "defeat", "reach", "survive"]
    target_id: str | None = Field(default=None, max_length=40)
    required_count: int = Field(default=1, ge=1, le=1000)

class MissionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$")
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=500)
    objectives: list[ObjectiveSpec] = Field(min_length=1, max_length=20)

class ActorBehaviourSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actor_id: str = Field(min_length=1, max_length=40)
    behaviour: Literal["idle", "patrol", "guard", "chase", "attack"]
    move_speed: float = Field(default=2.5, ge=0, le=20)
    detection_range: float = Field(default=10, ge=0, le=100)
    attack_range: float = Field(default=1.8, ge=0, le=20)
    damage: int = Field(default=10, ge=0, le=1000)

class InteractionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prop_id: str = Field(min_length=1, max_length=40)
    action: Literal["collect", "open", "activate", "talk", "damage"]
    objective_id: str | None = Field(default=None, max_length=40)
    item_id: str | None = Field(default=None, max_length=40)

class AudioBindingSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event: Literal["player_jump", "objective_progress", "objective_complete", "item_collected", "player_damaged", "victory", "defeat", "checkpoint_reached"]
    cue_id: str = Field(min_length=1, max_length=40)

class PlayerRules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    move_speed: float = Field(default=5.0, ge=0.5, le=30)
    jump_velocity: float = Field(default=4.5, ge=0, le=20)
    gravity: float = Field(default=9.8, ge=0, le=40)
    health: int = Field(default=100, ge=1, le=10000)
    inventory_capacity: int = Field(default=20, ge=1, le=1000)

class GameplayBuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    player: PlayerRules
    missions: list[MissionSpec] = Field(min_length=1, max_length=20)
    actor_behaviours: list[ActorBehaviourSpec] = Field(default_factory=list, max_length=12)
    interactions: list[InteractionSpec] = Field(default_factory=list, max_length=40)
    audio_bindings: list[AudioBindingSpec] = Field(default_factory=list, max_length=24)
    win_condition: Literal["all_objectives_complete"] = "all_objectives_complete"
    lose_condition: Literal["health_depleted"] = "health_depleted"

    @model_validator(mode="after")
    def validate_references_and_ids(self):
        mission_ids = [item.id for item in self.missions]
        objective_ids = [obj.id for mission in self.missions for obj in mission.objectives]
        if len(mission_ids) != len(set(mission_ids)):
            raise ValueError("Mission IDs must be unique")
        if len(objective_ids) != len(set(objective_ids)):
            raise ValueError("Objective IDs must be unique across all missions")
        for item in self.interactions:
            if item.objective_id and item.objective_id not in objective_ids:
                raise ValueError(f"Interaction references unknown objective: {item.objective_id}")
        if len({item.event for item in self.audio_bindings}) != len(self.audio_bindings):
            raise ValueError("Only one audio cue can be bound to each runtime event")
        return self

def register_gameplay_routes(app, manager_provider):
    router = APIRouter()
    @router.post("/api/projects/{pid}/movie-pipeline/gameplay/compile")
    def compile_gameplay_route(pid: str, request: GameplayBuildRequest):
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
        records = {record.stage: record for record in pipeline.stages}
        required = [StageId.ANALYSIS, StageId.PLAYER, StageId.ENVIRONMENT, StageId.ACTORS_PROPS, StageId.AUDIO]
        if any(records[item].state != StageState.APPROVED for item in required):
            raise HTTPException(409, "Approve analysis, player, environment, actors/props and audio before compiling gameplay")
        stage = records[StageId.GAMEPLAY]
        if stage.state != StageState.READY:
            raise HTTPException(409, "Gameplay stage is not READY; approve audio or regenerate upstream stages first")
        root = store.folder
        story_file = root / "story.json"
        actor_manifest = root / "actors-props" / f"revision-{records[StageId.ACTORS_PROPS].revision}" / "actors-props.manifest.json"
        audio_manifest_file = root / "audio" / f"revision-{records[StageId.AUDIO].revision}" / "audio-manifest.json"
        if not story_file.is_file() or not actor_manifest.is_file() or not audio_manifest_file.is_file():
            raise HTTPException(409, "Required approved story, actor/prop and audio manifests are missing")
        story = json.loads(story_file.read_text(encoding="utf-8"))
        actors_data = json.loads(actor_manifest.read_text(encoding="utf-8"))
        audio_manifest = json.loads(audio_manifest_file.read_text(encoding="utf-8"))
        known_actor_ids = {item.get("id") for item in actors_data.get("actors", [])}
        known_prop_ids = {item.get("id") for item in actors_data.get("props", [])}
        known_cue_ids = {item.get("id") for item in audio_manifest.get("effects", [])}
        errors = []
        for item in request.actor_behaviours:
            if item.actor_id not in known_actor_ids:
                errors.append(f"Unknown actor in behaviour: {item.actor_id}")
        for item in request.interactions:
            if item.prop_id not in known_prop_ids:
                errors.append(f"Unknown prop in interaction: {item.prop_id}")
        for item in request.audio_bindings:
            if item.cue_id not in known_cue_ids:
                errors.append(f"Unknown audio cue: {item.cue_id}")
        if errors:
            raise HTTPException(422, "; ".join(errors))
        spec = request.model_dump(mode="json")
        spec["source_story_title"] = story.get("title", "")
        output_dir = root / "gameplay" / f"revision-{stage.revision}"
        stage.state = StageState.RUNNING
        stage.summary = "Compiling creator-authored missions, controls, interactions and runtime event bindings"
        store.save(pipeline)
        try:
            manifest = compile_gameplay(output_dir, spec, audio_manifest)
            output = {"manifest":str((output_dir / "gameplay-manifest.json").relative_to(folder)),
              "gameplay_spec":str((output_dir / "gameplay.json").relative_to(folder)),
              "audio_events":str((output_dir / "audio-events.json").relative_to(folder)),
              "runtime_files":[str((output_dir / item).relative_to(folder)) for item in manifest["runtime_files"]],
              "mission_count":manifest["mission_count"],"objective_count":manifest["objective_count"],
              "audio_binding_count":manifest["audio_binding_count"],"requires_creator_review":True}
            reviewed = store.mark_review(StageId.GAMEPLAY, output, "Gameplay systems compiled; test controls, objectives, interactions, save/load and event audio before approval")
        except Exception as exc:
            current = store.load()
            record = next(item for item in current.stages if item.stage == StageId.GAMEPLAY)
            record.state = StageState.FAILED
            record.error = str(exc)[:2000]
            record.summary = "Gameplay compilation failed"
            store.save(current)
            raise HTTPException(500, "Gameplay compilation failed: " + str(exc)) from exc
        return {"compiled":True,"stage":next(item.model_dump(mode="json") for item in reviewed.stages if item.stage == StageId.GAMEPLAY),
          "manifest":output["manifest"],"mission_count":manifest["mission_count"],"objective_count":manifest["objective_count"],
          "runtime_files":output["runtime_files"],"audio_binding_count":manifest["audio_binding_count"],"requires_creator_review":True}
    app.include_router(router)
