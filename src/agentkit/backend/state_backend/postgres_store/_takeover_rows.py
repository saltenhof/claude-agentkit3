"""Row layer of the ownership-transfer (takeover) aggregate.

Owns BOTH halves of the takeover row contract: the transactional
confirm/reissue/deny/expiry/invalidation/CAS-reconcile entry points AND the
row primitives they are built from (basis locking, challenge and approval
transitions, binding rewrite). The fault-injection seam stays in
``_control_plane_rows`` because the operation ledger fires it too.

Both halves used to sit apart -- the entry points here, their primitives in
``_control_plane_rows``, which imported nothing back and merely hosted them.
AG3-229 reunited them: the control-plane operation ledger and the takeover
aggregate are two different write contracts, and the takeover primitives were
only ever called from this module. Pure structural move; the SQL, the CAS
fences and the raised errors are unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agentkit.backend.exceptions import (
    ControlPlaneBindingCollisionError,
    OwnershipFenceViolationError,
)

from ._connection import _connect_global
from ._control_plane_rows import (
    _insert_session_binding_row,
    _insert_story_execution_lock_row,
    _run_takeover_fault_hook,
)
from ._mutation_commit_rows import _conditional_upsert_control_plane_op_row
from ._runtime_rows import _insert_execution_event_row

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from agentkit.backend.control_plane.ownership_transfer import OwnershipBasis

    from ._compat import _CompatConnection


#: Fault-injection step names of the takeover transactions. Named once so the
#: test seam and the transactions cannot drift apart on a typo.
_STEP_OP_UPSERT = "control_plane_op_upsert"
_STEP_REQUEST_OPERATION_TERMINALIZE = "request_operation_terminalize"
_STEP_CHALLENGE_TERMINALIZE = "challenge_terminalize"
_STEP_EVENT_INSERT_PREFIX = "event_insert:"


def commit_takeover_confirm_global_row(
    *,
    op_row: dict[str, Any],
    expected_basis: OwnershipBasis,
    revoked_binding_row: dict[str, Any],
    new_binding_row: dict[str, Any],
    lock_rows: Sequence[dict[str, Any]],
    transfer_rows: Sequence[dict[str, Any]],
    event_rows: Sequence[dict[str, Any]],
    edge_command_rows: Sequence[dict[str, Any]],
    terminal_rows: dict[str, dict[str, Any] | None],
    fault_after_step: Callable[[str], None] | None = None,
) -> None:
    """Atomically commit a takeover confirm and all ownership side effects."""

    with _connect_global() as conn:
        _conditional_upsert_control_plane_op_row(conn, op_row)
        _run_takeover_fault_hook(fault_after_step, _STEP_OP_UPSERT)
        _verify_takeover_confirm_cas(
            conn,
            op_row=op_row,
            expected_basis=expected_basis,
        )
        cursor = conn.execute(
            """
            UPDATE run_ownership_records
            SET owner_session_id = ?, ownership_epoch = ?,
                acquired_via = 'takeover', acquired_at = ?, audit_ref = ?
            WHERE project_key = ? AND story_id = ? AND run_id = ?
              AND status = 'active'
            """,
            (
                new_binding_row["session_id"],
                expected_basis.ownership_epoch + 1,
                op_row["updated_at"],
                op_row["op_id"],
                op_row["project_key"],
                op_row["story_id"],
                op_row["run_id"],
            ),
        )
        if int(cursor.rowcount) != 1:
            raise OwnershipFenceViolationError(
                "takeover confirm CAS failed: active ownership update affected "
                "zero rows after verification",
                detail={
                    "project_key": op_row["project_key"],
                    "story_id": op_row["story_id"],
                    "run_id": op_row["run_id"],
                    "expected_owner_session_id": expected_basis.owner_session_id,
                    "expected_ownership_epoch": expected_basis.ownership_epoch,
                },
            )
        _run_takeover_fault_hook(fault_after_step, "ownership_update")
        _write_takeover_binding_rows(
            conn,
            revoked_binding_row=revoked_binding_row,
            new_binding_row=new_binding_row,
            fault_after_step=fault_after_step,
        )
        approved_approval_row = terminal_rows["approved_approval"]
        _approve_takeover_approval_row(conn, approved_approval_row)
        if approved_approval_row is not None:
            _run_takeover_fault_hook(fault_after_step, "approval_approve")
        challenge_row = terminal_rows["challenge"]
        request_op_row = terminal_rows["request_op"]
        if challenge_row is None or request_op_row is None:
            raise RuntimeError("takeover confirm terminal rows are incomplete")
        _terminalize_takeover_request_operation_row(conn, request_op_row)
        _run_takeover_fault_hook(
            fault_after_step,
            _STEP_REQUEST_OPERATION_TERMINALIZE,
        )
        _terminalize_takeover_challenge_row(conn, challenge_row)
        _run_takeover_fault_hook(fault_after_step, _STEP_CHALLENGE_TERMINALIZE)
        for lock_row in lock_rows:
            _insert_story_execution_lock_row(conn, lock_row)
            _run_takeover_fault_hook(fault_after_step, "lock_insert")
        for transfer_row in transfer_rows:
            conn.execute(
                """
                INSERT INTO takeover_transfer_records (
                    project_key, story_id, run_id, ownership_epoch, repo_id,
                    takeover_base_sha, last_push_at, push_lag_hint, base_quality,
                    challenge_ref, confirm_ref, reconciled_at, reconcile_ref
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    transfer_row["reconciled_at"],
                    transfer_row["reconcile_ref"],
                ),
            )
            _run_takeover_fault_hook(
                fault_after_step,
                f"transfer_record_insert:{transfer_row['repo_id']}",
            )
        _run_takeover_fault_hook(fault_after_step, "takeover_reconcile_required")
        for command_row in edge_command_rows:
            cursor = conn.execute(
                """
                INSERT INTO edge_command_records (
                    command_id, project_key, story_id, run_id, session_id,
                    command_kind, payload_json, status, ownership_epoch,
                    created_at, delivered_at, completed_at, result_op_id,
                    result_type, result_payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    command_row["command_id"],
                    command_row["project_key"],
                    command_row["story_id"],
                    command_row["run_id"],
                    command_row["session_id"],
                    command_row["command_kind"],
                    command_row["payload_json"],
                    command_row["status"],
                    command_row["ownership_epoch"],
                    command_row["created_at"],
                    command_row["delivered_at"],
                    command_row["completed_at"],
                    command_row["result_op_id"],
                    command_row["result_type"],
                    command_row["result_payload_json"],
                ),
            )
            if int(cursor.rowcount) != 1:
                raise RuntimeError("takeover reconcile command insert affected an unexpected row count")
            _run_takeover_fault_hook(
                fault_after_step,
                f"edge_command_insert:{command_row['command_id']}",
            )
        _run_takeover_fault_hook(fault_after_step, "takeover_reconcile_commands")
        for event_row in event_rows:
            _insert_execution_event_row(conn, event_row)
            _run_takeover_fault_hook(
                fault_after_step,
                f"{_STEP_EVENT_INSERT_PREFIX}{event_row['event_type']}",
            )


def commit_takeover_reissue_global_row(
    *,
    op_row: dict[str, Any],
    expected_basis: OwnershipBasis,
    expired_challenge_row: dict[str, Any],
    fresh_challenge_row: dict[str, Any],
    relinked_approval_row: dict[str, Any],
    event_rows: Sequence[dict[str, Any]],
    fault_after_step: Callable[[str], None] | None = None,
) -> None:
    """Commit a non-transferring challenge reissue in one transaction."""

    with _connect_global() as conn:
        _conditional_upsert_control_plane_op_row(conn, op_row)
        _run_takeover_fault_hook(fault_after_step, _STEP_OP_UPSERT)
        _verify_takeover_confirm_cas(
            conn,
            op_row=op_row,
            expected_basis=expected_basis,
        )
        approval = conn.execute(
            """
            SELECT approval_id, challenge_ref, status
            FROM takeover_approvals
            WHERE challenge_ref = ?
            FOR UPDATE
            """,
            (expired_challenge_row["challenge_id"],),
        ).fetchone()
        if (
            approval is None
            or str(approval["approval_id"]) != relinked_approval_row["approval_id"]
            or str(approval["status"]) not in {"pending", "approved"}
        ):
            raise OwnershipFenceViolationError(
                "takeover reissue CAS failed: approval link is no longer eligible",
                detail={"challenge_id": expired_challenge_row["challenge_id"]},
            )
        challenge = conn.execute(
            """
            SELECT status FROM takeover_challenges
            WHERE challenge_id = ? AND project_key = ? AND story_id = ? AND run_id = ?
            FOR UPDATE
            """,
            (
                expired_challenge_row["challenge_id"],
                expired_challenge_row["project_key"],
                expired_challenge_row["story_id"],
                expired_challenge_row["run_id"],
            ),
        ).fetchone()
        if challenge is None or str(challenge["status"]) != "pending":
            raise OwnershipFenceViolationError(
                "takeover reissue CAS failed: challenge is no longer pending",
                detail={"challenge_id": expired_challenge_row["challenge_id"]},
            )
        _relink_takeover_approval_row(
            conn,
            row=relinked_approval_row,
            expected_challenge_ref=str(expired_challenge_row["challenge_id"]),
        )
        _run_takeover_fault_hook(fault_after_step, "approval_relink")
        _terminalize_takeover_challenge_row(conn, expired_challenge_row)
        _run_takeover_fault_hook(fault_after_step, "expired_challenge_terminalize")
        _insert_takeover_challenge_row(conn, fresh_challenge_row)
        _run_takeover_fault_hook(fault_after_step, "fresh_challenge_insert")
        for event_row in event_rows:
            _insert_execution_event_row(conn, event_row)
            _run_takeover_fault_hook(
                fault_after_step,
                f"{_STEP_EVENT_INSERT_PREFIX}{event_row['event_type']}",
            )


def reconcile_takeover_confirm_cas_loss_global_row(
    *,
    op_row: dict[str, Any],
    expected_basis: OwnershipBasis,
    request_op_row: dict[str, Any],
    challenge_row: dict[str, Any],
    invalidated_approval_row: dict[str, Any] | None,
    event_rows: Sequence[dict[str, Any]],
    fault_after_step: Callable[[str], None] | None = None,
) -> str:
    """Lock all decision rows, classify a CAS loss, and invalidate when stale."""

    with _connect_global() as conn:
        initial = conn.execute(
            """
            SELECT request_op_id FROM takeover_challenges
            WHERE challenge_id = ? AND project_key = ? AND story_id = ? AND run_id = ?
            """,
            (
                challenge_row["challenge_id"],
                challenge_row["project_key"],
                challenge_row["story_id"],
                challenge_row["run_id"],
            ),
        ).fetchone()
        if initial is None:
            return "challenge_not_pending"
        active, binding = _lock_takeover_basis_rows(
            conn,
            project_key=str(challenge_row["project_key"]),
            story_id=str(challenge_row["story_id"]),
            run_id=str(challenge_row["run_id"]),
            expected_basis=expected_basis,
        )
        conn.execute(
            """
            SELECT approval_id FROM takeover_approvals
            WHERE challenge_ref = ?
            FOR UPDATE
            """,
            (challenge_row["challenge_id"],),
        ).fetchone()
        conn.execute(
            """
            SELECT op_id FROM control_plane_operations
            WHERE op_id = ?
            FOR UPDATE
            """,
            (str(initial["request_op_id"]),),
        ).fetchone()
        current_challenge = conn.execute(
            """
            SELECT status FROM takeover_challenges
            WHERE challenge_id = ? AND project_key = ? AND story_id = ? AND run_id = ?
            FOR UPDATE
            """,
            (
                challenge_row["challenge_id"],
                challenge_row["project_key"],
                challenge_row["story_id"],
                challenge_row["run_id"],
            ),
        ).fetchone()
        if current_challenge is None or str(current_challenge["status"]) != "pending":
            if current_challenge is not None and str(current_challenge["status"]) == "invalidated":
                return "terminal_invalidated"
            return "challenge_not_pending"
        if _locked_takeover_basis_matches(expected_basis, active, binding):
            return "takeover_confirm_cas_lost"
        _conditional_upsert_control_plane_op_row(conn, op_row)
        _run_takeover_fault_hook(fault_after_step, _STEP_OP_UPSERT)
        _invalidate_takeover_approval_row(conn, invalidated_approval_row)
        if invalidated_approval_row is not None:
            _run_takeover_fault_hook(fault_after_step, "approval_invalidate")
        _terminalize_takeover_request_operation_row(conn, request_op_row)
        _run_takeover_fault_hook(
            fault_after_step,
            _STEP_REQUEST_OPERATION_TERMINALIZE,
        )
        _terminalize_takeover_challenge_row(conn, challenge_row)
        _run_takeover_fault_hook(fault_after_step, _STEP_CHALLENGE_TERMINALIZE)
        for event_row in event_rows:
            _insert_execution_event_row(conn, event_row)
            _run_takeover_fault_hook(
                fault_after_step,
                f"{_STEP_EVENT_INSERT_PREFIX}{event_row['event_type']}",
            )
        return "invalidated"


def commit_takeover_reconcile_clear_global_row(
    *,
    op_row: dict[str, Any],
    ownership_epoch: int,
    reconciled_at: str,
    reconcile_ref: str,
) -> None:
    """Atomically write the reconcile op and clear transfer/freeze blockers."""

    with _connect_global() as conn:
        _conditional_upsert_control_plane_op_row(conn, op_row)
        cursor = conn.execute(
            """
            UPDATE takeover_transfer_records
            SET reconciled_at = ?, reconcile_ref = ?
            WHERE project_key = ? AND story_id = ? AND run_id = ?
              AND ownership_epoch = ?
              AND reconciled_at IS NULL
            """,
            (
                reconciled_at,
                reconcile_ref,
                op_row["project_key"],
                op_row["story_id"],
                op_row["run_id"],
                ownership_epoch,
            ),
        )
        if int(cursor.rowcount) < 1:
            raise OwnershipFenceViolationError(
                "takeover reconcile clear CAS failed: no unreconciled transfer "
                "rows exist for the active ownership epoch",
                detail={
                    "project_key": op_row["project_key"],
                    "story_id": op_row["story_id"],
                    "run_id": op_row["run_id"],
                    "ownership_epoch": ownership_epoch,
                },
            )
        freeze_cursor = conn.execute(
            "DELETE FROM governance_freeze_records "
            "WHERE story_id = ? AND kind = 'contested_local_writes'",
            (op_row["story_id"],),
        )
        if int(freeze_cursor.rowcount) not in {0, 1}:
            raise RuntimeError(
                "takeover reconcile contested-freeze clear affected an unexpected row count"
            )


def _write_takeover_binding_rows(
    conn: _CompatConnection,
    *,
    revoked_binding_row: dict[str, Any],
    new_binding_row: dict[str, Any],
    fault_after_step: Callable[[str], None] | None,
) -> None:
    """Write every binding row at the canonical, session-sorted lock position."""

    actions = sorted(
        (
            (str(revoked_binding_row["session_id"]), 0, revoked_binding_row),
            (str(new_binding_row["session_id"]), 1, new_binding_row),
        ),
        key=lambda item: (item[0], item[1]),
    )
    for _, action, row in actions:
        if action == 0:
            cursor = conn.execute(
                """
                UPDATE session_run_bindings
                SET status = 'revoked', revocation_reason = ?,
                    binding_version = ?, updated_at = ?
                WHERE session_id = ? AND project_key = ? AND story_id = ?
                  AND run_id = ? AND status = 'active'
                """,
                (
                    row["revocation_reason"],
                    row["binding_version"],
                    row["updated_at"],
                    row["session_id"],
                    row["project_key"],
                    row["story_id"],
                    row["run_id"],
                ),
            )
            if int(cursor.rowcount) != 1:
                raise ControlPlaneBindingCollisionError(
                    "takeover confirm could not revoke the previous active binding",
                )
            _run_takeover_fault_hook(fault_after_step, "previous_binding_revoke")
            continue
        _insert_session_binding_row(conn, row)
        _run_takeover_fault_hook(fault_after_step, "new_binding_insert")

def _verify_takeover_confirm_cas(
    conn: _CompatConnection,
    *,
    op_row: dict[str, Any],
    expected_basis: OwnershipBasis,
) -> None:
    active, binding = _lock_takeover_basis_rows(
        conn,
        project_key=str(op_row["project_key"]),
        story_id=str(op_row["story_id"]),
        run_id=str(op_row["run_id"]),
        expected_basis=expected_basis,
    )
    if _locked_takeover_basis_matches(expected_basis, active, binding):
        return
    raise OwnershipFenceViolationError(
        "takeover confirm CAS failed: current ownership basis no longer "
        "matches the stored challenge",
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


def _lock_takeover_basis_rows(
    conn: _CompatConnection,
    *,
    project_key: str,
    story_id: str,
    run_id: str,
    expected_basis: OwnershipBasis,
) -> tuple[Any, Any]:
    """Lock ownership then binding rows in the canonical takeover order."""

    active = conn.execute(
        """
        SELECT owner_session_id, ownership_epoch, status
        FROM run_ownership_records
        WHERE project_key = ? AND story_id = ? AND run_id = ?
          AND status = 'active'
        FOR UPDATE
        """,
        (project_key, story_id, run_id),
    ).fetchone()
    binding = conn.execute(
        """
        SELECT binding_version FROM session_run_bindings
        WHERE session_id = ? AND project_key = ? AND story_id = ?
          AND run_id = ? AND status = 'active'
        FOR UPDATE
        """,
        (
            expected_basis.owner_session_id,
            project_key,
            story_id,
            run_id,
        ),
    ).fetchone()
    return active, binding


def _locked_takeover_basis_matches(
    expected_basis: OwnershipBasis,
    active: Any,
    binding: Any,
) -> bool:
    """Compare the one persistence-side full basis after row locking."""

    return (
        active is not None
        and str(active["owner_session_id"]) == expected_basis.owner_session_id
        and int(active["ownership_epoch"]) == expected_basis.ownership_epoch
        and str(active["status"]) == "active"
        and binding is not None
        and str(binding["binding_version"]) == expected_basis.binding_version
    )


def commit_takeover_deny_global_row(
    *,
    op_row: dict[str, Any],
    request_op_row: dict[str, Any],
    denied_approval_row: dict[str, Any],
    challenge_row: dict[str, Any],
    event_rows: Sequence[dict[str, Any]],
    fault_after_step: Callable[[str], None] | None = None,
) -> None:
    """Atomically deny a pending takeover approval and terminalize its request."""

    with _connect_global() as conn:
        _conditional_upsert_control_plane_op_row(conn, op_row)
        _run_takeover_fault_hook(fault_after_step, _STEP_OP_UPSERT)
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
                denied_approval_row["status"],
                denied_approval_row["decided_at"],
                denied_approval_row["decided_by_session_id"],
                denied_approval_row["decision_reason"],
                denied_approval_row["approval_id"],
                denied_approval_row["project_key"],
                denied_approval_row["story_id"],
                denied_approval_row["run_id"],
            ),
        )
        if int(cursor.rowcount) != 1:
            raise OwnershipFenceViolationError(
                "takeover deny CAS failed: approval is no longer pending",
                detail={"approval_id": denied_approval_row["approval_id"]},
            )
        _run_takeover_fault_hook(fault_after_step, "approval_deny")
        cursor = conn.execute(
            """
            UPDATE control_plane_operations
            SET status = ?, response_json = ?, updated_at = ?,
                finalized_at = ?
            WHERE op_id = ?
              AND project_key = ?
              AND story_id = ?
              AND run_id = ?
              AND status = 'pending_human_approval'
            """,
            (
                request_op_row["status"],
                request_op_row["response_json"],
                request_op_row["updated_at"],
                request_op_row["updated_at"],
                request_op_row["op_id"],
                request_op_row["project_key"],
                request_op_row["story_id"],
                request_op_row["run_id"],
            ),
        )
        if int(cursor.rowcount) != 1:
            raise OwnershipFenceViolationError(
                "takeover deny CAS failed: request operation is no longer pending",
                detail={"op_id": request_op_row["op_id"]},
            )
        _run_takeover_fault_hook(
            fault_after_step,
            _STEP_REQUEST_OPERATION_TERMINALIZE,
        )
        _terminalize_takeover_challenge_row(conn, challenge_row)
        _run_takeover_fault_hook(fault_after_step, _STEP_CHALLENGE_TERMINALIZE)
        for event_row in event_rows:
            _insert_execution_event_row(conn, event_row)
            _run_takeover_fault_hook(
                fault_after_step,
                f"{_STEP_EVENT_INSERT_PREFIX}{event_row['event_type']}",
            )


def commit_takeover_expiry_global_row(
    *,
    op_row: dict[str, Any],
    request_op_row: dict[str, Any],
    challenge_row: dict[str, Any],
    expired_approval_row: dict[str, Any] | None,
    event_rows: Sequence[dict[str, Any]],
) -> None:
    """Atomically record lazy takeover expiry and terminalize its request."""

    with _connect_global() as conn:
        _conditional_upsert_control_plane_op_row(conn, op_row)
        _expire_takeover_approval_row(conn, expired_approval_row)
        _terminalize_takeover_request_operation_row(conn, request_op_row)
        _terminalize_takeover_challenge_row(conn, challenge_row)
        for event_row in event_rows:
            _insert_execution_event_row(conn, event_row)


def commit_takeover_invalidation_global_row(
    *,
    op_row: dict[str, Any],
    request_op_row: dict[str, Any],
    challenge_row: dict[str, Any],
    invalidated_approval_row: dict[str, Any] | None,
    event_rows: Sequence[dict[str, Any]],
    fault_after_step: Callable[[str], None] | None = None,
) -> None:
    """Atomically terminalize a stale takeover challenge and its request."""

    with _connect_global() as conn:
        _conditional_upsert_control_plane_op_row(conn, op_row)
        _run_takeover_fault_hook(fault_after_step, _STEP_OP_UPSERT)
        _invalidate_takeover_approval_row(conn, invalidated_approval_row)
        _run_takeover_fault_hook(fault_after_step, "approval_invalidate")
        _terminalize_takeover_request_operation_row(conn, request_op_row)
        _run_takeover_fault_hook(
            fault_after_step,
            _STEP_REQUEST_OPERATION_TERMINALIZE,
        )
        _terminalize_takeover_challenge_row(conn, challenge_row)
        _run_takeover_fault_hook(fault_after_step, _STEP_CHALLENGE_TERMINALIZE)
        for event_row in event_rows:
            _insert_execution_event_row(conn, event_row)
            _run_takeover_fault_hook(
                fault_after_step,
                f"{_STEP_EVENT_INSERT_PREFIX}{event_row['event_type']}",
            )


def _expire_takeover_approval_row(
    conn: _CompatConnection,
    row: dict[str, Any] | None,
) -> None:
    if row is None:
        return
    cursor = conn.execute(
        """
        UPDATE takeover_approvals
        SET status = ?, decided_at = ?, decision_reason = ?
        WHERE approval_id = ?
          AND project_key = ?
          AND story_id = ?
          AND run_id = ?
          AND status = 'pending'
        """,
        (
            row["status"],
            row["decided_at"],
            row["decision_reason"],
            row["approval_id"],
            row["project_key"],
            row["story_id"],
            row["run_id"],
        ),
    )
    if int(cursor.rowcount) != 1:
        raise OwnershipFenceViolationError(
            "takeover expiry CAS failed: approval is no longer pending",
            detail={"approval_id": row["approval_id"]},
        )


def _invalidate_takeover_approval_row(
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
            "takeover invalidation CAS failed: approval is no longer pending",
            detail={"approval_id": row["approval_id"]},
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
            decision_reason = ?, challenge_ref = ?
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
            row["challenge_ref"],
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


def _relink_takeover_approval_row(
    conn: _CompatConnection,
    *,
    row: dict[str, Any],
    expected_challenge_ref: str,
) -> None:
    """CAS-relink an eligible approval to a freshly minted challenge."""

    cursor = conn.execute(
        """
        UPDATE takeover_approvals
        SET status = ?, decided_at = ?, decided_by_session_id = ?,
            decision_reason = ?, challenge_ref = ?
        WHERE approval_id = ?
          AND project_key = ?
          AND story_id = ?
          AND run_id = ?
          AND challenge_ref = ?
          AND status IN ('pending', 'approved')
        """,
        (
            row["status"],
            row["decided_at"],
            row["decided_by_session_id"],
            row["decision_reason"],
            row["challenge_ref"],
            row["approval_id"],
            row["project_key"],
            row["story_id"],
            row["run_id"],
            expected_challenge_ref,
        ),
    )
    if int(cursor.rowcount) != 1:
        raise OwnershipFenceViolationError(
            "takeover reissue CAS failed: approval relink affected no row",
            detail={"approval_id": row["approval_id"]},
        )


def _terminalize_takeover_challenge_row(
    conn: _CompatConnection,
    row: dict[str, Any],
) -> None:
    cursor = conn.execute(
        """
        UPDATE takeover_challenges
        SET status = ?, decided_at = ?, terminal_op_id = ?
        WHERE challenge_id = ?
          AND project_key = ?
          AND story_id = ?
          AND run_id = ?
          AND status = 'pending'
        """,
        (
            row["status"],
            row["decided_at"],
            row["terminal_op_id"],
            row["challenge_id"],
            row["project_key"],
            row["story_id"],
            row["run_id"],
        ),
    )
    if int(cursor.rowcount) != 1:
        raise OwnershipFenceViolationError(
            "takeover confirm CAS failed: challenge is no longer pending",
            detail={"challenge_id": row["challenge_id"]},
        )


def _insert_takeover_challenge_row(
    conn: _CompatConnection,
    row: dict[str, Any],
) -> None:
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
        (
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
        ),
    )


def _terminalize_takeover_request_operation_row(
    conn: _CompatConnection,
    row: dict[str, Any],
) -> None:
    cursor = conn.execute(
        """
        UPDATE control_plane_operations
        SET status = ?, response_json = ?, updated_at = ?,
            finalized_at = ?
        WHERE op_id = ?
          AND project_key = ?
          AND story_id = ?
          AND run_id = ?
          AND status IN ('pending_human_approval', 'offered')
        """,
        (
            row["status"],
            row["response_json"],
            row["updated_at"],
            row["updated_at"],
            row["op_id"],
            row["project_key"],
            row["story_id"],
            row["run_id"],
        ),
    )
    if int(cursor.rowcount) != 1:
        raise OwnershipFenceViolationError(
            "takeover confirm CAS failed: request operation is no longer pending",
            detail={"op_id": row["op_id"]},
        )


__all__ = [
    "commit_takeover_confirm_global_row",
    "commit_takeover_reconcile_clear_global_row",
    "commit_takeover_reissue_global_row",
    "reconcile_takeover_confirm_cas_loss_global_row",
]
