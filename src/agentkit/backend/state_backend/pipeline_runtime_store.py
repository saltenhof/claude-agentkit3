"""Pipeline runtime-record persistence store."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.state_backend.runtime_scope_resolver import (
    resolve_runtime_scope as resolve_runtime_scope,
)
from agentkit.backend.state_backend.state_backend_connection_manager import (
    _backend_module,
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
    """Persist one canonical phase-state record."""
    from agentkit.backend.state_backend.store import mappers

    row = mappers.phase_state_to_row(state)
    _backend_module().save_phase_state_row(story_dir, row)


def load_phase_state(story_dir: Path) -> PhaseState | None:
    """Load one canonical phase-state record."""
    from agentkit.backend.state_backend.store import mappers

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
    """Load one global canonical phase-state record."""
    from agentkit.backend.state_backend.store import mappers

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
    """Compatibility alias for ``load_phase_state``."""
    return load_phase_state(story_dir)


def save_phase_snapshot(story_dir: Path, snapshot: PhaseSnapshot) -> None:
    """Persist one phase snapshot."""
    from agentkit.backend.state_backend.store import mappers

    row = mappers.phase_snapshot_to_row(snapshot)
    _backend_module().save_phase_snapshot_row(story_dir, row)


def load_phase_snapshot(story_dir: Path, phase: str) -> PhaseSnapshot | None:
    """Load one phase snapshot."""
    from agentkit.backend.state_backend.store import mappers

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
    """Compatibility alias for ``load_phase_snapshot``."""
    return load_phase_snapshot(story_dir, phase)


def save_attempt(story_dir: Path, attempt: AttemptRecord) -> None:
    """Persist one phase attempt record."""
    from agentkit.backend.state_backend.store import mappers

    row = mappers.attempt_record_to_row(attempt)
    _backend_module().save_attempt_row(story_dir, row)


def load_attempts(
    story_dir: Path,
    phase: str,
    *,
    run_id: str | None = None,
) -> list[AttemptRecord]:
    """Load phase-attempt records for a story and phase."""
    from agentkit.backend.state_backend.store import mappers

    rows = _backend_module().load_attempt_rows(story_dir, phase, run_id=run_id)
    return [mappers.attempt_row_to_record(row) for row in rows]


def save_flow_execution(story_dir: Path, record: FlowExecution) -> None:
    """Persist one flow-execution runtime record."""
    from agentkit.backend.state_backend.store import mappers

    row = mappers.flow_execution_to_row(record)
    _backend_module().save_flow_execution_row(story_dir, row)


def load_flow_execution(story_dir: Path) -> FlowExecution | None:
    """Load one flow-execution runtime record."""
    from agentkit.backend.state_backend.store import mappers

    row = _backend_module().load_flow_execution_row(story_dir)
    if row is None:
        return None
    return mappers.flow_execution_row_to_record(row)


def load_flow_execution_global(
    project_key: str,
    story_id: str,
) -> FlowExecution | None:
    """Load one global flow-execution runtime record."""
    from agentkit.backend.state_backend.store import mappers

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
    """Persist one node-execution ledger record."""
    from agentkit.backend.state_backend.store import mappers

    row = mappers.node_ledger_to_row(record)
    _backend_module().save_node_execution_ledger_row(story_dir, row)


def load_node_execution_ledger(
    story_dir: Path,
    flow_id: str,
    node_id: str,
) -> NodeExecutionLedger | None:
    """Load one node-execution ledger record."""
    from agentkit.backend.state_backend.store import mappers

    row = _backend_module().load_node_execution_ledger_row(story_dir, flow_id, node_id)
    if row is None:
        return None
    return mappers.node_ledger_row_to_record(row)


def save_override_record(story_dir: Path, record: OverrideRecord) -> None:
    """Persist one runtime override record."""
    from agentkit.backend.state_backend.store import mappers

    row = mappers.override_record_to_row(record)
    _backend_module().save_override_record_row(story_dir, row)


def load_override_records(story_dir: Path) -> list[OverrideRecord]:
    """Load runtime override records for one story."""
    from agentkit.backend.state_backend.store import mappers

    rows = _backend_module().load_override_record_rows(story_dir)
    return [mappers.override_row_to_record(row) for row in rows]


def backend_has_valid_phase_state(story_dir: Path) -> bool:
    """Return whether the story has a readable canonical phase state."""
    return load_phase_state(story_dir) is not None


def backend_has_completed_snapshot(story_dir: Path, phase: str) -> bool:
    """Return whether the story has a completed snapshot for ``phase``."""
    from agentkit.backend.state_backend.store import mappers

    snapshot = load_phase_snapshot(story_dir, phase)
    return snapshot is not None and mappers.phase_snapshot_completed(snapshot)


def purge_flow_executions(
    story_dir: Path,
    project_key: str,
    story_id: str,
    run_id: str,
) -> int:
    """Delete flow-execution rows for the run scope."""
    return int(
        _backend_module().purge_flow_executions_row(
            story_dir,
            project_key,
            story_id,
            run_id,
        )
    )


def purge_node_execution_ledgers(
    story_dir: Path,
    project_key: str,
    story_id: str,
    run_id: str,
) -> int:
    """Delete node-execution ledger rows for the run scope."""
    return int(
        _backend_module().purge_node_execution_ledgers_row(
            story_dir,
            project_key,
            story_id,
            run_id,
        )
    )


def purge_attempts(story_dir: Path, story_id: str, run_id: str) -> int:
    """Delete attempt rows for ``story_id`` and ``run_id``."""
    return int(_backend_module().purge_attempts_row(story_dir, story_id, run_id))


def purge_override_records(
    story_dir: Path,
    project_key: str,
    story_id: str,
    run_id: str,
) -> int:
    """Delete override records for the run scope."""
    return int(
        _backend_module().purge_override_records_row(
            story_dir,
            project_key,
            story_id,
            run_id,
        )
    )


def purge_phase_states(story_dir: Path, story_id: str) -> int:
    """Delete the canonical phase-state row for ``story_id``."""
    return int(_backend_module().purge_phase_states_row(story_dir, story_id))


def purge_phase_snapshots(story_dir: Path, story_id: str) -> int:
    """Delete all phase snapshots for ``story_id``."""
    return int(_backend_module().purge_phase_snapshots_row(story_dir, story_id))


def count_runtime_execution_residue(
    story_dir: Path,
    project_key: str,
    story_id: str,
    run_id: str,
) -> dict[str, int]:
    """Return remaining runtime-execution rows per table for the run scope."""
    return dict(
        _backend_module().count_runtime_execution_residue_row(
            story_dir,
            project_key,
            story_id,
            run_id,
        )
    )


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
    "save_flow_execution",
    "load_flow_execution",
    "load_flow_execution_global",
    "save_node_execution_ledger",
    "load_node_execution_ledger",
    "save_override_record",
    "load_override_records",
    "resolve_runtime_scope",
    "backend_has_valid_phase_state",
    "backend_has_completed_snapshot",
    "purge_flow_executions",
    "purge_node_execution_ledgers",
    "purge_attempts",
    "purge_override_records",
    "purge_phase_states",
    "purge_phase_snapshots",
    "count_runtime_execution_residue",
]
