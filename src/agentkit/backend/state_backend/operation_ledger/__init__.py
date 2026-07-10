"""Control-plane operation ledger shared infrastructure."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agentkit.backend.state_backend.state_backend_connection_manager import (
    _backend_module,
    _require_control_plane_backend,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from agentkit.backend.control_plane.ownership_transfer import OwnershipBasis
    from agentkit.backend.control_plane.records import (
        BindingDeleteScope,
        ControlPlaneOperationRecord,
        ObjectMutationClaimRecord,
        RunOwnershipRecord,
        SessionRunBindingRecord,
        TakeoverApprovalRecord,
        TakeoverChallengeRecord,
        TakeoverConfirmTerminalRecords,
        TakeoverReissueRecords,
        TakeoverTransferRecord,
    )
    from agentkit.backend.governance.guard_system.records import (
        StoryExecutionLockRecord,
    )
    from agentkit.backend.prompt_runtime.execution_contract import (
        ExecutionContractDigestRecord,
    )
    from agentkit.backend.telemetry.contract.records import ExecutionEventRecord

_GLOBAL_CP_OP_UNSUPPORTED = (
    "Global control-plane operations are unsupported by the active backend"
)


def save_control_plane_operation_global(
    record: ControlPlaneOperationRecord,
) -> None:
    """Persist one control-plane operation ledger record."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    backend = _backend_module()
    if not hasattr(backend, "save_control_plane_operation_global_row"):
        raise RuntimeError(_GLOBAL_CP_OP_UNSUPPORTED)
    row = mappers.control_plane_op_to_row(record)
    backend.save_control_plane_operation_global_row(row)


def claim_control_plane_operation_global(
    record: ControlPlaneOperationRecord,
) -> bool:
    """Atomically claim an op_id before dispatch."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    backend = _backend_module()
    if not hasattr(backend, "claim_control_plane_operation_global_row"):
        raise RuntimeError(
            "Atomic control-plane op claim is unsupported by the active backend",
        )
    row = mappers.control_plane_op_to_row(record)
    return bool(backend.claim_control_plane_operation_global_row(row))


def finalize_control_plane_operation_global(
    record: ControlPlaneOperationRecord,
    *,
    owner_token: str,
    owner_claimed_at: str | None = None,
    owner_operation_epoch: int | None = None,
) -> bool:
    """Ownership-scoped terminal write of a claimed operation."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    backend = _backend_module()
    if not hasattr(backend, "finalize_control_plane_operation_global_row"):
        raise RuntimeError(
            "Control-plane op finalize is unsupported by the active backend",
        )
    row = mappers.control_plane_op_to_row(record)
    return bool(
        backend.finalize_control_plane_operation_global_row(
            row,
            owner_token=owner_token,
            owner_claimed_at=owner_claimed_at,
            owner_operation_epoch=owner_operation_epoch,
        )
    )


def claim_inflight_operation_row_global(row: dict[str, Any]) -> bool:
    """Atomically claim an op_id from a caller-built row."""
    backend = _backend_module()
    if not hasattr(backend, "claim_control_plane_operation_global_row"):
        raise RuntimeError(
            "Atomic control-plane op claim is unsupported by the active backend",
        )
    return bool(backend.claim_control_plane_operation_global_row(row))


def load_inflight_operation_row_global(op_id: str) -> dict[str, Any] | None:
    """Load the raw inflight-operation-record row for ``op_id``."""
    backend = _backend_module()
    if not hasattr(backend, "load_control_plane_operation_global_row"):
        raise RuntimeError(_GLOBAL_CP_OP_UNSUPPORTED)
    row = backend.load_control_plane_operation_global_row(op_id)
    return dict(row) if row is not None else None


def finalize_inflight_operation_row_global(
    row: dict[str, Any],
    *,
    owner_token: str,
    owner_claimed_at: str | None = None,
) -> bool:
    """Ownership-scoped terminal write from a caller-built row."""
    backend = _backend_module()
    if not hasattr(backend, "finalize_control_plane_operation_global_row"):
        raise RuntimeError(
            "Control-plane op finalize is unsupported by the active backend",
        )
    return bool(
        backend.finalize_control_plane_operation_global_row(
            row,
            owner_token=owner_token,
            owner_claimed_at=owner_claimed_at,
        )
    )


