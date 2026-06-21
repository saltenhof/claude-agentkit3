"""Application-facing dashboard services for board and KPI read endpoints.

Migrated from agentkit.dashboard.service (AG3-029).
AG3-029 Pass-3: FK-64 §64.11 lifecycle_status -> column mapping introduced
(ERROR-1 fix). Local DashboardStorySummary DTO used for board columns.
AG3-084: DRIFT-AG3-038 resolved for the KPI/story-metrics read path —
get_story_metrics now reads from FactStore (fact_story) instead of StoryService.
The get_board live/Kanban path retains StoryService (different granularity:
active stories vs. completed fact_story rows).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING

from agentkit.backend.kpi_analytics.dashboard.models import (
    BoardColumn,
    DashboardBoardResponse,
    DashboardStoryMetricsItem,
    DashboardStoryMetricsResponse,
    DashboardStorySummary,
)
from agentkit.backend.kpi_analytics.errors import AnalyticsNotConfiguredError
from agentkit.backend.story import StoryService

if TYPE_CHECKING:
    from agentkit.backend.kpi_analytics.fact_store import FactStore
    from agentkit.backend.kpi_analytics.fact_store.models import PeriodFilter
    from agentkit.backend.story.models import StorySummary

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

    Args:
        story_service: Live story read service for the board/Kanban view
            (active stories only).  Defaults to a bare ``StoryService``.
        fact_store: Analytics fact store for the KPI/story-metrics read path
            (completed stories from ``fact_story``).  When ``None``,
            ``get_story_metrics`` raises ``AnalyticsNotConfiguredError``
            (fail-closed — the HTTP layer maps this to 503).
    """

    def __init__(
        self,
        *,
        story_service: StoryService | None = None,
        fact_store: FactStore | None = None,
    ) -> None:
        self._story_service = story_service or StoryService()
        self._fact_store = fact_store

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

    def get_story_metrics(
        self,
        project_key: str,
        period: PeriodFilter | None = None,
    ) -> DashboardStoryMetricsResponse:
        """Return closure metrics for completed stories read from fact_story (AG3-084).

        DRIFT-AG3-038 resolved: this path reads exclusively from the analytics
        ``fact_story`` table via ``FactStore`` — no ``StoryService`` borrowing.
        The ``get_board`` live/Kanban path (active stories) continues to use
        ``StoryService`` as a separate concern.

        Reset/validity rule (FK-63 §63.3.1): only already-cleaned facts are
        read.  No late-query compensation for reset/corrupt-discarded runs.
        Upstream purge (AG3-071/081/082) ensures deleted rows are absent.

        Args:
            project_key: Project scope.
            period: Optional half-open ``[start, end)`` window.  When ``None``,
                all completed stories for the project are returned.

        Returns:
            ``DashboardStoryMetricsResponse`` sorted by ``completed_at``
            descending.

        Raises:
            AnalyticsNotConfiguredError: When ``fact_store`` is not configured
                (fail-closed — the HTTP layer maps this to 503).
        """
        if self._fact_store is None:
            raise AnalyticsNotConfiguredError(
                "get_story_metrics requires FactStore; "
                "wire a FactStore into DashboardService or ensure the "
                "composition root provides one (AG3-084)."
            )

        fact_stories = self._fact_store.list_fact_stories(project_key, period)
        items: list[DashboardStoryMetricsItem] = []
        for fact in fact_stories:
            if fact.closed_at is None:
                continue
            items.append(
                DashboardStoryMetricsItem(
                    story_id=fact.story_id,
                    title=fact.story_id,  # fact_story has no title column; story_id used as display key
                    story_type=fact.story_type,
                    story_size=fact.story_size,  # str coerces to StorySize (StrEnum)
                    final_status=fact.final_status or "UNKNOWN",
                    processing_time_min=round(
                        (fact.processing_time_ms or 0) / 60_000.0, 2
                    ),
                    qa_rounds=fact.qa_round_count,
                    increments=fact.increment_count,
                    completed_at=fact.closed_at,
                )
            )
        items.sort(key=lambda item: item.completed_at, reverse=True)
        return DashboardStoryMetricsResponse(project_key=project_key, stories=items)
