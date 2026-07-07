"""SQLite runtime-execution purge and residue helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._connection import _connect

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

#
#   §53.6.2 entity              real table                purge key columns
#   --------------------------  -----------------------   ------------------------
#   FlowExecution               flow_executions           project_key,story_id,run_id
#   NodeExecution(Ledger)       node_execution_ledgers    project_key,story_id,run_id
#   AttemptRecord               attempts                  story_id,run_id  (no project_key col)
#   OverrideRecord              override_records          project_key,story_id,run_id
#   GuardDecision               guard_decisions           project_key,story_id,run_id
#   VerifyDecision (governance) decision_records          story_id  (no run_id col; second-QA closure)
#   canonical PhaseState        phase_states              story_id  (no project_key/run_id col)
#   PhaseState snapshot         phase_snapshots           story_id  (no run_id col; second-QA closure)
#   ExecutionEvent              execution_events          project_key,story_id,run_id
#   run-bound ArtifactRecord    artifact_envelopes        story_id,run_id  (no project_key col)
#
# NEVER reference phantom tables ``attempt_records`` / ``node_executions`` /
# ``artifact_records``. The read-model ``phase_state_projection`` is OUT OF SCOPE
# (already purged via projection_repositories.py:purge_run).
#
# All purge helpers are idempotent (FK-53 §53.9.1): delete-if-present, count zero
# when already gone, hard-fail only on real infra/permission errors (the open
# connection propagates those). They use ``?`` placeholders so the identical SQL
# runs on Postgres via ``postgres_store._CompatConnection`` (``?`` -> ``%s``).


def purge_flow_executions_row(
    story_dir: Path,
    project_key: str,
    story_id: str,
    run_id: str,
) -> int:
    """Delete flow_executions rows for (project_key, story_id, run_id)."""

    with _connect(story_dir) as conn:
        cursor = conn.execute(
            "DELETE FROM flow_executions WHERE project_key = ? AND story_id = ? AND run_id = ?",
            (project_key, story_id, run_id),
        )
        return int(cursor.rowcount)


def purge_node_execution_ledgers_row(
    story_dir: Path,
    project_key: str,
    story_id: str,
    run_id: str,
) -> int:
    """Delete node_execution_ledgers rows for (project_key, story_id, run_id)."""

    with _connect(story_dir) as conn:
        cursor = conn.execute(
            "DELETE FROM node_execution_ledgers WHERE project_key = ? AND story_id = ? AND run_id = ?",
            (project_key, story_id, run_id),
        )
        return int(cursor.rowcount)


def purge_attempts_row(
    story_dir: Path,
    story_id: str,
    run_id: str,
) -> int:
    """Delete attempts rows for (story_id, run_id).

    The ``attempts`` table has no ``project_key`` column (PK is
    ``(story_id, run_id, phase, attempt)``); the project scope is validated at
    the coordinating port, not implied as a column.
    """

    with _connect(story_dir) as conn:
        cursor = conn.execute(
            "DELETE FROM attempts WHERE story_id = ? AND run_id = ?",
            (story_id, run_id),
        )
        return int(cursor.rowcount)


def purge_override_records_row(
    story_dir: Path,
    project_key: str,
    story_id: str,
    run_id: str,
) -> int:
    """Delete override_records rows for (project_key, story_id, run_id)."""

    with _connect(story_dir) as conn:
        cursor = conn.execute(
            "DELETE FROM override_records WHERE project_key = ? AND story_id = ? AND run_id = ?",
            (project_key, story_id, run_id),
        )
        return int(cursor.rowcount)


def purge_guard_decisions_row(
    story_dir: Path,
    project_key: str,
    story_id: str,
    run_id: str,
) -> int:
    """Delete guard_decisions rows for (project_key, story_id, run_id)."""

    with _connect(story_dir) as conn:
        cursor = conn.execute(
            "DELETE FROM guard_decisions WHERE project_key = ? AND story_id = ? AND run_id = ?",
            (project_key, story_id, run_id),
        )
        return int(cursor.rowcount)


def purge_phase_states_row(
    story_dir: Path,
    story_id: str,
) -> int:
    """Delete the canonical phase_states row for story_id.

    The canonical ``phase_states`` table is keyed by ``story_id`` only (one
    runtime PhaseState per story); it carries no ``run_id``/``project_key``
    column. This purges the canonical runtime PhaseState, NOT the FK-39 read-model
    ``phase_state_projection`` (out of scope; already has its own purge).
    """

    with _connect(story_dir) as conn:
        cursor = conn.execute(
            "DELETE FROM phase_states WHERE story_id = ?",
            (story_id,),
        )
        return int(cursor.rowcount)


def purge_phase_snapshots_row(
    story_dir: Path,
    story_id: str,
) -> int:
    """Delete all phase_snapshots rows for story_id (every phase).

    ``phase_snapshots`` is keyed ``(story_id, phase)`` and carries no
    ``run_id``/``project_key`` column. Completed-phase snapshots are runtime
    PhaseState evidence read story-keyed by guard/gate paths
    (``backend_has_completed_snapshot`` -> Integrity-Gate Dim 2), so a purged
    run's leftover snapshot would influence a later restart/guard decision
    (FK-53 §53.7.5 rule). Second-QA closure of the §53.6.2 PhaseState mapping.
    """

    with _connect(story_dir) as conn:
        cursor = conn.execute(
            "DELETE FROM phase_snapshots WHERE story_id = ?",
            (story_id,),
        )
        return int(cursor.rowcount)


def purge_decision_records_row(
    story_dir: Path,
    story_id: str,
) -> int:
    """Delete all decision_records rows for story_id (every kind/attempt).

    ``decision_records`` is keyed ``(story_id, decision_kind, attempt_nr)``; it
    has no ``run_id`` column and attempt numbering restarts per run.
    ``load_latest_verify_decision`` selects ``MAX(attempt_nr)`` story-wide, so a
    purged run's leftover verify decision would SHADOW the next run's decision in
    the Integrity Gate (governance runtime residue, FK-53 §53.7.5 rule).
    Second-QA closure addition.
    """

    with _connect(story_dir) as conn:
        cursor = conn.execute(
            "DELETE FROM decision_records WHERE story_id = ?",
            (story_id,),
        )
        return int(cursor.rowcount)


def purge_execution_events_row(
    story_dir: Path,
    project_key: str,
    story_id: str,
    run_id: str,
) -> int:
    """Delete execution_events rows for (project_key, story_id, run_id)."""

    with _connect(story_dir) as conn:
        cursor = conn.execute(
            "DELETE FROM execution_events WHERE project_key = ? AND story_id = ? AND run_id = ?",
            (project_key, story_id, run_id),
        )
        return int(cursor.rowcount)


def purge_run_bound_artifact_envelopes_row(
    story_dir: Path,
    story_id: str,
    run_id: str,
) -> int:
    """Delete run-bound artifact_envelopes rows for (story_id, run_id).

    ``artifact_envelopes`` has no ``project_key`` column; every row is bound to a
    ``run_id`` (PK ``(story_id, run_id, stage, attempt, artifact_class,
    producer_name)``). A reset starts a NEW run with a NEW ``run_id``, so deleting
    all rows for the OLD ``(story_id, run_id)`` removes exactly the run-bound
    artefacts and leaves any other-run (durable across-run) rows untouched.
    """

    with _connect(story_dir) as conn:
        cursor = conn.execute(
            "DELETE FROM artifact_envelopes WHERE story_id = ? AND run_id = ?",
            (story_id, run_id),
        )
        return int(cursor.rowcount)


def count_runtime_execution_residue_row(
    story_dir: Path,
    project_key: str,
    story_id: str,
    run_id: str,
) -> dict[str, int]:
    """Count remaining Runtime-Execution rows per table for the run scope.

    Returns a ``table -> remaining row count`` map. Used by the Runtime-Residue
    probe (FK-53 §53.7.5 / §53.10 building block) to fail closed when any
    runtime-execution object survives a purge.

    The COUNT predicates are deliberately ``project_key``-agnostic (run-bound
    tables by ``(story_id, run_id)``, story-keyed tables by ``story_id``): the
    destructive purge keeps its narrow ``project_key`` predicate, so a
    mis-scoped purge (wrong-but-non-empty ``project_key``) surfaces HERE as
    residue instead of purge and probe sharing one blind spot. ``project_key``
    stays validated (non-empty) at the coordinating port.
    """

    # Residue counting is run-/story-scoped by design — see docstring.
    del project_key
    with _connect(story_dir) as conn:
        return _count_runtime_execution_residue(conn, story_id, run_id)


def _count_runtime_execution_residue(
    conn: sqlite3.Connection,
    story_id: str,
    run_id: str,
) -> dict[str, int]:
    def _count(sql: str, params: tuple[object, ...]) -> int:
        row = conn.execute(sql, params).fetchone()
        return int(row[0]) if row is not None else 0

    sr = (story_id, run_id)
    s = (story_id,)
    return {
        "flow_executions": _count(
            "SELECT COUNT(*) FROM flow_executions WHERE story_id = ? AND run_id = ?",
            sr,
        ),
        "node_execution_ledgers": _count(
            "SELECT COUNT(*) FROM node_execution_ledgers WHERE story_id = ? AND run_id = ?",
            sr,
        ),
        "attempts": _count(
            "SELECT COUNT(*) FROM attempts WHERE story_id = ? AND run_id = ?",
            sr,
        ),
        "override_records": _count(
            "SELECT COUNT(*) FROM override_records WHERE story_id = ? AND run_id = ?",
            sr,
        ),
        "guard_decisions": _count(
            "SELECT COUNT(*) FROM guard_decisions WHERE story_id = ? AND run_id = ?",
            sr,
        ),
        "decision_records": _count(
            "SELECT COUNT(*) FROM decision_records WHERE story_id = ?",
            s,
        ),
        "phase_states": _count(
            "SELECT COUNT(*) FROM phase_states WHERE story_id = ?",
            s,
        ),
        "phase_snapshots": _count(
            "SELECT COUNT(*) FROM phase_snapshots WHERE story_id = ?",
            s,
        ),
        "execution_events": _count(
            "SELECT COUNT(*) FROM execution_events WHERE story_id = ? AND run_id = ?",
            sr,
        ),
        "artifact_envelopes": _count(
            "SELECT COUNT(*) FROM artifact_envelopes WHERE story_id = ? AND run_id = ?",
            sr,
        ),
    }