def finalize_control_plane_start_phase_global(
    record: ControlPlaneOperationRecord,
    *,
    owner_token: str,
    owner_claimed_at: str | None = None,
    owner_operation_epoch: int | None = None,
    binding: SessionRunBindingRecord | None,
    locks: tuple[StoryExecutionLockRecord, ...],
    events: tuple[ExecutionEventRecord, ...],
    ownership_record_to_insert: RunOwnershipRecord | None = None,
    execution_contract_digest_to_insert: ExecutionContractDigestRecord | None = None,
    expected_ownership_epoch: int | None = None,
) -> bool:
    """Atomically CAS-finalize a start_phase and materialize side effects."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    backend = _backend_module()
    if not hasattr(backend, "finalize_control_plane_start_phase_global_row"):
        raise RuntimeError(
            "Control-plane start-phase finalize is unsupported by the active backend",
        )
    return bool(
        backend.finalize_control_plane_start_phase_global_row(
            op_row=mappers.control_plane_op_to_row(record),
            owner_token=owner_token,
            owner_claimed_at=owner_claimed_at,
            owner_operation_epoch=owner_operation_epoch,
            binding_row=(
                mappers.session_binding_to_row(binding)
                if binding is not None
                else None
            ),
            lock_rows=tuple(mappers.execution_lock_to_row(lock) for lock in locks),
            event_rows=tuple(mappers.execution_event_to_row(event) for event in events),
            ownership_row_to_insert=(
                mappers.run_ownership_to_row(ownership_record_to_insert)
                if ownership_record_to_insert is not None
                else None
            ),
            execution_contract_digest_row_to_insert=(
                mappers.execution_contract_digest_to_row(
                    execution_contract_digest_to_insert,
                )
                if execution_contract_digest_to_insert is not None
                else None
            ),
            expected_ownership_epoch=expected_ownership_epoch,
        )
    )


def commit_control_plane_operation_with_side_effects_global(
    record: ControlPlaneOperationRecord,
    *,
    binding_to_save: SessionRunBindingRecord | None,
    binding_to_delete: BindingDeleteScope | None,
    locks: tuple[StoryExecutionLockRecord, ...],
    events: tuple[ExecutionEventRecord, ...],
    expected_ownership_epoch: int | None = None,
) -> None:
    """Atomically commit a terminal operation and its side effects."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    backend = _backend_module()
    if not hasattr(backend, "commit_control_plane_operation_with_side_effects_global_row"):
        raise RuntimeError(
            "Atomic control-plane mutation commit is unsupported by the active backend",
        )
    backend.commit_control_plane_operation_with_side_effects_global_row(
        op_row=mappers.control_plane_op_to_row(record),
        binding_to_save=(
            mappers.session_binding_to_row(binding_to_save)
            if binding_to_save is not None
            else None
        ),
        binding_to_delete=(
            {
                "session_id": binding_to_delete.session_id,
                "project_key": binding_to_delete.project_key,
                "story_id": binding_to_delete.story_id,
                "run_id": binding_to_delete.run_id,
            }
            if binding_to_delete is not None
            else None
        ),
        expected_ownership_epoch=expected_ownership_epoch,
        lock_rows=tuple(mappers.execution_lock_to_row(lock) for lock in locks),
        event_rows=tuple(mappers.execution_event_to_row(event) for event in events),
    )


def commit_edge_command_result_global(
    op_record: ControlPlaneOperationRecord,
    *,
    command_id: str,
    result_status: str,
    completed_at: datetime,
    result_op_id: str,
    result_type: str,
    result_payload: dict[str, object],
    expected_ownership_epoch: int,
) -> None:
    """Atomically commit the operation ledger row and command-result CAS."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    _require_control_plane_backend()
    backend = _backend_module()
    backend.commit_edge_command_result_global_row(
        op_row=mappers.control_plane_op_to_row(op_record),
        command_id=command_id,
        result_row={
            "status": result_status,
            "completed_at": completed_at.isoformat(),
            "result_op_id": result_op_id,
            "result_type": result_type,
            "result_payload_json": mappers.dump_json(result_payload),
        },
        expected_ownership_epoch=expected_ownership_epoch,
    )


def commit_takeover_confirm_global(
    op_record: ControlPlaneOperationRecord,
    *,
    expected_basis: OwnershipBasis,
    revoked_binding: SessionRunBindingRecord,
    new_binding: SessionRunBindingRecord,
    locks: tuple[StoryExecutionLockRecord, ...],
    transfers: tuple[TakeoverTransferRecord, ...],
    events: tuple[ExecutionEventRecord, ...],
    terminal_records: TakeoverConfirmTerminalRecords,
    fault_after_step: Callable[[str], None] | None = None,
) -> None:
    """Atomically commit takeover confirm side effects in one transaction."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    _require_control_plane_backend()
    backend = _backend_module()
    backend.commit_takeover_confirm_global_row(
        op_row=mappers.control_plane_op_to_row(op_record),
        expected_basis=expected_basis,
        revoked_binding_row=mappers.session_binding_to_row(revoked_binding),
        new_binding_row=mappers.session_binding_to_row(new_binding),
        lock_rows=tuple(mappers.execution_lock_to_row(lock) for lock in locks),
        transfer_rows=tuple(
            mappers.takeover_transfer_to_row(record) for record in transfers
        ),
        event_rows=tuple(mappers.execution_event_to_row(event) for event in events),
        terminal_rows={
            "challenge": mappers.takeover_challenge_to_row(
                terminal_records.challenge,
            ),
            "request_op": mappers.control_plane_op_to_row(
                terminal_records.request_op_record,
            ),
            "approved_approval": (
                mappers.takeover_approval_to_row(terminal_records.approved_approval)
                if terminal_records.approved_approval is not None
                else None
            ),
        },
        fault_after_step=fault_after_step,
    )


