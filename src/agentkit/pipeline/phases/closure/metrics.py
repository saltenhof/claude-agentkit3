"""Closure-time story metrics materialization."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.exceptions import CorruptStateError
from agentkit.state_backend import (
    StoryMetricsRecord,
    load_attempts,
    load_execution_events,
    resolve_runtime_scope,
)
from agentkit.telemetry.events import EventType

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.story_context_manager.models import StoryContext


def build_story_metrics_record(
    story_dir: Path,
    ctx: StoryContext,
    *,
    completed_at: datetime,
    final_status: str,
) -> StoryMetricsRecord:
    """Build the required FK-16 story metrics from canonical runtime sources."""

    scope = resolve_runtime_scope(story_dir)
    if scope.story_id != ctx.story_id:
        raise CorruptStateError(
            "Cannot build story metrics for mismatched runtime scope",
            detail={
                "story_dir": str(story_dir),
                "scope_story_id": scope.story_id,
                "context_story_id": ctx.story_id,
            },
        )
    if scope.run_id is None:
        raise CorruptStateError(
            "Cannot build story metrics without a canonical run_id",
            detail={
                "story_dir": str(story_dir),
                "project_key": scope.project_key,
                "story_id": ctx.story_id,
            },
        )
    project_key = scope.project_key
    run_id = scope.run_id
    agent_start = _first_event_timestamp(
        story_dir,
        project_key=project_key,
        story_id=ctx.story_id,
        run_id=run_id,
        event_type=EventType.AGENT_START.value,
        error_message="Cannot build story metrics without a canonical agent_start",
    )
    duration_seconds = max(
        0.0,
        (completed_at - agent_start.astimezone(UTC)).total_seconds(),
    )
    processing_time_min = round(duration_seconds / 60.0, 2)

    qa_rounds = len(load_attempts(story_dir, "verify"))
    increments = len(
        load_execution_events(
            story_dir,
            project_key=project_key,
            story_id=ctx.story_id,
            run_id=run_id,
            event_type=EventType.INCREMENT_COMMIT.value,
        ),
    )

    return StoryMetricsRecord(
        project_key=project_key,
        story_id=ctx.story_id,
        run_id=run_id,
        story_type=ctx.story_type.value,
        story_size=ctx.story_size.value,
        mode=ctx.execution_route.value,
        processing_time_min=processing_time_min,
        qa_rounds=qa_rounds,
        increments=increments,
        final_status=final_status,
        completed_at=completed_at.isoformat(),
    )


def _first_event_timestamp(
    story_dir: Path,
    *,
    project_key: str,
    story_id: str,
    run_id: str,
    event_type: str,
    error_message: str,
) -> datetime:
    events = load_execution_events(
        story_dir,
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
        event_type=event_type,
    )
    if not events:
        raise CorruptStateError(
            error_message,
            detail={
                "story_dir": str(story_dir),
                "project_key": project_key,
                "story_id": story_id,
                "run_id": run_id,
                "event_type": event_type,
            },
        )
    return min(event.occurred_at for event in events)
