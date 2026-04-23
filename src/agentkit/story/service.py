"""Story read service for central AK3 list and detail endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from agentkit.story.models import (
    StoryDetail,
    StoryEventView,
    StoryListResponse,
    StoryMetricsView,
    StoryRunView,
    StorySummary,
)
from agentkit.story.repository import StoryRepository

if TYPE_CHECKING:
    from agentkit.phase_state_store.models import FlowExecution
    from agentkit.state_backend import ExecutionEventRecord, StoryMetricsRecord
    from agentkit.story_context_manager.models import PhaseState, StoryContext

_RECENT_EVENT_LIMIT = 25


class StoryService:
    """Build application-facing story list and detail payloads."""

    def __init__(self, *, repository: StoryRepository | None = None) -> None:
        self._repo = repository or StoryRepository()

    def list_stories(self, project_key: str) -> StoryListResponse:
        contexts = self._repo.list_story_contexts(project_key)
        stories = [self._build_summary(context) for context in contexts]
        return StoryListResponse(project_key=project_key, stories=stories)

    def get_story(self, project_key: str, story_id: str) -> StoryDetail | None:
        context = self._repo.load_story_context(project_key, story_id)
        if context is None:
            return None

        summary = self._build_summary(context)
        detail_run_id = _detail_run_id(
            current_run=summary.current_run,
            latest_metrics=summary.latest_metrics,
        )
        return StoryDetail(
            **summary.model_dump(mode="python"),
            labels=list(context.labels),
            participating_repos=list(context.participating_repos),
            created_at=context.created_at,
            recent_events=_story_event_views(
                self._load_recent_events(
                    project_key=context.project_key,
                    story_id=context.story_id,
                    run_id=detail_run_id,
                ),
            ),
        )

    def _build_summary(self, context: StoryContext) -> StorySummary:
        phase_state = self._repo.load_phase_state(context.story_id)
        flow = self._repo.load_flow_execution(context.project_key, context.story_id)
        metrics = self._repo.load_latest_story_metrics(
            context.project_key,
            context.story_id,
        )
        current_run = _story_run_view(flow)
        latest_metrics = _story_metrics_view(metrics)
        return StorySummary(
            project_key=context.project_key,
            story_id=context.story_id,
            title=context.title,
            story_type=context.story_type,
            execution_route=context.execution_route,
            implementation_contract=context.implementation_contract,
            story_size=context.story_size,
            issue_nr=context.issue_nr,
            lifecycle_status=_derive_lifecycle_status(
                phase_state=phase_state,
                flow=flow,
                metrics=metrics,
            ),
            active_phase=phase_state.phase if phase_state is not None else None,
            phase_status=(
                phase_state.status.value
                if phase_state is not None
                else None
            ),
            current_run=current_run,
            latest_metrics=latest_metrics,
        )

    def _load_recent_events(
        self,
        *,
        project_key: str,
        story_id: str,
        run_id: str | None,
    ) -> list[ExecutionEventRecord]:
        if run_id is None:
            return []
        return self._repo.load_recent_execution_events(
            project_key,
            story_id,
            run_id,
            _RECENT_EVENT_LIMIT,
        )


def _story_run_view(flow: FlowExecution | None) -> StoryRunView | None:
    if flow is None:
        return None
    return StoryRunView(
        run_id=flow.run_id,
        flow_id=flow.flow_id,
        status=flow.status,
        attempt_no=flow.attempt_no,
        started_at=flow.started_at,
        finished_at=flow.finished_at,
    )


def _story_metrics_view(metrics: StoryMetricsRecord | None) -> StoryMetricsView | None:
    if metrics is None:
        return None
    return StoryMetricsView(
        run_id=metrics.run_id,
        final_status=metrics.final_status,
        processing_time_min=metrics.processing_time_min,
        qa_rounds=metrics.qa_rounds,
        increments=metrics.increments,
        completed_at=datetime.fromisoformat(metrics.completed_at),
    )


def _detail_run_id(
    *,
    current_run: StoryRunView | None,
    latest_metrics: StoryMetricsView | None,
) -> str | None:
    if current_run is not None:
        return current_run.run_id
    if latest_metrics is not None:
        return latest_metrics.run_id
    return None


def _story_event_views(
    events: list[ExecutionEventRecord],
) -> list[StoryEventView]:
    return [
        StoryEventView(
            event_id=event.event_id,
            run_id=event.run_id,
            event_type=event.event_type,
            occurred_at=event.occurred_at,
            source_component=event.source_component,
            severity=event.severity,
            phase=event.phase,
            flow_id=event.flow_id,
            node_id=event.node_id,
            payload=dict(event.payload),
        )
        for event in reversed(events)
    ]


def _derive_lifecycle_status(
    *,
    phase_state: PhaseState | None,
    flow: FlowExecution | None,
    metrics: StoryMetricsRecord | None,
) -> str:
    if flow is not None and flow.finished_at is None:
        return "active"
    if phase_state is not None and phase_state.status.value in {
        "in_progress",
        "paused",
        "blocked",
        "failed",
        "escalated",
    }:
        return phase_state.status.value
    if metrics is not None:
        return metrics.final_status.lower()
    if phase_state is not None:
        return phase_state.status.value
    return "defined"
