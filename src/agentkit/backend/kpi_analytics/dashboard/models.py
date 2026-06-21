"""Read models for the central AK3 dashboard surface.

Migrated from agentkit.dashboard.models (AG3-029).
AG3-029 Pass-3: local DashboardStorySummary DTO introduced to avoid
importing agentkit.backend.story.models / story_context_manager outside
dashboard.service (ERROR-2 fix). The DRIFT-AG3-038 import exception
applies only to dashboard.service, not to models.py.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from agentkit.backend.core_types.story import StorySize


class DashboardStorySummary(BaseModel):
    """Local read-only DTO for one story in the board/metrics view.

    Contains only the fields the dashboard actually reads. Avoids
    importing agentkit.backend.story.models.StorySummary in this module
    (the DRIFT-AG3-038 StoryService import is confined to service.py).

    FK-64 §64.11 / AG3-029 §2.1.5.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    story_id: str
    title: str
    story_type: str
    execution_route: str
    story_size: StorySize
    lifecycle_status: str
    active_phase: str | None = None
    phase_status: str | None = None
    latest_metrics: object | None = None  # StoryMetricsView; kept as object to avoid cross-BC import


class BoardColumn(BaseModel):
    """One status column in the project-scoped story board view.

    FK-64 §64.11 (Kanban status columns).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: str
    stories: list[DashboardStorySummary]


class DashboardBoardResponse(BaseModel):
    """Board or list-style dashboard view for one project.

    FK-64 §64.11.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str
    columns: list[BoardColumn]


class DashboardStoryMetricsItem(BaseModel):
    """Dashboard-facing summary of one completed story outcome.

    FK-60 §60.4 / FK-64.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    story_id: str
    title: str
    story_type: str
    story_size: StorySize
    final_status: str
    processing_time_min: float
    qa_rounds: int
    increments: int
    completed_at: datetime


class DashboardStoryMetricsResponse(BaseModel):
    """Read-only closure metrics list for one project.

    FK-60 §60.4.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str
    stories: list[DashboardStoryMetricsItem]
