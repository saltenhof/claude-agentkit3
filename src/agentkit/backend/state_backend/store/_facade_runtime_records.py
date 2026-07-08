"""Pipeline runtime state, attempt, event, flow, node, and override facade operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.state_backend.store import mappers
from agentkit.backend.state_backend.store._facade_backend import _backend_module

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.phase_state_store.models import (
        FlowExecution,
        NodeExecutionLedger,
        OverrideRecord,
    )
    from agentkit.backend.pipeline_engine.phase_executor.models import (
        PhaseSnapshot,
        PhaseState,
    )
    from agentkit.backend.pipeline_engine.phase_executor.records import AttemptRecord
    from agentkit.backend.telemetry.contract.records import ExecutionEventRecord


def save_phase_state(story_dir: Path, state: PhaseState) -> None:
    row = mappers.phase_state_to_row(state)
    _backend_module().save_phase_state_row(story_dir, row)


def load_phase_state(story_dir: Path) -> PhaseState | None:
    row = _backend_module().load_phase_state_row(story_dir)
    if row is None:
        return None
    return mappers.phase_state_payload_to_record(
        str(row["payload_json"]),
        db_label=str(story_dir),
    )


def load_phase_state_global(
    story_id: str,
    store_dir: Path | None = None,
) -> PhaseState | None:
    backend = _backend_module()
    if not hasattr(backend, "load_phase_state_global_row"):
        raise RuntimeError(
            "Global phase-state reads are unsupported by the active backend",
        )
    row = backend.load_phase_state_global_row(store_dir, story_id)
    if row is None:
        return None
    return mappers.phase_state_payload_to_record(
        str(row["payload_json"]),
        db_label="postgres",
    )


def read_phase_state_record(story_dir: Path) -> PhaseState | None:
    return load_phase_state(story_dir)


def save_phase_snapshot(story_dir: Path, snapshot: PhaseSnapshot) -> None:
    row = mappers.phase_snapshot_to_row(snapshot)
    _backend_module().save_phase_snapshot_row(story_dir, row)


def load_phase_snapshot(story_dir: Path, phase: str) -> PhaseSnapshot | None:
    row = _backend_module().load_phase_snapshot_row(story_dir, phase)
    if row is None:
        return None
    return mappers.phase_snapshot_payload_to_record(
        str(row["payload_json"]),
        phase,
        db_label=str(story_dir),
    )


def read_phase_snapshot_record(
    story_dir: Path,
    phase: str,
) -> PhaseSnapshot | None:
    return load_phase_snapshot(story_dir, phase)


def save_attempt(story_dir: Path, attempt: AttemptRecord) -> None:
    row = mappers.attempt_record_to_row(attempt)
    _backend_module().save_attempt_row(story_dir, row)


def load_attempts(
    story_dir: Path,
    phase: str,
    *,
    run_id: str | None = None,
) -> list[AttemptRecord]:
    """Load AttemptRecords for a story+phase, optionally narrowed to a run.

    Fail-closed: invalid DB rows (CHECK-constraint drift, schema mismatch
    between backend and mapper, corrupt JSON payloads) propagate
    ``pydantic.ValidationError`` / ``ValueError`` to the caller. An earlier
    ``except`` silently swallowed defective rows — that masked real
    inconsistencies (cf. AG3-025 re-review finding 1).
    """

    rows = _backend_module().load_attempt_rows(story_dir, phase, run_id=run_id)
    return [mappers.attempt_row_to_record(row) for row in rows]


def append_execution_event(story_dir: Path, event: ExecutionEventRecord) -> None:
    row = mappers.execution_event_to_row(event)
    _backend_module().append_execution_event_row(story_dir, row)


def append_execution_event_global(event: ExecutionEventRecord) -> None:
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
    """Return the UNIX timestamp of the last ``governance_adjudication`` for the scope.

    Implements FK-35 §35.3.11: queries the EXACT ``(project_key, story_id,
    run_id, signal_type)`` tuple via a DB-side MAX(occurred_at) with exact
    JSON matching.  This avoids the bounded-scan + Python-max pattern that can
    miss same-signal adjudications when 200+ other-signal adjudications are newer.

    Both stores apply identical semantics (``payload_json`` is a ``TEXT``
    column in both schemas):
    - SQLite: ``json_extract(payload_json, '$.signal_type') = ?``
    - Postgres: ``(payload_json::jsonb)->>'signal_type' = ?`` (cast required
      because the ``->>`` operator does not apply to ``TEXT``).

    Neither uses LIKE (which could false-match substrings).

    Args:
        story_dir: Story directory (used by the SQLite driver; ignored by Postgres
            which derives the connection from the environment).
        project_key: Exact project scope.
        story_id: Exact story scope.
        run_id: Exact run scope.
        payload_signal_type: Exact ``signal_type`` wire value to match.

    Returns:
        UNIX float timestamp of the most-recent matching adjudication, or
        ``None`` when no such adjudication exists.
    """
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
    # occurred_at is stored as ISO-8601; parse and return as UNIX float.
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()


def save_flow_execution(story_dir: Path, record: FlowExecution) -> None:
    row = mappers.flow_execution_to_row(record)
    _backend_module().save_flow_execution_row(story_dir, row)


def load_flow_execution(story_dir: Path) -> FlowExecution | None:
    row = _backend_module().load_flow_execution_row(story_dir)
    if row is None:
        return None
    return mappers.flow_execution_row_to_record(row)


def load_flow_execution_global(
    project_key: str,
    story_id: str,
) -> FlowExecution | None:
    backend = _backend_module()
    if not hasattr(backend, "load_flow_execution_global_row"):
        raise RuntimeError(
            "Global flow-execution reads are unsupported by the active backend",
        )
    row = backend.load_flow_execution_global_row(project_key, story_id)
    if row is None:
        return None
    return mappers.flow_execution_row_to_record(row)


def save_node_execution_ledger(story_dir: Path, record: NodeExecutionLedger) -> None:
    row = mappers.node_ledger_to_row(record)
    _backend_module().save_node_execution_ledger_row(story_dir, row)


def load_node_execution_ledger(
    story_dir: Path,
    flow_id: str,
    node_id: str,
) -> NodeExecutionLedger | None:
    row = _backend_module().load_node_execution_ledger_row(story_dir, flow_id, node_id)
    if row is None:
        return None
    return mappers.node_ledger_row_to_record(row)


def save_override_record(story_dir: Path, record: OverrideRecord) -> None:
    row = mappers.override_record_to_row(record)
    _backend_module().save_override_record_row(story_dir, row)


def load_override_records(story_dir: Path) -> list[OverrideRecord]:
    rows = _backend_module().load_override_record_rows(story_dir)
    return [mappers.override_row_to_record(row) for row in rows]


__all__ = [
    "save_phase_state",
    "load_phase_state",
    "load_phase_state_global",
    "read_phase_state_record",
    "save_phase_snapshot",
    "load_phase_snapshot",
    "read_phase_snapshot_record",
    "save_attempt",
    "load_attempts",
    "append_execution_event",
    "append_execution_event_global",
    "load_execution_events",
    "load_execution_events_global",
    "load_execution_events_for_project_global",
    "load_last_adjudication_ts",
    "save_flow_execution",
    "load_flow_execution",
    "load_flow_execution_global",
    "save_node_execution_ledger",
    "load_node_execution_ledger",
    "save_override_record",
    "load_override_records",
]
