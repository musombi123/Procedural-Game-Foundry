"""Creator-authored game narrative contract; deliberately no generative model dependency."""
from __future__ import annotations
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Literal

class StoryBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["story", "movie", "guided"] = "guided"
    title: str = Field(default="Untitled Game", min_length=1, max_length=120)
    premise: str = Field(default="", max_length=12000)
    player_role: str = Field(default="Player", max_length=120)
    setting: str = Field(default="", max_length=4000)
    tone: str = Field(default="creator-defined", max_length=120)
    instructions: str = Field(default="", max_length=12000)
    ending: str = Field(default="", max_length=4000)
    mission_count: int = Field(default=5, ge=1, le=20)
    world_scale: Literal["small", "medium", "large"] = "medium"

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A game title is required")
        return value

    @field_validator("premise", "setting", "instructions", "ending")
    @classmethod
    def trim_text(cls, value: str) -> str:
        return value.strip()

    def as_manifest(self) -> dict:
        """Persist the creator's words verbatim; do not hallucinate missing plot details."""
        return {"schema_version": "1.0", "source": "creator", **self.model_dump(),
                "player": {"identity_source": "uploaded_portrait", "role": self.player_role,
                           "is_player_avatar": True},
                "missions": [{"id": f"mission-{i+1}", "title": f"Mission {i+1}",
                              "objective": "Creator-defined objective pending"} for i in range(self.mission_count)],
                "approval_required": True}