def commit_takeover_reissue_global(
    op_record: ControlPlaneOperationRecord,
    *,
    expected_basis: OwnershipBasis,
    records: TakeoverReissueRecords,
    events: tuple[ExecutionEventRecord, ...],
    fault_after_step: Callable[[str], None] | None = None,
) -> None:
    """Atomically expire, mint, approve/relink, and record one reissue."""

    from agentkit.backend.state_backend import persistence_mappers as mappers

    _require_control_plane_backend()
    backend = _backend_module()
    backend.commit_takeover_reissue_global_row(
        op_row=mappers.control_plane_op_to_row(op_record),
        expected_basis=expected_basis,
        expired_challenge_row=mappers.takeover_challenge_to_row(
            records.expired_challenge
        ),
        fresh_challenge_row=mappers.takeover_challenge_to_row(records.fresh_challenge),
        relinked_approval_row=mappers.takeover_approval_to_row(
            records.relinked_approval
        ),
        event_rows=tuple(mappers.execution_event_to_row(event) for event in events),
        fault_after_step=fault_after_step,
    )


def reconcile_takeover_confirm_cas_loss_global(
    op_record: ControlPlaneOperationRecord,
    *,
    expected_basis: OwnershipBasis,
    request_op_record: ControlPlaneOperationRecord,
    challenge: TakeoverChallengeRecord,
    invalidated_approval: TakeoverApprovalRecord | None,
    events: tuple[ExecutionEventRecord, ...],
) -> str:
    """Classify and, when stale, terminalize one confirm CAS loss."""

    from agentkit.backend.state_backend import persistence_mappers as mappers

    _require_control_plane_backend()
    backend = _backend_module()
    return str(
        backend.reconcile_takeover_confirm_cas_loss_global_row(
            op_row=mappers.control_plane_op_to_row(op_record),
            expected_basis=expected_basis,
            request_op_row=mappers.control_plane_op_to_row(request_op_record),
            challenge_row=mappers.takeover_challenge_to_row(challenge),
            invalidated_approval_row=(
                mappers.takeover_approval_to_row(invalidated_approval)
                if invalidated_approval is not None
                else None
            ),
            event_rows=tuple(
                mappers.execution_event_to_row(event) for event in events
            ),
        )
    )


def commit_takeover_deny_global(
    op_record: ControlPlaneOperationRecord,
    *,
    request_op_record: ControlPlaneOperationRecord,
    denied_approval: TakeoverApprovalRecord,
    challenge: TakeoverChallengeRecord,
    events: tuple[ExecutionEventRecord, ...],
) -> None:
    """Atomically deny a takeover approval and terminalize related rows."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    _require_control_plane_backend()
    backend = _backend_module()
    backend.commit_takeover_deny_global_row(
        op_row=mappers.control_plane_op_to_row(op_record),
        request_op_row=mappers.control_plane_op_to_row(request_op_record),
        denied_approval_row=mappers.takeover_approval_to_row(denied_approval),
        challenge_row=mappers.takeover_challenge_to_row(challenge),
        event_rows=tuple(mappers.execution_event_to_row(event) for event in events),
    )


def commit_takeover_expiry_global(
    op_record: ControlPlaneOperationRecord,
    *,
    request_op_record: ControlPlaneOperationRecord,
    challenge: TakeoverChallengeRecord,
    expired_approval: TakeoverApprovalRecord | None,
    events: tuple[ExecutionEventRecord, ...],
) -> None:
    """Atomically record lazy takeover expiry and terminalize related rows."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    _require_control_plane_backend()
    backend = _backend_module()
    backend.commit_takeover_expiry_global_row(
        op_row=mappers.control_plane_op_to_row(op_record),
        request_op_row=mappers.control_plane_op_to_row(request_op_record),
        challenge_row=mappers.takeover_challenge_to_row(challenge),
        expired_approval_row=(
            mappers.takeover_approval_to_row(expired_approval)
            if expired_approval is not None
            else None
        ),
        event_rows=tuple(mappers.execution_event_to_row(event) for event in events),
    )


