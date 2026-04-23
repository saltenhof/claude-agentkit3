from __future__ import annotations

from datetime import UTC, datetime

from agentkit.phase_state_store.models import FlowExecution
from agentkit.state_backend.records import ExecutionEventRecord, StoryMetricsRecord
from agentkit.story.repository import StoryRepository
from agentkit.story.service import StoryService
from agentkit.story_context_manager.models import PhaseState, PhaseStatus, StoryContext
from agentkit.story_context_manager.types import (
    ImplementationContract,
    StoryMode,
    StoryType,
)


def _context(story_id: str) -> StoryContext:
    return StoryContext(
        project_key="tenant-a",
        story_id=story_id,
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        implementation_contract=ImplementationContract.STANDARD,
        issue_nr=12,
        title=f"Story {story_id}",
        labels=["size:medium"],
        participating_repos=["app"],
        created_at=datetime(2026, 4, 22, 10, 0, tzinfo=UTC),
    )


def _event(
    story_id: str,
    run_id: str,
    event_id: str,
    minute: int,
) -> ExecutionEventRecord:
    return ExecutionEventRecord(
        project_key="tenant-a",
        story_id=story_id,
        run_id=run_id,
        event_id=event_id,
        event_type="node_result",
        occurred_at=datetime(2026, 4, 22, 10, minute, tzinfo=UTC),
        source_component="pipeline-engine",
        severity="info",
        phase="implementation",
        flow_id="implementation",
        node_id=f"node-{minute}",
        payload={"minute": minute},
    )


def test_list_stories_builds_project_scoped_read_model() -> None:
    context = _context("AG3-100")
    service = StoryService(
        repository=StoryRepository(
            list_story_contexts=lambda project_key: [context],
            load_story_context=lambda project_key, story_id: context,
            load_phase_state=lambda story_id: PhaseState(
                story_id=story_id,
                phase="implementation",
                status=PhaseStatus.IN_PROGRESS,
            ),
            load_flow_execution=lambda project_key, story_id: FlowExecution(
                project_key=project_key,
                story_id=story_id,
                run_id="run-100",
                flow_id="implementation",
                level="story",
                owner="pipeline_engine",
                status="RUNNING",
                attempt_no=2,
                started_at=datetime(2026, 4, 22, 10, 5, tzinfo=UTC),
            ),
            load_latest_story_metrics=lambda project_key, story_id: None,
        ),
    )

    response = service.list_stories("tenant-a")

    assert response.project_key == "tenant-a"
    assert len(response.stories) == 1
    story = response.stories[0]
    assert story.story_id == "AG3-100"
    assert story.lifecycle_status == "active"
    assert story.phase_status == "in_progress"
    assert story.current_run is not None
    assert story.current_run.run_id == "run-100"


def test_get_story_returns_detail_with_latest_metrics() -> None:
    context = _context("AG3-101")
    metrics = StoryMetricsRecord(
        project_key="tenant-a",
        story_id="AG3-101",
        run_id="run-101",
        story_type="implementation",
        story_size="medium",
        mode="execution",
        processing_time_min=18.5,
        qa_rounds=2,
        increments=3,
        final_status="DONE",
        completed_at="2026-04-22T11:30:00+00:00",
    )
    service = StoryService(
        repository=StoryRepository(
            list_story_contexts=lambda project_key: [context],
            load_story_context=lambda project_key, story_id: context,
            load_phase_state=lambda story_id: PhaseState(
                story_id=story_id,
                phase="closure",
                status=PhaseStatus.COMPLETED,
            ),
            load_flow_execution=lambda project_key, story_id: FlowExecution(
                project_key=project_key,
                story_id=story_id,
                run_id="run-101",
                flow_id="implementation",
                level="story",
                owner="pipeline_engine",
                status="COMPLETED",
                attempt_no=1,
                started_at=datetime(2026, 4, 22, 10, 0, tzinfo=UTC),
                finished_at=datetime(2026, 4, 22, 11, 30, tzinfo=UTC),
            ),
            load_latest_story_metrics=lambda project_key, story_id: metrics,
            load_recent_execution_events=lambda project_key, story_id, run_id, limit: [
                _event("AG3-101", "run-101", "evt-001", 10),
                _event("AG3-101", "run-101", "evt-002", 15),
            ],
        ),
    )

    detail = service.get_story("tenant-a", "AG3-101")

    assert detail is not None
    assert detail.story_id == "AG3-101"
    assert detail.labels == ["size:medium"]
    assert detail.participating_repos == ["app"]
    assert detail.latest_metrics is not None
    assert detail.latest_metrics.final_status == "DONE"
    assert detail.lifecycle_status == "done"
    assert [event.event_id for event in detail.recent_events] == [
        "evt-002",
        "evt-001",
    ]
    assert detail.recent_events[0].payload == {"minute": 15}


def test_get_story_uses_metrics_run_when_no_current_run_exists() -> None:
    context = _context("AG3-102")
    metrics = StoryMetricsRecord(
        project_key="tenant-a",
        story_id="AG3-102",
        run_id="run-102",
        story_type="implementation",
        story_size="medium",
        mode="execution",
        processing_time_min=9.0,
        qa_rounds=1,
        increments=1,
        final_status="DONE",
        completed_at="2026-04-22T09:30:00+00:00",
    )
    seen: list[tuple[str, str, str, int]] = []
    service = StoryService(
        repository=StoryRepository(
            list_story_contexts=lambda project_key: [context],
            load_story_context=lambda project_key, story_id: context,
            load_phase_state=lambda story_id: None,
            load_flow_execution=lambda project_key, story_id: None,
            load_latest_story_metrics=lambda project_key, story_id: metrics,
            load_recent_execution_events=lambda project_key, story_id, run_id, limit: (
                seen.append((project_key, story_id, run_id, limit)) or []
            ),
        ),
    )

    detail = service.get_story("tenant-a", "AG3-102")

    assert detail is not None
    assert seen == [("tenant-a", "AG3-102", "run-102", 25)]


def test_get_story_returns_none_when_missing() -> None:
    service = StoryService(
        repository=StoryRepository(
            list_story_contexts=lambda project_key: [],
            load_story_context=lambda project_key, story_id: None,
            load_phase_state=lambda story_id: None,
            load_flow_execution=lambda project_key, story_id: None,
            load_latest_story_metrics=lambda project_key, story_id: None,
            load_recent_execution_events=(
                lambda project_key, story_id, run_id, limit: []
            ),
        ),
    )

    assert service.get_story("tenant-a", "AG3-404") is None
