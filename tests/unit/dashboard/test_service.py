from __future__ import annotations

from datetime import UTC, datetime

from agentkit.dashboard.service import DashboardService
from agentkit.story.models import StoryListResponse, StoryMetricsView, StorySummary
from agentkit.story_context_manager.sizing import StorySize
from agentkit.story_context_manager.types import StoryMode, StoryType


class _FakeStoryService:
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
                    story_size=StorySize.MEDIUM,
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
                    story_size=StorySize.SMALL,
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
                    story_size=StorySize.LARGE,
                    lifecycle_status="blocked",
                ),
            ],
        )


def test_get_board_groups_stories_by_lifecycle_status() -> None:
    service = DashboardService(story_service=_FakeStoryService())

    response = service.get_board("tenant-a")

    assert response.project_key == "tenant-a"
    assert [column.status for column in response.columns] == [
        "active",
        "blocked",
        "done",
    ]
    assert [story.story_id for story in response.columns[0].stories] == ["AG3-100"]
    assert [story.story_id for story in response.columns[1].stories] == ["AG3-102"]
    assert [story.story_id for story in response.columns[2].stories] == ["AG3-101"]


def test_get_story_metrics_returns_completed_stories_only() -> None:
    service = DashboardService(story_service=_FakeStoryService())

    response = service.get_story_metrics("tenant-a")

    assert response.project_key == "tenant-a"
    assert len(response.stories) == 1
    item = response.stories[0]
    assert item.story_id == "AG3-101"
    assert item.final_status == "DONE"
    assert item.processing_time_min == 11.5