def commit_takeover_invalidation_global(
    op_record: ControlPlaneOperationRecord,
    *,
    request_op_record: ControlPlaneOperationRecord,
    challenge: TakeoverChallengeRecord,
    invalidated_approval: TakeoverApprovalRecord | None,
    events: tuple[ExecutionEventRecord, ...],
    fault_after_step: Callable[[str], None] | None = None,
) -> None:
    """Atomically record stale challenge invalidation and terminalize request rows."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    _require_control_plane_backend()
    backend = _backend_module()
    backend.commit_takeover_invalidation_global_row(
        op_row=mappers.control_plane_op_to_row(op_record),
        request_op_row=mappers.control_plane_op_to_row(request_op_record),
        challenge_row=mappers.takeover_challenge_to_row(challenge),
        invalidated_approval_row=(
            mappers.takeover_approval_to_row(invalidated_approval)
            if invalidated_approval is not None
            else None
        ),
        event_rows=tuple(mappers.execution_event_to_row(event) for event in events),
        fault_after_step=fault_after_step,
    )


def commit_takeover_reconcile_clear_global(
    op_record: ControlPlaneOperationRecord,
    *,
    ownership_epoch: int,
    reconciled_at: datetime,
    reconcile_ref: str,
) -> None:
    """Atomically record an admin clear of the takeover reconcile obligation."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    _require_control_plane_backend()
    backend = _backend_module()
    backend.commit_takeover_reconcile_clear_global_row(
        op_row=mappers.control_plane_op_to_row(op_record),
        ownership_epoch=ownership_epoch,
        reconciled_at=reconciled_at.isoformat(),
        reconcile_ref=reconcile_ref,
    )


def release_control_plane_operation_global(
    op_id: str,
    *,
    owner_token: str,
    owner_claimed_at: str | None = None,
) -> None:
    """Ownership-scoped release of a claimed control-plane operation."""
    backend = _backend_module()
    if not hasattr(backend, "release_control_plane_operation_global_row"):
        raise RuntimeError(
            "Control-plane op release is unsupported by the active backend",
        )
    backend.release_control_plane_operation_global_row(
        op_id,
        owner_token=owner_token,
        owner_claimed_at=owner_claimed_at,
    )


def list_orphaned_claimed_control_plane_operations_global(
    backend_instance_id: str,
    before_incarnation: int,
) -> tuple[ControlPlaneOperationRecord, ...]:
    """List claimed operations orphaned by earlier incarnations of this instance."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    _require_control_plane_backend()
    backend = _backend_module()
    rows = backend.list_orphaned_claimed_control_plane_operations_global_row(
        backend_instance_id=backend_instance_id,
        before_incarnation=before_incarnation,
    )
    return tuple(mappers.control_plane_op_row_to_record(row) for row in rows)


def finalize_orphaned_control_plane_operation_global(
    *,
    op_id: str,
    backend_instance_id: str,
    status: str,
    response_payload: dict[str, object],
    now: datetime,
    owner_operation_epoch: int,
) -> bool:
    """CAS-finalize one orphaned claim during startup reconciliation."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    _require_control_plane_backend()
    backend = _backend_module()
    return bool(
        backend.finalize_orphaned_control_plane_operation_global_row(
            op_id=op_id,
            backend_instance_id=backend_instance_id,
            status=status,
            response_json=mappers.dump_json(response_payload),
            now=now.isoformat(),
            owner_operation_epoch=owner_operation_epoch,
        )
    )


