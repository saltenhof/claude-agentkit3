"""Story read repository surface for central AK3 story queries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.state_backend import (
    load_execution_events_global,
    load_flow_execution_global,
    load_latest_story_metrics_global,
    load_phase_state_global,
    load_story_context_global,
    load_story_contexts_global,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.phase_state_store.models import FlowExecution
    from agentkit.state_backend import ExecutionEventRecord, StoryMetricsRecord
    from agentkit.story_context_manager.models import PhaseState, StoryContext


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
