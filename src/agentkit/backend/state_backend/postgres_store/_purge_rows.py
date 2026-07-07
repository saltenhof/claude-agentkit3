"""Runtime execution residue reads and purge row operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._connection import (
    _connect,
)
from ._constants import _PROJECT_KEY_FILTER, _RUN_ID_FILTER, _STORY_ID_FILTER
from ._runtime_rows import load_phase_state_row
from ._story_project_rows import load_story_context_row

if TYPE_CHECKING:
    from pathlib import Path

    from ._compat import _CompatConnection


def load_qa_stage_result_rows(
    story_dir: Path,
    *,
    project_key: str | None = None,
    story_id: str | None = None,
    run_id: str | None = None,
    attempt_no: int | None = None,
    stage_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return QA stage result row dicts matching the given filters."""

    clauses: list[str] = []
    params: list[object] = []
    if project_key is not None:
        clauses.append(_PROJECT_KEY_FILTER)
        params.append(project_key)
    if story_id is not None:
        clauses.append(_STORY_ID_FILTER)
        params.append(story_id)
    if run_id is not None:
        clauses.append(_RUN_ID_FILTER)
        params.append(run_id)
    if attempt_no is not None:
        clauses.append("attempt_no = ?")
        params.append(attempt_no)
    if stage_id is not None:
        clauses.append("stage_id = ?")
        params.append(stage_id)
    where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _connect(story_dir) as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM qa_stage_results
            {where_clause}
            ORDER BY attempt_no ASC, stage_id ASC
            """,
            tuple(params),
        ).fetchall()
    return [dict(row) for row in rows]


def load_qa_finding_rows(
    story_dir: Path,
    *,
    project_key: str | None = None,
    story_id: str | None = None,
    run_id: str | None = None,
    attempt_no: int | None = None,
    stage_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return QA finding row dicts matching the given filters."""

    clauses: list[str] = []
    params: list[object] = []
    if project_key is not None:
        clauses.append(_PROJECT_KEY_FILTER)
        params.append(project_key)
    if story_id is not None:
        clauses.append(_STORY_ID_FILTER)
        params.append(story_id)
    if run_id is not None:
        clauses.append(_RUN_ID_FILTER)
        params.append(run_id)
    if attempt_no is not None:
        clauses.append("attempt_no = ?")
        params.append(attempt_no)
    if stage_id is not None:
        clauses.append("stage_id = ?")
        params.append(stage_id)
    where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _connect(story_dir) as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM qa_findings
            {where_clause}
            ORDER BY attempt_no ASC, stage_id ASC, occurred_at ASC, finding_id ASC
            """,
            tuple(params),
        ).fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Runtime-Execution per-owner purge rows (AG3-109)
# ---------------------------------------------------------------------------
#
# Postgres mirror of ``sqlite_store`` purge helpers. The physical §1.3 mapping
# (code is ground truth; FK-18/FK-53 prose drift is a doc-only follow-up) is
# documented in ``sqlite_store``. ``?`` placeholders are translated to ``%s`` by
# ``_CompatConnection``, so the SQL is byte-for-byte the same across both stores.
# Idempotent per FK-53 §53.9.1: delete-if-present, zero when already gone, hard
# fail only on real infra/permission errors. NEVER reference phantom tables
# ``attempt_records`` / ``node_executions`` / ``artifact_records``. The read-model
# ``phase_state_projection`` is OUT OF SCOPE.


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
    """Delete attempts rows for (story_id, run_id) (no project_key column)."""

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
    """Delete the canonical phase_states row for story_id (NOT the projection)."""

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

    Story-keyed runtime PhaseState evidence (second-QA closure, FK-53 §53.7.5
    rule); mirrors the ``sqlite_store`` helper — see its docstring.
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
    """Delete all decision_records rows for story_id (every kind/attempt/run).

    Governance runtime residue (second-QA closure, FK-53 §53.7.5 rule): the
    Postgres reader falls back to a story-wide ``MAX(attempt_nr)`` lookup, so a
    purged run's leftover verify decision would shadow the next run's decision.
    Story-keyed delete mirrors the ``sqlite_store`` helper.
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

    No ``project_key`` column; every row is bound to ``run_id``. A reset starts a
    new run, so deleting all rows for the OLD ``(story_id, run_id)`` removes the
    run-bound artefacts and leaves other-run rows intact.
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

    Deliberately ``project_key``-agnostic counting (run-bound tables by
    ``(story_id, run_id)``, story-keyed tables by ``story_id``) so a mis-scoped
    purge surfaces as residue — see the ``sqlite_store`` twin's docstring.
    """

    # Residue counting is run-/story-scoped by design — see docstring.
    del project_key
    with _connect(story_dir) as conn:
        return _count_runtime_execution_residue(conn, story_id, run_id)


def _count_runtime_execution_residue(
    conn: _CompatConnection,
    story_id: str,
    run_id: str,
) -> dict[str, int]:
    def _count(sql: str, params: tuple[object, ...]) -> int:
        row = conn.execute(sql, params).fetchone()
        if row is None:
            return 0
        value = next(iter(row.values())) if isinstance(row, dict) else row[0]
        return int(value)

    sr = (story_id, run_id)
    s = (story_id,)
    return {
        "flow_executions": _count(
            "SELECT COUNT(*) AS n FROM flow_executions WHERE story_id = ? AND run_id = ?",
            sr,
        ),
        "node_execution_ledgers": _count(
            "SELECT COUNT(*) AS n FROM node_execution_ledgers WHERE story_id = ? AND run_id = ?",
            sr,
        ),
        "attempts": _count(
            "SELECT COUNT(*) AS n FROM attempts WHERE story_id = ? AND run_id = ?",
            sr,
        ),
        "override_records": _count(
            "SELECT COUNT(*) AS n FROM override_records WHERE story_id = ? AND run_id = ?",
            sr,
        ),
        "guard_decisions": _count(
            "SELECT COUNT(*) AS n FROM guard_decisions WHERE story_id = ? AND run_id = ?",
            sr,
        ),
        "decision_records": _count(
            "SELECT COUNT(*) AS n FROM decision_records WHERE story_id = ?",
            s,
        ),
        "phase_states": _count(
            "SELECT COUNT(*) AS n FROM phase_states WHERE story_id = ?",
            s,
        ),
        "phase_snapshots": _count(
            "SELECT COUNT(*) AS n FROM phase_snapshots WHERE story_id = ?",
            s,
        ),
        "execution_events": _count(
            "SELECT COUNT(*) AS n FROM execution_events WHERE story_id = ? AND run_id = ?",
            sr,
        ),
        "artifact_envelopes": _count(
            "SELECT COUNT(*) AS n FROM artifact_envelopes WHERE story_id = ? AND run_id = ?",
            sr,
        ),
    }


# ---------------------------------------------------------------------------
# Backend predicate helpers (kept as thin wrappers for driver-level checks)
# ---------------------------------------------------------------------------


def backend_has_valid_context(story_dir: Path) -> bool:
    return load_story_context_row(story_dir) is not None


def backend_has_valid_phase_state(story_dir: Path) -> bool:
    return load_phase_state_row(story_dir) is not None
