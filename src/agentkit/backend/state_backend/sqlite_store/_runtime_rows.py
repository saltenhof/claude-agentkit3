"""SQLite phase, flow, execution-event, metrics, ledger, and override rows."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from agentkit.backend.boundary.shared.time import now_iso
from agentkit.backend.exceptions import CorruptStateError
from agentkit.backend.state_backend.paths import PHASE_STATE_EXPORT_FILE

from ._common import (
    _execution_event_global_store_dir,
    _project_store_dir,
    _write_projection,
)
from ._connection import _connect
from ._story_identity import _story_id_for

if TYPE_CHECKING:
    from pathlib import Path


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

    with _connect(_project_store_dir(store_dir)) as conn:
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
    story-scoped on persistence (FK-39 §39.4.1).  INSERT OR REPLACE makes
    a repeated call with the same PK idempotent.
    """
    story_id = _story_id_for(story_dir)
    if story_id is None:
        raise CorruptStateError(
            "Cannot persist attempt without story context in canonical backend",
        )
    with _connect(story_dir) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO attempts (
                story_id, run_id, phase, attempt, outcome, failure_cause,
                started_at, ended_at, detail_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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

    from agentkit.backend.core_types.freeze import (
        ActiveFreezeState,
        FreezeKind,
        command_resolves_freeze,
        is_canonical_freeze_epoch,
    )
    from agentkit.backend.exceptions import OwnershipFenceViolationError

    story_id = _story_id_for(story_dir)
    if story_id is None or str(phase_state_row["story_id"]) != story_id:
        raise CorruptStateError(
            "Cannot persist phase completion without one canonical story scope",
        )
    payload_dict = json.loads(str(phase_state_row["payload_json"]))
    with _connect(story_dir) as conn:
        rows = conn.execute(
            "SELECT kind, freeze_reason, freeze_epoch "
            "FROM governance_freeze_records WHERE story_id=?",
            (story_id,),
        ).fetchall()
        for row in rows:
            try:
                kind = FreezeKind(str(row["kind"]))
            except ValueError:
                kind = None
            raw_reason = row["freeze_reason"]
            reason = raw_reason if isinstance(raw_reason, str) and raw_reason.strip() else None
            raw_epoch = row["freeze_epoch"]
            epoch = (
                raw_epoch
                if isinstance(raw_epoch, str) and is_canonical_freeze_epoch(raw_epoch)
                else None
            )
            freeze = ActiveFreezeState(kind=kind, freeze_reason=reason, freeze_epoch=epoch)
            if not command_resolves_freeze("executor_commit", freeze):
                raise OwnershipFenceViolationError(
                    f"story freeze blocks executor commit for story {story_id!r}",
                    detail={"error_code": "story_frozen"},
                )
        conn.execute(
            """
            INSERT OR REPLACE INTO attempts (
                story_id, run_id, phase, attempt, outcome, failure_cause,
                started_at, ended_at, detail_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    """Return attempt row dicts for a story+phase from the ``attempts`` table.

    Story-scoped: filters on ``story_id`` derived from ``story_dir``.
    When ``run_id`` is provided, additionally narrows to that run — used
    by ``EngineRuntimeState.generate_attempt_id`` to count attempts per
    run, not across runs.
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


# ---------------------------------------------------------------------------
# ExecutionEventRecord rows
# ---------------------------------------------------------------------------


def append_execution_event_row(story_dir: Path, row: dict[str, Any]) -> None:
    """Persist an execution-event row dict to the database."""

    with _connect(story_dir) as conn:
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


def append_execution_event_global_row(row: dict[str, Any]) -> None:
    """Append a global execution-event row to the global SQLite store.

    Resolves the store root via :func:`_execution_event_global_store_dir` (the
    explicit ``AGENTKIT_STORE_DIR`` root, fail-closed) so that the SSE stream and
    the KPI analytics source can read it cross-story via
    :func:`load_execution_event_rows_for_project_global`.

    AG3-094 (E8, backend parity): uses a *plain* ``INSERT`` (NOT
    ``INSERT OR IGNORE``) to match the Postgres global insert
    (``postgres_store._insert_execution_event_row``). A duplicate
    ``(project_key, run_id, event_id)`` therefore raises an
    :class:`sqlite3.IntegrityError`, exactly as Postgres raises on its PK — the
    idempotency/dup-key semantics are identical across backends, so a writer
    that silently tolerated dups on SQLite can no longer pass while breaking on
    the Postgres path.
    """
    with _connect(_execution_event_global_store_dir()) as conn:
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


# Execution-event WHERE-clause fragments (hoisted to avoid duplicated literals, Sonar S1192).
_CLAUSE_PROJECT_KEY = "project_key = ?"
_CLAUSE_STORY_ID = "story_id = ?"
_CLAUSE_RUN_ID = "run_id = ?"
_CLAUSE_EVENT_TYPE = "event_type = ?"


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
        clauses.append(_CLAUSE_PROJECT_KEY)
        params.append(project_key)
    if story_id is not None:
        clauses.append(_CLAUSE_STORY_ID)
        params.append(story_id)
    if run_id is not None:
        clauses.append(_CLAUSE_RUN_ID)
        params.append(run_id)
    if event_type is not None:
        clauses.append(_CLAUSE_EVENT_TYPE)
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
    ``(project_key, story_id, run_id, signal_type)`` tuple.  Uses
    ``json_extract(payload_json, '$.signal_type') = ?`` (NOT LIKE) to avoid
    false matches on substring keys.  Returns the raw ISO-8601 string from the
    DB (``occurred_at`` column), or ``None`` when no matching row exists.

    Args:
        story_dir: Story directory for the SQLite database.
        project_key: Exact project scope.
        story_id: Exact story scope.
        run_id: Exact run scope.
        payload_signal_type: Exact ``signal_type`` value to match in the JSON payload.

    Returns:
        ISO-8601 ``occurred_at`` string of the most-recent matching adjudication,
        or ``None`` when absent.
    """
    with _connect(story_dir) as conn:
        row = conn.execute(
            """
            SELECT MAX(occurred_at) AS max_occurred_at
            FROM execution_events
            WHERE project_key = ?
              AND story_id = ?
              AND run_id = ?
              AND event_type = 'governance_adjudication'
              AND json_extract(payload_json, '$.signal_type') = ?
            """,
            (project_key, story_id, run_id, payload_signal_type),
        ).fetchone()
    if row is None:
        return None
    value = row["max_occurred_at"] if isinstance(row, dict) else row[0]
    return str(value) if value is not None else None


def load_execution_event_rows_global(
    project_key: str,
    story_id: str,
    *,
    run_id: str | None = None,
    event_type: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Return execution-event rows ordered DESC by occurred_at for a rolling window.

    Implements the FK-35 §35.3.5 rolling-window query:
    ``ORDER BY occurred_at DESC LIMIT window_size`` so only the most-recent
    ``limit`` events are returned.  Callers sum ``payload.risk_points`` over
    the result to obtain the current risk score (no in-memory accumulation).

    Args:
        project_key: Project scope filter.
        story_id: Story scope filter.
        run_id: Optional run scope filter.
        event_type: Optional event-type filter (e.g. ``"governance_signal"``).
        limit: Maximum number of rows to return (the rolling-window width).

    Returns:
        Row dicts ordered by ``occurred_at DESC``, capped at ``limit``.
    """
    db_dir: Path = _execution_event_global_store_dir()
    clauses: list[str] = [_CLAUSE_PROJECT_KEY, _CLAUSE_STORY_ID]
    params: list[object] = [project_key, story_id]
    if run_id is not None:
        clauses.append(_CLAUSE_RUN_ID)
        params.append(run_id)
    if event_type is not None:
        clauses.append(_CLAUSE_EVENT_TYPE)
        params.append(event_type)
    where_clause = f"WHERE {' AND '.join(clauses)}"
    limit_clause = f"LIMIT {int(limit)}" if limit is not None else ""
    with _connect(db_dir) as conn:
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
    return [dict(row) for row in rows]


def load_execution_event_rows_for_project_global(
    project_key: str,
    *,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Return global execution-event rows for ``project_key`` from the global SQLite store.

    Reads from the same global database that
    :func:`append_execution_event_global_row` writes to (resolved via
    :func:`_execution_event_global_store_dir`).

    AG3-094 (E8, backend parity): the ordering/limit-window semantics MUST match
    :func:`postgres_store.load_execution_event_rows_for_project_global`. Postgres
    selects ``ORDER BY occurred_at DESC, event_id DESC LIMIT ?`` and then
    ``reversed(rows)`` — i.e. it takes the *most-recent N* rows and returns them
    in *ascending* (chronological) order. This SQLite implementation mirrors that
    exactly: it selects the most-recent-N window descending and reverses it to
    chronological order, so both backends return identical sequences for the same
    arguments (no silent SSE-store drift between local SQLite and the Postgres
    path on Jenkins).
    """
    if limit is not None and limit <= 0:
        return []
    params: list[object] = [project_key]
    limit_clause = ""
    if limit is not None:
        limit_clause = "LIMIT ?"
        params.append(limit)
    with _connect(_execution_event_global_store_dir()) as conn:
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
    """Reject the Postgres-only cross-project governance event read."""
    del event_type, limit
    raise RuntimeError("Takeover governance event reads require PostgreSQL")


# ---------------------------------------------------------------------------
# StoryMetricsRecord rows
# ---------------------------------------------------------------------------


def upsert_story_metrics_row(story_dir: Path, row: dict[str, Any]) -> None:
    """Persist a story-metrics row dict to the database."""

    with _connect(story_dir) as conn:
        conn.execute(
            """
            INSERT INTO story_metrics (
                project_key, story_id, run_id, story_type, story_size, mode,
                processing_time_min, qa_rounds, increments, final_status,
                completed_at, adversarial_findings, adversarial_tests_created,
                files_changed, agentkit_version, agentkit_commit,
                config_version, llm_roles_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_key, run_id) DO UPDATE SET
                story_id=excluded.story_id,
                story_type=excluded.story_type,
                story_size=excluded.story_size,
                mode=excluded.mode,
                processing_time_min=excluded.processing_time_min,
                qa_rounds=excluded.qa_rounds,
                increments=excluded.increments,
                final_status=excluded.final_status,
                completed_at=excluded.completed_at,
                adversarial_findings=excluded.adversarial_findings,
                adversarial_tests_created=excluded.adversarial_tests_created,
                files_changed=excluded.files_changed,
                agentkit_version=excluded.agentkit_version,
                agentkit_commit=excluded.agentkit_commit,
                config_version=excluded.config_version,
                llm_roles_json=excluded.llm_roles_json
            """,
            (
                row["project_key"],
                row["story_id"],
                row["run_id"],
                row["story_type"],
                row["story_size"],
                row["mode"],
                row["processing_time_min"],
                row["qa_rounds"],
                row["increments"],
                row["final_status"],
                row["completed_at"],
                row["adversarial_findings"],
                row["adversarial_tests_created"],
                row["files_changed"],
                row["agentkit_version"],
                row["agentkit_commit"],
                row["config_version"],
                row["llm_roles_json"],
            ),
        )


def load_story_metrics_rows(
    story_dir: Path,
    *,
    project_key: str | None = None,
    story_id: str | None = None,
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return story-metrics row dicts matching the given filters."""

    clauses: list[str] = []
    params: list[object] = []
    if project_key is not None:
        clauses.append(_CLAUSE_PROJECT_KEY)
        params.append(project_key)
    if story_id is not None:
        clauses.append(_CLAUSE_STORY_ID)
        params.append(story_id)
    if run_id is not None:
        clauses.append(_CLAUSE_RUN_ID)
        params.append(run_id)
    where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _connect(story_dir) as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM story_metrics
            {where_clause}
            ORDER BY completed_at ASC, run_id ASC
            """,
            tuple(params),
        ).fetchall()
    return [dict(row) for row in rows]


def load_latest_story_metrics_global_row(
    store_dir: Path | None,
    project_key: str,
    story_id: str,
) -> dict[str, Any] | None:
    """Return the latest raw story-metrics row for a global lookup, or None."""

    with _connect(_project_store_dir(store_dir)) as conn:
        row = conn.execute(
            """
            SELECT *
            FROM story_metrics
            WHERE project_key = ? AND story_id = ?
            ORDER BY completed_at DESC, run_id DESC
            LIMIT 1
            """,
            (project_key, story_id),
        ).fetchone()
    return dict(row) if row is not None else None


# ---------------------------------------------------------------------------
# NodeExecutionLedger rows
# ---------------------------------------------------------------------------


def save_node_execution_ledger_row(story_dir: Path, row: dict[str, Any]) -> None:
    """Persist a node-execution-ledger row dict to the database."""

    with _connect(story_dir) as conn:
        conn.execute(
            """
            INSERT INTO node_execution_ledgers (
                story_id, flow_id, node_id, project_key, run_id,
                execution_count, success_count, last_outcome,
                last_attempt_no, last_executed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(story_id, flow_id, node_id) DO UPDATE SET
                project_key=excluded.project_key,
                run_id=excluded.run_id,
                execution_count=excluded.execution_count,
                success_count=excluded.success_count,
                last_outcome=excluded.last_outcome,
                last_attempt_no=excluded.last_attempt_no,
                last_executed_at=excluded.last_executed_at
            """,
            (
                row["story_id"],
                row["flow_id"],
                row["node_id"],
                row["project_key"],
                row["run_id"],
                row["execution_count"],
                row["success_count"],
                row["last_outcome"],
                row["last_attempt_no"],
                row["last_executed_at"],
            ),
        )


def load_node_execution_ledger_row(
    story_dir: Path,
    flow_id: str,
    node_id: str,
) -> dict[str, Any] | None:
    """Return the raw node-execution-ledger row, or None."""

    story_id = _story_id_for(story_dir)
    if story_id is None:
        return None
    with _connect(story_dir) as conn:
        row = conn.execute(
            """
            SELECT * FROM node_execution_ledgers
            WHERE story_id = ? AND flow_id = ? AND node_id = ?
            """,
            (story_id, flow_id, node_id),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


# ---------------------------------------------------------------------------
# OverrideRecord rows
# ---------------------------------------------------------------------------


def save_override_record_row(story_dir: Path, row: dict[str, Any]) -> None:
    """Persist an override-record row dict to the database."""

    with _connect(story_dir) as conn:
        conn.execute(
            """
            INSERT INTO override_records (
                override_id, story_id, project_key, run_id, flow_id,
                target_node_id, override_type, actor_type, actor_id,
                reason, created_at, consumed_at, check_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(override_id) DO UPDATE SET
                target_node_id=excluded.target_node_id,
                override_type=excluded.override_type,
                actor_type=excluded.actor_type,
                actor_id=excluded.actor_id,
                reason=excluded.reason,
                created_at=excluded.created_at,
                consumed_at=excluded.consumed_at,
                check_id=excluded.check_id
            """,
            (
                row["override_id"],
                row["story_id"],
                row["project_key"],
                row["run_id"],
                row["flow_id"],
                row["target_node_id"],
                row["override_type"],
                row["actor_type"],
                row["actor_id"],
                row["reason"],
                row["created_at"],
                row["consumed_at"],
                row.get("check_id"),
            ),
        )


def load_override_record_rows(story_dir: Path) -> list[dict[str, Any]]:
    """Return override-record row dicts for a story, ordered by created_at."""

    story_id = _story_id_for(story_dir)
    if story_id is None:
        return []
    with _connect(story_dir) as conn:
        rows = conn.execute(
            """
            SELECT * FROM override_records
            WHERE story_id = ?
            ORDER BY created_at ASC
            """,
            (story_id,),
        ).fetchall()
    return [dict(row) for row in rows]
