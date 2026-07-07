"""Story metrics, QA stage/finding rows, layer artifacts, decisions, and closure reports."""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

from agentkit.backend.boundary.shared.time import now_iso
from agentkit.backend.core_types.qa_artifact_names import VERIFY_DECISION_FILE
from agentkit.backend.exceptions import (
    CorruptStateError,
)
from agentkit.backend.state_backend.paths import (
    CLOSURE_REPORT_FILE,
)

if TYPE_CHECKING:


    from pathlib import Path

    from agentkit.backend.state_backend.scope import RuntimeStateScope

from ._connection import (
    _connect,
    _connect_global,
    _database_label,
)
from ._constants import _PROJECT_KEY_FILTER, _RUN_ID_FILTER, _STORY_ID_FILTER
from ._control_plane_rows import _enforce_ownership_fence_row
from ._json_projection import (
    _cast_json_record,
    _dump_json,
    _JsonRecord,
    _write_projection,
)
from ._runtime_rows import load_flow_execution_row
from ._story_project_rows import (
    _artifact_id_for,
    _story_id_for,
)


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
        clauses.append(_PROJECT_KEY_FILTER)
        params.append(project_key)
    if story_id is not None:
        clauses.append(_STORY_ID_FILTER)
        params.append(story_id)
    if run_id is not None:
        clauses.append(_RUN_ID_FILTER)
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

    del store_dir
    with _connect_global() as conn:
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
    if row is None:
        return None
    return dict(row)


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


# ---------------------------------------------------------------------------
# QA layer artifacts + QA decision
# ---------------------------------------------------------------------------


def pg_execute_stage_upsert(conn: Any, row: dict[str, Any]) -> None:
    """Upsert a ``qa_stage_results`` row on an existing psycopg connection.

    Driver-owned SQL (FK-69 §69.4). Callable both from the in-transaction
    batch path (``persist_layer_artifact_rows``) and from the
    ``boundary.state_backend_repository`` Facade repos (R -> T), so the SQL
    lives exactly once in the driver (SSOT; AC010: the driver never imports a
    repository).

    Args:
        conn: Open psycopg connection (driver transaction).
        row: Fully serialised ``qa_stage_results`` row (dict).
    """
    conn.execute(
        """
        INSERT INTO qa_stage_results (
            project_key, story_id, run_id, attempt_no, stage_id, layer,
            producer_component, status, blocking, total_checks,
            failed_checks, warning_checks, artifact_id, recorded_at
        ) VALUES (
            %(project_key)s, %(story_id)s, %(run_id)s, %(attempt_no)s,
            %(stage_id)s, %(layer)s, %(producer_component)s, %(status)s,
            %(blocking)s, %(total_checks)s, %(failed_checks)s,
            %(warning_checks)s, %(artifact_id)s, %(recorded_at)s
        )
        ON CONFLICT (project_key, run_id, attempt_no, stage_id)
        DO UPDATE SET
            story_id=EXCLUDED.story_id,
            layer = EXCLUDED.layer,
            producer_component = EXCLUDED.producer_component,
            status = EXCLUDED.status,
            blocking = EXCLUDED.blocking,
            total_checks = EXCLUDED.total_checks,
            failed_checks = EXCLUDED.failed_checks,
            warning_checks = EXCLUDED.warning_checks,
            artifact_id = EXCLUDED.artifact_id,
            recorded_at = EXCLUDED.recorded_at
        """,
        row,
    )


