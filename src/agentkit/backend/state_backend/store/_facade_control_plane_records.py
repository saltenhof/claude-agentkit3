"""Control-plane command, sync, ownership-adjacent, and lock record facade operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.state_backend.store import mappers
from agentkit.backend.state_backend.store._facade_backend import (
    _backend_module,
    _require_control_plane_backend,
)

if TYPE_CHECKING:
    from datetime import datetime

    from agentkit.backend.control_plane.push_sync import (
        PushBarrierVerdict,
        PushFreshnessRecord,
        RefProtectionDegradationFinding,
        SyncPointBarrierType,
    )
    from agentkit.backend.control_plane.records import (
        BackendInstanceIdentityRecord,
        ControlPlaneOperationRecord,
        EdgeCommandRecord,
        ObjectMutationClaimRecord,
        TakeoverTransferRecord,
    )
    from agentkit.backend.governance.guard_system.records import (
        StoryExecutionLockRecord,
    )
    from agentkit.backend.prompt_runtime.execution_contract import (
        ExecutionContractDigestRecord,
    )


def insert_edge_command_record_global(record: EdgeCommandRecord) -> None:
    """Strictly INSERT one edge-command row (AG3-145 command creation).

    Fail-closed on a non-Postgres backend (``ConfigError``, K5).
    """
    _require_control_plane_backend()
    backend = _backend_module()
    backend.insert_edge_command_record_global_row(mappers.edge_command_record_to_row(record))


def commission_edge_command_record_global(record: EdgeCommandRecord) -> bool:
    """Atomically INSERT one edge-command row if absent (AG3-145 commissioning).

    Idempotent by the deterministic ``command_id`` (``ON CONFLICT DO NOTHING``):
    a concurrent double commissioning is a no-op, never a ``UniqueViolation``
    (FK-10 §10.5.3). Fail-closed on a non-Postgres backend (``ConfigError``, K5).

    Returns:
        ``True`` iff THIS call inserted the row; ``False`` when the command
        already exists.
    """
    _require_control_plane_backend()
    backend = _backend_module()
    return bool(backend.commission_edge_command_record_global_row(mappers.edge_command_record_to_row(record)))


def load_edge_command_record_global(command_id: str) -> EdgeCommandRecord | None:
    """Load one edge-command record by ``command_id``, or ``None`` (K5)."""
    _require_control_plane_backend()
    backend = _backend_module()
    row = backend.load_edge_command_record_global_row(command_id)
    if row is None:
        return None
    return mappers.edge_command_row_to_record(row)


def list_and_ack_open_edge_command_records_global(
    *,
    project_key: str,
    run_id: str,
    session_id: str,
    delivered_at: datetime,
) -> tuple[EdgeCommandRecord, ...]:
    """Return + ack the session's open commands (K5, FK-91 §91.1a Rule 13: no lock)."""
    _require_control_plane_backend()
    backend = _backend_module()
    rows = backend.list_and_ack_open_edge_command_records_global_row(
        project_key=project_key,
        run_id=run_id,
        session_id=session_id,
        delivered_at=delivered_at.isoformat(),
    )
    return tuple(mappers.edge_command_row_to_record(row) for row in rows)


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


def supersede_open_edge_command_global(
    *,
    command_id: str,
    completed_at: datetime,
    result_payload: dict[str, object],
) -> bool:
    """Terminalize an open edge command superseded by a newer boundary epoch."""
    _require_control_plane_backend()
    backend = _backend_module()
    return bool(
        backend.supersede_open_edge_command_global_row(
            command_id=command_id,
            completed_at=completed_at.isoformat(),
            result_payload_json=mappers.dump_json(result_payload),
        )
    )


def upsert_push_freshness_record_global(record: PushFreshnessRecord) -> None:
    """Upsert one push-freshness row per ``(project, story, run, repo)`` (AG3-147).

    Fail-closed on a non-Postgres backend (``ConfigError``, K5): the push
    freshness / backlog read surface is Postgres-only, no SQLite mirror (AC13).
    """
    _require_control_plane_backend()
    backend = _backend_module()
    backend.upsert_push_freshness_record_global_row(mappers.push_freshness_record_to_row(record))


def load_push_freshness_record_global(project_key: str, story_id: str, run_id: str, repo_id: str) -> PushFreshnessRecord | None:
    """Load one push-freshness record for a repo, or ``None`` (AG3-147, K5)."""
    _require_control_plane_backend()
    backend = _backend_module()
    row = backend.load_push_freshness_record_global_row(project_key, story_id, run_id, repo_id)
    if row is None:
        return None
    return mappers.push_freshness_row_to_record(row)


def list_push_freshness_records_global(project_key: str, story_id: str, run_id: str) -> tuple[PushFreshnessRecord, ...]:
    """List the run's push-freshness records, one per repo (AG3-147, K5)."""
    _require_control_plane_backend()
    backend = _backend_module()
    rows = backend.list_push_freshness_records_global_row(project_key, story_id, run_id)
    return tuple(mappers.push_freshness_row_to_record(row) for row in rows)


def upsert_push_barrier_verdict_global(record: PushBarrierVerdict) -> None:
    """Upsert the authoritative per-repo push-barrier verdict (AG3-147, K5)."""
    _require_control_plane_backend()
    backend = _backend_module()
    backend.upsert_push_barrier_verdict_global_row(mappers.push_barrier_verdict_to_row(record))


