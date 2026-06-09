"""Unit tests for DashboardService (migrated from tests/unit/dashboard/test_service.py).

AG3-029 Pass-3: Tests pin FK-64 §64.11-compliant behaviour after ERROR-1 fix.
- _COLUMN_ORDER uses FK-64 Title-Case values (Backlog/Approved/In Progress/Done/Cancelled).
- get_board() groups stories via _LIFECYCLE_TO_COLUMN mapping (not raw lifecycle_status).
- stories with "active" map to "In Progress", "done" maps to "Done", "failed" maps to "Cancelled".
"""

from __future__ import annotations

from datetime import UTC, datetime

from agentkit.kpi_analytics.dashboard.service import _COLUMN_ORDER, _LIFECYCLE_TO_COLUMN, DashboardService
from agentkit.story.models import StoryListResponse, StoryMetricsView, StorySummary
from agentkit.story.service import StoryService
from agentkit.story_context_manager.sizing import StorySize
from agentkit.story_context_manager.types import StoryMode, StoryType


class _FakeStoryService(StoryService):
    def list_stories(self, project_key: str) -> StoryListResponse:
        return StoryListResponse(
            project_key=project_key,
            stories=[
                StorySummary(
                    project_key=project_key,
                    story_id="AG3-100",
                    title="Implement control plane",
                    story_type=StoryType.IMPLEMENTATION,
                    execution_route=StoryMode.EXECUTION,
                    story_size=StorySize.M,
                    lifecycle_status="active",
                    active_phase="implementation",
                    phase_status="in_progress",
                ),
                StorySummary(
                    project_key=project_key,
                    story_id="AG3-101",
                    title="Stabilize telemetry",
                    story_type=StoryType.IMPLEMENTATION,
                    execution_route=StoryMode.EXECUTION,
                    story_size=StorySize.S,
                    lifecycle_status="done",
                    latest_metrics=StoryMetricsView(
                        run_id="run-101",
                        final_status="DONE",
                        processing_time_min=11.5,
                        qa_rounds=2,
                        increments=1,
                        completed_at=datetime(2026, 4, 22, 11, 0, tzinfo=UTC),
                    ),
                ),
                StorySummary(
                    project_key=project_key,
                    story_id="AG3-102",
                    title="Repair dashboard",
                    story_type=StoryType.BUGFIX,
                    execution_route=StoryMode.EXECUTION,
                    story_size=StorySize.L,
                    lifecycle_status="failed",
                ),
            ],
        )


def test_column_order_is_fk64_values() -> None:
    """_COLUMN_ORDER must contain exactly the FK-64 §64.11 values."""
    assert _COLUMN_ORDER == ("Backlog", "Approved", "In Progress", "Done", "Cancelled")


def test_lifecycle_to_column_mapping_covers_common_statuses() -> None:
    """_LIFECYCLE_TO_COLUMN covers the common lifecycle_status values."""
    assert _LIFECYCLE_TO_COLUMN["active"] == "In Progress"
    assert _LIFECYCLE_TO_COLUMN["done"] == "Done"
    assert _LIFECYCLE_TO_COLUMN["failed"] == "Cancelled"
    assert _LIFECYCLE_TO_COLUMN["defined"] == "Backlog"
    assert _LIFECYCLE_TO_COLUMN["approved"] == "Approved"


def test_get_board_groups_stories_by_fk64_column() -> None:
    """get_board() maps lifecycle_status via _LIFECYCLE_TO_COLUMN to FK-64 columns.

    "active" -> "In Progress", "done" -> "Done", "failed" -> "Cancelled".
    Pass-4 ERROR-1: all five FK-64 columns are always emitted, even when empty.
    FK-64 column order is preserved.
    """
    service = DashboardService(story_service=_FakeStoryService())

    response = service.get_board("tenant-a")

    assert response.project_key == "tenant-a"
    # All five FK-64 columns are always returned, in FK-64 order.
    column_statuses = [column.status for column in response.columns]
    assert column_statuses == ["Backlog", "Approved", "In Progress", "Done", "Cancelled"]

    # Empty columns are present but contain no stories.
    backlog = next(c for c in response.columns if c.status == "Backlog")
    assert backlog.stories == []
    approved = next(c for c in response.columns if c.status == "Approved")
    assert approved.stories == []

    # "active" -> "In Progress"
    in_progress = next(c for c in response.columns if c.status == "In Progress")
    assert [s.story_id for s in in_progress.stories] == ["AG3-100"]

    # "done" -> "Done"
    done = next(c for c in response.columns if c.status == "Done")
    assert [s.story_id for s in done.stories] == ["AG3-101"]

    # "failed" -> "Cancelled"
    cancelled = next(c for c in response.columns if c.status == "Cancelled")
    assert [s.story_id for s in cancelled.stories] == ["AG3-102"]


def test_get_board_returns_dashboard_story_summary_dtos() -> None:
    """Stories in columns are DashboardStorySummary instances (local DTO, not StorySummary)."""
    from agentkit.kpi_analytics.dashboard.models import DashboardStorySummary

    service = DashboardService(story_service=_FakeStoryService())
    response = service.get_board("tenant-a")

    for column in response.columns:
        for story in column.stories:
            assert isinstance(story, DashboardStorySummary)


def test_get_story_metrics_returns_completed_stories_only() -> None:
    service = DashboardService(story_service=_FakeStoryService())

    response = service.get_story_metrics("tenant-a")

    assert response.project_key == "tenant-a"
    assert len(response.stories) == 1
    item = response.stories[0]
    assert item.story_id == "AG3-101"
    assert item.final_status == "DONE"
    assert item.processing_time_min == 11.5
