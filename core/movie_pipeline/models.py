from datetime import datetime, timezone
from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field

class StageId(StrEnum):
    ANALYSIS = "analysis"
    PLAYER = "player"
    ENVIRONMENT = "environment"
    ACTORS_PROPS = "actors_props"
    AUDIO = "audio"
    GAMEPLAY = "gameplay"
    ASSEMBLY = "assembly"

STAGE_ORDER = list(StageId)

class StageState(StrEnum):
    LOCKED = "LOCKED"
    READY = "READY"
    RUNNING = "RUNNING"
    REVIEW = "REVIEW"
    APPROVED = "APPROVED"
    FAILED = "FAILED"

class RightsDeclaration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    has_video_rights: bool
    has_photo_rights: bool
    likeness_consent: bool
    accepts_original_assets_only: bool

class StageRecord(BaseModel):
    stage: StageId
    state: StageState = StageState.LOCKED
    revision: int = 0
    progress: int = Field(default=0, ge=0, le=100)
    summary: str = "Waiting for prerequisite stage approval"
    output: dict = Field(default_factory=dict)
    error: str | None = None
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class PipelineDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = "1.0"
    project_id: str
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    rights: RightsDeclaration
    source_photo: dict | None = None
    source_video: dict | None = None
    stages: list[StageRecord]
    active_stage: StageId = StageId.ANALYSIS

class PipelineCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rights: RightsDeclaration

class StageDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str = Field(default="", max_length=2000)

def new_pipeline(project_id: str, rights: RightsDeclaration) -> PipelineDocument:
    stages = [StageRecord(stage=stage, state=StageState.READY if index == 0 else StageState.LOCKED,
                          summary="Ready for local processing" if index == 0 else "Waiting for previous stage approval")
              for index, stage in enumerate(STAGE_ORDER)]
    return PipelineDocument(project_id=project_id, rights=rights, stages=stages)
