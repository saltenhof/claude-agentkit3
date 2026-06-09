"""Application-facing dashboard services for board and KPI read endpoints.

Migrated from agentkit.dashboard.service (AG3-029).
AG3-029 Pass-3: FK-64 §64.11 lifecycle_status -> column mapping introduced
(ERROR-1 fix). Local DashboardStorySummary DTO used for board columns.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING

# DRIFT-AG3-038: temporary StoryService leihe — DashboardService reads directly
# from StoryService instead of from Fact-Tables. This is a known trust-boundary
# violation (kpi-and-dashboard.C1/B1). The Fact-Table read path is implemented
# in AG3-038. This import is explicitly permitted as a time-limited transition
# exception per Story AG3-029 §AK7.
from agentkit.kpi_analytics.dashboard.models import (
    BoardColumn,
    DashboardBoardResponse,
    DashboardStoryMetricsItem,
    DashboardStoryMetricsResponse,
    DashboardStorySummary,
)
from agentkit.story import StoryService

if TYPE_CHECKING:
    from agentkit.story.models import StorySummary

logger = logging.getLogger(__name__)

# FK-64 §64.11: canonical Kanban status column labels (Title-Case).
_COL_BACKLOG = "Backlog"
_COL_APPROVED = "Approved"
_COL_IN_PROGRESS = "In Progress"
_COL_DONE = "Done"
_COL_CANCELLED = "Cancelled"

_COLUMN_ORDER: tuple[str, ...] = (
    _COL_BACKLOG,
    _COL_APPROVED,
    _COL_IN_PROGRESS,
    _COL_DONE,
    _COL_CANCELLED,
)

# FK-64 §64.11: mapping from story.lifecycle_status (lowercase) to FK-64 column label.
# Unmapped lifecycle_status values are logged as MAJOR and projected to "Cancelled".
_LIFECYCLE_TO_COLUMN: dict[str, str] = {
    "defined": _COL_BACKLOG,
    "approved": _COL_APPROVED,
    "active": _COL_IN_PROGRESS,
    "in_progress": _COL_IN_PROGRESS,
    "paused": _COL_IN_PROGRESS,
    "done": _COL_DONE,
    "completed": _COL_DONE,
    "cancelled": _COL_CANCELLED,
    "escalated": _COL_CANCELLED,
    "failed": _COL_CANCELLED,
}


def _map_lifecycle_to_column(lifecycle_status: str) -> str:
    """Map a story lifecycle_status to an FK-64 §64.11 Kanban column label.

    Args:
        lifecycle_status: Lowercase lifecycle status string from StorySummary.

    Returns:
        FK-64 column label (Title-Case). Unmapped values default to "Cancelled"
        with a WARNING log (DRIFT-AG3-038: full mapping land with Fact-Tables).
    """
    column = _LIFECYCLE_TO_COLUMN.get(lifecycle_status)
    if column is None:
        logger.warning(
            "lifecycle_status %r has no FK-64 §64.11 column mapping; "
            "defaulting to 'Cancelled'. Add mapping to _LIFECYCLE_TO_COLUMN "
            "or report to AG3-038 follow-up.",
            lifecycle_status,
        )
        return "Cancelled"
    return column


class DashboardService:
    """Build read-only dashboard payloads from central story read models.

    FK-64 §64.11 / AG3-029.
    """

    def __init__(self, *, story_service: StoryService | None = None) -> None:
        self._story_service = story_service or StoryService()

    def get_board(self, project_key: str) -> DashboardBoardResponse:
        """Return a Kanban board view for the given project.

        Stories are grouped into FK-64 §64.11 columns using the
        lifecycle_status -> column mapping (_LIFECYCLE_TO_COLUMN).
        All five FK-64 columns are always present in the response,
        even when empty (stable board layout for clients).

        Args:
            project_key: Project scope.

        Returns:
            DashboardBoardResponse with all five FK-64 columns and their stories.
        """
        raw_stories: list[StorySummary] = self._story_service.list_stories(project_key).stories
        grouped: dict[str, list[DashboardStorySummary]] = defaultdict(list)
        for story in raw_stories:
            column = _map_lifecycle_to_column(story.lifecycle_status)
            dto = DashboardStorySummary(
                story_id=story.story_id,
                title=story.title,
                story_type=str(story.story_type),
                execution_route=str(story.execution_route),
                story_size=story.story_size,
                lifecycle_status=story.lifecycle_status,
                active_phase=story.active_phase,
                phase_status=story.phase_status,
                latest_metrics=story.latest_metrics,
            )
            grouped[column].append(dto)

        # FK-64 §64.11: always emit all five columns in canonical order,
        # even when empty (stable board layout).
        columns = [
            BoardColumn(status=status, stories=grouped[status])
            for status in _COLUMN_ORDER
        ]
        return DashboardBoardResponse(project_key=project_key, columns=columns)

    def get_story_metrics(self, project_key: str) -> DashboardStoryMetricsResponse:
        """Return closure metrics for all completed stories in the project.

        Args:
            project_key: Project scope.

        Returns:
            DashboardStoryMetricsResponse sorted by completed_at descending.
        """
        stories = self._story_service.list_stories(project_key).stories
        items = [
            DashboardStoryMetricsItem(
                story_id=story.story_id,
                title=story.title,
                story_type=str(story.story_type),
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