def admin_abort_control_plane_operation_global(
    *,
    op_id: str,
    status: str,
    response_payload: dict[str, object],
    now: datetime,
) -> bool:
    """CAS-abort one in-flight claim via the admin-abort service path."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    _require_control_plane_backend()
    backend = _backend_module()
    return bool(
        backend.admin_abort_control_plane_operation_global_row(
            op_id=op_id,
            status=status,
            response_json=mappers.dump_json(response_payload),
            now=now.isoformat(),
        )
    )


def resolve_repair_control_plane_operation_global(
    *,
    op_id: str,
    response_payload: dict[str, object],
    now: datetime,
) -> bool:
    """CAS-resolve one open repair operation to resolved."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    _require_control_plane_backend()
    backend = _backend_module()
    return bool(
        backend.resolve_repair_control_plane_operation_global_row(
            op_id=op_id,
            response_json=mappers.dump_json(response_payload),
            now=now.isoformat(),
        )
    )


def has_engine_writes_since_control_plane_claim_global(
    story_id: str,
    since: datetime,
) -> bool:
    """Return whether engine writes exist since a claim timestamp."""
    _require_control_plane_backend()
    backend = _backend_module()
    return bool(
        backend.has_engine_writes_since_control_plane_claim_global_row(
            story_id=story_id,
            since=since.isoformat(),
        )
    )


def has_open_repair_control_plane_operation_for_story_global(
    project_key: str,
    story_id: str,
) -> bool:
    """Return whether a story has an open repair operation."""
    _require_control_plane_backend()
    backend = _backend_module()
    return bool(
        backend.has_open_repair_control_plane_operation_for_story_global_row(
            project_key=project_key,
            story_id=story_id,
        )
    )


def has_unreconciled_takeover_transfer_for_story_global(
    project_key: str,
    story_id: str,
) -> bool:
    """Return whether a story has an unreconciled takeover transfer."""
    _require_control_plane_backend()
    backend = _backend_module()
    return bool(
        backend.has_unreconciled_takeover_transfer_for_story_global_row(
            project_key=project_key,
            story_id=story_id,
        )
    )


def list_open_control_plane_operation_ids_for_story_global(
    project_key: str,
    story_id: str,
) -> tuple[str, ...]:
    """Return currently claimed control-plane operation ids for one story."""
    _require_control_plane_backend()
    backend = _backend_module()
    return tuple(
        backend.list_open_control_plane_operation_ids_for_story_global_row(
            project_key,
            story_id,
        )
    )


def has_committed_control_plane_operation_for_run_global(
    project_key: str,
    story_id: str,
    run_id: str,
) -> bool:
    """Return whether a committed control-plane operation exists for one run."""
    backend = _backend_module()
    if not hasattr(backend, "has_committed_control_plane_operation_for_run_global_row"):
        raise RuntimeError(
            "Control-plane run-admission probe is unsupported by the active backend",
        )
    return bool(
        backend.has_committed_control_plane_operation_for_run_global_row(
            project_key,
            story_id,
            run_id,
        )
    )


def has_committed_story_exit_operation_for_run_global(
    project_key: str,
    story_id: str,
    run_id: str,
) -> bool:
    """Return whether a committed story-exit terminal marker exists for one run."""
    backend = _backend_module()
    if not hasattr(backend, "has_committed_story_exit_operation_for_run_global_row"):
        raise RuntimeError(
            "Control-plane story-exit terminal probe is unsupported by the active backend",
        )
    return bool(
        backend.has_committed_story_exit_operation_for_run_global_row(
            project_key,
            story_id,
            run_id,
        )
    )


def has_committed_ownership_invalidating_operation_for_run_global(
    project_key: str,
    story_id: str,
    run_id: str,
) -> bool:
    """Return whether a committed terminal predecessor invalidates takeover challenges."""
    backend = _backend_module()
    if not hasattr(
        backend,
        "has_committed_ownership_invalidating_operation_for_run_global_row",
    ):
        raise RuntimeError(
            "Control-plane ownership-invalidation probe is unsupported by the active backend",
        )
    return bool(
        backend.has_committed_ownership_invalidating_operation_for_run_global_row(
            project_key,
            story_id,
            run_id,
        )
    )


def delete_control_plane_operation_global(op_id: str) -> None:
    """Unconditionally delete a control-plane operation row."""
    backend = _backend_module()
    if not hasattr(backend, "delete_control_plane_operation_global_row"):
        raise RuntimeError(
            "Control-plane op deletion is unsupported by the active backend",
        )
    backend.delete_control_plane_operation_global_row(op_id)


