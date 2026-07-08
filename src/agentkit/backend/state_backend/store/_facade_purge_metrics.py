"""Runtime residue purge and story metrics facade operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.state_backend.artifact_catalog_store import (
    purge_run_bound_artifact_envelopes as purge_run_bound_artifact_envelopes,
)
from agentkit.backend.state_backend.store._facade_backend import _backend_module
from agentkit.backend.state_backend.telemetry_event_store import (
    load_latest_story_metrics_global as load_latest_story_metrics_global,
)
from agentkit.backend.state_backend.telemetry_event_store import (
    load_story_metrics as load_story_metrics,
)
from agentkit.backend.state_backend.telemetry_event_store import (
    load_story_metrics_for_scope as load_story_metrics_for_scope,
)
from agentkit.backend.state_backend.telemetry_event_store import (
    purge_execution_events as purge_execution_events,
)
from agentkit.backend.state_backend.telemetry_event_store import (
    upsert_story_metrics as upsert_story_metrics,
)
from agentkit.backend.state_backend.verify_artifact_store import (
    purge_decision_records as purge_decision_records,
)

if TYPE_CHECKING:
    from pathlib import Path



def purge_flow_executions(story_dir: Path, project_key: str, story_id: str, run_id: str) -> int:
    """Delete flow_executions rows for the run scope; return deleted row count."""

    return int(_backend_module().purge_flow_executions_row(story_dir, project_key, story_id, run_id))


def purge_node_execution_ledgers(story_dir: Path, project_key: str, story_id: str, run_id: str) -> int:
    """Delete node_execution_ledgers rows for the run scope; return row count."""

    return int(_backend_module().purge_node_execution_ledgers_row(story_dir, project_key, story_id, run_id))


def purge_attempts(story_dir: Path, story_id: str, run_id: str) -> int:
    """Delete attempts rows for (story_id, run_id); return deleted row count.

    The ``attempts`` table has no ``project_key`` column; project scope is
    validated at the coordinating port, not implied here.
    """

    return int(_backend_module().purge_attempts_row(story_dir, story_id, run_id))


def purge_override_records(story_dir: Path, project_key: str, story_id: str, run_id: str) -> int:
    """Delete override_records rows for the run scope; return deleted row count."""

    return int(_backend_module().purge_override_records_row(story_dir, project_key, story_id, run_id))


def purge_guard_decisions(story_dir: Path, project_key: str, story_id: str, run_id: str) -> int:
    """Delete guard_decisions rows for the run scope; return deleted row count."""

    return int(_backend_module().purge_guard_decisions_row(story_dir, project_key, story_id, run_id))


def purge_phase_states(story_dir: Path, story_id: str) -> int:
    """Delete the canonical phase_states row for story_id; return row count.

    Purges the canonical runtime PhaseState (keyed by ``story_id`` only), NOT the
    FK-39 read-model ``phase_state_projection`` (out of scope).
    """

    return int(_backend_module().purge_phase_states_row(story_dir, story_id))


def purge_phase_snapshots(story_dir: Path, story_id: str) -> int:
    """Delete all phase_snapshots rows for story_id; return deleted row count.

    Completed-phase snapshots are runtime PhaseState evidence keyed by
    ``(story_id, phase)`` — no ``run_id`` column. They feed guard/gate decisions
    story-keyed (``backend_has_completed_snapshot`` -> Integrity-Gate Dim 2), so
    a purged run's leftover snapshot would influence a later restart/guard
    decision (FK-53 §53.7.5 rule). Purged for the whole story.
    """

    return int(_backend_module().purge_phase_snapshots_row(story_dir, story_id))


def count_runtime_execution_residue(story_dir: Path, project_key: str, story_id: str, run_id: str) -> dict[str, int]:
    """Return remaining Runtime-Execution rows per table for the run scope.

    Building block for the Runtime-Residue verify (FK-53 §53.7.5 / §53.10
    fragment); a non-zero count for any table means residue survived a purge.

    Fail-closed scoping: the residue COUNT is deliberately ``project_key``-
    agnostic (run-bound tables are counted by ``(story_id, run_id)``, the
    story-keyed tables by ``story_id``). The destructive purge keeps its narrow
    ``project_key`` predicate; a mis-scoped purge call (wrong-but-non-empty
    ``project_key``) therefore shows up HERE as residue instead of both sides
    sharing the same blind spot. ``project_key`` stays validated at the port.
    """

    return dict(_backend_module().count_runtime_execution_residue_row(story_dir, project_key, story_id, run_id))


__all__ = [
    "purge_flow_executions",
    "purge_node_execution_ledgers",
    "purge_attempts",
    "purge_override_records",
    "purge_guard_decisions",
    "purge_phase_states",
    "purge_phase_snapshots",
    "purge_decision_records",
    "purge_execution_events",
    "purge_run_bound_artifact_envelopes",
    "count_runtime_execution_residue",
    "upsert_story_metrics",
    "load_story_metrics",
    "load_story_metrics_for_scope",
    "load_latest_story_metrics_global",
]
