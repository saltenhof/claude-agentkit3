"""Runtime phase, snapshot, flow, event, and session-binding row persistence."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from agentkit.backend.boundary.shared.time import now_iso
from agentkit.backend.exceptions import (
    ControlPlaneBindingCollisionError,
    CorruptStateError,
)
from agentkit.backend.state_backend.paths import (
    PHASE_STATE_EXPORT_FILE,
)

from ._connection import (
    _connect,
    _connect_global,
)
from ._constants import _PROJECT_KEY_FILTER, _RUN_ID_FILTER, _STORY_ID_FILTER
from ._json_projection import (
    _write_projection,
)
from ._story_project_rows import _story_id_for

if TYPE_CHECKING:
    from pathlib import Path

    from ._compat import _CompatConnection

_LIMIT_CLAUSE = "LIMIT ?"


def save_phase_state_row(story_dir: Path, row: dict[str, Any]) -> None:
    """Persist a phase-state row dict to the database and projection file."""

    payload_dict = json.loads(str(row["payload_json"]))
    with _connect(story_dir) as conn:
        conn.execute(
            """
            INSERT INTO phase_states (
                story_id, phase, status, paused_reason, review_round,
                attempt_id, errors_json, payload_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(story_id) DO UPDATE SET
                phase=excluded.phase,
                status=excluded.status,
                paused_reason=excluded.paused_reason,
                review_round=excluded.review_round,
                attempt_id=excluded.attempt_id,
                errors_json=excluded.errors_json,
                payload_json=excluded.payload_json,
                updated_at=excluded.updated_at
            """,
            (
                row["story_id"],
                row["phase"],
                row["status"],
                row["paused_reason"],
                row["review_round"],
                row["attempt_id"],
                row["errors_json"],
                row["payload_json"],
                now_iso(),
            ),
        )
    _write_projection(story_dir / PHASE_STATE_EXPORT_FILE, payload_dict)


def load_phase_state_row(story_dir: Path) -> dict[str, Any] | None:
    """Return the raw payload row for a phase state, or None."""

    story_id = _story_id_for(story_dir)
    if story_id is None:
        return None
    with _connect(story_dir) as conn:
        row = conn.execute(
            """
            SELECT payload_json FROM phase_states
            WHERE story_id = ?
            """,
            (story_id,),
        ).fetchone()
    if row is None:
        return None
    return {"payload_json": str(row["payload_json"])}


def read_phase_state_row(story_dir: Path) -> dict[str, Any] | None:
    """Canonical reader name for protected runtime modules."""

    return load_phase_state_row(story_dir)


def load_phase_state_global_row(
    store_dir: Path | None,
    story_id: str,
) -> dict[str, Any] | None:
    """Return the raw payload row for a global phase state, or None."""

    del store_dir
    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT payload_json FROM phase_states
            WHERE story_id = ?
            """,
            (story_id,),
        ).fetchone()
    if row is None:
        return None
    return {"payload_json": str(row["payload_json"])}


# ---------------------------------------------------------------------------
# PhaseSnapshot rows
# ---------------------------------------------------------------------------


def save_phase_snapshot_row(story_dir: Path, row: dict[str, Any]) -> None:
    """Persist a phase-snapshot row dict to the database and projection file."""

    payload_dict = json.loads(str(row["payload_json"]))
    phase = str(row["phase"])
    with _connect(story_dir) as conn:
        conn.execute(
            """
            INSERT INTO phase_snapshots (
                story_id, phase, status, completed_at, payload_json
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(story_id, phase) DO UPDATE SET
                status=excluded.status,
                completed_at=excluded.completed_at,
                payload_json=excluded.payload_json
            """,
            (
                row["story_id"],
                row["phase"],
                row["status"],
                row["completed_at"],
                row["payload_json"],
            ),
        )
    _write_projection(story_dir / f"phase-state-{phase}.json", payload_dict)


def load_phase_snapshot_row(story_dir: Path, phase: str) -> dict[str, Any] | None:
    """Return the raw payload row for a phase snapshot, or None."""

    story_id = _story_id_for(story_dir)
    if story_id is None:
        return None
    with _connect(story_dir) as conn:
        row = conn.execute(
            """
            SELECT payload_json FROM phase_snapshots
            WHERE story_id = ? AND phase = ?
            """,
            (story_id, phase),
        ).fetchone()
    if row is None:
        return None
    return {"payload_json": str(row["payload_json"])}


def read_phase_snapshot_row(story_dir: Path, phase: str) -> dict[str, Any] | None:
    """Canonical reader name for protected runtime modules."""

    return load_phase_snapshot_row(story_dir, phase)


