"""Story read service for central AK3 list and detail endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from agentkit.story.models import (
    StoryDetail,
    StoryListResponse,
    StoryMetricsView,
    StoryRunView,
    StorySummary,
)
from agentkit.story.repository import StoryRepository

if TYPE_CHECKING:
    from agentkit.phase_state_store.models import FlowExecution
    from agentkit.state_backend import StoryMetricsRecord
    from agentkit.story_context_manager.models import PhaseState, StoryContext


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
        return StoryDetail(
            **summary.model_dump(mode="python"),
            labels=list(context.labels),
            participating_repos=list(context.participating_repos),
            created_at=context.created_at,
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
