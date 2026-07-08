"""Control-plane command, sync, ownership-adjacent, and lock record facade operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.state_backend.harness_edge_command_store import (
    commission_edge_command_record_global as commission_edge_command_record_global,
)
from agentkit.backend.state_backend.harness_edge_command_store import (
    insert_edge_command_record_global as insert_edge_command_record_global,
)
from agentkit.backend.state_backend.harness_edge_command_store import (
    list_and_ack_open_edge_command_records_global as list_and_ack_open_edge_command_records_global,
)
from agentkit.backend.state_backend.harness_edge_command_store import (
    load_edge_command_record_global as load_edge_command_record_global,
)
from agentkit.backend.state_backend.harness_edge_command_store import (
    supersede_open_edge_command_global as supersede_open_edge_command_global,
)
from agentkit.backend.state_backend.prompt_runtime_store import (
    insert_execution_contract_digest_global as insert_execution_contract_digest_global,
)
from agentkit.backend.state_backend.prompt_runtime_store import (
    load_execution_contract_digest_global as load_execution_contract_digest_global,
)
from agentkit.backend.state_backend.store import mappers
from agentkit.backend.state_backend.store._facade_backend import (
    _backend_module,
    _require_control_plane_backend,
)
from agentkit.backend.state_backend.story_closure_store import (
    list_push_barrier_verdicts_global as list_push_barrier_verdicts_global,
)
from agentkit.backend.state_backend.story_closure_store import (
    list_push_freshness_records_global as list_push_freshness_records_global,
)
from agentkit.backend.state_backend.story_closure_store import (
    list_ref_protection_degradation_findings_global as list_ref_protection_degradation_findings_global,
)
from agentkit.backend.state_backend.story_closure_store import (
    load_push_barrier_verdict_global as load_push_barrier_verdict_global,
)
from agentkit.backend.state_backend.story_closure_store import (
    load_push_freshness_record_global as load_push_freshness_record_global,
)
from agentkit.backend.state_backend.story_closure_store import (
    upsert_push_barrier_verdict_global as upsert_push_barrier_verdict_global,
)
from agentkit.backend.state_backend.story_closure_store import (
    upsert_push_freshness_record_global as upsert_push_freshness_record_global,
)
from agentkit.backend.state_backend.story_closure_store import (
    upsert_ref_protection_degradation_finding_global as upsert_ref_protection_degradation_finding_global,
)

if TYPE_CHECKING:
    from datetime import datetime

    from agentkit.backend.control_plane.records import (
        ControlPlaneOperationRecord,
        ObjectMutationClaimRecord,
        TakeoverTransferRecord,
    )
    from agentkit.backend.governance.guard_system.records import (
        StoryExecutionLockRecord,
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
    """Atomically commit the op-ledger row AND the command-result CAS (K5, AG3-145).

    Fail-closed on a non-Postgres backend (``ConfigError``, K5).

    Raises:
        ControlPlaneClaimCollisionError: On an op_id collision with a LIVE
            claimed row.
        OwnershipFenceViolationError: (AG3-142 reuse) When the story's active
            ownership record no longer admits this exact snapshot.
        EdgeCommandNotOpenError: When ``command_id`` is unknown or already
            terminal (double-completion) -- nothing committed.
    """
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


def insert_object_mutation_claim_global(record: ObjectMutationClaimRecord) -> None:
    """Strictly INSERT one object-mutation claim (AG3-137). Fail-closed off-Postgres."""
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
    """Load one object-mutation claim by claimed-object identity, or ``None``."""
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
    """Atomically acquire the per-Story object-mutation claim (AG3-141).

    An ``INSERT ... ON CONFLICT DO NOTHING`` on the object PK at the backend
    (:func:`agentkit.backend.state_backend.postgres_store.acquire_object_mutation_claim_global_row`)
    -- the PK collision IS the serialization. Fail-closed off-Postgres (K5).
    """
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
    """Ownership-scoped (op_id-CAS) release of one object-mutation claim (AG3-141).

    Idempotent: a no-op (``False``) when the row is already gone or held by a
    different ``op_id``. Fail-closed off-Postgres.
    """
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
    """List object-mutation claims orphaned by EARLIER incarnations of THIS instance.

    Startup reconciliation (AG3-141 Scope item 7): only claims stamped with the
    CALLING instance's own ``backend_instance_id`` from a strictly earlier
    ``instance_incarnation`` are returned -- never a foreign identity.
    """
    _require_control_plane_backend()
    backend = _backend_module()
    rows = backend.list_orphaned_object_mutation_claims_global_row(
        backend_instance_id=backend_instance_id,
        before_incarnation=before_incarnation,
    )
    return tuple(mappers.object_mutation_claim_row_to_record(row) for row in rows)


def save_takeover_transfer_record_global(record: TakeoverTransferRecord) -> None:
    """Upsert one takeover-transfer record (AG3-137). Fail-closed off-Postgres."""
    _require_control_plane_backend()
    backend = _backend_module()
    backend.save_takeover_transfer_record_global_row(
        mappers.takeover_transfer_to_row(record),
    )


def load_takeover_transfer_record_global(
    project_key: str,
    story_id: str,
    run_id: str,
    ownership_epoch: int,
    repo_id: str,
) -> TakeoverTransferRecord | None:
    """Load one takeover-transfer record by per-repo identity, or ``None``."""
    _require_control_plane_backend()
    backend = _backend_module()
    row = backend.load_takeover_transfer_record_global_row(
        project_key,
        story_id,
        run_id,
        ownership_epoch,
        repo_id,
    )
    if row is None:
        return None
    return mappers.takeover_transfer_row_to_record(row)


def save_story_execution_lock_global(record: StoryExecutionLockRecord) -> None:
    backend = _backend_module()
    if not hasattr(backend, "save_story_execution_lock_global_row"):
        raise RuntimeError(
            "Global story-execution locks are unsupported by the active backend",
        )
    row = mappers.execution_lock_to_row(record)
    backend.save_story_execution_lock_global_row(row)


def load_story_execution_lock_global(
    project_key: str,
    story_id: str,
    run_id: str,
    lock_type: str = "story_execution",
) -> StoryExecutionLockRecord | None:
    backend = _backend_module()
    if not hasattr(backend, "load_story_execution_lock_global_row"):
        raise RuntimeError(
            "Global story-execution locks are unsupported by the active backend",
        )
    row = backend.load_story_execution_lock_global_row(
        project_key,
        story_id,
        run_id,
        lock_type,
    )
    if row is None:
        return None
    return mappers.execution_lock_row_to_record(row)


__all__ = [
    "insert_edge_command_record_global",
    "commission_edge_command_record_global",
    "load_edge_command_record_global",
    "list_and_ack_open_edge_command_records_global",
    "commit_edge_command_result_global",
    "supersede_open_edge_command_global",
    "upsert_push_freshness_record_global",
    "load_push_freshness_record_global",
    "list_push_freshness_records_global",
    "upsert_push_barrier_verdict_global",
    "load_push_barrier_verdict_global",
    "list_push_barrier_verdicts_global",
    "upsert_ref_protection_degradation_finding_global",
    "list_ref_protection_degradation_findings_global",
    "insert_execution_contract_digest_global",
    "load_execution_contract_digest_global",
    "insert_object_mutation_claim_global",
    "load_object_mutation_claim_global",
    "acquire_object_mutation_claim_global",
    "delete_object_mutation_claim_global",
    "list_orphaned_object_mutation_claims_global",
    "save_takeover_transfer_record_global",
    "load_takeover_transfer_record_global",
    "save_story_execution_lock_global",
    "load_story_execution_lock_global",
]
