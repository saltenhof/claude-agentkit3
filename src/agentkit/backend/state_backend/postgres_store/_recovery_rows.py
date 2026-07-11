"""Transactional crash-recovery ownership supersede rows."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agentkit.backend.exceptions import OwnershipFenceViolationError

from ._connection import _connect_global
from ._control_plane_rows import (
    _insert_story_execution_lock_row,
    _write_takeover_binding_rows,
)
from ._mutation_commit_rows import (
    _conditional_upsert_control_plane_op_row,
    _enforce_blocking_freeze_row,
)
from ._ownership_rows import _insert_run_ownership_record_row
from ._runtime_rows import _insert_execution_event_row

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from agentkit.backend.control_plane.records import RunOwnershipRecord


def commit_recovery_acquisition_global_row(
    *,
    op_row: dict[str, Any],
    expected_active: RunOwnershipRecord,
    recovery_ownership_row: dict[str, Any],
    revoked_binding_row: dict[str, Any],
    new_binding_row: dict[str, Any],
    lock_rows: Sequence[dict[str, Any]],
    event_rows: Sequence[dict[str, Any]],
    fault_after_step: Callable[[str], None] | None = None,
) -> None:
    """Atomically supersede one active run and acquire its existing worktree."""

    with _connect_global() as conn:
        _conditional_upsert_control_plane_op_row(conn, op_row)
        if fault_after_step is not None:
            fault_after_step("control_plane_op_upsert")
        _enforce_blocking_freeze_row(
            conn,
            story_id=expected_active.story_id,
            command_id="ownership_recovery",
        )
        active = conn.execute(
            """
            SELECT run_id, owner_session_id, ownership_epoch, status
            FROM run_ownership_records
            WHERE project_key = ? AND story_id = ? AND status = 'active'
            FOR UPDATE
            """,
            (expected_active.project_key, expected_active.story_id),
        ).fetchone()
        if (
            active is None
            or str(active["run_id"]) != expected_active.run_id
            or str(active["owner_session_id"]) != expected_active.owner_session_id
            or int(active["ownership_epoch"]) != expected_active.ownership_epoch
        ):
            raise OwnershipFenceViolationError(
                "recovery supersede requires the exact observed active ownership record",
                detail={
                    "project_key": expected_active.project_key,
                    "story_id": expected_active.story_id,
                    "expected_run_id": expected_active.run_id,
                    "expected_owner_session_id": expected_active.owner_session_id,
                    "expected_ownership_epoch": expected_active.ownership_epoch,
                },
            )
        unreconciled = conn.execute(
            """
            SELECT 1 FROM takeover_transfer_records
            WHERE project_key = ? AND story_id = ? AND run_id = ?
              AND ownership_epoch = ? AND reconciled_at IS NULL
            LIMIT 1
            """,
            (
                expected_active.project_key,
                expected_active.story_id,
                expected_active.run_id,
                expected_active.ownership_epoch,
            ),
        ).fetchone()
        if unreconciled is not None:
            raise OwnershipFenceViolationError(
                "recovery is blocked by an unreconciled takeover obligation",
                detail={"error_code": "takeover_reconcile_required"},
            )
        cursor = conn.execute(
            """
            UPDATE run_ownership_records
            SET status = 'transferred'
            WHERE project_key = ? AND story_id = ? AND run_id = ?
              AND owner_session_id = ? AND ownership_epoch = ?
              AND status = 'active'
            """,
            (
                expected_active.project_key,
                expected_active.story_id,
                expected_active.run_id,
                expected_active.owner_session_id,
                expected_active.ownership_epoch,
            ),
        )
        if int(cursor.rowcount) != 1:
            raise OwnershipFenceViolationError(
                "recovery terminalization must affect exactly one active ownership row",
            )
        if fault_after_step is not None:
            fault_after_step("superseded_ownership_terminalized")
        _insert_run_ownership_record_row(conn, recovery_ownership_row)
        if fault_after_step is not None:
            fault_after_step("recovery_ownership_inserted")
        _write_takeover_binding_rows(
            conn,
            revoked_binding_row=revoked_binding_row,
            new_binding_row=new_binding_row,
            fault_after_step=None,
        )
        if fault_after_step is not None:
            fault_after_step("bindings_written")
        for lock_row in lock_rows:
            _insert_story_execution_lock_row(conn, lock_row)
        for event_row in event_rows:
            _insert_execution_event_row(conn, event_row)


__all__ = ["commit_recovery_acquisition_global_row"]
