"""Pipeline runtime state, attempt, event, flow, node, and override facade operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.state_backend.store import mappers
from agentkit.backend.state_backend.store._facade_backend import _backend_module
from agentkit.backend.state_backend.telemetry_event_store import (
    append_execution_event as append_execution_event,
)
from agentkit.backend.state_backend.telemetry_event_store import (
    append_execution_event_global as append_execution_event_global,
)
from agentkit.backend.state_backend.telemetry_event_store import (
    load_execution_events as load_execution_events,
)
from agentkit.backend.state_backend.telemetry_event_store import (
    load_execution_events_for_project_global as load_execution_events_for_project_global,
)
from agentkit.backend.state_backend.telemetry_event_store import (
    load_execution_events_global as load_execution_events_global,
)
from agentkit.backend.state_backend.telemetry_event_store import (
    load_last_adjudication_ts as load_last_adjudication_ts,
)

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
