"""Repository surface for control-plane runtime lifecycle operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.backend.state_backend.store import (
    acquire_object_mutation_claim_global,
    admin_abort_control_plane_operation_global,
    append_execution_event_global,
    boot_backend_instance_identity_global,
    claim_control_plane_operation_global,
    commission_edge_command_record_global,
    commit_control_plane_operation_with_side_effects_global,
    commit_edge_command_result_global,
    delete_control_plane_operation_global,
    delete_object_mutation_claim_global,
    delete_session_run_binding_global,
    finalize_control_plane_operation_global,
    finalize_control_plane_start_phase_global,
    finalize_orphaned_control_plane_operation_global,
    has_committed_control_plane_operation_for_run_global,
    has_committed_story_exit_operation_for_run_global,
    has_engine_writes_since_control_plane_claim_global,
    has_open_repair_control_plane_operation_for_story_global,
    insert_edge_command_record_global,
    insert_object_mutation_claim_global,
    insert_run_ownership_record_global,
    list_and_ack_open_edge_command_records_global,
    list_orphaned_claimed_control_plane_operations_global,
    list_orphaned_object_mutation_claims_global,
    load_active_run_ownership_record_global,
    load_backend_instance_identity_global,
    load_control_plane_operation_global,
    load_edge_command_record_global,
    load_object_mutation_claim_global,
    load_run_ownership_record_global,
    load_session_run_binding_global,
    load_story_execution_lock_global,
    load_takeover_transfer_record_global,
    release_control_plane_operation_global,
    resolve_repair_control_plane_operation_global,
    save_backend_instance_identity_global,
    save_control_plane_operation_global,
    save_session_run_binding_global,
    save_story_execution_lock_global,
    save_takeover_transfer_record_global,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from agentkit.backend.control_plane.records import (
        BackendInstanceIdentityRecord,
        ControlPlaneOperationRecord,
        EdgeCommandRecord,
        ObjectMutationClaimRecord,
        RunOwnershipRecord,
        SessionRunBindingRecord,
        TakeoverTransferRecord,
    )
    from agentkit.backend.governance.guard_system.records import StoryExecutionLockRecord
    from agentkit.backend.story_context_manager.models import StoryContext
    from agentkit.backend.telemetry.contract.records import ExecutionEventRecord


def _load_story_context_via_story_surface(
    project_key: str,
    story_id: str,
) -> StoryContext | None:
    """Resolve a StoryContext through the sanctioned story read port (FK-07 §7.6).

    Architecture Conformance AC004 (``architecture-conformance.rule.
    story_read_surface``): the global story read loader
    (``load_story_context_global``) may only be imported from
    ``agentkit.backend.state_backend`` / ``agentkit.backend.story.repository``. The
    control plane therefore consumes the story read view via the productive
    :class:`StoryReadPort` adapter
    (``state_backend.store.story_read_repository.StateBackendStoryReadRepository``),
    never by importing the loader symbol directly.
    """
    from agentkit.backend.state_backend.store.story_read_repository import (
        StateBackendStoryReadRepository,
    )

    return StateBackendStoryReadRepository().load_story_context(project_key, story_id)


@dataclass(frozen=True)
class ControlPlaneRuntimeRepository:
    """Persistence dependencies for runtime mutations and sync."""

    load_operation: Callable[[str], ControlPlaneOperationRecord | None] = (
        load_control_plane_operation_global
    )
    save_operation: Callable[[ControlPlaneOperationRecord], None] = (
        save_control_plane_operation_global
    )
    #: AG3-054 owner-scoped claim: atomically claim an op_id BEFORE dispatch with a
    #: per-call owner token. Returns ``True`` iff this caller inserted the
    #: ``claimed`` row (won the claim). A loser inspects the row (terminal=>replay,
    #: a foreign claim of ANY age=>in-flight reject; AG3-139: never a CAS
    #: takeover). Backed by an ``INSERT ... ON CONFLICT DO NOTHING`` at the store.
    claim_operation: Callable[[ControlPlaneOperationRecord], bool] = (
        claim_control_plane_operation_global
    )
    #: AG3-054 owner-scoped claim: ownership-scoped terminal write. Writes the terminal
    #: result + clears ``claimed_by`` ONLY when the row is still ``claimed`` by the
    #: owner token. Returns ``True`` iff this owner's terminal write applied.
    finalize_operation: Callable[..., bool] = finalize_control_plane_operation_global
    #: AG3-054 (#1): ownership-scoped, atomic start_phase finalize. CAS-finalizes
    #: the claimed op AND materializes its side effects (binding/locks/events) in
    #: ONE transaction, gated on still owning the claim. A loser (a stale claim
    #: generation whose CAS no longer matches) writes NOTHING (the transaction
    #: rolls back). Returns ``True`` iff applied. AG3-142: accepts
    #: ``ownership_record_to_insert`` (a fresh setup atomically inserts the
    #: run's NEW active ``RunOwnershipRecord`` in this SAME transaction) and
    #: ``expected_ownership_epoch`` (every OTHER start/resume re-verifies the
    #: caller's observed ``(run_id, owner_session_id, ownership_epoch)``
    #: snapshot at commit time, no TOCTOU -- raises
    #: ``OwnershipFenceViolationError`` on a lost fence).
    finalize_start_phase: Callable[..., bool] = (
        finalize_control_plane_start_phase_global
    )
    #: AG3-054 (#2): ownership-collision-gated, atomic complete/fail/closure commit.
    #: The conditional op-row upsert (refuses to clobber a LIVE ``claimed`` start
    #: claim -> ``ControlPlaneClaimCollisionError``) and the mutation's side effects
    #: (binding create/delete, lock records, lifecycle events) commit in ONE
    #: transaction with the collision gate FIRST. A collision rolls back EVERYTHING,
    #: so a rejected complete/fail/closure leaves NO orphan side effect (ERROR-2).
    #: AG3-142: ``expected_ownership_epoch``, when given, re-verifies the
    #: caller's observed ownership snapshot at commit time in this SAME
    #: transaction (raises ``OwnershipFenceViolationError`` on a lost fence);
    #: ``None`` (the default) skips the fence -- preserved for ``story_split``'s
    #: reuse of this same primitive (FK-54 §54.8), which is fenced by its OWN
    #: entry-gate, not run-ownership.
    commit_operation_with_side_effects: Callable[..., None] = (
        commit_control_plane_operation_with_side_effects_global
    )
    #: AG3-054 owner-scoped claim: ownership-scoped release. Deletes the row ONLY when it
    #: is still ``claimed`` by the owner token (never a terminal / foreign row).
    release_operation: Callable[..., None] = release_control_plane_operation_global
    #: AG3-054 (#3): run-scoped admission evidence -- whether a COMMITTED op exists
    #: for THIS exact ``(project_key, story_id, run_id)``.
    has_committed_operation_for_run: Callable[[str, str, str], bool] = (
        has_committed_control_plane_operation_for_run_global
    )
    #: FK-58 run-terminal evidence: a committed ``story_exit`` operation marks the
    #: run terminal/non-resumable and must be consulted before admission evidence.
    has_committed_story_exit_operation_for_run: Callable[[str, str, str], bool] = (
        has_committed_story_exit_operation_for_run_global
    )
    #: AG3-054: unconditional delete for administrative recovery only (the
    #: productive release path is ``release_operation``). Idempotent.
    delete_operation: Callable[[str], None] = delete_control_plane_operation_global
    load_binding: Callable[[str], SessionRunBindingRecord | None] = (
        load_session_run_binding_global
    )
    save_binding: Callable[[SessionRunBindingRecord], None] = (
        save_session_run_binding_global
    )
    delete_binding: Callable[[str], None] = delete_session_run_binding_global
    load_lock: Callable[[str, str, str, str], StoryExecutionLockRecord | None] = (
        load_story_execution_lock_global
    )
    save_lock: Callable[[StoryExecutionLockRecord], None] = (
        save_story_execution_lock_global
    )
    append_event: Callable[[ExecutionEventRecord], None] = append_execution_event_global
    #: Authoritative server-side resolver for the run ``StoryContext`` keyed by
    #: ``(project_key, story_id)``. AG3-018 (FK-24 §24.3.4): the control plane
    #: reads the operating mode from the state-backend record, NEVER from an
    #: agent-supplied request field (which would be forgeable). Used by
    #: ``_mutate_phase`` to decide whether story-scoped session/locks are
    #: materialized for a fast story.
    load_story_context: Callable[[str, str], StoryContext | None] = (
        _load_story_context_via_story_surface
    )
    #: AG3-138 startup reconciliation: claimed operations orphaned by EARLIER
    #: incarnations of the CALLING instance's own identity (never a foreign
    #: identity; FK-91 §91.1a rule 16).
    list_orphaned_claimed_operations: Callable[
        [str, int], tuple[ControlPlaneOperationRecord, ...]
    ] = list_orphaned_claimed_control_plane_operations_global
    #: AG3-138 startup reconciliation: identity-fenced CAS finalize of one
    #: orphaned claim (``failed`` or ``repair``).
    finalize_orphaned_operation: Callable[..., bool] = (
        finalize_orphaned_control_plane_operation_global
    )
    #: AG3-138 ``admin_abort_inflight_operation`` (FK-91 §91.1a, FK-55 §55.5
    #: ``admin_transition``): CAS-abort ANY currently-``claimed`` operation.
    admin_abort_operation: Callable[..., bool] = admin_abort_control_plane_operation_global
    #: AG3-138 (AC10): CAS-resolve an open ``repair`` operation to ``resolved`` --
    #: the productive end-way out of the story-scoped repair mutation lock (op-class
    #: ``admin_transition``, FK-55 §55.5). Returns ``False`` (409) when the target is
    #: not currently in ``repair``.
    resolve_repair_operation: Callable[..., bool] = (
        resolve_repair_control_plane_operation_global
    )
    #: AG3-138 (IMPL-005): deterministic partial-write detection -- have
    #: ``phase_states``/``flow_executions`` already been written for this story at
    #: or after the claim's own ``claimed_at`` (never the current wall clock)? Bound
    #: to the concrete operation by its claim window, not a ``run_id`` column (the
    #: engine's ``flow_executions.run_id`` is engine-internal, distinct from the
    #: control-plane operation ``run_id``; ``phase_states`` has no ``run_id`` at all).
    has_engine_writes_since: Callable[[str, datetime], bool] = (
        has_engine_writes_since_control_plane_claim_global
    )
    #: AG3-138 (AC10): whether *story_id* carries an open reconcile/repair state
    #: -- backs the fail-closed dispatch-/operations-layer mutation lock.
    has_open_repair_for_story: Callable[[str, str], bool] = (
        has_open_repair_control_plane_operation_for_story_global
    )
    #: AG3-142 (SOLL-014/SOLL-015): the SOLE admission/fencing truth for every
    #: regime mutation path -- the story's single active ``RunOwnershipRecord``
    #: (``status='active'``), or ``None`` when none exists (fail-closed: no
    #: active record admits nothing). Replaces the removed
    #: ``has_committed_operation_for_run`` POSITIVE admission evidence; a
    #: historical record (``status != 'active'``) is never returned here and is
    #: therefore never admission evidence
    #: (``historical_ownership_records_are_never_admission_evidence``).
    load_active_ownership: Callable[[str, str], RunOwnershipRecord | None] = (
        load_active_run_ownership_record_global
    )


@dataclass(frozen=True)
class RunOwnershipRepository:
    """Persistence port for the canonical run-ownership record (AG3-137).

    The single writer is ``control_plane_runtime`` on behalf of the
    ``story-lifecycle`` BC (FK-17 §17.5). ``insert_ownership`` is a strict insert:
    the DB-enforced ``at_most_one_active_ownership_per_story`` partial-unique
    invariant (FK-56 §56.8a) rejects a second active record for the same story,
    and the facade rejects a ``transferred`` write (no writer in this strand).
    Postgres-only (K5): a non-Postgres backend fails closed with ``ConfigError``.
    """

    insert_ownership: Callable[[RunOwnershipRecord], None] = (
        insert_run_ownership_record_global
    )
    load_ownership: Callable[[str, str, str], RunOwnershipRecord | None] = (
        load_run_ownership_record_global
    )
    load_active_ownership: Callable[[str, str], RunOwnershipRecord | None] = (
        load_active_run_ownership_record_global
    )


@dataclass(frozen=True)
class ObjectMutationClaimRepository:
    """Persistence port for instance-bound object-mutation claims (AG3-137/AG3-141).

    The claim never expires by wall clock (no TTL) --
    ``object_mutation_claims_are_instance_bound_and_never_expire_by_wall_clock``.
    Postgres-only (K5). ``acquire_claim``/``release_claim`` are the AG3-141
    productive per-Story protocol (an atomic ``INSERT ... ON CONFLICT DO
    NOTHING`` on the object PK IS the serialization; ownership (op_id)-scoped
    release); ``object_claims.py`` is the thin A-core over this port. The
    project-scope / lock-set / cross-scope fairness apparatus was removed as
    speculative (PO decision). ``insert_claim``/``load_claim`` stay the raw
    schema-level primitives (AG3-137; also used to seed a permanently-held
    competing claim in tests).
    """

    insert_claim: Callable[[ObjectMutationClaimRecord], None] = (
        insert_object_mutation_claim_global
    )
    load_claim: Callable[[str, str, str], ObjectMutationClaimRecord | None] = (
        load_object_mutation_claim_global
    )
    #: AG3-141: atomic per-Story acquire -- an ``INSERT ... ON CONFLICT DO
    #: NOTHING`` on the object PK (see ``object_claims.py``). Returns ``True``
    #: iff THIS caller now holds the claim (won the PK insert), ``False`` when
    #: the Story object is already claimed (busy/409).
    acquire_claim: Callable[..., bool] = acquire_object_mutation_claim_global
    #: AG3-141: ownership-scoped (op_id-CAS) release; idempotent, returns
    #: ``True`` iff a row matching ALL of (identity, op_id) was deleted.
    release_claim: Callable[[str, str, str, str], bool] = (
        delete_object_mutation_claim_global
    )
    #: AG3-141 (startup-reconcile hookup, Scope item 7): object claims orphaned
    #: by EARLIER incarnations of the CALLING instance's own identity (never a
    #: foreign identity) -- a DIRECT scan of ``object_mutation_claims``,
    #: independent of the paired ``control_plane_operations`` row's own
    #: lifecycle (mirrors ``ControlPlaneRuntimeRepository.list_orphaned_claimed_operations``).
    list_orphaned: Callable[[str, int], tuple[ObjectMutationClaimRecord, ...]] = (
        list_orphaned_object_mutation_claims_global
    )


@dataclass(frozen=True)
class TakeoverTransferRepository:
    """Persistence port for per-repo takeover transfer records (AG3-137).

    Schema/record/repository foundation only; the productive challenge → confirm
    CAS writer is AG3-148. One row per participating repo. Postgres-only (K5).
    """

    save_transfer: Callable[[TakeoverTransferRecord], None] = (
        save_takeover_transfer_record_global
    )
    load_transfer: Callable[
        [str, str, str, int, str], TakeoverTransferRecord | None
    ] = load_takeover_transfer_record_global


@dataclass(frozen=True)
class BackendInstanceIdentityRepository:
    """Persistence port for the backend instance identity (AG3-137, IMPL-004).

    Persists ``backend_instance_id`` plus a monotone boot incarnation so AG3-138
    need only create/increment on boot. Postgres-only (K5).
    """

    save_identity: Callable[[BackendInstanceIdentityRecord], None] = (
        save_backend_instance_identity_global
    )
    load_identity: Callable[[str], BackendInstanceIdentityRecord | None] = (
        load_backend_instance_identity_global
    )
    #: AG3-138 (IMPL-003/IMPL-004): atomically resolve the boot-time identity.
    #: First boot ever persists ``candidate_backend_instance_id`` with
    #: incarnation 1; every later boot keeps the EXISTING stable id and
    #: increments the incarnation by exactly 1.
    boot_identity: Callable[[str, datetime], BackendInstanceIdentityRecord] = (
        boot_backend_instance_identity_global
    )


@dataclass(frozen=True)
class EdgeCommandRepository:
    """Persistence port for the Edge-Command-Queue (FK-91 §91.1b, AG3-145).

    Postgres-only (K5): every method fails closed with ``ConfigError`` off
    Postgres (``_require_control_plane_backend``, mirrors
    :class:`RunOwnershipRepository` / :class:`ObjectMutationClaimRepository`).
    ``insert_command`` is the strict commissioning write (setup provisioning,
    sub-step C); ``commission_command`` is the ATOMICALLY IDEMPOTENT commissioning
    write (``INSERT ... ON CONFLICT DO NOTHING``) used by the teardown path
    (sub-step D) so a concurrent double-detach is one visible command / no error
    (FK-10 §10.5.3); ``list_and_ack_open_commands`` is the GET Ack-read (Rule 13,
    no lock); ``load_command`` is a raw identity lookup (idempotency-replay / test
    support); ``commit_result`` is the atomic op-ledger + Rule-15-fenced
    command-result commit (sub-step A).
    """

    insert_command: Callable[[EdgeCommandRecord], None] = (
        insert_edge_command_record_global
    )
    commission_command: Callable[[EdgeCommandRecord], bool] = (
        commission_edge_command_record_global
    )
    load_command: Callable[[str], EdgeCommandRecord | None] = (
        load_edge_command_record_global
    )
    list_and_ack_open_commands: Callable[..., tuple[EdgeCommandRecord, ...]] = (
        list_and_ack_open_edge_command_records_global
    )
    commit_result: Callable[..., None] = commit_edge_command_result_global
