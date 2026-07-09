"""Control-plane ledger, ownership, and backend-identity row mappers."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from ._common import (
    _optional_int,
    _optional_iso_datetime,
    _optional_str,
    _OptionalString,
    _parse_aware_claimed_at,
    cast_json_record,
    dump_json,
    load_json,
)

if TYPE_CHECKING:
    from agentkit.backend.control_plane.records import (
        ControlPlaneOperationRecord,
        ObjectMutationClaimRecord,
        RunOwnershipRecord,
        SessionRunBindingRecord,
        TakeoverApprovalRecord,
        TakeoverTransferRecord,
    )
    from agentkit.backend.state_backend.backend_instance_identity_types import BackendInstanceIdentityRecord



def session_binding_to_row(record: SessionRunBindingRecord) -> dict[str, Any]:
    """Convert a ``SessionRunBindingRecord`` to a DB-insertable row dict."""

    return {
        "session_id": record.session_id,
        "project_key": record.project_key,
        "story_id": record.story_id,
        "run_id": record.run_id,
        "principal_type": record.principal_type,
        "worktree_roots_json": dump_json(list(record.worktree_roots)),
        "binding_version": record.binding_version,
        "updated_at": record.updated_at.isoformat(),
        # AG3-137 additive (FK-56 §56.7a): session-binding status + revocation
        # reason. Defaults keep pre-AG3-137 rows lossless.
        "status": record.status,
        "revocation_reason": record.revocation_reason,
    }



def session_binding_row_to_record(row: dict[str, Any]) -> SessionRunBindingRecord:
    """Convert a DB row dict to a ``SessionRunBindingRecord``."""


    from agentkit.backend.control_plane.records import (
        SessionRunBindingRecord as _SessionRunBindingRecord,
    )

    status_value = row.get("status")
    reason_value = row.get("revocation_reason")
    return _SessionRunBindingRecord(
        session_id=str(row["session_id"]),
        project_key=str(row["project_key"]),
        story_id=str(row["story_id"]),
        run_id=str(row["run_id"]),
        principal_type=str(row["principal_type"]),
        worktree_roots=tuple(load_json(row["worktree_roots_json"], [])),
        binding_version=str(row["binding_version"]),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
        status=str(status_value) if status_value is not None else "active",
        revocation_reason=str(reason_value) if reason_value is not None else None,
    )



def control_plane_op_to_row(record: ControlPlaneOperationRecord) -> dict[str, Any]:
    """Convert a ``ControlPlaneOperationRecord`` to a DB-insertable row dict."""

    return {
        "op_id": record.op_id,
        "project_key": record.project_key,
        "story_id": record.story_id,
        "run_id": record.run_id,
        "session_id": record.session_id,
        "operation_kind": record.operation_kind,
        "phase": record.phase,
        "status": record.status,
        "response_json": dump_json(record.response_payload),
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        # AG3-054 owner-scoped claim: ``claimed_at`` is stored as ISO-8601 TEXT so the
        # ownership-scoped finalize/release CAS (WARNING-4) exact-match
        # roundtrips through plain text (matching the table's
        # created_at/updated_at convention).
        "claimed_by": record.claimed_by,
        "claimed_at": (
            record.claimed_at.isoformat() if record.claimed_at is not None else None
        ),
        # AG3-137 additive (inflight-operation-record, FK-91 §91.1a rules 13/16).
        # ``None`` on AG3-137 writes; populated by AG3-138/AG3-141.
        "operation_epoch": record.operation_epoch,
        "backend_instance_id": record.backend_instance_id,
        "instance_incarnation": record.instance_incarnation,
        "declared_serialization_scope": record.declared_serialization_scope,
        "finalized_at": (
            record.finalized_at.isoformat()
            if record.finalized_at is not None
            else None
        ),
        # AG3-140 (unified idempotency contract): body-hash for the
        # replay-vs-mismatch decision. ``None`` on op_id-only dedup paths.
        "request_body_hash": record.request_body_hash,
    }



def control_plane_op_row_to_record(
    row: dict[str, Any],
) -> ControlPlaneOperationRecord:
    """Convert a DB row dict to a ``ControlPlaneOperationRecord``."""

    from typing import cast

    from agentkit.backend.control_plane.records import (
        ControlPlaneOperationRecord as _ControlPlaneOperationRecord,
    )

    return _ControlPlaneOperationRecord(
        op_id=str(row["op_id"]),
        project_key=str(row["project_key"]),
        story_id=str(row["story_id"]),
        run_id=cast("_OptionalString", row["run_id"]),
        session_id=cast("_OptionalString", row["session_id"]),
        operation_kind=str(row["operation_kind"]),
        phase=cast("_OptionalString", row["phase"]),
        status=str(row["status"]),
        response_payload=cast_json_record(load_json(row["response_json"], {})),
        created_at=datetime.fromisoformat(str(row["created_at"])),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
        claimed_by=cast("_OptionalString", row.get("claimed_by")),
        claimed_at=_parse_aware_claimed_at(row.get("claimed_at")),
        # AG3-137 additive (inflight-operation-record). ``None`` on legacy /
        # pre-AG3-137 rows (the columns are absent or NULL).
        operation_epoch=_optional_int(row.get("operation_epoch")),
        backend_instance_id=cast("_OptionalString", row.get("backend_instance_id")),
        instance_incarnation=_optional_int(row.get("instance_incarnation")),
        declared_serialization_scope=cast(
            "_OptionalString", row.get("declared_serialization_scope")
        ),
        finalized_at=_optional_iso_datetime(row.get("finalized_at")),
        # AG3-140: ``None`` on legacy / pre-AG3-140 rows (column absent or NULL).
        request_body_hash=cast("_OptionalString", row.get("request_body_hash")),
    )



def run_ownership_to_row(record: RunOwnershipRecord) -> dict[str, Any]:
    """Convert a ``RunOwnershipRecord`` to a DB-insertable row dict."""

    return {
        "project_key": record.project_key,
        "story_id": record.story_id,
        "run_id": record.run_id,
        "owner_session_id": record.owner_session_id,
        "ownership_epoch": record.ownership_epoch,
        "status": record.status.value,
        "acquired_via": record.acquired_via.value,
        "acquired_at": record.acquired_at.isoformat(),
        "audit_ref": record.audit_ref,
    }



def run_ownership_row_to_record(row: dict[str, Any]) -> RunOwnershipRecord:
    """Convert a DB row dict to a ``RunOwnershipRecord``."""


    from agentkit.backend.control_plane.ownership import (
        OwnershipAcquisition,
        OwnershipStatus,
    )
    from agentkit.backend.control_plane.records import (
        RunOwnershipRecord as _RunOwnershipRecord,
    )

    return _RunOwnershipRecord(
        project_key=str(row["project_key"]),
        story_id=str(row["story_id"]),
        run_id=str(row["run_id"]),
        owner_session_id=str(row["owner_session_id"]),
        ownership_epoch=int(row["ownership_epoch"]),
        status=OwnershipStatus(str(row["status"])),
        acquired_via=OwnershipAcquisition(str(row["acquired_via"])),
        acquired_at=datetime.fromisoformat(str(row["acquired_at"])),
        audit_ref=str(row["audit_ref"]),
    )



def object_mutation_claim_to_row(record: ObjectMutationClaimRecord) -> dict[str, Any]:
    """Convert an ``ObjectMutationClaimRecord`` to a DB-insertable row dict."""

    return {
        "project_key": record.project_key,
        "serialization_scope": record.serialization_scope,
        "scope_key": record.scope_key,
        "op_id": record.op_id,
        "backend_instance_id": record.backend_instance_id,
        "instance_incarnation": record.instance_incarnation,
        "acquired_at": record.acquired_at.isoformat(),
        "queue_position": record.queue_position,
    }



def object_mutation_claim_row_to_record(
    row: dict[str, Any],
) -> ObjectMutationClaimRecord:
    """Convert a DB row dict to an ``ObjectMutationClaimRecord``."""


    from agentkit.backend.control_plane.records import (
        ObjectMutationClaimRecord as _ObjectMutationClaimRecord,
    )

    return _ObjectMutationClaimRecord(
        project_key=str(row["project_key"]),
        serialization_scope=str(row["serialization_scope"]),
        scope_key=str(row["scope_key"]),
        op_id=str(row["op_id"]),
        backend_instance_id=str(row["backend_instance_id"]),
        instance_incarnation=int(row["instance_incarnation"]),
        acquired_at=datetime.fromisoformat(str(row["acquired_at"])),
        queue_position=int(row["queue_position"]),
    )



def takeover_transfer_to_row(record: TakeoverTransferRecord) -> dict[str, Any]:
    """Convert a ``TakeoverTransferRecord`` to a DB-insertable row dict."""

    return {
        "project_key": record.project_key,
        "story_id": record.story_id,
        "run_id": record.run_id,
        "ownership_epoch": record.ownership_epoch,
        "repo_id": record.repo_id,
        "takeover_base_sha": record.takeover_base_sha,
        "last_push_at": (
            record.last_push_at.isoformat()
            if record.last_push_at is not None
            else None
        ),
        "push_lag_hint": record.push_lag_hint,
        "base_quality": record.base_quality,
        "challenge_ref": record.challenge_ref,
        "confirm_ref": record.confirm_ref,
    }



def takeover_transfer_row_to_record(row: dict[str, Any]) -> TakeoverTransferRecord:
    """Convert a DB row dict to a ``TakeoverTransferRecord``."""

    from agentkit.backend.control_plane.records import (
        TakeoverTransferRecord as _TakeoverTransferRecord,
    )

    return _TakeoverTransferRecord(
        project_key=str(row["project_key"]),
        story_id=str(row["story_id"]),
        run_id=str(row["run_id"]),
        ownership_epoch=int(row["ownership_epoch"]),
        repo_id=str(row["repo_id"]),
        takeover_base_sha=_optional_str(row.get("takeover_base_sha")),
        last_push_at=_optional_iso_datetime(row.get("last_push_at")),
        push_lag_hint=_optional_str(row.get("push_lag_hint")),
        base_quality=_optional_str(row.get("base_quality")),
        challenge_ref=_optional_str(row.get("challenge_ref")),
        confirm_ref=_optional_str(row.get("confirm_ref")),
    )


def takeover_approval_to_row(record: TakeoverApprovalRecord) -> dict[str, Any]:
    """Convert a ``TakeoverApprovalRecord`` to a DB-insertable row dict."""

    return {
        "approval_id": record.approval_id,
        "project_key": record.project_key,
        "story_id": record.story_id,
        "run_id": record.run_id,
        "requested_by_session_id": record.requested_by_session_id,
        "requested_by_principal_type": record.requested_by_principal_type,
        "reason": record.reason,
        "challenge_ref": record.challenge_ref,
        "status": record.status.value,
        "requested_at": record.requested_at.isoformat(),
        "expires_at": record.expires_at.isoformat(),
        "decided_at": (
            record.decided_at.isoformat() if record.decided_at is not None else None
        ),
        "decided_by_session_id": record.decided_by_session_id,
        "decision_reason": record.decision_reason,
    }


def takeover_approval_row_to_record(row: dict[str, Any]) -> TakeoverApprovalRecord:
    """Convert a DB row dict to a ``TakeoverApprovalRecord``."""

    from agentkit.backend.control_plane.ownership import TakeoverApprovalStatus
    from agentkit.backend.control_plane.records import (
        TakeoverApprovalRecord as _TakeoverApprovalRecord,
    )

    return _TakeoverApprovalRecord(
        approval_id=str(row["approval_id"]),
        project_key=str(row["project_key"]),
        story_id=str(row["story_id"]),
        run_id=str(row["run_id"]),
        requested_by_session_id=str(row["requested_by_session_id"]),
        requested_by_principal_type=str(row["requested_by_principal_type"]),
        reason=str(row["reason"]),
        challenge_ref=str(row["challenge_ref"]),
        status=TakeoverApprovalStatus(str(row["status"])),
        requested_at=datetime.fromisoformat(str(row["requested_at"])),
        expires_at=datetime.fromisoformat(str(row["expires_at"])),
        decided_at=_optional_iso_datetime(row.get("decided_at")),
        decided_by_session_id=_optional_str(row.get("decided_by_session_id")),
        decision_reason=_optional_str(row.get("decision_reason")),
    )



def backend_instance_identity_to_row(
    record: BackendInstanceIdentityRecord,
) -> dict[str, Any]:
    """Convert a ``BackendInstanceIdentityRecord`` to a DB-insertable row dict."""

    return {
        "backend_instance_id": record.backend_instance_id,
        "instance_incarnation": record.instance_incarnation,
        "updated_at": record.updated_at.isoformat(),
    }



def backend_instance_identity_row_to_record(
    row: dict[str, Any],
) -> BackendInstanceIdentityRecord:
    """Convert a DB row dict to a ``BackendInstanceIdentityRecord``."""


    from agentkit.backend.state_backend.backend_instance_identity_types import (
        BackendInstanceIdentityRecord as _BackendInstanceIdentityRecord,
    )

    return _BackendInstanceIdentityRecord(
        backend_instance_id=str(row["backend_instance_id"]),
        instance_incarnation=int(row["instance_incarnation"]),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
    )