def pg_execute_finding_upsert(conn: Any, row: dict[str, Any]) -> None:
    """Upsert a ``qa_findings`` row on an existing psycopg connection.

    Driver-owned SQL (FK-69 §69.4). See :func:`pg_execute_stage_upsert` for the
    SSOT / AC010 rationale.

    Args:
        conn: Open psycopg connection (driver transaction).
        row: Fully serialised ``qa_findings`` row (dict).
    """
    conn.execute(
        """
        INSERT INTO qa_findings (
            project_key, story_id, run_id, attempt_no, stage_id,
            finding_id, check_id, status, severity, blocking,
            source_component, artifact_id, occurred_at,
            category, reason, description, detail, metadata_json
        ) VALUES (
            %(project_key)s, %(story_id)s, %(run_id)s, %(attempt_no)s,
            %(stage_id)s, %(finding_id)s, %(check_id)s, %(status)s,
            %(severity)s, %(blocking)s, %(source_component)s,
            %(artifact_id)s, %(occurred_at)s, %(category)s, %(reason)s,
            %(description)s, %(detail)s, %(metadata_json)s
        )
        ON CONFLICT (project_key, run_id, attempt_no, stage_id, finding_id)
        DO UPDATE SET
            story_id=EXCLUDED.story_id,
            check_id = EXCLUDED.check_id,
            status = EXCLUDED.status,
            severity = EXCLUDED.severity,
            blocking = EXCLUDED.blocking,
            source_component = EXCLUDED.source_component,
            artifact_id = EXCLUDED.artifact_id,
            occurred_at = EXCLUDED.occurred_at,
            category = EXCLUDED.category,
            reason = EXCLUDED.reason,
            description = EXCLUDED.description,
            detail = EXCLUDED.detail,
            metadata_json = EXCLUDED.metadata_json
        """,
        row,
    )


def pg_delete_findings_for_scope(
    conn: Any,
    *,
    project_key: str,
    run_id: str,
    attempt_no: int,
    stage_id: str,
) -> None:
    """Delete ``qa_findings`` for a scope on an existing psycopg connection.

    Driver-owned SQL (FK-69). Removes stale findings before a batch re-write so
    no outdated rows survive (idempotency invariant of the batch write).

    Args:
        conn: Open psycopg connection (driver transaction).
        project_key: Project key.
        run_id: Run ID.
        attempt_no: Attempt number.
        stage_id: Layer / stage ID.
    """
    conn.execute(
        """
        DELETE FROM qa_findings
        WHERE project_key = %s AND run_id = %s AND attempt_no = %s AND stage_id = %s
        """,
        (project_key, run_id, attempt_no, stage_id),
    )


def persist_layer_artifact_rows(
    story_dir: Path,
    *,
    flow_row: dict[str, Any] | None,
    layer_payload_rows: list[dict[str, object]],
    attempt_nr: int,
    owner_session_id: str,
    expected_ownership_epoch: int,
    projection_dir: Path | None = None,
) -> tuple[str, ...]:
    """Persist QA layer artifact rows, FK-69 read models, and projection files.

    ``layer_payload_rows`` contains pre-serialized dicts from the mapper layer.
    Each element has keys: ``layer``, ``artifact_name``, ``producer_component``,
    ``payload``, ``passed``, ``recorded_at``, ``stage_row``, ``finding_rows``.

    Finding D (AG3-035 remediation): FK-69 row persistence runs through the
    driver-owned upsert/delete functions (``pg_execute_stage_upsert``,
    ``pg_execute_finding_upsert``, ``pg_delete_findings_for_scope`` in this
    module). The transaction stays in the driver (FAIL-CLOSED: stage+findings+
    artifact_records atomic in ONE transaction). The accessor repos
    (boundary.state_backend_repository) delegate their Postgres write path
    to the same functions -- the SQL lives exactly once in the driver (SSOT;
    AC010: the driver imports no repository).

    AG3-144 (FK-91 §91.1a Rule 15, no-lease-no-write): ``owner_session_id`` /
    ``expected_ownership_epoch`` are the caller's early-captured
    ``run_ownership_records`` snapshot (mirrors the AG3-142 regime-commit
    pattern). The AG3-142 fence (``_enforce_ownership_fence_row``) is
    re-verified AT COMMIT TIME, in THIS SAME transaction, under
    ``SELECT ... FOR UPDATE``, BEFORE any row or projection file is written --
    a lost lease rejects with :class:`OwnershipFenceViolationError` and writes
    NOTHING (no projection file, no ``qa_stage_results``/``qa_findings`` row).

    Raises:
        OwnershipFenceViolationError: When the story's active ownership record
            no longer admits this exact ``(flow_row.run_id, owner_session_id,
            expected_ownership_epoch)`` snapshot at commit time.
    """
    story_id = _story_id_for(story_dir)
    if story_id is None:
        raise CorruptStateError(
            "Cannot persist QA layer artifacts without story context in canonical backend",
        )
    if flow_row is None:
        raise CorruptStateError(
            "Cannot materialize FK-69 QA read models without flow execution scope in canonical Postgres backend",
        )
    produced: list[str] = []
    with _connect(story_dir) as conn:
        # AG3-144: fence FIRST, before any file/row write -- a stale lease
        # rolls back before touching the filesystem or the DB.
        _enforce_ownership_fence_row(
            conn,
            project_key=str(flow_row["project_key"]),
            story_id=story_id,
            run_id=str(flow_row["run_id"]),
            session_id=owner_session_id,
            expected_ownership_epoch=expected_ownership_epoch,
        )
        for item in layer_payload_rows:
            layer = str(item["layer"])
            artifact_name = str(item["artifact_name"])
            payload = cast("_JsonRecord", item["payload"])
            target_dir = projection_dir or story_dir
            _write_projection(target_dir / artifact_name, payload)
            artifact_id = _artifact_id_for(layer, attempt_nr)
            # FK-69: delete old findings for this scope + layer (driver-owned SQL)
            pg_delete_findings_for_scope(
                conn,
                project_key=str(flow_row["project_key"]),
                run_id=str(flow_row["run_id"]),
                attempt_no=attempt_nr,
                stage_id=layer,
            )
            # Rebuild stage_row and finding_rows with the real artifact_id
            stage_row = cast("dict[str, object] | None", item.get("stage_row"))
            finding_rows = cast("list[dict[str, object]]", item.get("finding_rows") or [])
            if stage_row is not None:
                updated_stage = dict(stage_row)
                updated_stage["artifact_id"] = artifact_id
                pg_execute_stage_upsert(conn, updated_stage)
            for fr in finding_rows:
                updated_fr = dict(fr)
                updated_fr["artifact_id"] = artifact_id
                pg_execute_finding_upsert(conn, updated_fr)
            produced.append(artifact_name)
    return tuple(produced)


