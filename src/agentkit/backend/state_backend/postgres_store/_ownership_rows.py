"""Run ownership, edge-command, push synchronization, claim, transfer, and lock rows."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agentkit.backend.exceptions import (
    EdgeCommandNotOpenError,
)

from ._connection import (
    _connect_global,
)
from ._mutation_commit_rows import (
    _conditional_upsert_control_plane_op_row,
    _enforce_ownership_fence_row,
)

if TYPE_CHECKING:
    from ._compat import _CompatConnection


def _insert_run_ownership_record_row(conn: _CompatConnection, row: dict[str, Any]) -> None:
    """Strictly INSERT one run-ownership row on an EXISTING connection (AG3-142).

    A plain ``INSERT`` (no ``ON CONFLICT``): a duplicate identity
    ``(project_key, story_id, run_id)`` OR a second ``status='active'`` row for
    the same ``(project_key, story_id)`` fails deterministically with a
    constraint violation (the primary key resp. the
    ``run_ownership_records_active_uidx`` partial-unique index). There is no
    silent overwrite and no application-side check — the persistence layer is the
    single enforcer of ``at_most_one_active_ownership_per_story`` (FK-56 §56.8a,
    AK1). The idempotent backfill uses its own ``ON CONFLICT DO NOTHING`` path.

    Raises:
        psycopg.errors.UniqueViolation: On a duplicate identity or a second
            active ownership record for the same story (fail-closed).
    """

    conn.execute(
        """
        INSERT INTO run_ownership_records (
            project_key, story_id, run_id, owner_session_id,
            ownership_epoch, status, acquired_via, acquired_at, audit_ref
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row["project_key"],
            row["story_id"],
            row["run_id"],
            row["owner_session_id"],
            row["ownership_epoch"],
            row["status"],
            row["acquired_via"],
            row["acquired_at"],
            row["audit_ref"],
        ),
    )


def insert_run_ownership_record_global_row(row: dict[str, Any]) -> None:
    """Strictly INSERT one run-ownership row on a FRESH connection (AG3-137).

    Standalone entrypoint (AG3-137 backfill / test seeding); the AG3-142
    productive setup-start writer inserts atomically WITHIN the
    ``finalize_control_plane_start_phase_global_row`` transaction instead (see
    ``ownership_row_to_insert``), never via this standalone call.

    Raises:
        psycopg.errors.UniqueViolation: On a duplicate identity or a second
            active ownership record for the same story (fail-closed).
    """

    with _connect_global() as conn:
        _insert_run_ownership_record_row(conn, row)


def load_run_ownership_record_global_row(
    project_key: str,
    story_id: str,
    run_id: str,
) -> dict[str, Any] | None:
    """Return the raw run-ownership row for one run identity, or None."""

    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT * FROM run_ownership_records
            WHERE project_key = ? AND story_id = ? AND run_id = ?
            """,
            (project_key, story_id, run_id),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


def load_active_run_ownership_record_global_row(
    project_key: str,
    story_id: str,
) -> dict[str, Any] | None:
    """Return the raw ACTIVE run-ownership row for a story, or None.

    At most one active row can exist per ``(project_key, story_id)``
    (partial-unique), so this returns a single row.
    """

    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT * FROM run_ownership_records
            WHERE project_key = ? AND story_id = ? AND status = 'active'
            """,
            (project_key, story_id),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


# ---------------------------------------------------------------------------
# ExecutionContractDigestRecord rows (AG3-143, Postgres-only K5)
# ---------------------------------------------------------------------------