# ---------------------------------------------------------------------------
# AttemptRecord rows
# ---------------------------------------------------------------------------


def save_attempt_row(story_dir: Path, row: dict[str, Any]) -> None:
    """Persist an attempt row dict to the ``attempts`` table (Schema 3.5.0).

    ``story_id`` is derived from ``story_dir`` so AttemptRecords are
    story-scoped on the persistence side (FK-39 §39.4.1).  Idempotent:
    ``INSERT ... ON CONFLICT DO UPDATE`` overwrites the row on a
    re-write with the same ``(story_id, run_id, phase, attempt)`` key.
    """
    story_id = _story_id_for(story_dir)
    if story_id is None:
        raise CorruptStateError(
            "Cannot persist attempt without story context in canonical backend",
        )
    with _connect(story_dir) as conn:
        conn.execute(
            """
            INSERT INTO attempts (
                story_id, run_id, phase, attempt, outcome, failure_cause,
                started_at, ended_at, detail_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (story_id, run_id, phase, attempt) DO UPDATE SET
                outcome=excluded.outcome,
                failure_cause=excluded.failure_cause,
                started_at=excluded.started_at,
                ended_at=excluded.ended_at,
                detail_json=excluded.detail_json
            """,
            (
                story_id,
                row["run_id"],
                row["phase"],
                row["attempt"],
                row["outcome"],
                row.get("failure_cause"),
                row["started_at"],
                row["ended_at"],
                row.get("detail_json"),
            ),
        )


def save_phase_completion_rows(
    story_dir: Path,
    attempt_row: dict[str, Any],
    phase_state_row: dict[str, Any],
) -> None:
    """Atomically freeze-fence and persist one attempt/state completion pair."""

    story_id = _story_id_for(story_dir)
    if story_id is None or str(phase_state_row["story_id"]) != story_id:
        raise CorruptStateError(
            "Cannot persist phase completion without one canonical story scope",
        )
    payload_dict = json.loads(str(phase_state_row["payload_json"]))
    from ._mutation_commit_rows import _enforce_blocking_freeze_row

    with _connect(story_dir) as conn:
        _enforce_blocking_freeze_row(
            conn,
            story_id=story_id,
            command_id="executor_commit",
        )
        conn.execute(
            """
            INSERT INTO attempts (
                story_id, run_id, phase, attempt, outcome, failure_cause,
                started_at, ended_at, detail_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (story_id, run_id, phase, attempt) DO UPDATE SET
                outcome=excluded.outcome,
                failure_cause=excluded.failure_cause,
                started_at=excluded.started_at,
                ended_at=excluded.ended_at,
                detail_json=excluded.detail_json
            """,
            (
                story_id,
                attempt_row["run_id"],
                attempt_row["phase"],
                attempt_row["attempt"],
                attempt_row["outcome"],
                attempt_row.get("failure_cause"),
                attempt_row["started_at"],
                attempt_row["ended_at"],
                attempt_row.get("detail_json"),
            ),
        )
        conn.execute(
            """
            INSERT INTO phase_states (
                story_id, phase, status, paused_reason, review_round,
                attempt_id, errors_json, payload_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(story_id) DO UPDATE SET
                phase=excluded.phase,
                status=excluded.status,
                paused_reason=excluded.paused_reason,
                review_round=excluded.review_round,
                attempt_id=excluded.attempt_id,
                errors_json=excluded.errors_json,
                payload_json=excluded.payload_json,
                updated_at=excluded.updated_at
            """,
            (
                story_id,
                phase_state_row["phase"],
                phase_state_row["status"],
                phase_state_row["paused_reason"],
                phase_state_row["review_round"],
                phase_state_row["attempt_id"],
                phase_state_row["errors_json"],
                phase_state_row["payload_json"],
                now_iso(),
            ),
        )
    _write_projection(story_dir / PHASE_STATE_EXPORT_FILE, payload_dict)


def load_attempt_rows(
    story_dir: Path,
    phase: str,
    *,
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return attempt row dicts for a story+phase from ``attempts``.

    Filters on ``story_id`` (derived from ``story_dir``) and ``phase``.
    An optional ``run_id`` additionally narrows to a single run — used by
    ``EngineRuntimeState.generate_attempt_id`` to count attempts per
    run and not across runs.
    """
    story_id = _story_id_for(story_dir)
    if story_id is None:
        return []
    with _connect(story_dir) as conn:
        if run_id is None:
            rows = conn.execute(
                """
                SELECT * FROM attempts
                WHERE story_id = ? AND phase = ?
                ORDER BY attempt ASC
                """,
                (story_id, phase),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM attempts
                WHERE story_id = ? AND run_id = ? AND phase = ?
                ORDER BY attempt ASC
                """,
                (story_id, run_id, phase),
            ).fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# FlowExecution rows
