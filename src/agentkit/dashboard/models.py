"""Read models for the central AK3 dashboard surface."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from agentkit.story.models import StorySummary
from agentkit.story_context_manager.sizing import StorySize
from agentkit.story_context_manager.types import StoryType


class BoardColumn(BaseModel):
    """One status column in the project-scoped story board view."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: str
    stories: list[StorySummary]


class DashboardBoardResponse(BaseModel):
    """Board or list-style dashboard view for one project."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str
    columns: list[BoardColumn]


class DashboardStoryMetricsItem(BaseModel):
    """Dashboard-facing summary of one completed story outcome."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    story_id: str
    title: str
    story_type: StoryType
    story_size: StorySize
    final_status: str
    processing_time_min: float
    qa_rounds: int
    increments: int
    completed_at: datetime


class DashboardStoryMetricsResponse(BaseModel):
    """Read-only closure metrics list for one project."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str
    stories: list[DashboardStoryMetricsItem]
