"""Creator-authored procedural audio build route."""
from pathlib import Path
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from core.movie_pipeline.models import StageId, StageState
from core.movie_pipeline.service import PipelineStore
from core.audio_foundry.synth import generate_audio

class AudioCue(BaseModel):
    model_config=ConfigDict(extra="forbid")
    id:str=Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$")
    label:str=Field(min_length=1,max_length=80)
    kind:Literal["tone","impact","sweep","pulse","noise","alarm"]="tone"
    frequency:float=Field(default=440,ge=40,le=4000)
    duration:float=Field(default=.8,ge=.08,le=8)
    seed:int=Field(default=1,ge=0,le=2147483647)
    trigger:str=Field(default="manual",max_length=200)

class MusicSpec(BaseModel):
    model_config=ConfigDict(extra="forbid")
    mood:Literal["adventure","calm","tense","triumphant"]="adventure"
    duration:float=Field(default=24,ge=4,le=180)
    seed:int=Field(default=7,ge=0,le=2147483647)
    loop:bool=True

class AudioBuildRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")
    cues:list[AudioCue]=Field(default_factory=list,max_length=24)
    music:MusicSpec|None=None

def register_audio_routes(app,manager_provider):
    router=APIRouter()
    @router.post("/api/projects/{pid}/movie-pipeline/audio/build")
    def build_audio(pid:str,request:AudioBuildRequest):
        manager=manager_provider()
        try:
            folder=manager.path_for(pid); manager.load(pid); store=PipelineStore(folder); pipeline=store.load()
        except FileNotFoundError as exc: raise HTTPException(404,"Project or movie pipeline not found") from exc
        except ValueError as exc: raise HTTPException(400,str(exc)) from exc
        stage=next(item for item in pipeline.stages if item.stage==StageId.AUDIO)
        if stage.state!=StageState.READY:
            raise HTTPException(409,"Approve the actors and props stage before generating audio")
        if not request.cues and request.music is None:
            raise HTTPException(400,"Add at least one sound cue or a background music track")
        ids=[cue.id for cue in request.cues]
        if len(ids)!=len(set(ids)): raise HTTPException(400,"Audio cue IDs must be unique")
        output_dir=store.folder/"audio"/f"revision-{stage.revision}"
        stage.state=StageState.RUNNING; stage.summary="Synthesizing original WAV sound effects and music from creator-authored specifications"; store.save(pipeline)
        try:
            manifest=generate_audio(output_dir,[cue.model_dump() for cue in request.cues],request.music.model_dump() if request.music else None)
            files=[output_dir/item["file"] for item in manifest["effects"]]
            if manifest["music"]: files.append(output_dir/manifest["music"]["file"])
            if not files or any(not item.is_file() or item.stat().st_size<44 for item in files):
                raise RuntimeError("Audio synthesis did not produce valid WAV files")
            relative=lambda p:str(p.relative_to(folder))
            output={"manifest":relative(output_dir/"audio-manifest.json"),"effects":[{**item,"asset":relative(output_dir/item["file"])} for item in manifest["effects"]],"music":({**manifest["music"],"asset":relative(output_dir/manifest["music"]["file"])} if manifest["music"] else None),"requires_creator_review":True}
            reviewed=store.mark_review(StageId.AUDIO,output,"Original procedural audio generated; listen to every cue and music loop before approval")
        except Exception as exc:
            current=store.load(); record=next(item for item in current.stages if item.stage==StageId.AUDIO)
            record.state=StageState.FAILED; record.error=str(exc)[:2000]; record.summary="Audio generation failed"; store.save(current)
            raise HTTPException(500,"Audio generation failed: "+str(exc)) from exc
        return {"generated":True,"stage":next(item.model_dump(mode="json") for item in reviewed.stages if item.stage==StageId.AUDIO),"effects_count":len(manifest["effects"]),"music_generated":bool(manifest["music"]),"sample_rate":manifest["sample_rate"],"requires_creator_review":True}
    app.include_router(router)