def persist_verify_decision_row(
    story_dir: Path,
    *,
    flow_row: dict[str, Any] | None,
    decision_row: dict[str, Any],
    canonical_payload: dict[str, object],
    attempt_nr: int,
    owner_session_id: str,
    expected_ownership_epoch: int,
    projection_dir: Path | None = None,
) -> tuple[str, ...]:
    """Persist a verify-decision row and write the projection file.

    AG3-144 (FK-91 §91.1a Rule 15, no-lease-no-write): the AG3-142 fence
    (``_enforce_ownership_fence_row``) is re-verified AT COMMIT TIME, in the
    SAME transaction as the ``decision_records`` upsert, under
    ``SELECT ... FOR UPDATE``, BEFORE the projection file or the row is
    written. The projection-file write is therefore moved INSIDE the fenced
    transaction (it used to precede the connection): a lost lease raises
    :class:`OwnershipFenceViolationError` and writes NEITHER the file NOR the
    row.

    Raises:
        OwnershipFenceViolationError: When the story's active ownership record
            no longer admits this exact ``(flow_row.run_id, owner_session_id,
            expected_ownership_epoch)`` snapshot at commit time.
    """

    story_id = _story_id_for(story_dir)
    if story_id is None:
        raise CorruptStateError(
            "Cannot persist verify decision without story context in canonical backend",
        )
    if flow_row is None:
        raise CorruptStateError(
            "Cannot persist verify decision artifact without flow execution scope in canonical Postgres backend",
        )
    target_dir = projection_dir or story_dir
    written = (VERIFY_DECISION_FILE,)
    with _connect(story_dir) as conn:
        # AG3-144: fence FIRST, before the projection file or the row is
        # written -- a stale lease rolls back before any state write.
        _enforce_ownership_fence_row(
            conn,
            project_key=str(flow_row["project_key"]),
            story_id=story_id,
            run_id=str(flow_row["run_id"]),
            session_id=owner_session_id,
            expected_ownership_epoch=expected_ownership_epoch,
        )
        _write_projection(target_dir / VERIFY_DECISION_FILE, canonical_payload)
        recorded_at = datetime.fromisoformat(now_iso())
        conn.execute(
            """
            INSERT INTO decision_records (
                project_key, story_id, run_id, flow_id, decision_kind,
                attempt_nr, status, passed, summary, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_key, run_id, decision_kind, attempt_nr)
            DO UPDATE SET
                story_id=excluded.story_id,
                flow_id=excluded.flow_id,
                status=excluded.status,
                passed=excluded.passed,
                summary=excluded.summary,
                payload_json=excluded.payload_json,
                created_at=excluded.created_at
            """,
            (
                flow_row["project_key"],
                story_id,
                flow_row["run_id"],
                flow_row["flow_id"],
                "verify",
                attempt_nr,
                decision_row["status"],
                1 if decision_row["passed"] else 0,
                decision_row["summary"],
                _dump_json(canonical_payload),
                recorded_at.isoformat(),
            ),
        )
    return written


