"""Story read repository surface for central AK3 story queries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.backend.state_backend.store import (
    load_execution_events_global,
    load_flow_execution_global,
    load_latest_story_metrics_global,
    load_phase_state_global,
    load_story_context_global,
    load_story_contexts_global,
)

__all__ = [
    "StoryRepository",
    "load_execution_events_global",
    "load_flow_execution_global",
    "load_latest_story_metrics_global",
    "load_phase_state_global",
    "load_story_context_global",
    "load_story_contexts_global",
]

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.backend.closure.post_merge_finalization.records import StoryMetricsRecord
    from agentkit.backend.phase_state_store.models import FlowExecution
    from agentkit.backend.pipeline_engine.phase_executor import PhaseState
    from agentkit.backend.story_context_manager.models import StoryContext
    from agentkit.backend.telemetry.contract.records import ExecutionEventRecord


def _load_recent_execution_events(
    project_key: str,
    story_id: str,
    run_id: str,
    limit: int,
) -> list[ExecutionEventRecord]:
    return load_execution_events_global(
        project_key,
        story_id,
        run_id=run_id,
        limit=limit,
    )


@dataclass(frozen=True)
class StoryRepository:
    """Persistence dependencies for central story read endpoints."""

    list_story_contexts: Callable[[str], list[StoryContext]] = (
        load_story_contexts_global
    )
    load_story_context: Callable[[str, str], StoryContext | None] = (
        load_story_context_global
    )
    load_phase_state: Callable[[str], PhaseState | None] = load_phase_state_global
    load_flow_execution: Callable[[str, str], FlowExecution | None] = (
        load_flow_execution_global
    )
    load_latest_story_metrics: Callable[[str, str], StoryMetricsRecord | None] = (
        load_latest_story_metrics_global
    )
    load_recent_execution_events: Callable[
        [str, str, str, int],
        list[ExecutionEventRecord],
    ] = _load_recent_execution_events
