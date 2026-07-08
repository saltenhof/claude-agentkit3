"""Telemetry event and projection persistence store."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.state_backend.state_backend_connection_manager import (
    _backend_module,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.closure.post_merge_finalization.records import (
        StoryMetricsRecord,
    )
    from agentkit.backend.state_backend.scope import RuntimeStateScope
    from agentkit.backend.telemetry.contract.records import ExecutionEventRecord
    from agentkit.backend.verify_system.stage_registry.records import (
        QAFindingRecord,
        QAStageResultRecord,
    )


def append_execution_event(story_dir: Path, event: ExecutionEventRecord) -> None:
    """Append one local execution event."""
    from agentkit.backend.state_backend.store import mappers

    row = mappers.execution_event_to_row(event)
    _backend_module().append_execution_event_row(story_dir, row)


def append_execution_event_global(event: ExecutionEventRecord) -> None:
    """Append one global execution event."""
    from agentkit.backend.state_backend.store import mappers

    backend = _backend_module()
    if not hasattr(backend, "append_execution_event_global_row"):
        raise RuntimeError(
            "Global execution-event append is unsupported by the active backend",
        )
    row = mappers.execution_event_to_row(event)
    backend.append_execution_event_global_row(row)


def load_execution_events(
    story_dir: Path,
    *,
    project_key: str | None = None,
    story_id: str | None = None,
    run_id: str | None = None,
    event_type: str | None = None,
    limit: int | None = None,
) -> list[ExecutionEventRecord]:
    """Load local execution events with optional filters."""
    from agentkit.backend.state_backend.store import mappers

    rows = _backend_module().load_execution_event_rows(
        story_dir,
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
        event_type=event_type,
        limit=limit,
    )
    return [mappers.execution_event_row_to_record(row) for row in rows]


def load_execution_events_global(
    project_key: str,
    story_id: str,
    *,
    run_id: str | None = None,
    event_type: str | None = None,
    limit: int | None = None,
) -> list[ExecutionEventRecord]:
    """Load global execution events for one story."""
    from agentkit.backend.state_backend.store import mappers

    backend = _backend_module()
    if not hasattr(backend, "load_execution_event_rows_global"):
        raise RuntimeError(
            "Global execution-event reads are unsupported by the active backend",
        )
    rows = backend.load_execution_event_rows_global(
        project_key,
        story_id,
        run_id=run_id,
        event_type=event_type,
        limit=limit,
    )
    return [mappers.execution_event_row_to_record(row) for row in rows]


def load_execution_events_for_project_global(
    project_key: str,
    *,
    limit: int | None = None,
) -> list[ExecutionEventRecord]:
    """Load global execution events for one project."""
    from agentkit.backend.state_backend.store import mappers

    backend = _backend_module()
    if not hasattr(backend, "load_execution_event_rows_for_project_global"):
        raise RuntimeError(
            "Global project execution-event reads are unsupported by the active backend",
        )
    rows = backend.load_execution_event_rows_for_project_global(
        project_key,
        limit=limit,
    )
    return [mappers.execution_event_row_to_record(row) for row in rows]


def load_last_adjudication_ts(
    story_dir: Path,
    *,
    project_key: str,
    story_id: str,
    run_id: str,
    payload_signal_type: str,
) -> float | None:
    """Return the UNIX timestamp of the last matching governance adjudication."""
    from datetime import UTC, datetime

    raw = _backend_module().max_adjudication_occurred_at(
        story_dir,
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
        payload_signal_type=payload_signal_type,
    )
    if raw is None:
        return None
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()


def purge_execution_events(
    story_dir: Path,
    project_key: str,
    story_id: str,
    run_id: str,
) -> int:
    """Delete execution-event rows for the run scope."""
    return int(
        _backend_module().purge_execution_events_row(
            story_dir,
            project_key,
            story_id,
            run_id,
        )
    )


def upsert_story_metrics(story_dir: Path, metrics: StoryMetricsRecord) -> None:
    """Upsert one story-metrics projection record."""
    from agentkit.backend.state_backend.store import mappers

    row = mappers.story_metrics_to_row(metrics)
    _backend_module().upsert_story_metrics_row(story_dir, row)


def load_story_metrics(
    story_dir: Path,
    *,
    project_key: str | None = None,
    story_id: str | None = None,
    run_id: str | None = None,
) -> list[StoryMetricsRecord]:
    """Load story-metrics projection records with optional filters."""
    from agentkit.backend.state_backend.store import mappers

    rows = _backend_module().load_story_metrics_rows(
        story_dir,
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
    )
    return [mappers.story_metrics_row_to_record(row) for row in rows]


def load_story_metrics_for_scope(
    scope: RuntimeStateScope,
) -> list[StoryMetricsRecord]:
    """Load story-metrics projection records for an explicit runtime scope."""
    return load_story_metrics(
        scope.story_dir,
        project_key=scope.project_key,
        story_id=scope.story_id,
        run_id=scope.run_id,
    )


def load_latest_story_metrics_global(
    project_key: str,
    story_id: str,
    store_dir: Path | None = None,
) -> StoryMetricsRecord | None:
    """Load the latest global story-metrics projection for one story."""
    from agentkit.backend.state_backend.store import mappers

    backend = _backend_module()
    if not hasattr(backend, "load_latest_story_metrics_global_row"):
        raise RuntimeError(
            "Global story-metrics reads are unsupported by the active backend",
        )
    row = backend.load_latest_story_metrics_global_row(store_dir, project_key, story_id)
    if row is None:
        return None
    return mappers.story_metrics_row_to_record(row)


def load_qa_stage_results(
    story_dir: Path,
    *,
    project_key: str | None = None,
    story_id: str | None = None,
    run_id: str | None = None,
    attempt_no: int | None = None,
    stage_id: str | None = None,
) -> list[QAStageResultRecord]:
    """Load QA stage-result projection rows with optional filters."""
    from agentkit.backend.state_backend.store import mappers

    rows = _backend_module().load_qa_stage_result_rows(
        story_dir,
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
        attempt_no=attempt_no,
        stage_id=stage_id,
    )
    return [mappers.qa_stage_result_row_to_record(row) for row in rows]


def load_qa_stage_results_for_scope(
    scope: RuntimeStateScope,
    *,
    attempt_no: int | None = None,
    stage_id: str | None = None,
) -> list[QAStageResultRecord]:
    """Load QA stage-result projection rows for an explicit runtime scope."""
    return load_qa_stage_results(
        scope.story_dir,
        project_key=scope.project_key,
        story_id=scope.story_id,
        run_id=scope.run_id,
        attempt_no=attempt_no,
        stage_id=stage_id,
    )


def load_qa_findings(
    story_dir: Path,
    *,
    project_key: str | None = None,
    story_id: str | None = None,
    run_id: str | None = None,
    attempt_no: int | None = None,
    stage_id: str | None = None,
) -> list[QAFindingRecord]:
    """Load QA finding projection rows with optional filters."""
    from agentkit.backend.state_backend.store import mappers

    rows = _backend_module().load_qa_finding_rows(
        story_dir,
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
        attempt_no=attempt_no,
        stage_id=stage_id,
    )
    return [mappers.qa_finding_row_to_record(row) for row in rows]


def load_qa_findings_for_scope(
    scope: RuntimeStateScope,
    *,
    attempt_no: int | None = None,
    stage_id: str | None = None,
) -> list[QAFindingRecord]:
    """Load QA finding projection rows for an explicit runtime scope."""
    return load_qa_findings(
        scope.story_dir,
        project_key=scope.project_key,
        story_id=scope.story_id,
        run_id=scope.run_id,
        attempt_no=attempt_no,
        stage_id=stage_id,
    )


__all__ = [
    "append_execution_event",
    "append_execution_event_global",
    "load_execution_events",
    "load_execution_events_global",
    "load_execution_events_for_project_global",
    "load_last_adjudication_ts",
    "purge_execution_events",
    "upsert_story_metrics",
    "load_story_metrics",
    "load_story_metrics_for_scope",
    "load_latest_story_metrics_global",
    "load_qa_stage_results",
    "load_qa_stage_results_for_scope",
    "load_qa_findings",
    "load_qa_findings_for_scope",
]