def load_control_plane_operation_global(
    op_id: str,
) -> ControlPlaneOperationRecord | None:
    """Load one control-plane operation record."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    backend = _backend_module()
    if not hasattr(backend, "load_control_plane_operation_global_row"):
        raise RuntimeError(_GLOBAL_CP_OP_UNSUPPORTED)
    row = backend.load_control_plane_operation_global_row(op_id)
    if row is None:
        return None
    return mappers.control_plane_op_row_to_record(row)


def insert_object_mutation_claim_global(record: ObjectMutationClaimRecord) -> None:
    """Strictly insert one object-mutation claim."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    _require_control_plane_backend()
    backend = _backend_module()
    backend.insert_object_mutation_claim_global_row(
        mappers.object_mutation_claim_to_row(record),
    )


def load_object_mutation_claim_global(
    project_key: str,
    serialization_scope: str,
    scope_key: str,
) -> ObjectMutationClaimRecord | None:
    """Load one object-mutation claim by claimed-object identity."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    _require_control_plane_backend()
    backend = _backend_module()
    row = backend.load_object_mutation_claim_global_row(
        project_key,
        serialization_scope,
        scope_key,
    )
    if row is None:
        return None
    return mappers.object_mutation_claim_row_to_record(row)


def acquire_object_mutation_claim_global(
    *,
    project_key: str,
    serialization_scope: str,
    scope_key: str,
    op_id: str,
    backend_instance_id: str,
    instance_incarnation: int,
    acquired_at: datetime,
) -> bool:
    """Atomically acquire the per-story object-mutation claim."""
    _require_control_plane_backend()
    backend = _backend_module()
    return bool(
        backend.acquire_object_mutation_claim_global_row(
            {
                "project_key": project_key,
                "serialization_scope": serialization_scope,
                "scope_key": scope_key,
                "op_id": op_id,
                "backend_instance_id": backend_instance_id,
                "instance_incarnation": instance_incarnation,
                "acquired_at": acquired_at.isoformat(),
            },
        ),
    )


def delete_object_mutation_claim_global(
    project_key: str,
    serialization_scope: str,
    scope_key: str,
    op_id: str,
) -> bool:
    """Ownership-scoped release of one object-mutation claim."""
    _require_control_plane_backend()
    backend = _backend_module()
    return bool(
        backend.delete_object_mutation_claim_global(
            project_key,
            serialization_scope,
            scope_key,
            op_id,
        ),
    )


def list_orphaned_object_mutation_claims_global(
    backend_instance_id: str,
    before_incarnation: int,
) -> tuple[ObjectMutationClaimRecord, ...]:
    """List object-mutation claims orphaned by earlier incarnations of this instance."""
    from agentkit.backend.state_backend import persistence_mappers as mappers

    _require_control_plane_backend()
    backend = _backend_module()
    rows = backend.list_orphaned_object_mutation_claims_global_row(
        backend_instance_id=backend_instance_id,
        before_incarnation=before_incarnation,
    )
    return tuple(mappers.object_mutation_claim_row_to_record(row) for row in rows)


__all__ = [
    "save_control_plane_operation_global",
    "claim_control_plane_operation_global",
    "finalize_control_plane_operation_global",
    "claim_inflight_operation_row_global",
    "load_inflight_operation_row_global",
    "finalize_inflight_operation_row_global",
    "finalize_control_plane_start_phase_global",
    "commit_control_plane_operation_with_side_effects_global",
    "commit_edge_command_result_global",
    "commit_takeover_deny_global",
    "commit_takeover_confirm_global",
    "commit_takeover_reissue_global",
    "reconcile_takeover_confirm_cas_loss_global",
    "commit_takeover_expiry_global",
    "commit_takeover_invalidation_global",
    "commit_takeover_reconcile_clear_global",
    "release_control_plane_operation_global",
    "list_orphaned_claimed_control_plane_operations_global",
    "finalize_orphaned_control_plane_operation_global",
    "admin_abort_control_plane_operation_global",
    "resolve_repair_control_plane_operation_global",
    "has_engine_writes_since_control_plane_claim_global",
    "has_open_repair_control_plane_operation_for_story_global",
    "has_unreconciled_takeover_transfer_for_story_global",
    "list_open_control_plane_operation_ids_for_story_global",
    "has_committed_control_plane_operation_for_run_global",
    "has_committed_story_exit_operation_for_run_global",
    "has_committed_ownership_invalidating_operation_for_run_global",
    "delete_control_plane_operation_global",
    "load_control_plane_operation_global",
    "insert_object_mutation_claim_global",
    "load_object_mutation_claim_global",
    "acquire_object_mutation_claim_global",
    "delete_object_mutation_claim_global",
    "list_orphaned_object_mutation_claims_global",
]
