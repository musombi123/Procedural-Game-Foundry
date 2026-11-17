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
    camera: Literal["first-person","third-person","top-down"] = "first-person"
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

class SceneObject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["outpost","beacon","tree","rock","crate"]
    x: float = Field(ge=-512, le=512)
    y: float = Field(default=0, ge=-100, le=100)
    z: float = Field(ge=-512, le=512)
    rotation: float = Field(default=0, ge=-360, le=360)
    scale: float = Field(default=1, ge=0.25, le=4)
    color: str = Field(default="#8ba7c7", pattern=r"^#[0-9A-Fa-f]{6}$")
    asset_path: str | None = Field(default=None, pattern=r"^res://assets/[A-Za-z0-9_-]+\.glb$")

class TerrainEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    operation: Literal["raise", "lower", "smooth"]
    x: float = Field(ge=-512, le=512)
    z: float = Field(ge=-512, le=512)
    radius: float = Field(default=6.0, ge=0.5, le=40)
    strength: float = Field(default=2.0, ge=0.05, le=12)


class WorldDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seed: int = Field(ge=0, le=4294967295)
    world: WorldDefinition = Field(default_factory=WorldDefinition)
    objects: list[SceneObject] = Field(default_factory=list, max_length=500)
    terrain_edits: list[TerrainEdit] = Field(default_factory=list, max_length=1000)
    sun_angle: float = Field(default=-28, ge=-180, le=180)
    fog: bool = True
    water_level: float = Field(default=-1.5, ge=-20, le=20)

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
