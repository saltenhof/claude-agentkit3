"""Story read models for the central AK3 application surface."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from agentkit.backend.story_context_manager.sizing import StorySize
from agentkit.backend.story_context_manager.story_model import StorySpecification
from agentkit.backend.story_context_manager.types import (
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


class StoryEventView(BaseModel):
    """Read-only telemetry event shown on the central story detail page."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    run_id: str
    event_type: str
    occurred_at: datetime
    source_component: str
    severity: str
    phase: str | None = None
    flow_id: str | None = None
    node_id: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)


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
    lifecycle_status: str
    active_phase: str | None = None
    phase_status: str | None = None
    current_run: StoryRunView | None = None
    latest_metrics: StoryMetricsView | None = None


class StoryDetail(StorySummary):
    """Detail view for one AK3 story.

    ``specification`` closes the gap AG3-240 measured: the project-scoped detail
    route is the ONLY story detail surface the control-plane application exposes
    (bare ``/v1/stories`` paths are deliberately not delegated, ``app.py``), yet
    the story specification -- need, solution, acceptance criteria -- was
    reachable only through the undelegated route. Anything off the core that
    needs a story and its specification had to build the core story service
    locally instead, which is a distribution boundary violation by construction.

    ``None`` means the story has no specification recorded, never "not loaded":
    the read port resolves it in the same call as the context.
    """

    labels: list[str] = Field(default_factory=list)
    participating_repos: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    recent_events: list[StoryEventView] = Field(default_factory=list)
    specification: StorySpecification | None = None


class StoryListResponse(BaseModel):
    """Response envelope for project-scoped story listing."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str
    stories: list[StorySummary]
