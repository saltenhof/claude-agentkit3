"""Application-facing dashboard services for board and KPI read endpoints."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from agentkit.dashboard.models import (
    BoardColumn,
    DashboardBoardResponse,
    DashboardStoryMetricsItem,
    DashboardStoryMetricsResponse,
)
from agentkit.story import StoryService

if TYPE_CHECKING:
    from agentkit.story.models import StorySummary

_COLUMN_ORDER = (
    "defined",
    "approved",
    "in_progress",
    "active",
    "paused",
    "blocked",
    "failed",
    "escalated",
    "done",
    "cancelled",
)


class DashboardService:
    """Build read-only dashboard payloads from central story read models."""

    def __init__(self, *, story_service: StoryService | None = None) -> None:
        self._story_service = story_service or StoryService()

    def get_board(self, project_key: str) -> DashboardBoardResponse:
        stories = self._story_service.list_stories(project_key).stories
        grouped: dict[str, list[StorySummary]] = defaultdict(list)
        for story in stories:
            grouped[story.lifecycle_status].append(story)

        ordered_statuses = [
            status for status in _COLUMN_ORDER if grouped.get(status)
        ] + sorted(status for status in grouped if status not in _COLUMN_ORDER)
        columns = [
            BoardColumn(status=status, stories=grouped[status])
            for status in ordered_statuses
        ]
        return DashboardBoardResponse(project_key=project_key, columns=columns)

    def get_story_metrics(self, project_key: str) -> DashboardStoryMetricsResponse:
        stories = self._story_service.list_stories(project_key).stories
        items = [
            DashboardStoryMetricsItem(
                story_id=story.story_id,
                title=story.title,
                story_type=story.story_type,
                story_size=story.story_size,
                final_status=story.latest_metrics.final_status,
                processing_time_min=story.latest_metrics.processing_time_min,
                qa_rounds=story.latest_metrics.qa_rounds,
                increments=story.latest_metrics.increments,
                completed_at=story.latest_metrics.completed_at,
            )
            for story in stories
            if story.latest_metrics is not None
        ]
        items.sort(key=lambda item: item.completed_at, reverse=True)
        return DashboardStoryMetricsResponse(project_key=project_key, stories=items)