# ---------------------------------------------------------------------------


def save_flow_execution_row(story_dir: Path, row: dict[str, Any]) -> None:
    """Persist a flow-execution row dict to the database."""

    with _connect(story_dir) as conn:
        conn.execute(
            """
            INSERT INTO flow_executions (
                story_id, project_key, run_id, flow_id, level, owner,
                parent_flow_id, status, current_node_id, attempt_no,
                started_at, finished_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(story_id) DO UPDATE SET
                project_key=excluded.project_key,
                run_id=excluded.run_id,
                flow_id=excluded.flow_id,
                level=excluded.level,
                owner=excluded.owner,
                parent_flow_id=excluded.parent_flow_id,
                status=excluded.status,
                current_node_id=excluded.current_node_id,
                attempt_no=excluded.attempt_no,
                started_at=excluded.started_at,
                finished_at=excluded.finished_at
            """,
            (
                row["story_id"],
                row["project_key"],
                row["run_id"],
                row["flow_id"],
                row["level"],
                row["owner"],
                row["parent_flow_id"],
                row["status"],
                row["current_node_id"],
                row["attempt_no"],
                row["started_at"],
                row["finished_at"],
            ),
        )


def load_flow_execution_row(story_dir: Path) -> dict[str, Any] | None:
    """Return the raw flow-execution row, or None."""

    story_id = _story_id_for(story_dir)
    if story_id is None:
        return None
    with _connect(story_dir) as conn:
        row = conn.execute(
            """
            SELECT * FROM flow_executions
            WHERE story_id = ?
            """,
            (story_id,),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


def load_flow_execution_global_row(
    project_key: str,
    story_id: str,
) -> dict[str, Any] | None:
    """Return the raw flow-execution row for a global lookup, or None."""

    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT * FROM flow_executions
            WHERE project_key = ? AND story_id = ?
            """,
            (project_key, story_id),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


# ---------------------------------------------------------------------------
# ExecutionEventRecord rows
# ---------------------------------------------------------------------------


def _insert_execution_event_row(
    conn: _CompatConnection,
    row: dict[str, Any],
) -> None:
    conn.execute(
        """
        INSERT INTO execution_events (
            project_key, story_id, run_id, event_id, event_type,
            occurred_at, source_component, severity, phase, flow_id,
            node_id, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row["project_key"],
            row["story_id"],
            row["run_id"],
            row["event_id"],
            row["event_type"],
            row["occurred_at"],
            row["source_component"],
            row["severity"],
            row["phase"],
            row["flow_id"],
            row["node_id"],
            row["payload_json"],
        ),
    )


def append_execution_event_row(story_dir: Path, row: dict[str, Any]) -> None:
    """Persist an execution-event row dict to the database."""

    with _connect(story_dir) as conn:
        _insert_execution_event_row(conn, row)
        _invalidate_push_barriers_for_registered_commit(conn, row)


def append_execution_event_global_row(row: dict[str, Any]) -> None:
    """Persist an execution-event row dict globally."""

    with _connect_global() as conn:
        _insert_execution_event_row(conn, row)
        _invalidate_push_barriers_for_registered_commit(conn, row)


def _invalidate_push_barriers_for_registered_commit(
    conn: _CompatConnection,
    row: dict[str, Any],
) -> None:
    """Supersede live push barriers for an AK3-registered commit event.

    The event hook is intentionally best-effort at extracting repo and SHA
    metadata from shell execution. Missing metadata must degrade fail-closed:
    unknown repo supersedes every repo in the run scope, and unknown SHA clears
    the expected head instead of leaving an old PASS usable.
    """

    if row["event_type"] != "increment_commit":
        return
    payload = json.loads(str(row["payload_json"]))
    if not isinstance(payload, dict):
        return
    repo_name = payload.get("repo_name")
    repo_id = repo_name.strip() if isinstance(repo_name, str) else ""
    head_value = payload.get("commit_sha")
    commit_sha = head_value.strip() if isinstance(head_value, str) else ""
    repo_filter = "AND repo_id = ?" if repo_id else ""
    params: list[object] = [
        commit_sha or None,
        row["occurred_at"],
        row["occurred_at"],
        row["project_key"],
        row["story_id"],
        row["run_id"],
    ]
    if repo_id:
        params.append(repo_id)
    conn.execute(
        f"""
        UPDATE push_barrier_verdicts
        SET boundary_epoch = boundary_epoch + 1,
            expected_head_sha = ?,
            server_head_sha = NULL,
            status = 'superseded',
            updated_at = ?,
            resolved_at = ?,
            status_detail = 'superseded_by_registered_commit'
        WHERE project_key = ?
          AND story_id = ?
          AND run_id = ?
          {repo_filter}
          AND status IN ('pending', 'passed')
        """,
        tuple(params),
    )