def _insert_execution_contract_digest_row(
    conn: _CompatConnection,
    row: dict[str, Any],
) -> None:
    """Strictly INSERT one execution-contract-digest row on an EXISTING connection.

    A plain ``INSERT`` (no ``ON CONFLICT``): a duplicate identity
    ``(project_key, story_id, run_id)`` fails deterministically with a
    primary-key violation -- there is no silent overwrite and no
    application-side check (FK-44 §44.3a: read-only after insert).

    Raises:
        psycopg.errors.UniqueViolation: On a duplicate identity (fail-closed).
    """

    conn.execute(
        """
        INSERT INTO execution_contract_digests (
            project_key, story_id, run_id, execution_contract_digest,
            digest_format_version, formed_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            row["project_key"],
            row["story_id"],
            row["run_id"],
            row["execution_contract_digest"],
            row["digest_format_version"],
            row["formed_at"],
        ),
    )


def insert_execution_contract_digest_global_row(row: dict[str, Any]) -> None:
    """Strictly INSERT one execution-contract-digest row on a FRESH connection.

    Standalone entrypoint (test seeding); the productive setup-start writer
    inserts atomically WITHIN the
    ``finalize_control_plane_start_phase_global_row`` transaction instead
    (see ``execution_contract_digest_row_to_insert``), never via this
    standalone call.

    Raises:
        psycopg.errors.UniqueViolation: On a duplicate identity (fail-closed).
    """

    with _connect_global() as conn:
        _insert_execution_contract_digest_row(conn, row)


def load_execution_contract_digest_global_row(
    project_key: str,
    story_id: str,
    run_id: str,
) -> dict[str, Any] | None:
    """Return the raw execution-contract-digest row for one run, or None.

    Lock-free (FK-44 §44.3a: the digest fence predicate never takes a lock).
    """

    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT * FROM execution_contract_digests
            WHERE project_key = ? AND story_id = ? AND run_id = ?
            """,
            (project_key, story_id, run_id),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


# ---------------------------------------------------------------------------
# EdgeCommandRecord rows (AG3-145, Postgres-only K5)
# ---------------------------------------------------------------------------


def insert_edge_command_record_global_row(row: dict[str, Any]) -> None:
    """Strictly INSERT one edge-command row (AG3-145 command creation).

    A plain ``INSERT``: a duplicate ``command_id`` fails deterministically
    with a primary-key violation (fail-closed, no silent overwrite).

    Raises:
        psycopg.errors.UniqueViolation: On a duplicate ``command_id``.
    """

    with _connect_global() as conn:
        conn.execute(
            """
            INSERT INTO edge_command_records (
                command_id, project_key, story_id, run_id, session_id,
                command_kind, payload_json, status, ownership_epoch,
                created_at, delivered_at, completed_at, result_op_id,
                result_type, result_payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["command_id"],
                row["project_key"],
                row["story_id"],
                row["run_id"],
                row["session_id"],
                row["command_kind"],
                row["payload_json"],
                row["status"],
                row["ownership_epoch"],
                row["created_at"],
                row["delivered_at"],
                row["completed_at"],
                row["result_op_id"],
                row["result_type"],
                row["result_payload_json"],
            ),
        )


def commission_edge_command_record_global_row(row: dict[str, Any]) -> bool:
    """Atomically INSERT one edge-command row if absent (AG3-145 commissioning).

    ``INSERT ... ON CONFLICT (command_id) DO NOTHING`` (mirrors
    :func:`acquire_object_mutation_claim_global_row`): a CONCURRENT double
    commissioning of the SAME deterministic ``command_id`` collides on the
    primary key and is a NO-OP, never a ``UniqueViolation``. Exactly one caller
    inserts (``True``); a duplicate returns ``False`` (the command already
    exists, one visible command / no error -- FK-10 §10.5.3 idempotency).

    Returns:
        ``True`` iff THIS call inserted the row; ``False`` when the deterministic
        ``command_id`` already exists.
    """

    with _connect_global() as conn:
        cursor = conn.execute(
            """
            INSERT INTO edge_command_records (
                command_id, project_key, story_id, run_id, session_id,
                command_kind, payload_json, status, ownership_epoch,
                created_at, delivered_at, completed_at, result_op_id,
                result_type, result_payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (command_id) DO NOTHING
            """,
            (
                row["command_id"],
                row["project_key"],
                row["story_id"],
                row["run_id"],
                row["session_id"],
                row["command_kind"],
                row["payload_json"],
                row["status"],
                row["ownership_epoch"],
                row["created_at"],
                row["delivered_at"],
                row["completed_at"],
                row["result_op_id"],
                row["result_type"],
                row["result_payload_json"],
            ),
        )
        return int(cursor.rowcount) == 1


def load_edge_command_record_global_row(command_id: str) -> dict[str, Any] | None:
    """Return the raw edge-command row for one ``command_id``, or ``None``."""

    with _connect_global() as conn:
        row = conn.execute(
            "SELECT * FROM edge_command_records WHERE command_id = ?",
            (command_id,),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


def list_and_ack_open_edge_command_records_global_row(
    *,
    project_key: str,
    run_id: str,
    session_id: str,
    delivered_at: str,
) -> list[dict[str, Any]]:
    """Return the session's open commands and ack delivery, atomically (AG3-145).

    FK-91 §91.1a Rule 13 ("Reads nehmen niemals Sperren"): this stamps
    ``status='delivered'``/``delivered_at`` on a FIRST-time (``created``) row
    as part of the SAME read -- an audit ack, not an object-mutation claim; it
    takes no durable lock and never blocks a concurrent caller. An
    already-delivered row is left untouched (its FIRST ``delivered_at`` is
    preserved, never overwritten by a later re-fetch). Scoped by
    ``(project_key, run_id, session_id)`` -- a foreign session (or a mismatched
    ``project_key``) matches zero rows, fail-closed by construction (AC1).
    """

    with _connect_global() as conn:
        conn.execute(
            """
            UPDATE edge_command_records
            SET status = 'delivered', delivered_at = ?
            WHERE project_key = ? AND run_id = ? AND session_id = ?
              AND status = 'created'
            """,
            (delivered_at, project_key, run_id, session_id),
        )
        rows = conn.execute(
            """
            SELECT * FROM edge_command_records
            WHERE project_key = ? AND run_id = ? AND session_id = ?
              AND status IN ('created', 'delivered')
            ORDER BY created_at, command_id
            """,
            (project_key, run_id, session_id),
        ).fetchall()
    return [dict(row) for row in rows]


def commit_edge_command_result_global_row(
    *,
    op_row: dict[str, Any],
    command_id: str,
    result_row: dict[str, Any],
    expected_ownership_epoch: int,
) -> None:
    """Atomically commit the op-ledger row AND the command-result CAS (AG3-145).

    Mirrors ``commit_control_plane_operation_with_side_effects_global_row``:
    the SAME collision-gated op-row upsert (idempotency ledger, Rule 5) plus
    the Rule-15 ownership fence (``_enforce_ownership_fence_row``, reused
    verbatim -- the AG3-142 fence surface) in ONE transaction, followed by the
    actual side effect -- a conditional UPDATE of the command row from an
    OPEN status to its terminal result. The UPDATE is a CAS on
    ``status IN ('created', 'delivered')``: a caller targeting an unknown
    ``command_id`` or one that is ALREADY terminal affects zero rows, which
    raises :class:`EdgeCommandNotOpenError` and rolls back the WHOLE
    transaction (including the op-row insert) -- no orphan idempotency-ledger
    entry for a rejected command-result attempt.

    Raises:
        ControlPlaneClaimCollisionError: On an op_id collision with a LIVE
            claimed row (never expected on this one-shot commit shape).
        OwnershipFenceViolationError: (AG3-142 reuse) When the story's active
            ownership record no longer admits this exact snapshot.
        EdgeCommandNotOpenError: When ``command_id`` is unknown or already
            terminal (double-completion) -- nothing committed.
    """

    with _connect_global() as conn:
        _conditional_upsert_control_plane_op_row(conn, op_row)
        _enforce_ownership_fence_row(
            conn,
            project_key=str(op_row["project_key"]),
            story_id=str(op_row["story_id"]),
            run_id=str(op_row["run_id"]),
            session_id=str(op_row["session_id"]),
            expected_ownership_epoch=expected_ownership_epoch,
        )
        cursor = conn.execute(
            """
            UPDATE edge_command_records
            SET status = ?, completed_at = ?, result_op_id = ?,
                result_type = ?, result_payload_json = ?
            WHERE command_id = ? AND status IN ('created', 'delivered')
            """,
            (
                result_row["status"],
                result_row["completed_at"],
                result_row["result_op_id"],
                result_row["result_type"],
                result_row["result_payload_json"],
                command_id,
            ),
        )
        if cursor.rowcount == 0:
            raise EdgeCommandNotOpenError(command_id)


def supersede_open_edge_command_global_row(
    *,
    command_id: str,
    completed_at: str,
    result_payload_json: str,
) -> bool:
    """Terminalize an open edge command superseded by a newer boundary epoch."""

    with _connect_global() as conn:
        cursor = conn.execute(
            """
            UPDATE edge_command_records
            SET status = 'superseded',
                completed_at = ?,
                result_type = 'command_superseded',
                result_payload_json = ?
            WHERE command_id = ? AND status IN ('created', 'delivered')
            """,
            (completed_at, result_payload_json, command_id),
        )
        return int(cursor.rowcount) == 1


# ---------------------------------------------------------------------------
# PushFreshnessRecord rows (AG3-147, Postgres-only K5)
# ---------------------------------------------------------------------------


def upsert_push_freshness_record_global_row(row: dict[str, Any]) -> None:
    """Upsert one push-freshness row per ``(project, story, run, repo)`` (AG3-147).

    Last-writer-wins per repo: the caller (control-plane runtime) computes the
    next projected record from the loaded previous row (``project_push_freshness``,
    the A-core) and persists it here. Freshness / silence is INFORMATION only --
    this write never triggers an ownership transition (AC5).
    """

    with _connect_global() as conn:
        conn.execute(
            """
            INSERT INTO push_freshness_records (
                project_key, story_id, run_id, repo_id,
                last_reported_head_sha, last_pushed_head_sha, last_reported_at,
                last_sync_point_id, last_command_id, backlog, backlog_detail
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (project_key, story_id, run_id, repo_id) DO UPDATE SET
                last_reported_head_sha = EXCLUDED.last_reported_head_sha,
                last_pushed_head_sha = EXCLUDED.last_pushed_head_sha,
                last_reported_at = EXCLUDED.last_reported_at,
                last_sync_point_id = EXCLUDED.last_sync_point_id,
                last_command_id = EXCLUDED.last_command_id,
                backlog = EXCLUDED.backlog,
                backlog_detail = EXCLUDED.backlog_detail
            """,
            (
                row["project_key"],
                row["story_id"],
                row["run_id"],
                row["repo_id"],
                row["last_reported_head_sha"],
                row["last_pushed_head_sha"],
                row["last_reported_at"],
                row["last_sync_point_id"],
                row["last_command_id"],
                row["backlog"],
                row["backlog_detail"],
            ),
        )


def load_push_freshness_record_global_row(project_key: str, story_id: str, run_id: str, repo_id: str) -> dict[str, Any] | None:
    """Return the raw push-freshness row for one repo, or ``None`` (AG3-147)."""

    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT * FROM push_freshness_records
            WHERE project_key = ? AND story_id = ? AND run_id = ? AND repo_id = ?
            """,
            (project_key, story_id, run_id, repo_id),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


def list_push_freshness_records_global_row(project_key: str, story_id: str, run_id: str) -> list[dict[str, Any]]:
    """Return the run's push-freshness rows, one per repo, ordered (AG3-147)."""

    with _connect_global() as conn:
        rows = conn.execute(
            """
            SELECT * FROM push_freshness_records
            WHERE project_key = ? AND story_id = ? AND run_id = ?
            ORDER BY repo_id
            """,
            (project_key, story_id, run_id),
        ).fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# PushBarrierVerdict rows (AG3-147 redesign, Postgres-only K5)
# ---------------------------------------------------------------------------


def upsert_push_barrier_verdict_global_row(row: dict[str, Any]) -> None:
    """Upsert the authoritative per-repo push-barrier verdict row."""

    with _connect_global() as conn:
        conn.execute(
            """
            INSERT INTO push_barrier_verdicts (
                project_key, story_id, run_id, boundary_type, boundary_id, repo_id,
                producer, boundary_epoch, expected_head_sha, server_head_sha,
                ownership_epoch, status, created_at, updated_at, resolved_at,
                status_detail
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (
                project_key, story_id, run_id, boundary_type, boundary_id, repo_id
            ) DO UPDATE SET
                producer = EXCLUDED.producer,
                boundary_epoch = EXCLUDED.boundary_epoch,
                expected_head_sha = EXCLUDED.expected_head_sha,
                server_head_sha = EXCLUDED.server_head_sha,
                ownership_epoch = EXCLUDED.ownership_epoch,
                status = EXCLUDED.status,
                updated_at = EXCLUDED.updated_at,
                resolved_at = EXCLUDED.resolved_at,
                status_detail = EXCLUDED.status_detail
            """,
            _push_barrier_verdict_params(row),
        )


def load_push_barrier_verdict_global_row(
    project_key: str,
    story_id: str,
    run_id: str,
    boundary_type: str,
    boundary_id: str,
    repo_id: str,
) -> dict[str, Any] | None:
    """Load one push-barrier verdict row, or ``None``."""

    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT * FROM push_barrier_verdicts
            WHERE project_key = ?
              AND story_id = ?
              AND run_id = ?
              AND boundary_type = ?
              AND boundary_id = ?
              AND repo_id = ?
            """,
            (project_key, story_id, run_id, boundary_type, boundary_id, repo_id),
        ).fetchone()
    return dict(row) if row is not None else None


def list_push_barrier_verdicts_global_row(
    project_key: str,
    story_id: str,
    run_id: str,
    boundary_type: str,
    boundary_id: str,
) -> list[dict[str, Any]]:
    """List all repo verdicts for one boundary instance, ordered by repo."""

    with _connect_global() as conn:
        rows = conn.execute(
            """
            SELECT * FROM push_barrier_verdicts
            WHERE project_key = ?
              AND story_id = ?
              AND run_id = ?
              AND boundary_type = ?
              AND boundary_id = ?
            ORDER BY repo_id
            """,
            (project_key, story_id, run_id, boundary_type, boundary_id),
        ).fetchall()
    return [dict(row) for row in rows]


def _push_barrier_verdict_params(row: dict[str, Any]) -> tuple[object, ...]:
    """Return DB parameter order for a push-barrier verdict row."""

    return (
        row["project_key"],
        row["story_id"],
        row["run_id"],
        row["boundary_type"],
        row["boundary_id"],
        row["repo_id"],
        row["producer"],
        row["boundary_epoch"],
        row["expected_head_sha"],
        row["server_head_sha"],
        row["ownership_epoch"],
        row["status"],
        row["created_at"],
        row["updated_at"],
        row["resolved_at"],
        row["status_detail"],
    )


# Ref-protection degradation findings (AG3-147, Postgres-only K5)


def upsert_ref_protection_degradation_finding_global_row(row: dict[str, Any]) -> None:
    """Upsert a project-visible ref-protection degradation WARNING (AG3-147)."""
    with _connect_global() as conn:
        conn.execute(
            """
            INSERT INTO ref_protection_degradation_findings (
                project_key, story_id, repo_id, finding_code, severity,
                provider_label, detail, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (project_key, story_id, repo_id, finding_code)
            DO UPDATE SET
                severity = EXCLUDED.severity,
                provider_label = EXCLUDED.provider_label,
                detail = EXCLUDED.detail,
                recorded_at = EXCLUDED.recorded_at
            """,
            (
                row["project_key"],
                row["story_id"],
                row["repo_id"],
                row["finding_code"],
                row["severity"],
                row["provider_label"],
                row["detail"],
                row["recorded_at"],
            ),
        )


def list_ref_protection_degradation_finding_global_rows(project_key: str, story_id: str) -> list[dict[str, Any]]:
    """Return project-visible ref-protection degradation WARNING rows."""
    with _connect_global() as conn:
        rows = conn.execute(
            """
            SELECT * FROM ref_protection_degradation_findings
            WHERE project_key = ? AND story_id = ?
            ORDER BY repo_id, finding_code
            """,
            (project_key, story_id),
        ).fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# ObjectMutationClaimRecord rows (AG3-137, Postgres-only K5)
# ---------------------------------------------------------------------------


def insert_object_mutation_claim_global_row(row: dict[str, Any]) -> None:
    """Strictly INSERT one object-mutation-claim row (AG3-137).

    Plain ``INSERT``: a duplicate identity
    ``(project_key, serialization_scope, scope_key)`` fails deterministically
    with a primary-key violation (AK2, the claimed object is exclusive). The
    productive claim-acquisition / queue logic is AG3-141.

    Raises:
        psycopg.errors.UniqueViolation: On a duplicate claimed object.
    """

    with _connect_global() as conn:
        conn.execute(
            """
            INSERT INTO object_mutation_claims (
                project_key, serialization_scope, scope_key, op_id,
                backend_instance_id, instance_incarnation, acquired_at,
                queue_position
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["project_key"],
                row["serialization_scope"],
                row["scope_key"],
                row["op_id"],
                row["backend_instance_id"],
                row["instance_incarnation"],
                row["acquired_at"],
                row["queue_position"],
            ),
        )


def load_object_mutation_claim_global_row(
    project_key: str,
    serialization_scope: str,
    scope_key: str,
) -> dict[str, Any] | None:
    """Return the raw object-mutation-claim row for one object, or None."""

    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT * FROM object_mutation_claims
            WHERE project_key = ? AND serialization_scope = ? AND scope_key = ?
            """,
            (project_key, serialization_scope, scope_key),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


def acquire_object_mutation_claim_global_row(row: dict[str, Any]) -> bool:
    """Atomically acquire the per-Story object-mutation claim (AG3-141).

    Serialization is PER MUTATED OBJECT = the Story (FK-91 §91.1a Rule 13,
    default ``(project_key, story_id)``): two mutations of the SAME Story
    collide on the ``object_mutation_claims`` primary key
    ``(project_key, serialization_scope, scope_key)``. A single
    ``INSERT ... ON CONFLICT DO NOTHING`` on that PK IS the serialization --
    exactly one caller inserts (wins); a conflict is the busy/409 case. The PK
    collision is atomic, so no advisory lock and no read-then-write window is
    needed.

    The project-scope / multi-object lock-set / cross-scope fairness /
    ``queue_position`` apparatus was REMOVED as speculative (PO decision, two
    independent reviews): it had no genuine requirement. Project-wide mutations
    (mode-lock, story-number) are single-transaction and stay xact-locked
    (FK-10 §10.5.4). ``queue_position`` is a vestigial
    ``state-storage.entity.object-mutation-claim`` attribute (AG3-137 column)
    with no ordering role here -- it is stamped as a constant ``0``.

    Returns:
        ``True`` iff THIS call now holds the claim; ``False`` when the Story
        object is already claimed by another in-flight mutation -- the caller
        surfaces the deterministic 409 + Retry-After (K4, IMPL-016), never a
        blocking wait.
    """

    with _connect_global() as conn:
        cursor = conn.execute(
            """
            INSERT INTO object_mutation_claims (
                project_key, serialization_scope, scope_key, op_id,
                backend_instance_id, instance_incarnation, acquired_at,
                queue_position
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 0)
            ON CONFLICT (project_key, serialization_scope, scope_key) DO NOTHING
            """,
            (
                row["project_key"],
                row["serialization_scope"],
                row["scope_key"],
                row["op_id"],
                row["backend_instance_id"],
                row["instance_incarnation"],
                row["acquired_at"],
            ),
        )
        #: rowcount == 1 -> THIS caller inserted the claim row (won). rowcount
        #: == 0 -> the object PK already exists (another mutation holds the
        #: Story) -> busy/409. The PK collision IS the serialization.
        return int(cursor.rowcount) == 1


def delete_object_mutation_claim_global(
    project_key: str,
    serialization_scope: str,
    scope_key: str,
    op_id: str,
) -> bool:
    """Ownership-scoped (op_id-CAS) release of one object-mutation claim (AG3-141).

    Deletes the row ONLY when it is still held by *op_id* -- never an
    unconditional delete: a late/duplicate release call after a concurrent
    admin-abort or startup reconciliation already freed the claim (or after a
    DIFFERENT operation has since acquired the same object) is a safe no-op,
    never touching a foreign holder's claim.

    Returns:
        ``True`` iff a row matching ALL of ``(project_key,
        serialization_scope, scope_key, op_id)`` was deleted.
    """

    with _connect_global() as conn:
        cursor = conn.execute(
            """
            DELETE FROM object_mutation_claims
            WHERE project_key = ? AND serialization_scope = ? AND scope_key = ?
              AND op_id = ?
            """,
            (project_key, serialization_scope, scope_key, op_id),
        )
        return int(cursor.rowcount) == 1


def list_orphaned_object_mutation_claims_global_row(
    *,
    backend_instance_id: str,
    before_incarnation: int,
) -> list[dict[str, Any]]:
    """Return object-mutation claims orphaned by EARLIER incarnations of THIS instance.

    Startup reconciliation (AG3-141 Scope item 7, extending the AG3-138
    reconcile scan; ``orphaned_claims_are_finalized_only_by_same_instance_startup_reconciliation_or_admin_abort``):
    a DIRECT scan of ``object_mutation_claims`` (mirrors
    :func:`list_orphaned_claimed_control_plane_operations_global_row` exactly)
    -- independent of whatever happened to the claim's owning
    ``control_plane_operations`` row, so a crash between the durable
    object-claim acquire and the owning operation's own finalize is caught
    even in an edge case where the two rows' lifecycles have diverged (e.g. an
    administrative unconditional delete of the operation row). Claims carrying
    a FOREIGN ``backend_instance_id`` are never returned -- fail-closed, no
    "generous" cleanup of un-attributable claims.
    """

    with _connect_global() as conn:
        rows = conn.execute(
            """
            SELECT * FROM object_mutation_claims
            WHERE backend_instance_id = ?
              AND instance_incarnation < ?
            ORDER BY project_key, serialization_scope, scope_key
            """,
            (backend_instance_id, before_incarnation),
        ).fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# TakeoverTransferRecord rows (AG3-137, Postgres-only K5)
# ---------------------------------------------------------------------------


def save_takeover_transfer_record_global_row(row: dict[str, Any]) -> None:
    """Upsert one takeover-transfer row, keyed per participating repo (AG3-137).

    Identity is ``(project_key, story_id, run_id, ownership_epoch, repo_id)`` —
    one row per repo (state-storage v5). Upsert so the productive writer AG3-148
    can materialise the attributes across the challenge → confirm lifecycle.
    It is not a reconcile-clear API: pre-AG3-151 clears must go through the
    audited runtime ``admin_transition`` unit of work.
    """
    if row.get("reconciled_at") is not None or row.get("reconcile_ref") is not None:
        raise ValueError(
            "takeover reconcile clear requires the audited admin_transition "
            "runtime operation; generic transfer upsert must not write "
            "reconciled_at/reconcile_ref",
        )

    with _connect_global() as conn:
        conn.execute(
            """
            INSERT INTO takeover_transfer_records (
                project_key, story_id, run_id, ownership_epoch, repo_id,
                takeover_base_sha, last_push_at, push_lag_hint, base_quality,
                challenge_ref, confirm_ref, reconciled_at, reconcile_ref
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (project_key, story_id, run_id, ownership_epoch, repo_id)
            DO UPDATE SET
                takeover_base_sha = EXCLUDED.takeover_base_sha,
                last_push_at = EXCLUDED.last_push_at,
                push_lag_hint = EXCLUDED.push_lag_hint,
                base_quality = EXCLUDED.base_quality,
                challenge_ref = EXCLUDED.challenge_ref,
                confirm_ref = EXCLUDED.confirm_ref,
                reconciled_at = EXCLUDED.reconciled_at,
                reconcile_ref = EXCLUDED.reconcile_ref
            """,
            (
                row["project_key"],
                row["story_id"],
                row["run_id"],
                row["ownership_epoch"],
                row["repo_id"],
                row.get("takeover_base_sha"),
                row.get("last_push_at"),
                row.get("push_lag_hint"),
                row.get("base_quality"),
                row.get("challenge_ref"),
                row.get("confirm_ref"),
                row.get("reconciled_at"),
                row.get("reconcile_ref"),
            ),
        )


def load_takeover_transfer_record_global_row(
    project_key: str,
    story_id: str,
    run_id: str,
    ownership_epoch: int,
    repo_id: str,
) -> dict[str, Any] | None:
    """Return the raw takeover-transfer row for one repo identity, or None."""

    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT * FROM takeover_transfer_records
            WHERE project_key = ? AND story_id = ? AND run_id = ?
            AND ownership_epoch = ? AND repo_id = ?
            """,
            (project_key, story_id, run_id, ownership_epoch, repo_id),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


def list_takeover_transfer_records_for_story_global_row(
    project_key: str,
    story_id: str,
) -> list[dict[str, Any]]:
    """Return takeover-transfer rows for one story, newest epoch first."""

    with _connect_global() as conn:
        rows = conn.execute(
            """
            SELECT * FROM takeover_transfer_records
            WHERE project_key = ? AND story_id = ?
            ORDER BY ownership_epoch DESC, repo_id
            """,
            (project_key, story_id),
        ).fetchall()
    return [dict(row) for row in rows]


def insert_takeover_challenge_global_row(row: dict[str, Any]) -> None:
    """Strictly insert one server-minted takeover challenge."""

    with _connect_global() as conn:
        conn.execute(
            """
            INSERT INTO takeover_challenges (
                challenge_id, request_op_id, project_key, story_id, run_id,
                requesting_session_id, requesting_principal_type,
                requesting_worktree_roots_json, reason,
                owner_session_id, ownership_epoch, binding_version, phase_status,
                issued_at, expires_at, repos_json, open_operation_ids_json,
                takeover_history_refs_json, status, decided_at, terminal_op_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            _takeover_challenge_params(row),
        )


def load_takeover_challenge_global_row(challenge_id: str) -> dict[str, Any] | None:
    """Return one takeover challenge row, or None."""

    with _connect_global() as conn:
        row = conn.execute(
            "SELECT * FROM takeover_challenges WHERE challenge_id = ?",
            (challenge_id,),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


def update_takeover_challenge_status_global_row(row: dict[str, Any]) -> bool:
    """Terminalize a pending challenge only."""

    with _connect_global() as conn:
        cursor = conn.execute(
            """
            UPDATE takeover_challenges
            SET status = ?, decided_at = ?, terminal_op_id = ?
            WHERE challenge_id = ? AND status = 'pending'
            """,
            (
                row["status"],
                row["decided_at"],
                row["terminal_op_id"],
                row["challenge_id"],
            ),
        )
        return int(cursor.rowcount) == 1


# ---------------------------------------------------------------------------
# TakeoverApprovalRecord rows (AG3-148, Postgres-only K5)
# ---------------------------------------------------------------------------


def insert_takeover_approval_global_row(row: dict[str, Any]) -> None:
    """Strictly insert one takeover approval request."""

    with _connect_global() as conn:
        conn.execute(
            """
            INSERT INTO takeover_approvals (
                approval_id, project_key, story_id, run_id,
                requested_by_session_id, requested_by_principal_type,
                reason, challenge_ref, status, requested_at, expires_at,
                decided_at, decided_by_session_id, decision_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            _takeover_approval_params(row),
        )


def load_takeover_approval_global_row(approval_id: str) -> dict[str, Any] | None:
    """Return one takeover approval row, or None."""

    with _connect_global() as conn:
        row = conn.execute(
            "SELECT * FROM takeover_approvals WHERE approval_id = ?",
            (approval_id,),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


def load_takeover_approval_for_challenge_global_row(
    challenge_id: str,
) -> dict[str, Any] | None:
    """Return the at-most-one approval linked to a challenge, or None."""

    with _connect_global() as conn:
        row = conn.execute(
            "SELECT * FROM takeover_approvals WHERE challenge_ref = ?",
            (challenge_id,),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


def update_takeover_approval_status_global_row(row: dict[str, Any]) -> bool:
    """Update one approval status if the row still exists."""

    with _connect_global() as conn:
        cursor = conn.execute(
            """
            UPDATE takeover_approvals
            SET status = ?, decided_at = ?, decided_by_session_id = ?,
                decision_reason = ?
            WHERE approval_id = ?
              AND status = 'pending'
            """,
            (
                row["status"],
                row["decided_at"],
                row["decided_by_session_id"],
                row["decision_reason"],
                row["approval_id"],
            ),
        )
        return int(cursor.rowcount) == 1


def list_pending_takeover_approval_rows_global(project_key: str | None = None) -> list[dict[str, Any]]:
    """Return pending approval rows, oldest first."""

    with _connect_global() as conn:
        if project_key is None:
            rows = conn.execute(
                """
                SELECT * FROM takeover_approvals
                WHERE status = 'pending'
                ORDER BY requested_at, approval_id
                """,
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM takeover_approvals
                WHERE status = 'pending' AND project_key = ?
                ORDER BY requested_at, approval_id
                """,
                (project_key,),
            ).fetchall()
    return [dict(row) for row in rows]


def list_verified_push_barrier_verdicts_for_run_global_row(
    project_key: str,
    story_id: str,
    run_id: str,
) -> list[dict[str, Any]]:
    """List the latest passed push-barrier verdict for each repo in a run."""

    with _connect_global() as conn:
        rows = conn.execute(
            """
            SELECT verdicts.*
            FROM push_barrier_verdicts verdicts
            JOIN (
                SELECT repo_id, MAX(updated_at) AS updated_at
                FROM push_barrier_verdicts
                WHERE project_key = ?
                  AND story_id = ?
                  AND run_id = ?
                  AND status = 'passed'
                  AND expected_head_sha IS NOT NULL
                  AND expected_head_sha <> ''
                GROUP BY repo_id
            ) latest
              ON latest.repo_id = verdicts.repo_id
             AND latest.updated_at = verdicts.updated_at
            WHERE verdicts.project_key = ?
              AND verdicts.story_id = ?
              AND verdicts.run_id = ?
              AND verdicts.status = 'passed'
              AND verdicts.expected_head_sha IS NOT NULL
              AND verdicts.expected_head_sha <> ''
            ORDER BY verdicts.repo_id
            """,
            (project_key, story_id, run_id, project_key, story_id, run_id),
        ).fetchall()
    return [dict(row) for row in rows]


def _takeover_approval_params(row: dict[str, Any]) -> tuple[object, ...]:
    """Return DB parameter order for a takeover approval row."""

    return (
        row["approval_id"],
        row["project_key"],
        row["story_id"],
        row["run_id"],
        row["requested_by_session_id"],
        row["requested_by_principal_type"],
        row["reason"],
        row["challenge_ref"],
        row["status"],
        row["requested_at"],
        row["expires_at"],
        row["decided_at"],
        row["decided_by_session_id"],
        row["decision_reason"],
    )


def _takeover_challenge_params(row: dict[str, Any]) -> tuple[object, ...]:
    """Return DB parameter order for a takeover challenge row."""

    return (
        row["challenge_id"],
        row["request_op_id"],
        row["project_key"],
        row["story_id"],
        row["run_id"],
        row["requesting_session_id"],
        row["requesting_principal_type"],
        row["requesting_worktree_roots_json"],
        row["reason"],
        row["owner_session_id"],
        row["ownership_epoch"],
        row["binding_version"],
        row["phase_status"],
        row["issued_at"],
        row["expires_at"],
        row["repos_json"],
        row["open_operation_ids_json"],
        row["takeover_history_refs_json"],
        row["status"],
        row["decided_at"],
        row["terminal_op_id"],
    )


# ---------------------------------------------------------------------------
# BackendInstanceIdentityRecord rows (AG3-137, Postgres-only K5)
# ---------------------------------------------------------------------------


def save_backend_instance_identity_global_row(row: dict[str, Any]) -> None:
    """Upsert the persistent backend-instance-identity row (AG3-137, IMPL-004)."""

    with _connect_global() as conn:
        conn.execute(
            """
            INSERT INTO backend_instance_identity (
                backend_instance_id, instance_incarnation, updated_at
            ) VALUES (?, ?, ?)
            ON CONFLICT (backend_instance_id) DO UPDATE SET
                instance_incarnation = EXCLUDED.instance_incarnation,
                updated_at = EXCLUDED.updated_at
            """,
            (
                row["backend_instance_id"],
                row["instance_incarnation"],
                row["updated_at"],
            ),
        )


def load_backend_instance_identity_global_row(
    backend_instance_id: str,
) -> dict[str, Any] | None:
    """Return the raw backend-instance-identity row, or None."""

    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT * FROM backend_instance_identity
            WHERE backend_instance_id = ?
            """,
            (backend_instance_id,),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


#: Advisory-lock key for the boot-time instance-identity resolution (AG3-138).
#: Serializes the read-generate/increment-write sequence against a concurrent
#: boot of the same database (defense in depth; the normative operating
#: assumption is a single active writer instance, FK-10 §10.5.4).
_BACKEND_INSTANCE_IDENTITY_BOOT_LOCK_KEY = "agentkit_backend_instance_identity_boot"


class BackendInstanceIdentitySingletonError(RuntimeError):
    """Raised when ``backend_instance_identity`` unexpectedly holds >1 row.

    The table is a per-installation singleton (AG3-137 schema, AG3-138 boot
    logic): exactly zero or one row is ever written. Finding more than one is a
    schema-invariant violation -- fail-closed rather than guessing which row is
    "the" installation identity.
    """


def boot_backend_instance_identity_global_row(
    *,
    candidate_backend_instance_id: str,
    now: str,
) -> dict[str, Any]:
    """Atomically resolve the boot-time backend instance identity (AG3-138, IMPL-004).

    Under an advisory transaction lock (serialized against a concurrent boot of
    the same database): reads the (at most one) existing
    ``backend_instance_identity`` row.

    * No row exists yet -- this is the FIRST boot ever for this installation:
      insert ``candidate_backend_instance_id`` with ``instance_incarnation = 1``.
    * A row exists -- ``backend_instance_id`` is STABLE across restarts (AC3):
      the EXISTING id is kept unchanged and ``instance_incarnation`` is
      incremented by exactly 1 (monotone, deterministic, no wall-clock input).

    Args:
        candidate_backend_instance_id: The id to use ONLY on a genuine first
            boot (a fresh, unused identity generated by the caller, e.g. a
            uuid4 hex string). Ignored when an installation identity already
            exists.
        now: The ``updated_at`` instant to stamp (ISO-8601 TEXT), matching the
            table's other instant columns.

    Returns:
        The resulting raw row (the stable ``backend_instance_id`` and the new
        ``instance_incarnation``).

    Raises:
        BackendInstanceIdentitySingletonError: When the table unexpectedly
            holds more than one row (schema-invariant violation).
    """

    with _connect_global() as conn:
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            (_BACKEND_INSTANCE_IDENTITY_BOOT_LOCK_KEY,),
        )
        rows = conn.execute(
            "SELECT * FROM backend_instance_identity LIMIT 2",
        ).fetchall()
        if len(rows) > 1:
            raise BackendInstanceIdentitySingletonError(
                "backend_instance_identity holds more than one row; the table "
                "is a per-installation singleton (AG3-137/AG3-138) -- refusing "
                "to guess which row is the installation identity (fail-closed).",
            )
        if not rows:
            conn.execute(
                """
                INSERT INTO backend_instance_identity (
                    backend_instance_id, instance_incarnation, updated_at
                ) VALUES (?, ?, ?)
                """,
                (candidate_backend_instance_id, 1, now),
            )
            return {
                "backend_instance_id": candidate_backend_instance_id,
                "instance_incarnation": 1,
                "updated_at": now,
            }
        existing = dict(rows[0])
        next_incarnation = int(existing["instance_incarnation"]) + 1
        conn.execute(
            """
            UPDATE backend_instance_identity
            SET instance_incarnation = ?, updated_at = ?
            WHERE backend_instance_id = ?
            """,
            (next_incarnation, now, existing["backend_instance_id"]),
        )
        return {
            "backend_instance_id": existing["backend_instance_id"],
            "instance_incarnation": next_incarnation,
            "updated_at": now,
        }


# ---------------------------------------------------------------------------
# StoryExecutionLockRecord rows
# ---------------------------------------------------------------------------


def save_story_execution_lock_global_row(row: dict[str, Any]) -> None:
    """Persist a story-execution-lock row dict globally."""

    with _connect_global() as conn:
        conn.execute(
            """
            INSERT INTO story_execution_locks (
                project_key, story_id, run_id, lock_type, status,
                worktree_roots_json, binding_version, activated_at,
                updated_at, deactivated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (project_key, story_id, run_id, lock_type) DO UPDATE SET
                story_id = EXCLUDED.story_id,
                status = EXCLUDED.status,
                worktree_roots_json = EXCLUDED.worktree_roots_json,
                binding_version = EXCLUDED.binding_version,
                activated_at = EXCLUDED.activated_at,
                updated_at = EXCLUDED.updated_at,
                deactivated_at = EXCLUDED.deactivated_at
            """,
            (
                row["project_key"],
                row["story_id"],
                row["run_id"],
                row["lock_type"],
                row["status"],
                row["worktree_roots_json"],
                row["binding_version"],
                row["activated_at"],
                row["updated_at"],
                row["deactivated_at"],
            ),
        )


def load_story_execution_lock_global_row(
    project_key: str,
    story_id: str,
    run_id: str,
    lock_type: str = "story_execution",
) -> dict[str, Any] | None:
    """Return the raw story-execution-lock row, or None."""

    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT * FROM story_execution_locks
            WHERE project_key = ? AND story_id = ? AND run_id = ? AND lock_type = ?
            """,
            (project_key, story_id, run_id, lock_type),
        ).fetchone()
    if row is None:
        return None
    return dict(row)
