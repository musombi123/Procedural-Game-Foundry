"""Approval-gated actor/prop generation routes; registered by the main API."""
import json, shutil, subprocess
from pathlib import Path
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from core.movie_pipeline.models import StageId, StageState
from core.movie_pipeline.service import PipelineStore

class ActorSpec(BaseModel):
    model_config=ConfigDict(extra="forbid")
    id: str = Field(min_length=1,max_length=40)
    name: str = Field(min_length=1,max_length=80)
    kind: Literal["npc","enemy","animal","robot"] = "npc"
    behavior: str = Field(default="idle",max_length=500)
    scale: float = Field(default=1.0,ge=.5,le=2.0)
    position: tuple[float,float,float] = (0.0,0.0,0.0)

class PropSpec(BaseModel):
    model_config=ConfigDict(extra="forbid")
    id: str = Field(min_length=1,max_length=40)
    name: str = Field(min_length=1,max_length=80)
    kind: Literal["weapon","tool","vehicle","item","obstacle","container"] = "item"
    interaction: str = Field(default="inspect",max_length=500)
    scale: float = Field(default=1.0,ge=.15,le=8.0)
    position: tuple[float,float,float] = (0.0,0.0,0.0)

class ActorsPropsRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")
    actors: list[ActorSpec] = Field(default_factory=list,max_length=12)
    props: list[PropSpec] = Field(default_factory=list,max_length=40)

    @field_validator("actors","props")
    @classmethod
    def unique_ids(cls, values):
        ids=[item.id for item in values]
        if len(ids)!=len(set(ids)): raise ValueError("Actor and prop IDs must be unique within their collection")
        return values

def register_actor_props_routes(app, manager_provider):
    router=APIRouter()
    @router.post("/api/projects/{pid}/movie-pipeline/actors-props/build")
    def build_actors_props(pid: str, request: ActorsPropsRequest):
        manager=manager_provider()
        try:
            folder=manager.path_for(pid); manager.load(pid); store=PipelineStore(folder); pipeline=store.load()
        except FileNotFoundError as exc: raise HTTPException(404,"Project or movie pipeline not found") from exc
        except ValueError as exc: raise HTTPException(400,str(exc)) from exc
        stage=next(item for item in pipeline.stages if item.stage==StageId.ACTORS_PROPS)
        if stage.state != StageState.READY:
            raise HTTPException(409,"Approve the 3D environment before generating actors and props")
        if not request.actors and not request.props:
            raise HTTPException(400,"Add at least one actor or prop descriptor")
        if len({item.id for item in request.actors+request.props}) != len(request.actors)+len(request.props):
            raise HTTPException(400,"Actor and prop IDs must be unique across the whole build")
        blender=shutil.which("blender")
        if not blender: raise HTTPException(503,"Blender is required for procedural actor and prop generation")
        output_dir=store.folder/"actors-props"/f"revision-{stage.revision}"; output_dir.mkdir(parents=True,exist_ok=True)
        spec_path=output_dir/"actors-props.json"; glb=output_dir/"actors-props.glb"
        spec={"actors":[item.model_dump() for item in request.actors],"props":[item.model_dump() for item in request.props]}
        spec_path.write_text(json.dumps(spec,indent=2),encoding="utf-8")
        script=Path(__file__).resolve().parents[2]/"blender"/"scripts"/"build_actors_props.py"
        stage.state=StageState.RUNNING; stage.summary="Building creator-defined actors, rigs, props and collision metadata"; store.save(pipeline)
        try:
            result=subprocess.run([blender,"--background","--python",str(script),"--","--spec",str(spec_path),"--output",str(glb)],capture_output=True,text=True,timeout=900,check=True)
        except subprocess.TimeoutExpired as exc:
            stage.state=StageState.FAILED; stage.error="Blender actor/prop generation exceeded 15 minutes"; store.save(pipeline); raise HTTPException(504,stage.error) from exc
        except subprocess.CalledProcessError as exc:
            detail=(exc.stderr or exc.stdout or "Blender actor/prop generation failed")[-2500:]
            stage.state=StageState.FAILED; stage.error=detail; stage.summary="Actor and prop generation failed"; store.save(pipeline); raise HTTPException(500,detail) from exc
        if not glb.is_file() or glb.stat().st_size<1024:
            stage.state=StageState.FAILED; stage.error="Blender did not produce a valid actor/prop GLB"; store.save(pipeline); raise HTTPException(500,stage.error)
        manifest=glb.with_suffix(".manifest.json")
        if not manifest.is_file(): raise HTTPException(500,"Actor/prop manifest was not produced")
        reviewed=store.mark_review(StageId.ACTORS_PROPS,{"glb_scene":str(glb.relative_to(folder)),"manifest":str(manifest.relative_to(folder)),"spec":str(spec_path.relative_to(folder)),"actor_count":len(request.actors),"prop_count":len(request.props),"glb_bytes":glb.stat().st_size,"requires_creator_review":True},"Procedural actors and props generated; inspect geometry, rig controls and interactions before approval")
        return {"generated":True,"stage":next(item.model_dump(mode="json") for item in reviewed.stages if item.stage==StageId.ACTORS_PROPS),"glb_scene":str(glb.relative_to(folder)),"manifest":str(manifest.relative_to(folder)),"actor_count":len(request.actors),"prop_count":len(request.props),"glb_bytes":glb.stat().st_size,"requires_creator_review":True}
    app.include_router(router)
