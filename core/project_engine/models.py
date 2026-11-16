from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
import re

class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    genre: Literal["science-fiction","fantasy","modern","survival","adventure"] = "science-fiction"
    dimension: Literal["2d","3d"] = "3d"
    seed: int = Field(default=784215, ge=0, le=4294967295)
    description: str = Field(default="", max_length=2000)

class WorldDefinition(BaseModel):
    width: int = Field(default=96, ge=16, le=512)
    depth: int = Field(default=96, ge=16, le=512)
    resolution: int = Field(default=48, ge=8, le=256)
    amplitude: float = Field(default=9.0, ge=0, le=100)
    frequency: float = Field(default=0.055, gt=0.001, le=1)
    biomes: list[str] = Field(default_factory=lambda: ["rocky-desert","alien-forest"])
    weather: bool = True

class GameplayDefinition(BaseModel):
    camera: Literal["first-person","third-person","top-down"] = "third-person"
    controller: Literal["exploration","survival"] = "survival"
    combat: bool = False
    inventory: bool = True
    missions: bool = True
    save_system: bool = True

class ExportDefinition(BaseModel):
    windows: bool = True
    linux: bool = True
    web: bool = False
    android: bool = False

class ProjectDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["pgf-project"] = "pgf-project"
    version: str = "1.0"
    id: str
    project: ProjectCreate
    world: WorldDefinition = Field(default_factory=WorldDefinition)
    gameplay: GameplayDefinition = Field(default_factory=GameplayDefinition)
    export: ExportDefinition = Field(default_factory=ExportDefinition)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

def safe_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+","-",value.lower()).strip("-")[:48] or "untitled"