def load_execution_event_rows(
    story_dir: Path,
    *,
    project_key: str | None = None,
    story_id: str | None = None,
    run_id: str | None = None,
    event_type: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Return execution-event row dicts matching the given filters.

    When *limit* is ``None`` rows are ordered ``occurred_at ASC, event_id ASC``
    (chronological — default for existing callers such as closure).  When *limit*
    is set to a positive integer the query flips to ``ORDER BY occurred_at DESC,
    event_id DESC LIMIT limit`` so the *most-recent* rows are returned first
    (FK-35 §35.3.5 rolling-window semantics).  A non-positive *limit* returns
    an empty list immediately.
    """
    if limit is not None and limit <= 0:
        return []
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
    if event_type is not None:
        clauses.append("event_type = ?")
        params.append(event_type)
    where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    if limit is not None:
        params.append(limit)
        order_and_limit = "ORDER BY occurred_at DESC, event_id DESC LIMIT ?"
    else:
        order_and_limit = "ORDER BY occurred_at ASC, event_id ASC"
    with _connect(story_dir) as conn:
        rows = conn.execute(
            f"""
            SELECT project_key, story_id, run_id, event_id, event_type,
                   occurred_at, source_component, severity, phase, flow_id,
                   node_id, payload_json
            FROM execution_events
            {where_clause}
            {order_and_limit}
            """,
            tuple(params),
        ).fetchall()
    return [dict(row) for row in rows]


def max_adjudication_occurred_at(
    story_dir: Path,
    *,
    project_key: str,
    story_id: str,
    run_id: str,
    payload_signal_type: str,
) -> str | None:
    """Return MAX(occurred_at) for governance_adjudication rows matching the exact scope.

    Implements FK-35 §35.3.11: the last adjudication timestamp for the EXACT
    ``(project_key, story_id, run_id, signal_type)`` tuple.  ``payload_json``
    is a ``TEXT`` column, so it is cast to ``jsonb`` before the ``->>``
    operator (``(payload_json::jsonb)->>'signal_type' = ?``, NOT LIKE) to
    avoid false matches on substring keys.  Returns the raw ISO-8601 string
    from the DB (``occurred_at`` column), or ``None`` when no matching row
    exists.

    Args:
        story_dir: Unused for Postgres (connection is derived from env); kept
            for API parity with the SQLite driver (FK-35 §35.3.11 / FIX B).
        project_key: Exact project scope.
        story_id: Exact story scope.
        run_id: Exact run scope.
        payload_signal_type: Exact ``signal_type`` value to match in the payload JSON.

    Returns:
        ISO-8601 ``occurred_at`` string of the most-recent matching adjudication,
        or ``None`` when absent.
    """
    del story_dir  # unused — Postgres derives connection from env
    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT MAX(occurred_at) AS max_occurred_at
            FROM execution_events
            WHERE project_key = ?
              AND story_id = ?
              AND run_id = ?
              AND event_type = 'governance_adjudication'
              AND (payload_json::jsonb)->>'signal_type' = ?
            """,
            (project_key, story_id, run_id, payload_signal_type),
        ).fetchone()
    if row is None:
        return None
    value = row.get("max_occurred_at") if isinstance(row, dict) else None
    return str(value) if value is not None else None


