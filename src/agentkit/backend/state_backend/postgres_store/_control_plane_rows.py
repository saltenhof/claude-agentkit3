"""Control-plane operation rows and same-transaction mutation orchestration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agentkit.backend.exceptions import (
    ControlPlaneBindingCollisionError,
    ControlPlaneClaimCollisionError,
    OwnershipFenceViolationError,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ._compat import _CompatConnection


from ._connection import (
    _connect_global,
)
from ._mutation_commit_rows import (
    _conditional_upsert_control_plane_op_row,
    _enforce_ownership_fence_row,
)
from ._ownership_rows import (
    _insert_execution_contract_digest_row,
    _insert_run_ownership_record_row,
)
from ._runtime_rows import _insert_execution_event_row


def save_control_plane_operation_global_row(row: dict[str, Any]) -> None:
    """Persist a control-plane-operation row dict globally.

    NOTE (AG3-054): this is the legacy upsert kept for direct test/contract use.
    The PRODUCTIVE terminal write goes through
    :func:`finalize_control_plane_operation_global_row` (ownership-scoped CAS), so
    a non-owner can never clobber a terminal/foreign row. The upsert always clears
    ``claimed_by`` (a stored row carries no live owner once it is saved as a
    terminal result).

    ERROR-3 fix (AG3-054): the upsert is CONDITIONAL -- it REFUSES to overwrite a
    row whose ``status='claimed'`` (a live, owned claim). Only the owner's
    ownership-scoped finalize/release may transition a claimed row. So a
    ``complete_phase`` / ``fail_phase`` (or any non-owner save) reusing a live
    ``start_phase`` op_id can no longer overwrite the claimed row and steal/destroy
    its ownership. The collision is surfaced fail-closed via
    :class:`ControlPlaneClaimCollisionError` (NO ERROR BYPASSING -- it is never a
    silent no-op). A fresh insert and an update of a TERMINAL (non-claimed) row are
    unaffected.

    Raises:
        ControlPlaneClaimCollisionError: When the row already exists and is still
            ``claimed`` (the upsert would have clobbered a live claim).
    """

    with _connect_global() as conn:
        cursor = conn.execute(
            """
            INSERT INTO control_plane_operations (
                op_id, project_key, story_id, run_id, session_id,
                operation_kind, phase, status, response_json,
                created_at, updated_at, claimed_by, claimed_at,
                operation_epoch, backend_instance_id, instance_incarnation,
                declared_serialization_scope, finalized_at, request_body_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (op_id) DO UPDATE SET
                project_key = EXCLUDED.project_key,
                story_id = EXCLUDED.story_id,
                run_id = EXCLUDED.run_id,
                session_id = EXCLUDED.session_id,
                operation_kind = EXCLUDED.operation_kind,
                phase = EXCLUDED.phase,
                status = EXCLUDED.status,
                response_json = EXCLUDED.response_json,
                updated_at = EXCLUDED.updated_at,
                claimed_by = EXCLUDED.claimed_by,
                claimed_at = EXCLUDED.claimed_at,
                operation_epoch = EXCLUDED.operation_epoch,
                backend_instance_id = EXCLUDED.backend_instance_id,
                instance_incarnation = EXCLUDED.instance_incarnation,
                declared_serialization_scope =
                    EXCLUDED.declared_serialization_scope,
                finalized_at = EXCLUDED.finalized_at,
                request_body_hash = EXCLUDED.request_body_hash
            WHERE control_plane_operations.status <> 'claimed'
            """,
            (
                row["op_id"],
                row["project_key"],
                row["story_id"],
                row["run_id"],
                row["session_id"],
                row["operation_kind"],
                row["phase"],
                row["status"],
                row["response_json"],
                row["created_at"],
                row["updated_at"],
                row.get("claimed_by"),
                row.get("claimed_at"),
                row.get("operation_epoch"),
                row.get("backend_instance_id"),
                row.get("instance_incarnation"),
                row.get("declared_serialization_scope"),
                row.get("finalized_at"),
                # AG3-140: carry the body-hash on the terminal upsert too.
                row.get("request_body_hash"),
            ),
        )
        # rowcount == 1 on a fresh insert or a qualifying (non-claimed) update;
        # rowcount == 0 ONLY when the conflicting row is still ``claimed`` and the
        # WHERE blocked the overwrite. Fail-closed: a live claimed row was hit.
        if int(cursor.rowcount) == 0:
            raise ControlPlaneClaimCollisionError(
                "control-plane operation save refused: op_id "
                f"{row['op_id']!r} is held by a LIVE 'claimed' row; only the "
                "owner's finalize/release may transition it. A non-owner save "
                "(e.g. complete/fail reusing a live start's op_id) must not "
                "clobber the claim (AG3-054 ERROR-3, fail-closed).",
            )


def claim_control_plane_operation_global_row(row: dict[str, Any]) -> bool:
    """Atomically claim an op_id, inserting only if absent (AG3-054 owner-scoped claim).

    Performs a single ``INSERT ... ON CONFLICT (op_id) DO NOTHING`` with
    ``status='claimed'`` and the per-call ``claimed_by`` / ``claimed_at`` stamp, so
    exactly ONE concurrent caller wins the claim for a given ``op_id``; the loser
    sees zero affected rows and must inspect the row (terminal => replay, a
    foreign claim of ANY age => in-flight rejection; AG3-139: never a CAS
    takeover). The claim happens BEFORE dispatch, so a loser never dispatches.

    AG3-138 (``inflight-operation-record``, FK-91 §91.1a rule 16): the fresh
    ``claimed`` placeholder additionally stamps ``operation_epoch``,
    ``backend_instance_id``, ``instance_incarnation`` and
    ``declared_serialization_scope`` -- every newly-acquired claim carries the
    caller's instance identity and its initial fencing epoch. AG3-139: a foreign
    ``claimed`` row is NEVER taken over here (no CAS takeover exists anymore) --
    a loser always gets the fail-closed in-flight rejection; these columns are
    re-stamped only on a genuinely fresh claim (a new op_id, or one released /
    ended via admin-abort / startup reconciliation).

    Returns:
        ``True`` iff this caller inserted the row (won the claim); ``False`` when
        the op_id already existed (a concurrent/earlier caller owns it).
    """

    with _connect_global() as conn:
        cursor = conn.execute(
            """
            INSERT INTO control_plane_operations (
                op_id, project_key, story_id, run_id, session_id,
                operation_kind, phase, status, response_json,
                created_at, updated_at, claimed_by, claimed_at,
                operation_epoch, backend_instance_id, instance_incarnation,
                declared_serialization_scope, request_body_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (op_id) DO NOTHING
            """,
            (
                row["op_id"],
                row["project_key"],
                row["story_id"],
                row["run_id"],
                row["session_id"],
                row["operation_kind"],
                row["phase"],
                row["status"],
                row["response_json"],
                row["created_at"],
                row["updated_at"],
                row.get("claimed_by"),
                row.get("claimed_at"),
                row.get("operation_epoch"),
                row.get("backend_instance_id"),
                row.get("instance_incarnation"),
                row.get("declared_serialization_scope"),
                # AG3-140: stamp the request body-hash on the claim so a later
                # claim-loser can decide replay vs idempotency_mismatch.
                row.get("request_body_hash"),
            ),
        )
        return int(cursor.rowcount) == 1


def finalize_control_plane_operation_global_row(
    row: dict[str, Any],
    *,
    owner_token: str,
    owner_claimed_at: str | None = None,
    owner_operation_epoch: int | None = None,
) -> bool:
    """Ownership-scoped terminal write of a claimed op (AG3-054 owner-scoped claim).

    Writes the terminal status + response_json and CLEARS ``claimed_by`` ONLY when
    the row is still ``claimed`` by ``owner_token``. If another owner finalized the
    claim, or an admin-abort ended it, in between, the CAS affects zero rows and
    this caller must NOT overwrite the foreign/terminal row -- it returns
    ``False`` so the runtime surfaces a replay/rejection instead.

    WARNING-4 fix (#4): when ``owner_claimed_at`` (the RAW claim instant the owner
    stamped) is given, the CAS also matches ``claimed_at`` (raw column) so it
    scopes to THIS claim generation -- a reused stale owner token (DI/test
    wiring) cannot match a NEWER claim. ``None`` keeps the legacy owner-only CAS.

    AG3-138 (``operation_finalize_requires_cas_on_operation_epoch``): when
    ``owner_operation_epoch`` is given, the CAS additionally requires the stored
    ``operation_epoch`` to be UNCHANGED. An ``admin_abort_inflight_operation``
    bumps the epoch on abort, so a late executor's finalize -- even one whose
    ``owner_token``/``claimed_at`` would otherwise still match -- fails this
    fence deterministically and writes nothing (at most a no-op).

    Returns:
        ``True`` iff this owner's terminal write applied (rowcount == 1).
    """

    epoch_clause, epoch_params = _owner_fencing_cas_clause(owner_claimed_at, owner_operation_epoch)
    with _connect_global() as conn:
        # epoch_clause is a constant fragment, not user data.
        cursor = conn.execute(
            f"""
            UPDATE control_plane_operations
            SET status = ?, response_json = ?, updated_at = ?,
                run_id = ?, session_id = ?, phase = ?,
                claimed_by = NULL, claimed_at = NULL
            WHERE op_id = ?
              AND status = 'claimed'
              AND claimed_by = ?{epoch_clause}
            """,  # noqa: S608
            (
                row["status"],
                row["response_json"],
                row["updated_at"],
                row["run_id"],
                row["session_id"],
                row["phase"],
                row["op_id"],
                owner_token,
                *epoch_params,
            ),
        )
        return int(cursor.rowcount) == 1


def _owner_epoch_cas_clause(
    owner_claimed_at: str | None,
) -> tuple[str, tuple[str, ...]]:
    """Build the optional claim-generation CAS fragment (AG3-054 WARNING-4, #4).

    When ``owner_claimed_at`` is given, returns a SQL fragment matching the RAW
    ``claimed_at`` column plus its bind parameter, so the ownership CAS scopes to
    THIS claim generation. When ``None`` (legacy administrative callers), returns
    an empty fragment so the CAS stays owner-only (backward compatible). The
    fragment is a fixed string with NO interpolated user data.
    """
    if owner_claimed_at is None:
        return "", ()
    return "\n              AND claimed_at IS NOT DISTINCT FROM ?", (owner_claimed_at,)


def _owner_fencing_cas_clause(
    owner_claimed_at: str | None,
    owner_operation_epoch: int | None,
) -> tuple[str, tuple[str | int, ...]]:
    """Build the optional claim-generation AND operation-epoch CAS fragment (AG3-138).

    Combines the AG3-054 raw-``claimed_at`` claim-generation fence with the
    AG3-138 ``operation_epoch`` fence
    (``operation_finalize_requires_cas_on_operation_epoch``). Either, both or
    neither may be given; each present value adds its own ``AND`` predicate.
    Fixed fragment text, no interpolated user data.
    """
    claim_clause, claim_params = _owner_epoch_cas_clause(owner_claimed_at)
    if owner_operation_epoch is None:
        return claim_clause, claim_params
    epoch_clause = claim_clause + "\n              AND operation_epoch = ?"
    return epoch_clause, (*claim_params, owner_operation_epoch)


def _insert_session_binding_row(conn: _CompatConnection, row: dict[str, Any]) -> None:
    """Run-scoped insert/upsert of one session-run-binding row (AG3-054 sweep).

    The binding is keyed by ``session_id`` (one row per session) but carries
    ``(project_key, story_id, run_id)``. The conditional upsert creates the row when
    absent and updates it ONLY when the existing row already belongs to the SAME
    ``(project_key, story_id, run_id)``. A live binding for a DIFFERENT run that has
    since rebound the same ``session_id`` is NEVER overwritten: the
    ``DO UPDATE ... WHERE`` predicate is false, the statement touches zero rows, and
    a still-present foreign row makes this raise
    :class:`ControlPlaneBindingCollisionError` so the WHOLE atomic transaction rolls
    back (no foreign-binding clobber).

    Raises:
        ControlPlaneBindingCollisionError: When the session is bound to a DIFFERENT
            ``(project_key, story_id, run_id)`` (the upsert refused to overwrite).
    """
    cursor = conn.execute(
        """
        INSERT INTO session_run_bindings (
            session_id, project_key, story_id, run_id, principal_type,
            worktree_roots_json, binding_version, updated_at,
            status, revocation_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (session_id) DO UPDATE SET
            principal_type = EXCLUDED.principal_type,
            worktree_roots_json = EXCLUDED.worktree_roots_json,
            binding_version = EXCLUDED.binding_version,
            updated_at = EXCLUDED.updated_at,
            -- AG3-137 (Codex WARNING §5b): carry status / revocation_reason on a
            -- same-run rebind too, so an update never leaves a stale status or a
            -- stale reason behind (the mapper always supplies both).
            status = EXCLUDED.status,
            revocation_reason = EXCLUDED.revocation_reason
        WHERE session_run_bindings.project_key = EXCLUDED.project_key
          AND session_run_bindings.story_id = EXCLUDED.story_id
          AND session_run_bindings.run_id = EXCLUDED.run_id
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
            row["status"],
            row["revocation_reason"],
        ),
    )
    if int(cursor.rowcount) == 0:
        # Zero rows == a conflicting row exists whose run did NOT match (a fresh
        # insert affects 1 row; a run-matched update affects 1 row). Confirm a
        # foreign row is present and fail closed -- never silently overwrite it.
        raise ControlPlaneBindingCollisionError(
            "control-plane session-binding save refused: session "
            f"{row['session_id']!r} is bound to a DIFFERENT run than "
            f"({row['project_key']!r}, {row['story_id']!r}, {row['run_id']!r}); a "
            "stale/late operation for an old run must not overwrite a live "
            "binding that has since rebound the same session_id (AG3-054 "
            "run-scoping, fail-closed).",
        )


def _run_scoped_delete_session_binding_row(
    conn: _CompatConnection,
    *,
    session_id: str,
    project_key: str,
    story_id: str,
    run_id: str,
) -> None:
    """Run-scoped delete of one session-run-binding row (AG3-054 sweep).

    Deletes the binding ONLY when its ``(project_key, story_id, run_id)`` matches the
    closing run. When the session has since been rebound to a DIFFERENT run, the
    live binding is left untouched and this raises
    :class:`ControlPlaneBindingCollisionError` so the WHOLE atomic teardown rolls
    back (no foreign run's regime is torn down). A missing binding is a benign no-op
    (idempotent closure).

    Raises:
        ControlPlaneBindingCollisionError: When a live binding exists for the
            session but belongs to a DIFFERENT run.
    """
    cursor = conn.execute(
        """
        DELETE FROM session_run_bindings
        WHERE session_id = ? AND project_key = ? AND story_id = ? AND run_id = ?
        """,
        (session_id, project_key, story_id, run_id),
    )
    if int(cursor.rowcount) == 1:
        return
    # Nothing matched the closing run: either there is no binding at all (benign
    # no-op) or a FOREIGN run rebound this session. Probe to distinguish.
    foreign = conn.execute(
        "SELECT run_id FROM session_run_bindings WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if foreign is not None:
        raise ControlPlaneBindingCollisionError(
            "control-plane session-binding delete refused: session "
            f"{session_id!r} is bound to run {foreign['run_id']!r}, not the "
            f"closing run {run_id!r}; closure must not tear down a foreign run's "
            "live binding (AG3-054 run-scoping, fail-closed).",
        )


def _insert_story_execution_lock_row(conn: _CompatConnection, row: dict[str, Any]) -> None:
    """Insert/upsert one story-execution-lock row on an EXISTING connection (#1)."""
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


def finalize_control_plane_start_phase_global_row(
    *,
    op_row: dict[str, Any],
    owner_token: str,
    owner_claimed_at: str | None = None,
    owner_operation_epoch: int | None = None,
    binding_row: dict[str, Any] | None,
    lock_rows: Sequence[dict[str, Any]],
    event_rows: Sequence[dict[str, Any]],
    ownership_row_to_insert: dict[str, Any] | None = None,
    execution_contract_digest_row_to_insert: dict[str, Any] | None = None,
    expected_ownership_epoch: int | None = None,
) -> bool:
    """Atomically CAS-finalize a start_phase AND materialize its side effects (#1).

    ERROR-1 fix (#1): the ownership CAS finalize and the start_phase side effects
    (session binding, story/QA locks, lifecycle events) are applied in ONE
    connection / ONE transaction, gated on STILL owning the claim. The CAS finalize
    runs FIRST: ``UPDATE ... WHERE op_id=? AND status='claimed' AND claimed_by=?``.

    * rowcount == 1 -> this owner still holds the claim: the binding / locks /
      events are inserted on the SAME connection and the whole transaction commits
      atomically. The terminal op and its canonical side effects appear together.
    * rowcount == 0 -> the claim was already resolved by a concurrent process (a
      slow owner's own later finalize, or an admin-abort, AG3-138): NOTHING is
      materialized and the transaction is rolled back (the ``with`` block raises
      before commit), so the loser writes NO duplicate/conflicting binding / lock
      / event. The runtime then surfaces the winner's terminal row as a replay.

    The loser therefore never writes canonical side effects -- materialization is
    ownership-gated and atomic with the finalize (FK-22 §22.9, FK-91).

    Args:
        op_row: The terminal control-plane operation row (committed result).
        owner_token: This caller's owner token (the CAS scope).
        owner_claimed_at: This caller's RAW claim instant; when given, the ownership
            CAS also matches ``claimed_at`` so it scopes to THIS claim generation
            (WARNING-4, #4). ``None`` keeps the legacy owner-only CAS.
        owner_operation_epoch: This caller's observed ``operation_epoch`` (AG3-138,
            ``operation_finalize_requires_cas_on_operation_epoch``); when given,
            the CAS additionally requires the stored epoch to be UNCHANGED, so an
            ``admin_abort_inflight_operation`` bump fences a late executor's
            finalize even when its owner token/claim instant would otherwise still match.
        binding_row: The session-run-binding row to materialize, or ``None`` for a
            fast story (no story-scoped binding).
        lock_rows: The story-execution / qa-artifact-write lock rows (empty for a
            fast story).
        event_rows: The lifecycle execution-event rows (empty for a fast story).

    AG3-054 run-scoping sweep: the binding INSERT is RUN-scoped
    (:func:`_insert_session_binding_row`). A start finalize for an OLD run can never
    overwrite a live binding that has since rebound the same ``session_id`` to a
    DIFFERENT run -- the conditional upsert raises
    :class:`ControlPlaneBindingCollisionError` and the whole transaction rolls back.

    Returns:
        ``True`` iff this owner's terminal write applied and the side effects were
        materialized atomically; ``False`` when the claim was lost (nothing written).

    Raises:
        ControlPlaneBindingCollisionError: When the binding would overwrite a
            FOREIGN run's live binding (nothing committed; the binding intact).
        OwnershipFenceViolationError: (AG3-142, ``expected_ownership_epoch`` given)
            When the story's active run-ownership record no longer admits this
            exact ``(run_id, session_id, ownership_epoch)`` snapshot at commit
            time (no TOCTOU) -- nothing committed, the claim-CAS above is
            rolled back too.

    AG3-142 (SOLL-015): ``ownership_row_to_insert`` atomically materializes the
    NEW active ``run_ownership_records`` row for a genuinely fresh setup start
    (``ownership_epoch=1``) in this SAME transaction -- a claim-CAS loser writes
    no record, mirroring the binding/lock/event side effects. Mutually exclusive
    in practice with ``expected_ownership_epoch`` (a fresh setup has no existing
    record to fence against; every OTHER start/resume finalize fences against
    the existing record via ``expected_ownership_epoch`` and inserts none).

    AG3-143 (FK-44 §44.3a): ``execution_contract_digest_row_to_insert``
    atomically materializes the run's NEW ``execution_contract_digests`` row
    in this SAME transaction, mirroring ``ownership_row_to_insert`` exactly
    -- present iff this is a genuinely fresh setup start, ``None`` otherwise.
    """

    class _NotOwnerError(RuntimeError):
        """Internal sentinel: abort + roll back when the ownership CAS loses."""

    epoch_clause, epoch_params = _owner_fencing_cas_clause(owner_claimed_at, owner_operation_epoch)
    try:
        with _connect_global() as conn:
            cursor = conn.execute(
                f"""
                UPDATE control_plane_operations
                SET status = ?, response_json = ?, updated_at = ?,
                    run_id = ?, session_id = ?, phase = ?,
                    claimed_by = NULL, claimed_at = NULL
                WHERE op_id = ?
                  AND status = 'claimed'
                  AND claimed_by = ?{epoch_clause}
                """,  # noqa: S608 -- epoch_clause is a constant fragment
                (
                    op_row["status"],
                    op_row["response_json"],
                    op_row["updated_at"],
                    op_row["run_id"],
                    op_row["session_id"],
                    op_row["phase"],
                    op_row["op_id"],
                    owner_token,
                    *epoch_params,
                ),
            )
            if int(cursor.rowcount) != 1:
                # Lost the ownership CAS: roll back so NO side effect is written.
                raise _NotOwnerError
            if expected_ownership_epoch is not None:
                # AG3-142: re-verify AT COMMIT TIME, in THIS transaction (no
                # TOCTOU) -- a failure raises and rolls back EVERYTHING above too.
                _enforce_ownership_fence_row(
                    conn,
                    project_key=str(op_row["project_key"]),
                    story_id=str(op_row["story_id"]),
                    run_id=str(op_row["run_id"]),
                    session_id=str(op_row["session_id"]),
                    expected_ownership_epoch=expected_ownership_epoch,
                )
            if ownership_row_to_insert is not None:
                _insert_run_ownership_record_row(conn, ownership_row_to_insert)
            if execution_contract_digest_row_to_insert is not None:
                _insert_execution_contract_digest_row(
                    conn,
                    execution_contract_digest_row_to_insert,
                )
            if binding_row is not None:
                _insert_session_binding_row(conn, binding_row)
            for lock_row in lock_rows:
                _insert_story_execution_lock_row(conn, lock_row)
            for event_row in event_rows:
                _insert_execution_event_row(conn, event_row)
    except _NotOwnerError:
        return False
    return True


def list_orphaned_claimed_control_plane_operations_global_row(
    *,
    backend_instance_id: str,
    before_incarnation: int,
) -> list[dict[str, Any]]:
    """Return claimed operations orphaned by EARLIER incarnations of THIS instance.

    Startup reconciliation (AG3-138, FK-91 §91.1a rule 16 /
    ``orphaned_claims_are_finalized_only_by_same_instance_startup_reconciliation_or_admin_abort``):
    finds ``claimed`` control-plane operations stamped with the CALLING
    instance's own ``backend_instance_id`` from a strictly earlier
    ``instance_incarnation``. Claims carrying a FOREIGN ``backend_instance_id``
    (or ``NULL``, a pre-AG3-137 legacy row with no instance stamp) are never
    returned -- fail-closed, no "generous" cleanup of un-attributable claims.
    """

    with _connect_global() as conn:
        rows = conn.execute(
            """
            SELECT * FROM control_plane_operations
            WHERE status = 'claimed'
              AND backend_instance_id = ?
              AND instance_incarnation < ?
            ORDER BY op_id
            """,
            (backend_instance_id, before_incarnation),
        ).fetchall()
    return [dict(row) for row in rows]


def finalize_orphaned_control_plane_operation_global_row(
    *,
    op_id: str,
    backend_instance_id: str,
    status: str,
    response_json: str,
    now: str,
    owner_operation_epoch: int,
) -> bool:
    """CAS-finalize one orphaned claim during startup reconciliation (AG3-138).

    Fail-closed identity fence: the CAS matches ``op_id`` AND
    ``status = 'claimed'`` AND ``backend_instance_id = ?`` -- a claim whose
    identity or status changed concurrently is left untouched (returns
    ``False``); a foreign identity can never be matched by this predicate.
    ``operation_epoch`` is bumped (``operation_finalize_requires_cas_on_operation_epoch``)
    and the claim columns are cleared.

    ``owner_operation_epoch`` is MANDATORY (AC4): it fences the finalize on the
    ``operation_epoch`` OBSERVED BY THE ORPHAN SCAN, exactly like the normal
    :func:`finalize_control_plane_operation_global_row` claim-generation fence. If the
    row's ``operation_epoch`` changed between the scan and this finalize (e.g. a
    concurrent admin-abort of the same still-``claimed`` identity bumped it), the
    CAS matches zero rows and this call is a deterministic no-op (returns
    ``False``) instead of stamping a terminal status over a row that already moved
    on. There is deliberately NO identity-only (epoch-less) finalize path: a row
    whose ``operation_epoch`` is ``NULL`` can never satisfy ``operation_epoch = ?``
    for a real integer, so a malformed/legacy ``NULL``-epoch row fails the fence and
    is left untouched (fail-closed) rather than finalized without a CAS.

    Returns:
        ``True`` iff this call's finalize applied (rowcount == 1).
    """

    with _connect_global() as conn:
        cursor = conn.execute(
            """
            UPDATE control_plane_operations
            SET status = ?, response_json = ?, updated_at = ?, finalized_at = ?,
                operation_epoch = operation_epoch + 1,
                claimed_by = NULL, claimed_at = NULL
            WHERE op_id = ?
              AND status = 'claimed'
              AND backend_instance_id = ?
              AND operation_epoch = ?
            """,
            (
                status,
                response_json,
                now,
                now,
                op_id,
                backend_instance_id,
                owner_operation_epoch,
            ),
        )
        return int(cursor.rowcount) == 1


def admin_abort_control_plane_operation_global_row(
    *,
    op_id: str,
    status: str,
    response_json: str,
    now: str,
) -> bool:
    """CAS-abort one in-flight claim via the admin-abort service path (AG3-138).

    Acts on ANY currently-``claimed`` operation regardless of which instance
    stamped it -- an explicit administrative override (FK-91 §91.1a
    ``admin_abort_inflight_operation``, FK-55 §55.5 ``admin_transition``) is by
    construction not scoped to the claim's own owner_token/claim generation. Bumps
    ``operation_epoch`` so a late, physically-still-running executor's
    subsequent finalize fails the epoch fence deterministically (at most a
    no-op abort note; ``operation_finalize_requires_cas_on_operation_epoch``).

    Returns:
        ``True`` iff the abort applied; ``False`` when the row was no longer
        ``claimed`` (already resolved) -- the caller surfaces this as a 409.
    """

    with _connect_global() as conn:
        cursor = conn.execute(
            """
            UPDATE control_plane_operations
            SET status = ?, response_json = ?, updated_at = ?, finalized_at = ?,
                operation_epoch = operation_epoch + 1,
                claimed_by = NULL, claimed_at = NULL
            WHERE op_id = ?
              AND status = 'claimed'
            """,
            (status, response_json, now, now, op_id),
        )
        return int(cursor.rowcount) == 1


def has_engine_writes_since_control_plane_claim_global_row(
    *,
    story_id: str,
    since: str,
) -> bool:
    """Whether the engine persisted partial writes UNDER a specific claim window.

    Deterministic, event-based partial-write detection (AG3-138, IMPL-005): compares
    the ALREADY-RECORDED ``flow_executions.started_at`` / ``phase_states.updated_at``
    against ``since`` (the orphaned/aborted claim's OWN ``claimed_at``) -- never the
    current wall clock. ``control_plane/dispatch.py`` runs
    ``engine.run_phase``/``resume_phase`` (own transactions, per the atomicity note
    in this module) BEFORE the control-plane finalize commits; a persisted value
    at/after ``since`` proves the engine already wrote under the claim now being
    finalized as orphaned/aborted, so it must go to the ``repair`` state, never
    silently ``failed``.

    Soundness axis -- FAIL-CLOSED, not silent. The probe is deliberately biased
    toward ``repair``: it reports a partial write on ANY ``story_id`` engine write
    at/after ``since``. This can NEVER produce a false NEGATIVE (a genuine partial
    write silently routed to ``failed``), which is the dangerous, fail-OPEN
    direction that IMPL-005 forbids ("never silently failed"). A ``run_id`` filter
    is deliberately NOT applied precisely because it WOULD introduce false
    negatives: the engine persists
    ``flow_executions.run_id = EngineRuntimeState.resolve_run_id(ctx)`` -- an
    engine-internal id (a fresh ``uuid4`` seed reused via the story's own
    ``flow_executions`` row), DISTINCT from the control-plane operation ``run_id``
    (the client-supplied ``/story-runs/{run_id}`` path value); filtering by the
    control-plane ``run_id`` would miss the engine's real write. ``phase_states`` is
    a story-keyed singleton with no ``run_id`` column at all, so no per-run binding
    exists for it either.

    Precision axis -- bounded, recoverable, AG3-141-dependent. Full precision (no
    false POSITIVE, i.e. no over-conservative ``repair`` for a story whose only
    post-``since`` engine write actually came from a DIFFERENT, successfully
    committed operation of the same story) requires the ``story-lifecycle``
    at-most-one-active-operation-per-story guarantee, so that any ``story_id`` engine
    write in the claim window provably belongs to THIS operation. That guarantee is
    the durable object-mutation-claim (``state-storage.entity.object-mutation-claim``,
    FK-10 §10.5.4) acquired before dispatch -- and its acquisition is AG3-141's
    charter, NOT wired in the AG3-138 window (``control_plane_operations`` claims are
    keyed by ``op_id`` alone; ``run_ownership_records`` and ``object_mutation_claims``
    exist in the schema but have no dispatch-path writer yet). FK-10 §10.5.1/§10.5.4
    make single-writer-per-story a NORMATIVE operating assumption (sequential
    per-story phase runner, one active control-plane writer instance per DB), under
    which this probe is also precise; the residual imprecision is exactly the window
    in which that normative assumption is violated before AG3-141 durably enforces
    it. A false-positive ``repair`` is never a permanent story deadlock: it is
    productively resolved via the admin-abort repair-resolve path
    (:func:`resolve_repair_control_plane_operation_global_row`, AC10).
    """

    with _connect_global() as conn:
        flow_row = conn.execute(
            """
            SELECT 1 FROM flow_executions
            WHERE story_id = ? AND started_at >= ?
            LIMIT 1
            """,
            (story_id, since),
        ).fetchone()
        if flow_row is not None:
            return True
        phase_row = conn.execute(
            """
            SELECT 1 FROM phase_states
            WHERE story_id = ? AND updated_at >= ?
            LIMIT 1
            """,
            (story_id, since),
        ).fetchone()
        return phase_row is not None


def has_open_repair_control_plane_operation_for_story_global_row(
    *,
    project_key: str,
    story_id: str,
) -> bool:
    """Whether *story_id* has an open (unresolved) reconcile/repair state.

    Backs the AC10 fail-closed mutation lock at the dispatch-/operations-layer.
    "Open" means a stored ``repair``-status control-plane operation exists for
    this story; the repair record itself is the single source of truth for the
    lock (no second, driftable boolean flag). AG3-138 provides the productive
    exit: an audited ``admin_abort`` repair-resolve transitions the operation to
    ``resolved`` (see ``resolve_repair_control_plane_operation_global_row``),
    which clears the lock. AG3-150 later generalizes the lock family
    (``freeze_epoch``); this story builds the story-scoped lock and its resolver.
    """

    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM control_plane_operations
            WHERE project_key = ? AND story_id = ? AND status = 'repair'
            LIMIT 1
            """,
            (project_key, story_id),
        ).fetchone()
        if row is not None:
            return True
        blocker = conn.execute(
            """
            SELECT 1 FROM stories
            WHERE project_key = ? AND story_display_id = ?
              AND blocker = 'takeover_reconcile_required'
            LIMIT 1
            """,
            (project_key, story_id),
        ).fetchone()
        return blocker is not None


def resolve_repair_control_plane_operation_global_row(
    *,
    op_id: str,
    response_json: str,
    now: str,
) -> bool:
    """CAS-resolve one open ``repair`` operation to a terminal ``resolved`` state.

    The productive end-way out of the AC10 mutation lock (AG3-138): once an operator
    has handled the partial engine writes that put the story into ``repair`` (out of
    band), the admin-abort repair-resolve path transitions the ``repair`` row to
    ``resolved``. Because :func:`has_open_repair_control_plane_operation_for_story_global_row`
    keys the story-scoped lock on ``status = 'repair'``, moving the row off ``repair``
    lifts the lock and re-admits mutating operations for the story -- so a ``repair``
    (including an over-conservative one, see
    :func:`has_engine_writes_since_control_plane_claim_global_row`) can never be a
    permanent deadlock.

    Fail-closed CAS: the update matches ``op_id`` AND ``status = 'repair'`` only. A
    row that is not (or is no longer) in ``repair`` -- a live ``claimed`` claim, an
    already-``resolved`` row, or any other terminal status -- is left untouched and
    the caller surfaces the miss as a 409 (never a second/duplicate resolve). The
    ``operation_epoch`` is NOT re-bumped: the row is already terminal (its epoch was
    bumped when it entered ``repair``); this is a bookkeeping close-out of an open
    handling state, not a fence against a still-running executor.

    Returns:
        ``True`` iff this call's resolve applied (rowcount == 1).
    """

    with _connect_global() as conn:
        cursor = conn.execute(
            """
            UPDATE control_plane_operations
            SET status = 'resolved', response_json = ?, updated_at = ?,
                finalized_at = ?
            WHERE op_id = ?
              AND status = 'repair'
            """,
            (response_json, now, now, op_id),
        )
        return int(cursor.rowcount) == 1


def commit_control_plane_operation_with_side_effects_global_row(
    *,
    op_row: dict[str, Any],
    binding_to_save: dict[str, Any] | None,
    binding_to_delete: dict[str, Any] | None,
    lock_rows: Sequence[dict[str, Any]],
    event_rows: Sequence[dict[str, Any]],
    expected_ownership_epoch: int | None = None,
) -> None:
    """Atomically commit a terminal op AND its side effects in ONE transaction (#2).

    ERROR-2 fix (#2): ``complete_phase`` / ``fail_phase`` (the admitted-phase
    mutation) and ``complete_closure`` (standard + fast teardown) previously wrote
    their side effects (session-binding create/delete, lock records, lifecycle
    events) via SEPARATE ``_connect_global()`` transactions and THEN called the
    conditional op-row upsert -- which raises :class:`ControlPlaneClaimCollisionError`
    when it would clobber a LIVE ``claimed`` start claim. By then the side effects
    were already committed -> orphan state (e.g. a deleted binding / deactivated
    lock while the live claim survived and the result was a rejection).

    This function applies the conditional op-row upsert AND all side effects on the
    SAME connection / ONE transaction, with the collision gate running FIRST: a
    collision raises before any commit, so the whole transaction (including every
    side effect) rolls back. The mutation is therefore atomic -- a collision leaves
    NO side effect written and the live claimed row intact (FK-22 §22.9).

    Args:
        op_row: The terminal control-plane operation row (committed result).
        binding_to_save: A session-run-binding row to RUN-scoped-upsert, or ``None``
            (the complete/fail standard path materializes one; closure never does).
            A foreign-run conflict raises :class:`ControlPlaneBindingCollisionError`.
        binding_to_delete: A run-scoped delete spec dict (``session_id`` +
            ``project_key`` + ``story_id`` + ``run_id``) whose binding must be
            removed, or ``None`` (closure removes the binding; complete/fail never
            does). A foreign-run live binding is left untouched and raises
            :class:`ControlPlaneBindingCollisionError`.
        lock_rows: The story/QA lock rows to upsert (empty when none apply).
        event_rows: The lifecycle execution-event rows to append (empty for none).

    Raises:
        ControlPlaneClaimCollisionError: When ``op_row`` collides with a LIVE
            ``claimed`` row (nothing is committed; the live claim is intact).
        ControlPlaneBindingCollisionError: When the binding save/delete would touch
            a FOREIGN run's live binding (nothing committed; the binding intact).
        OwnershipFenceViolationError: (AG3-142, ``expected_ownership_epoch`` given)
            When the story's active run-ownership record no longer admits this
            exact ``(run_id, session_id, ownership_epoch)`` snapshot at commit
            time (no TOCTOU) -- nothing committed, the collision-gated upsert
            above is rolled back too.
    """
    with _connect_global() as conn:
        # Collision gate FIRST: a live-claim collision raises here, BEFORE any side
        # effect is durable, so the transaction rolls back with zero orphan state.
        _conditional_upsert_control_plane_op_row(conn, op_row)
        if expected_ownership_epoch is not None:
            # AG3-142: re-verify AT COMMIT TIME, in THIS transaction (no TOCTOU) --
            # a failure raises and rolls back the op upsert above too.
            _enforce_ownership_fence_row(
                conn,
                project_key=str(op_row["project_key"]),
                story_id=str(op_row["story_id"]),
                run_id=str(op_row["run_id"]),
                session_id=str(op_row["session_id"]),
                expected_ownership_epoch=expected_ownership_epoch,
            )
        if binding_to_save is not None:
            _insert_session_binding_row(conn, binding_to_save)
        if binding_to_delete is not None:
            # Run-scoped delete: a foreign run's live binding raises and rolls back
            # the WHOLE transaction (no foreign teardown, no orphan op/lock/event).
            _run_scoped_delete_session_binding_row(
                conn,
                session_id=str(binding_to_delete["session_id"]),
                project_key=str(binding_to_delete["project_key"]),
                story_id=str(binding_to_delete["story_id"]),
                run_id=str(binding_to_delete["run_id"]),
            )
        for lock_row in lock_rows:
            _insert_story_execution_lock_row(conn, lock_row)
        for event_row in event_rows:
            _insert_execution_event_row(conn, event_row)


def commit_takeover_confirm_global_row(
    *,
    op_row: dict[str, Any],
    expected_owner_session_id: str,
    expected_ownership_epoch: int,
    expected_binding_version: str,
    revoked_binding_row: dict[str, Any],
    new_binding_row: dict[str, Any],
    lock_rows: Sequence[dict[str, Any]],
    transfer_rows: Sequence[dict[str, Any]],
    event_rows: Sequence[dict[str, Any]],
    approved_approval_row: dict[str, Any] | None = None,
    fault_after_step: Callable[[str], None] | None = None,
) -> None:
    """Atomically commit a takeover confirm and all ownership side effects.

    CAS-loss raises before durable side effects survive. The active ownership row
    remains ``status='active'`` and is updated in place to the new owner with
    ``ownership_epoch + 1``.
    """

    with _connect_global() as conn:
        _conditional_upsert_control_plane_op_row(conn, op_row)
        active = conn.execute(
            """
            SELECT owner_session_id, ownership_epoch, status
            FROM run_ownership_records
            WHERE project_key = ? AND story_id = ? AND run_id = ?
              AND status = 'active'
            FOR UPDATE
            """,
            (op_row["project_key"], op_row["story_id"], op_row["run_id"]),
        ).fetchone()
        if (
            active is None
            or str(active["owner_session_id"]) != expected_owner_session_id
            or int(active["ownership_epoch"]) != expected_ownership_epoch
            or str(active["status"]) != "active"
        ):
            raise OwnershipFenceViolationError(
                "takeover confirm CAS failed: active ownership row no longer "
                "matches the echoed challenge",
                detail={
                    "current_owner_session_id": (
                        str(active["owner_session_id"]) if active is not None else None
                    ),
                    "current_ownership_epoch": (
                        int(active["ownership_epoch"]) if active is not None else None
                    ),
                    "transferred_at": str(op_row["updated_at"]) if active is not None else None,
                },
            )
        binding = conn.execute(
            """
            SELECT binding_version FROM session_run_bindings
            WHERE session_id = ? AND project_key = ? AND story_id = ?
              AND run_id = ? AND status = 'active'
            FOR UPDATE
            """,
            (
                expected_owner_session_id,
                op_row["project_key"],
                op_row["story_id"],
                op_row["run_id"],
            ),
        ).fetchone()
        if binding is None or str(binding["binding_version"]) != expected_binding_version:
            raise OwnershipFenceViolationError(
                "takeover confirm CAS failed: owner binding version no longer "
                "matches the echoed challenge",
                detail={
                    "current_owner_session_id": expected_owner_session_id,
                    "current_ownership_epoch": expected_ownership_epoch,
                    "transferred_at": str(op_row["updated_at"]),
                },
            )
        conn.execute(
            """
            UPDATE run_ownership_records
            SET owner_session_id = ?, ownership_epoch = ?,
                acquired_via = 'takeover', acquired_at = ?, audit_ref = ?
            WHERE project_key = ? AND story_id = ? AND run_id = ?
              AND status = 'active'
            """,
            (
                new_binding_row["session_id"],
                expected_ownership_epoch + 1,
                op_row["updated_at"],
                op_row["op_id"],
                op_row["project_key"],
                op_row["story_id"],
                op_row["run_id"],
            ),
        )
        _run_takeover_fault_hook(fault_after_step, "ownership_update")
        cursor = conn.execute(
            """
            UPDATE session_run_bindings
            SET status = 'revoked', revocation_reason = ?,
                binding_version = ?, updated_at = ?
            WHERE session_id = ? AND project_key = ? AND story_id = ?
              AND run_id = ?
            """,
            (
                revoked_binding_row["revocation_reason"],
                revoked_binding_row["binding_version"],
                revoked_binding_row["updated_at"],
                revoked_binding_row["session_id"],
                revoked_binding_row["project_key"],
                revoked_binding_row["story_id"],
                revoked_binding_row["run_id"],
            ),
        )
        if int(cursor.rowcount) != 1:
            raise ControlPlaneBindingCollisionError(
                "takeover confirm could not revoke the previous owner's active binding",
            )
        _run_takeover_fault_hook(fault_after_step, "previous_binding_revoke")
        _approve_takeover_approval_row(conn, approved_approval_row)
        if approved_approval_row is not None:
            _run_takeover_fault_hook(fault_after_step, "approval_approve")
        _insert_session_binding_row(conn, new_binding_row)
        _run_takeover_fault_hook(fault_after_step, "new_binding_insert")
        for lock_row in lock_rows:
            _insert_story_execution_lock_row(conn, lock_row)
            _run_takeover_fault_hook(fault_after_step, "lock_insert")
        for transfer_row in transfer_rows:
            conn.execute(
                """
                INSERT INTO takeover_transfer_records (
                    project_key, story_id, run_id, ownership_epoch, repo_id,
                    takeover_base_sha, last_push_at, push_lag_hint, base_quality,
                    challenge_ref, confirm_ref
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    transfer_row["project_key"],
                    transfer_row["story_id"],
                    transfer_row["run_id"],
                    transfer_row["ownership_epoch"],
                    transfer_row["repo_id"],
                    transfer_row["takeover_base_sha"],
                    transfer_row["last_push_at"],
                    transfer_row["push_lag_hint"],
                    transfer_row["base_quality"],
                    transfer_row["challenge_ref"],
                    transfer_row["confirm_ref"],
                ),
            )
            _run_takeover_fault_hook(
                fault_after_step,
                f"transfer_record_insert:{transfer_row['repo_id']}",
            )
        conn.execute(
            """
            UPDATE stories
            SET blocker = 'takeover_reconcile_required'
            WHERE project_key = ? AND story_display_id = ?
            """,
            (op_row["project_key"], op_row["story_id"]),
        )
        _run_takeover_fault_hook(fault_after_step, "takeover_reconcile_required")
        for event_row in event_rows:
            _insert_execution_event_row(conn, event_row)
            _run_takeover_fault_hook(
                fault_after_step,
                f"event_insert:{event_row['event_type']}",
            )


def _approve_takeover_approval_row(
    conn: _CompatConnection,
    row: dict[str, Any] | None,
) -> None:
    if row is None:
        return
    cursor = conn.execute(
        """
        UPDATE takeover_approvals
        SET status = ?, decided_at = ?, decided_by_session_id = ?,
            decision_reason = ?
        WHERE approval_id = ?
          AND project_key = ?
          AND story_id = ?
          AND run_id = ?
          AND status = 'pending'
        """,
        (
            row["status"],
            row["decided_at"],
            row["decided_by_session_id"],
            row["decision_reason"],
            row["approval_id"],
            row["project_key"],
            row["story_id"],
            row["run_id"],
        ),
    )
    if int(cursor.rowcount) != 1:
        raise OwnershipFenceViolationError(
            "takeover confirm CAS failed: approval is no longer pending",
            detail={"approval_id": row["approval_id"]},
        )


def _run_takeover_fault_hook(
    fault_after_step: Callable[[str], None] | None,
    step: str,
) -> None:
    if fault_after_step is not None:
        fault_after_step(step)


def release_control_plane_operation_global_row(
    op_id: str,
    *,
    owner_token: str,
    owner_claimed_at: str | None = None,
) -> None:
    """Ownership-scoped release of a claimed op (AG3-054 owner-scoped claim).

    Deletes the row ONLY when it is still ``claimed`` by ``owner_token``. NEVER an
    unconditional delete: a terminal row (``status != 'claimed'``) and another
    owner's claim are both left untouched, so a release on the exception/rejection
    path can never delete a foreign or committed result. Idempotent.

    WARNING-4 fix (#4): when ``owner_claimed_at`` (the RAW claim instant the owner
    stamped) is given, the delete CAS also matches ``claimed_at`` so it scopes to
    THIS claim generation -- a stale owner (a reused token in DI/test wiring)
    cannot delete a NEWER claim. ``None`` keeps the legacy owner-only CAS.
    """

    epoch_clause, epoch_params = _owner_epoch_cas_clause(owner_claimed_at)
    with _connect_global() as conn:
        # epoch_clause is a constant fragment, not user data.
        conn.execute(
            f"""
            DELETE FROM control_plane_operations
            WHERE op_id = ? AND status = 'claimed' AND claimed_by = ?{epoch_clause}
            """,  # noqa: S608
            (op_id, owner_token, *epoch_params),
        )


def delete_control_plane_operation_global_row(op_id: str) -> None:
    """Unconditional delete of a control-plane-operation row by op_id.

    Retained for administrative recovery only (it ignores ownership/status). The
    PRODUCTIVE release path uses
    :func:`release_control_plane_operation_global_row` (ownership-scoped).
    Idempotent: deleting an absent op_id is a no-op.
    """

    with _connect_global() as conn:
        conn.execute(
            "DELETE FROM control_plane_operations WHERE op_id = ?",
            (op_id,),
        )


def has_committed_control_plane_operation_for_run_global_row(
    project_key: str,
    story_id: str,
    run_id: str,
) -> bool:
    """Whether a committed setup ``phase_start`` exists for THIS run (AG3-054 #3).

    ERROR-3 fix (#3): admission evidence must prove an admitted START, not merely
    that ANY committed op exists for the run. A committed ``phase_complete`` /
    ``closure_complete`` with no committed start would otherwise bootstrap
    admission from thin air. The probe is therefore narrowed to the ONLY operation
    the pre-start guard gates: a ``committed`` ``phase_start`` of phase ``setup``
    for the exact ``(project_key, story_id, run_id)``. A ``claimed`` placeholder,
    a ``rejected`` row, and a non-setup / non-start committed op are NOT evidence.
    """

    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM control_plane_operations
            WHERE project_key = ? AND story_id = ? AND run_id = ?
              AND status = 'committed'
              AND operation_kind = 'phase_start'
              AND phase = 'setup'
            LIMIT 1
            """,
            (project_key, story_id, run_id),
        ).fetchone()
    return row is not None


def has_committed_story_exit_operation_for_run_global_row(
    project_key: str,
    story_id: str,
    run_id: str,
) -> bool:
    """Whether a committed story-exit terminal marker exists for THIS run."""

    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM control_plane_operations
            WHERE project_key = ? AND story_id = ? AND run_id = ?
              AND status = 'committed'
              AND operation_kind = 'story_exit'
            LIMIT 1
            """,
            (project_key, story_id, run_id),
        ).fetchone()
    return row is not None


def load_control_plane_operation_global_row(
    op_id: str,
) -> dict[str, Any] | None:
    """Return the raw control-plane-operation row, or None."""

    with _connect_global() as conn:
        row = conn.execute(
            """
            SELECT * FROM control_plane_operations
            WHERE op_id = ?
            """,
            (op_id,),
        ).fetchone()
    if row is None:
        return None
    return dict(row)
