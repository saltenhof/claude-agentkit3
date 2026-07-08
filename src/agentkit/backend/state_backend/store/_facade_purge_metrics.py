"""Runtime residue purge and story metrics facade operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.state_backend.store import mappers
from agentkit.backend.state_backend.store._facade_backend import _backend_module

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.closure.post_merge_finalization.records import (
        StoryMetricsRecord,
    )
    from agentkit.backend.state_backend.scope import RuntimeStateScope


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


def purge_decision_records(story_dir: Path, story_id: str) -> int:
    """Delete all decision_records rows for story_id; return deleted row count.

    Canonical verify decisions (governance runtime residue, FK-53 §53.7.5) are
    keyed ``(story_id, decision_kind, attempt_nr)`` in the canonical SQLite
    schema — attempt numbering restarts per run, and ``load_latest_verify_decision``
    selects ``MAX(attempt_nr)`` story-wide (Postgres falls back story-wide), so a
    purged run's leftover decision would SHADOW the next run's verify decision in
    the Integrity Gate. Purged for the whole story.
    """

    return int(_backend_module().purge_decision_records_row(story_dir, story_id))


def purge_execution_events(story_dir: Path, project_key: str, story_id: str, run_id: str) -> int:
    """Delete execution_events rows for the run scope; return deleted row count."""

    return int(_backend_module().purge_execution_events_row(story_dir, project_key, story_id, run_id))


def purge_run_bound_artifact_envelopes(story_dir: Path, story_id: str, run_id: str) -> int:
    """Delete run-bound artifact_envelopes rows for (story_id, run_id).

    ``artifact_envelopes`` has no ``project_key`` column; every row is run-bound
    via ``run_id``. Other-run (across-run/durable) rows are left intact.
    """

    return int(_backend_module().purge_run_bound_artifact_envelopes_row(story_dir, story_id, run_id))


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


def upsert_story_metrics(story_dir: Path, metrics: StoryMetricsRecord) -> None:
    row = mappers.story_metrics_to_row(metrics)
    _backend_module().upsert_story_metrics_row(story_dir, row)


def load_story_metrics(
    story_dir: Path,
    *,
    project_key: str | None = None,
    story_id: str | None = None,
    run_id: str | None = None,
) -> list[StoryMetricsRecord]:
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
    backend = _backend_module()
    if not hasattr(backend, "load_latest_story_metrics_global_row"):
        raise RuntimeError(
            "Global story-metrics reads are unsupported by the active backend",
        )
    row = backend.load_latest_story_metrics_global_row(store_dir, project_key, story_id)
    if row is None:
        return None
    return mappers.story_metrics_row_to_record(row)


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