def load_execution_event_rows_global(
    project_key: str,
    story_id: str,
    *,
    run_id: str | None = None,
    event_type: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Return execution-event row dicts for a global project/story query."""

    if limit is not None and limit <= 0:
        return []
    clauses = [_PROJECT_KEY_FILTER, _STORY_ID_FILTER]
    params: list[object] = [project_key, story_id]
    if run_id is not None:
        clauses.append(_RUN_ID_FILTER)
        params.append(run_id)
    if event_type is not None:
        clauses.append("event_type = ?")
        params.append(event_type)
    limit_clause = ""
    if limit is not None:
        limit_clause = _LIMIT_CLAUSE
        params.append(limit)
    where_clause = f"WHERE {' AND '.join(clauses)}"
    with _connect_global() as conn:
        rows = conn.execute(
            f"""
            SELECT project_key, story_id, run_id, event_id, event_type,
                   occurred_at, source_component, severity, phase, flow_id,
                   node_id, payload_json
            FROM execution_events
            {where_clause}
            ORDER BY occurred_at DESC, event_id DESC
            {limit_clause}
            """,
            tuple(params),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def load_execution_event_rows_for_project_global(
    project_key: str,
    *,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Return recent execution-event rows for one project."""

    if limit is not None and limit <= 0:
        return []
    params: list[object] = [project_key]
    limit_clause = ""
    if limit is not None:
        limit_clause = _LIMIT_CLAUSE
        params.append(limit)
    with _connect_global() as conn:
        rows = conn.execute(
            f"""
            SELECT project_key, story_id, run_id, event_id, event_type,
                   occurred_at, source_component, severity, phase, flow_id,
                   node_id, payload_json
            FROM execution_events
            WHERE project_key = ?
            ORDER BY occurred_at DESC, event_id DESC
            {limit_clause}
            """,
            tuple(params),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def load_execution_event_rows_by_type_global(
    event_type: str,
    *,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Return recent execution-event rows of one type across all projects."""
    if limit is not None and limit <= 0:
        return []
    params: list[object] = [event_type]
    limit_clause = ""
    if limit is not None:
        limit_clause = _LIMIT_CLAUSE
        params.append(limit)
    with _connect_global() as conn:
        rows = conn.execute(
            f"""
            SELECT project_key, story_id, run_id, event_id, event_type,
                   occurred_at, source_component, severity, phase, flow_id,
                   node_id, payload_json
            FROM execution_events
            WHERE event_type = ?
            ORDER BY occurred_at DESC, event_id DESC
            {limit_clause}
            """,
            tuple(params),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


# ---------------------------------------------------------------------------
# SessionRunBindingRecord rows
# ---------------------------------------------------------------------------


def save_session_run_binding_global_row(row: dict[str, Any]) -> None:
    """Persist a session binding without bypassing the one-slot guard.

    This compatibility surface may insert a new row or update the same ACTIVE
    run.  Superseding a revoked notification is deliberately excluded here:
    that exception is legal only inside an audited operation-ledger unit of
    work (``_insert_session_binding_row``).

    Raises:
        ControlPlaneBindingCollisionError: If the session slot contains a
            foreign active binding or a revoked notification.
    """

    with _connect_global() as conn:
        cursor = conn.execute(
            """
            INSERT INTO session_run_bindings (
                session_id, project_key, story_id, run_id, principal_type,
                worktree_roots_json, binding_version, updated_at,
                status, revocation_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (session_id) DO UPDATE SET
                project_key = EXCLUDED.project_key,
                story_id = EXCLUDED.story_id,
                run_id = EXCLUDED.run_id,
                principal_type = EXCLUDED.principal_type,
                worktree_roots_json = EXCLUDED.worktree_roots_json,
                binding_version = EXCLUDED.binding_version,
                updated_at = EXCLUDED.updated_at,
                status = EXCLUDED.status,
                revocation_reason = EXCLUDED.revocation_reason
            WHERE session_run_bindings.project_key = EXCLUDED.project_key
              AND session_run_bindings.story_id = EXCLUDED.story_id
              AND session_run_bindings.run_id = EXCLUDED.run_id
              AND session_run_bindings.status = 'active'
              AND EXCLUDED.status = 'active'
              AND EXCLUDED.revocation_reason IS NULL
            """,
            (
                row["session_id"],
                row["project_key"],
                row["story_id"],
                row["run_id"],
                row["principal_type"],
                row["worktree_roots_json"],
                row["binding_version"],
                row["updated_at"],
                row.get("status", "active"),
                row.get("revocation_reason"),
            ),
        )
        if int(cursor.rowcount) == 0:
            raise ControlPlaneBindingCollisionError(
                "public session-binding save refused: the one-slot session row "
                "contains a foreign active binding, a revoked notification, or "
                "the update attempts a revocation transition; disown and "
                "revoked-row supersede require an audited operation-ledger commit",
            )


def load_session_run_binding_global_row(
    session_id: str,
) -> dict[str, Any] | None:
    """Return the raw session-run-binding row for a session, or None."""

    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT * FROM session_run_bindings
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


def delete_session_run_binding_global(session_id: str) -> None:
    """Delete a session-run-binding globally."""

    with _connect_global() as conn:
        conn.execute(
            """
            DELETE FROM session_run_bindings
            WHERE session_id = ?
            """,
            (session_id,),
        )