def load_latest_verify_decision_payload(
    story_dir: Path,
) -> dict[str, object] | None:
    """Return the latest verify-decision payload dict, or None."""

    story_id = _story_id_for(story_dir)
    if story_id is None:
        return None
    flow_row = load_flow_execution_row(story_dir)
    with _connect(story_dir) as conn:
        if flow_row is not None:
            row = conn.execute(
                """
                SELECT payload_json
                FROM decision_records
                WHERE project_key = ? AND story_id = ? AND run_id = ?
                  AND decision_kind = 'verify'
                ORDER BY attempt_nr DESC
                LIMIT 1
                """,
                (flow_row["project_key"], flow_row["story_id"], flow_row["run_id"]),
            ).fetchone()
            if row is None:
                row = conn.execute(
                    """
                    SELECT payload_json
                    FROM decision_records
                    WHERE story_id = ? AND decision_kind = 'verify'
                    ORDER BY attempt_nr DESC
                    LIMIT 1
                    """,
                    (story_id,),
                ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT payload_json
                FROM decision_records
                WHERE story_id = ? AND decision_kind = 'verify'
                ORDER BY attempt_nr DESC
                LIMIT 1
                """,
                (story_id,),
            ).fetchone()
    if row is None:
        return None
    try:
        return _cast_json_record(json.loads(str(row["payload_json"])))
    except json.JSONDecodeError as exc:
        raise CorruptStateError(
            f"decision_records payload is invalid in {_database_label()}: {exc}",
        ) from exc


def load_latest_verify_decision_payload_for_scope(
    scope: RuntimeStateScope,
) -> dict[str, object] | None:
    """Return the latest verify-decision payload for a scope, or None."""

    with _connect(scope.story_dir) as conn:
        row = conn.execute(
            """
            SELECT payload_json
            FROM decision_records
            WHERE project_key = ? AND story_id = ? AND run_id = ?
              AND decision_kind = 'verify'
            ORDER BY attempt_nr DESC
            LIMIT 1
            """,
            (scope.project_key, scope.story_id, scope.run_id),
        ).fetchone()
    if row is None:
        return None
    try:
        return _cast_json_record(json.loads(str(row["payload_json"])))
    except json.JSONDecodeError as exc:
        raise CorruptStateError(
            f"decision_records payload is invalid in {_database_label()}: {exc}",
        ) from exc


def load_artifact_record_payload(
    story_dir: Path,
    artifact_kind: str,
) -> dict[str, object] | None:
    """Return the latest QA artifact payload from artifact_envelopes for a kind.

    Maps artifact_kind ("structural"/"semantic"/"adversarial") to stage
    "qa-layer-{kind}" and reads from artifact_envelopes (AG3-023 3.4.0).
    Uses run_id from current flow execution when available for scoped lookup.
    """
    story_id = _story_id_for(story_dir)
    if story_id is None:
        return None
    stage = f"qa-layer-{artifact_kind}"
    flow_row = load_flow_execution_row(story_dir)
    with _connect(story_dir) as conn:
        if flow_row is not None:
            row = conn.execute(
                """
                SELECT payload_json
                FROM artifact_envelopes
                WHERE story_id = ? AND run_id = ? AND stage = ?
                ORDER BY attempt DESC
                LIMIT 1
                """,
                (story_id, flow_row["run_id"], stage),
            ).fetchone()
            if row is None:
                row = conn.execute(
                    """
                    SELECT payload_json
                    FROM artifact_envelopes
                    WHERE story_id = ? AND stage = ?
                    ORDER BY attempt DESC
                    LIMIT 1
                    """,
                    (story_id, stage),
                ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT payload_json
                FROM artifact_envelopes
                WHERE story_id = ? AND stage = ?
                ORDER BY attempt DESC
                LIMIT 1
                """,
                (story_id, stage),
            ).fetchone()
    if row is None:
        return None
    raw = row["payload_json"]
    if raw is None:
        return None
    try:
        result = raw if isinstance(raw, dict) else json.loads(str(raw))
        return _cast_json_record(result)
    except json.JSONDecodeError as exc:
        raise CorruptStateError(
            f"artifact_envelopes payload is invalid in {_database_label()}: {exc}",
        ) from exc


