"""Story read models for the central AK3 application surface."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from agentkit.story_context_manager.sizing import StorySize
from agentkit.story_context_manager.types import (
    ImplementationContract,
    StoryMode,
    StoryType,
)


class StoryRunView(BaseModel):
    """Read-only summary of the current or latest known story run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    flow_id: str
    status: str
    attempt_no: int
    started_at: datetime
    finished_at: datetime | None = None


class StoryMetricsView(BaseModel):
    """Read-only closure metrics summary for one completed story run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    final_status: str
    processing_time_min: float
    qa_rounds: int
    increments: int
    completed_at: datetime


class StorySummary(BaseModel):
    """List-view summary for one AK3 story."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str
    story_id: str
    title: str
    story_type: StoryType
    execution_route: StoryMode
    implementation_contract: ImplementationContract | None = None
    story_size: StorySize
    issue_nr: int | None = None
    lifecycle_status: str
    active_phase: str | None = None
    phase_status: str | None = None
    current_run: StoryRunView | None = None
    latest_metrics: StoryMetricsView | None = None


class StoryDetail(StorySummary):
    """Detail view for one AK3 story."""

    labels: list[str] = Field(default_factory=list)
    participating_repos: list[str] = Field(default_factory=list)
    created_at: datetime | None = None


class StoryListResponse(BaseModel):
    """Response envelope for project-scoped story listing."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str
    stories: list[StorySummary]

