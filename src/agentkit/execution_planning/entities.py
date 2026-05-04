"""Domain entities for execution planning."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StoryDependencyKind(StrEnum):
    """Typed story-dependency edge kind."""

    BLOCKS = "blocks"
    DERIVES_FROM = "derives_from"
    BRANCHES_OFF = "branches_off"


class StoryDependency(BaseModel):
    """Directed dependency edge between two stories in one project graph."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    story_id: str
    depends_on_story_id: str
    kind: StoryDependencyKind
    created_at: datetime

    @field_validator("depends_on_story_id")
    @classmethod
    def _validate_no_self_edge(cls, value: str, info: object) -> str:
        data = getattr(info, "data", {})
        if isinstance(data, dict) and data.get("story_id") == value:
            raise ValueError("story dependency must not point to itself")
        return value


class ParallelizationConfig(BaseModel):
    """Project-local practical parallelization limits."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str
    max_parallel_stories: int = Field(ge=1)
    max_parallel_stories_per_repo: int | None = Field(default=None, ge=1)


class StoryRefForPlanning(BaseModel):
    """Minimal story read model consumed by planning calculations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str
    story_id: str
    story_number: int = Field(ge=1)
    title: str
    lifecycle_status: str
    repo: str | None = None


class WaveStory(BaseModel):
    """Story projection inside a readiness wave."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    story_id: str
    story_number: int = Field(ge=1)
    title: str
    wave: int = Field(ge=0)
    is_ready: bool
    blocked_by: list[str] = Field(default_factory=list)


class ReadinessAssessment(BaseModel):
    """Deterministic answer for the next-ready planning question."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    next_ready: list[WaveStory]
    next_wave_after: list[WaveStory]
    theoretical_parallelism: int = Field(ge=0)
    practical_parallelism: int = Field(ge=0)
    reason: str
