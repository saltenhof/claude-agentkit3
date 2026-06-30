"""Unit tests for DashboardService.

AG3-029 Pass-3: Tests pin FK-64 §64.11-compliant behaviour after ERROR-1 fix.
- _COLUMN_ORDER uses FK-64 Title-Case values (Backlog/Approved/In Progress/Done/Cancelled).
- get_board() groups stories via _LIFECYCLE_TO_COLUMN mapping (not raw lifecycle_status).
- stories with "active" map to "In Progress", "done" maps to "Done", "failed" maps to "Cancelled".

AG3-084: get_story_metrics reads from FactStore (DRIFT-AG3-038 resolved).
- get_board() path unchanged (StoryService, live active stories).
- get_story_metrics() reads fact_story via FactStore.
"""

from __future__ import annotations

from datetime import UTC, datetime

from tests.story_read_port_stub import StubStoryReadPort

from agentkit.backend.kpi_analytics.dashboard.service import (
    _COLUMN_ORDER,
    _LIFECYCLE_TO_COLUMN,
    DashboardService,
    _map_lifecycle_to_column,
)
from agentkit.backend.kpi_analytics.fact_store.models import FactStory
from agentkit.backend.story.models import StoryListResponse, StorySummary
from agentkit.backend.story.service import StoryService
from agentkit.backend.story_context_manager.sizing import StorySize
from agentkit.backend.story_context_manager.types import StoryMode, StoryType


class _FakeStoryService(StoryService):
    def __init__(self) -> None:
        super().__init__(repository=StubStoryReadPort())

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


class _FakeFactStore:
    """Minimal FactStore double for DashboardService.get_story_metrics tests."""

    def __init__(self, stories: list[FactStory]) -> None:
        self._stories = stories

    def list_fact_stories(
        self, project_key: str, period: object = None
    ) -> list[FactStory]:
        return [s for s in self._stories if s.project_key == project_key]


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


def test_unmapped_lifecycle_status_defaults_to_cancelled() -> None:
    """Unknown lifecycle_status values default to the Cancelled column."""
    assert _map_lifecycle_to_column("blocked") == "Cancelled"


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
    from agentkit.backend.kpi_analytics.dashboard.models import DashboardStorySummary

    service = DashboardService(story_service=_FakeStoryService())
    response = service.get_board("tenant-a")

    for column in response.columns:
        for story in column.stories:
            assert isinstance(story, DashboardStorySummary)


def test_get_story_metrics_no_fact_store_raises() -> None:
    """AG3-084 finding #6 fix: get_story_metrics without FactStore raises AnalyticsNotConfiguredError.

    Fail-closed: a missing FactStore must NOT silently return an empty response.
    The HTTP layer maps AnalyticsNotConfiguredError to 503.
    """
    import pytest as _pytest

    from agentkit.backend.kpi_analytics.errors import AnalyticsNotConfiguredError

    service = DashboardService(story_service=_FakeStoryService(), fact_store=None)

    with _pytest.raises(AnalyticsNotConfiguredError):
        service.get_story_metrics("tenant-a")


def test_get_story_metrics_reads_from_fact_store_not_story_service() -> None:
    """AG3-084 AC3 DRIFT-fix: get_story_metrics reads from FactStore (not StoryService).

    Asserts that when FactStore has a completed fact_story row, it appears in
    the response — and StoryService is NOT consulted (the FakeStoryService
    has no metrics view, yet the result comes from FactStore).
    """
    completed_story = FactStory(
        project_key="tenant-a",
        story_id="AG3-101",
        story_type="implementation",
        story_size="S",
        opened_at=datetime(2026, 4, 22, 9, 0, tzinfo=UTC),
        closed_at=datetime(2026, 4, 22, 11, 0, tzinfo=UTC),
        qa_round_count=2,
        final_status="DONE",
        are_gate_passed=True,
        computed_at=datetime(2026, 4, 22, 11, 0, tzinfo=UTC),
    )
    fact_store = _FakeFactStore([completed_story])
    service = DashboardService(story_service=_FakeStoryService(), fact_store=fact_store)

    response = service.get_story_metrics("tenant-a")

    assert response.project_key == "tenant-a"
    assert len(response.stories) == 1
    item = response.stories[0]
    assert item.story_id == "AG3-101"


def test_get_story_metrics_no_story_service_call_when_fact_store_present() -> None:
    """AG3-084 DRIFT-fix: get_story_metrics does NOT call StoryService.list_stories.

    Uses a spy StoryService that raises if called, ensuring the KPI path is
    fully decoupled from StoryService.
    """

    class _SpyStoryService(StoryService):
        def __init__(self) -> None:
            super().__init__(repository=StubStoryReadPort())

        def list_stories(self, project_key: str) -> StoryListResponse:
            raise AssertionError(
                "get_story_metrics MUST NOT call StoryService.list_stories "
                "(DRIFT-AG3-038 trust-boundary violation)"
            )

    fact_store = _FakeFactStore([])
    service = DashboardService(story_service=_SpyStoryService(), fact_store=fact_store)

    # Must not raise: fact_store path is used, StoryService is never called.
    response = service.get_story_metrics("tenant-a")
    assert response.stories == []


def test_get_board_still_uses_story_service() -> None:
    """AG3-084 AC3 regression: get_board (live Kanban) still reads from StoryService.

    The get_board path retains StoryService — it reads active stories, which
    fact_story (completed-only) cannot supply.
    """
    service = DashboardService(story_service=_FakeStoryService())

    # get_board works normally via StoryService (no fact_store required).
    response = service.get_board("tenant-a")

    assert response.project_key == "tenant-a"
    # All five FK-64 columns are always returned.
    column_statuses = [column.status for column in response.columns]
    assert column_statuses == ["Backlog", "Approved", "In Progress", "Done", "Cancelled"]
    # "active" -> "In Progress"
    in_progress = next(c for c in response.columns if c.status == "In Progress")
    assert [s.story_id for s in in_progress.stories] == ["AG3-100"]