def load_push_barrier_verdict_global(
    *,
    project_key: str,
    story_id: str,
    run_id: str,
    boundary_type: SyncPointBarrierType,
    boundary_id: str,
    repo_id: str,
) -> PushBarrierVerdict | None:
    """Load one push-barrier verdict, or ``None`` (AG3-147, K5)."""
    _require_control_plane_backend()
    backend = _backend_module()
    row = backend.load_push_barrier_verdict_global_row(
        project_key,
        story_id,
        run_id,
        boundary_type.value,
        boundary_id,
        repo_id,
    )
    if row is None:
        return None
    return mappers.push_barrier_verdict_row_to_record(row)


def list_push_barrier_verdicts_global(
    *,
    project_key: str,
    story_id: str,
    run_id: str,
    boundary_type: SyncPointBarrierType,
    boundary_id: str,
) -> tuple[PushBarrierVerdict, ...]:
    """List the per-repo verdicts for one boundary instance (AG3-147, K5)."""
    _require_control_plane_backend()
    backend = _backend_module()
    rows = backend.list_push_barrier_verdicts_global_row(
        project_key,
        story_id,
        run_id,
        boundary_type.value,
        boundary_id,
    )
    return tuple(mappers.push_barrier_verdict_row_to_record(row) for row in rows)


def upsert_ref_protection_degradation_finding_global(
    *,
    project_key: str,
    story_id: str,
    repo_id: str,
    finding: RefProtectionDegradationFinding,
    recorded_at: datetime,
) -> None:
    """Persist a project-visible ref-protection degradation WARNING (AG3-147)."""
    backend = _backend_module()
    _require_control_plane_backend()
    backend.upsert_ref_protection_degradation_finding_global_row(
        {
            "project_key": project_key,
            "story_id": story_id,
            "repo_id": repo_id,
            "finding_code": finding.finding_code,
            "severity": finding.severity,
            "provider_label": finding.provider_label,
            "detail": finding.detail,
            "recorded_at": recorded_at.isoformat(),
        }
    )


def list_ref_protection_degradation_findings_global(project_key: str, story_id: str) -> tuple[dict[str, object], ...]:
    """List project-visible ref-protection degradation WARNING rows."""
    backend = _backend_module()
    _require_control_plane_backend()
    rows = backend.list_ref_protection_degradation_finding_global_rows(project_key, story_id)
    return tuple(dict(row) for row in rows)


def insert_execution_contract_digest_global(
    record: ExecutionContractDigestRecord,
) -> None:
    """Strictly INSERT one execution-contract-digest row (AG3-143).

    Standalone entrypoint (test seeding / backfill parity with
    ``insert_run_ownership_record_global``); the productive setup-start
    writer inserts atomically WITHIN the
    ``finalize_control_plane_start_phase_global_row`` transaction instead
    (see ``execution_contract_digest_row_to_insert``), never via this
    standalone call. Fail-closed on a non-Postgres backend (``ConfigError``,
    K5); a second row for the same ``(project_key, story_id, run_id)``
    identity is rejected by the persistence layer's primary key (read-only
    after insert, FK-44 §44.3a).
    """
    _require_control_plane_backend()
    backend = _backend_module()
    backend.insert_execution_contract_digest_global_row(
        mappers.execution_contract_digest_to_row(record),
    )


def load_execution_contract_digest_global(
    project_key: str,
    story_id: str,
    run_id: str,
) -> ExecutionContractDigestRecord | None:
    """Load the run's persisted ``execution_contract_digest`` row, or ``None``.

    Lock-free (FK-44 §44.3a: the digest fence predicate never takes a lock).
    """
    _require_control_plane_backend()
    backend = _backend_module()
    row = backend.load_execution_contract_digest_global_row(
        project_key,
        story_id,
        run_id,
    )
    if row is None:
        return None
    return mappers.execution_contract_digest_row_to_record(row)


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


def save_backend_instance_identity_global(
    record: BackendInstanceIdentityRecord,
) -> None:
    """Upsert the backend-instance-identity record (AG3-137). Fail-closed off-Postgres."""
    _require_control_plane_backend()
    backend = _backend_module()
    backend.save_backend_instance_identity_global_row(
        mappers.backend_instance_identity_to_row(record),
    )


def load_backend_instance_identity_global(
    backend_instance_id: str,
) -> BackendInstanceIdentityRecord | None:
    """Load the backend-instance-identity record, or ``None``."""
    _require_control_plane_backend()
    backend = _backend_module()
    row = backend.load_backend_instance_identity_global_row(backend_instance_id)
    if row is None:
        return None
    return mappers.backend_instance_identity_row_to_record(row)


def boot_backend_instance_identity_global(
    candidate_backend_instance_id: str,
    now: datetime,
) -> BackendInstanceIdentityRecord:
    """Atomically resolve the boot-time backend instance identity (AG3-138).

    First boot ever: persists ``candidate_backend_instance_id`` with
    ``instance_incarnation = 1``. Every later boot: keeps the EXISTING
    (stable) ``backend_instance_id`` and increments ``instance_incarnation`` by
    exactly 1 -- deterministic, no wall-clock input. Fail-closed off-Postgres.
    """
    _require_control_plane_backend()
    backend = _backend_module()
    row = backend.boot_backend_instance_identity_global_row(
        candidate_backend_instance_id=candidate_backend_instance_id,
        now=now.isoformat(),
    )
    return mappers.backend_instance_identity_row_to_record(row)


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
    "save_backend_instance_identity_global",
    "load_backend_instance_identity_global",
    "boot_backend_instance_identity_global",
    "save_story_execution_lock_global",
    "load_story_execution_lock_global",
]