def load_artifact_record_payload_for_scope(
    scope: RuntimeStateScope,
    artifact_kind: str,
) -> dict[str, object] | None:
    """Return the latest artifact payload for a scope and kind from artifact_envelopes."""

    stage = f"qa-layer-{artifact_kind}"
    with _connect(scope.story_dir) as conn:
        row = conn.execute(
            """
            SELECT payload_json
            FROM artifact_envelopes
            WHERE story_id = ? AND run_id = ? AND stage = ?
            ORDER BY attempt DESC
            LIMIT 1
            """,
            (scope.story_id, scope.run_id, stage),
        ).fetchone()
    if row is None:
        return None
    raw = row["payload_json"]
    if raw is None:
        return None
    try:
        result = raw if isinstance(raw, dict) else json.loads(str(raw))
        return _cast_json_record(result)
    except json.JSONDecodeError as exc:
        raise CorruptStateError(
            f"artifact_envelopes payload is invalid in {_database_label()}: {exc}",
        ) from exc


def persist_closure_report_row(
    story_dir: Path,
    *,
    flow_row: dict[str, Any] | None,
    report_row: dict[str, Any],
    owner_session_id: str,
    expected_ownership_epoch: int,
    projection_dir: Path | None = None,
) -> Path:
    """Persist a closure-report and write the projection file.

    AG3-144 (FK-91 §91.1a Rule 15, no-lease-no-write): the closure report has
    no dedicated DB row (the projection file IS the persisted artifact), so
    the AG3-142 fence (``_enforce_ownership_fence_row``) is re-verified AT
    COMMIT TIME, under ``SELECT ... FOR UPDATE``, BEFORE the projection file
    is written -- a lost lease raises :class:`OwnershipFenceViolationError`
    and writes NOTHING.

    Codex round-2 TOCTOU fix: the row lock MUST span the file write, not just
    the fence check. The prior shape opened a SEPARATE ``with _connect(...)``
    block for the fence, exited it (releasing the row lock and committing),
    and only THEN wrote the projection file -- a takeover landing in the
    window between the lock release and the file write let the ex-owner still
    write the closure report. The file write now happens INSIDE the SAME
    ``with _connect(...)`` block, after the fence call, so the
    ``run_ownership_records`` row lock is held (via ``SELECT ... FOR UPDATE``)
    for the file write's entire duration and is only released when this
    function's transaction commits -- there is no window between "fence
    passed" and "file written" for a takeover to land in.

    Raises:
        OwnershipFenceViolationError: When the story's active ownership record
            no longer admits this exact ``(flow_row.run_id, owner_session_id,
            expected_ownership_epoch)`` snapshot at commit time.
    """

    if flow_row is None:
        raise CorruptStateError(
            "Cannot persist closure artifact without flow execution scope in canonical Postgres backend",
        )
    story_id = _story_id_for(story_dir)
    if story_id is None:
        raise CorruptStateError(
            "Cannot persist closure artifact without story context in canonical backend",
        )
    target_dir = projection_dir or story_dir
    path = target_dir / CLOSURE_REPORT_FILE
    payload = cast("_JsonRecord", report_row["payload"])
    with _connect(story_dir) as conn:
        # AG3-144: fence FIRST -- no DB row is written for the closure report
        # (the projection file IS the artifact), so the fence transaction's
        # sole purpose is to reject a lost lease BEFORE the file write below.
        _enforce_ownership_fence_row(
            conn,
            project_key=str(flow_row["project_key"]),
            story_id=story_id,
            run_id=str(flow_row["run_id"]),
            session_id=owner_session_id,
            expected_ownership_epoch=expected_ownership_epoch,
        )
        # Codex round-2: the file write stays INSIDE the fenced transaction so
        # the row lock spans it -- no TOCTOU window between the fence and the
        # write (see the docstring above).
        _write_projection(path, payload)
    return path
