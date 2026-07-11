from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from agentkit.backend.control_plane.models import (
    AdminAbortRequest,
    ClosureCompleteRequest,
    ControlPlaneMutationResult,
    PhaseDispatchResult,
    PhaseMutationRequest,
    ProjectEdgeSyncRequest,
    TakeoverConfirmRequest,
    TakeoverRequest,
)
from agentkit.backend.control_plane.ownership import (
    INITIAL_OWNERSHIP_EPOCH,
    OwnershipAcquisition,
    OwnershipStatus,
    TakeoverApprovalStatus,
)
from agentkit.backend.control_plane.push_sync import (
    PushBarrierVerdict,
    PushBarrierVerdictStatus,
    PushFreshnessRecord,
    SyncPointBarrierType,
)
from agentkit.backend.control_plane.records import (
    BackendInstanceIdentityRecord,
    BindingDeleteScope,
    ControlPlaneOperationRecord,
    EdgeCommandRecord,
    RunOwnershipRecord,
    SessionRunBindingRecord,
    TakeoverApprovalRecord,
    TakeoverChallengeRecord,
    TakeoverChallengeRepoRecord,
    TakeoverConfirmTerminalRecords,
    TakeoverReissueRecords,
    TakeoverTransferRecord,
)
from agentkit.backend.control_plane.repository import ControlPlaneRuntimeRepository
from agentkit.backend.control_plane.runtime import (
    ControlPlaneRuntimeService,
    OperationNotAbortableError,
    OperationNotFoundError,
    TakeoverConfirmCommand,
    _build_claim_placeholder,
    _control_plane_request_body_hash,
    _next_binding_version,
)
from agentkit.backend.core_types import StoryMode
from agentkit.backend.exceptions import OwnershipFenceViolationError
from agentkit.backend.governance.guard_system.records import StoryExecutionLockRecord
from agentkit.backend.governance.principal_capabilities.principals import Principal
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.story_model import WireStoryMode
from agentkit.backend.story_context_manager.types import StoryType
from agentkit.backend.telemetry.events import EventType

if TYPE_CHECKING:
    from agentkit.backend.control_plane.ownership_transfer import OwnershipBasis
    from agentkit.backend.pipeline_engine.engine import PipelineEngine
    from agentkit.backend.prompt_runtime.execution_contract import (
        ExecutionContractDigestRecord,
    )
    from agentkit.backend.telemetry.contract.records import ExecutionEventRecord


class _RepoState:
    def __init__(self) -> None:
        self.operations: dict[str, ControlPlaneOperationRecord] = {}
        self.bindings: dict[str, SessionRunBindingRecord] = {}
        self.locks: dict[tuple[str, str, str, str], StoryExecutionLockRecord] = {}
        self.events: list[ExecutionEventRecord] = []
        #: Authoritative server-side StoryContext store keyed by
        #: ``(project_key, story_id)``. Empty => unresolvable (fail-closed).
        self.story_contexts: dict[tuple[str, str], StoryContext] = {}
        #: AG3-138: story_id -> earliest persisted engine-write timestamp
        #: (phase_states/flow_executions partial write). Empty => no partial writes
        #: (an abort/orphan finalize -> aborted/failed rather than repair). The
        #: partial-write detection is claim-window scoped (story + ``since``), never
        #: a ``run_id`` column (the engine's ``flow_executions.run_id`` is
        #: engine-internal, distinct from the control-plane operation ``run_id``).
        self.engine_writes: dict[str, datetime] = {}
        #: AG3-142: the SOLE admission/fencing truth, keyed by
        #: ``(project_key, story_id, run_id)`` -- mirrors
        #: ``run_ownership_records`` (identity PK; at most one ``status=active``
        #: per ``(project_key, story_id)`` enforced on insert, like the real
        #: partial-unique index).
        self.ownership_records: dict[tuple[str, str, str], RunOwnershipRecord] = {}
        #: AG3-143: the run-scoped execution_contract_digest rows, keyed by
        #: ``(project_key, story_id, run_id)`` -- mirrors
        #: ``execution_contract_digests`` (identity PK, read-only after insert).
        self.execution_contract_digests: dict[
            tuple[str, str, str], ExecutionContractDigestRecord
        ] = {}
        self.push_freshness: dict[
            tuple[str, str, str], tuple[PushFreshnessRecord, ...]
        ] = {}
        self.push_barrier_verdicts: dict[
            tuple[str, str, str], tuple[PushBarrierVerdict, ...]
        ] = {}
        self.takeover_transfers: list[TakeoverTransferRecord] = []
        self.takeover_challenges: dict[str, TakeoverChallengeRecord] = {}
        self.takeover_approvals: dict[str, TakeoverApprovalRecord] = {}
        self.active_freeze: object | None = None

    def load_active_ownership(
        self, project_key: str, story_id: str
    ) -> RunOwnershipRecord | None:
        for record in self.ownership_records.values():
            if (
                record.project_key == project_key
                and record.story_id == story_id
                and record.status is OwnershipStatus.ACTIVE
            ):
                return record
        return None

    def insert_ownership(self, record: RunOwnershipRecord) -> None:
        identity = (record.project_key, record.story_id, record.run_id)
        if identity in self.ownership_records:
            raise ValueError(f"duplicate run-ownership identity {identity!r}")
        if record.status is OwnershipStatus.ACTIVE and self.load_active_ownership(
            record.project_key, record.story_id
        ):
            raise ValueError(
                "a second active run-ownership record for "
                f"({record.project_key!r}, {record.story_id!r}) is not allowed "
                "(at_most_one_active_ownership_per_story)",
            )
        self.ownership_records[identity] = record


class _FakeOps:
    """In-memory control-plane operation/claim fakes (owner-scoped claim CAS protocol).

    Encapsulates the operation-lifecycle behaviors so ``_repository`` stays a thin
    wiring function (keeps cyclomatic complexity bounded; the owner-scoped claim CAS
    semantics live here next to the state they mutate).
    """

    def __init__(self, state: _RepoState) -> None:
        self._state = state

    def claim(self, record: ControlPlaneOperationRecord) -> bool:
        # Atomic insert-if-absent: win iff the op_id is not already stored.
        if record.op_id in self._state.operations:
            return False
        self._state.operations[record.op_id] = record
        return True

    def _still_owned(
        self,
        record: ControlPlaneOperationRecord,
        owner_token: str,
        owner_claimed_at: str | None = None,
        owner_operation_epoch: int | None = None,
    ) -> bool:
        # WARNING-4 (#4): the CAS scopes to BOTH owner token AND claim instant when
        # the epoch is given. The fake compares the observed value against the
        # stored record's TEXT-equivalent ``claimed_at`` (mirroring the store's
        # raw-column CAS). AG3-138: additionally fences on the unchanged
        # operation_epoch when given
        # (``operation_finalize_requires_cas_on_operation_epoch``): an admin-abort
        # bumps the stored epoch, so a stale-epoch finalize matches nothing.
        existing = self._state.operations.get(record.op_id)
        if (
            existing is None
            or existing.status != "claimed"
            or existing.claimed_by != owner_token
        ):
            return False
        if (
            owner_claimed_at is not None
            and _claimed_at_text(existing) != owner_claimed_at
        ):
            return False
        return not (
            owner_operation_epoch is not None
            and existing.operation_epoch != owner_operation_epoch
        )

    def finalize(
        self,
        record: ControlPlaneOperationRecord,
        *,
        owner_token: str,
        owner_claimed_at: str | None = None,
        owner_operation_epoch: int | None = None,
    ) -> bool:
        # Ownership-scoped terminal write: apply iff still claimed by owner_token
        # (and claim instant when given, #4; and operation_epoch when given, AG3-138).
        if not self._still_owned(
            record, owner_token, owner_claimed_at, owner_operation_epoch
        ):
            return False
        self._state.operations[record.op_id] = record
        return True

    def finalize_start_phase(
        self,
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
        # ERROR-1 (#1): ownership CAS finalize + side-effect materialization in ONE
        # atomic step. Apply ONLY if still claimed by owner_token (and claim instant
        # when given, #4; and operation_epoch when given, AG3-138); else write
        # NOTHING.
        if not self._still_owned(
            record, owner_token, owner_claimed_at, owner_operation_epoch
        ):
            return False
        # AG3-142 (no TOCTOU): mirrors ``_enforce_ownership_fence_row`` -- raises
        # BEFORE any state mutation so a lost fence writes nothing (the fake has
        # no real transaction, so ordering IS the atomicity guarantee here).
        if expected_ownership_epoch is not None:
            _fake_enforce_ownership_fence(
                self._state,
                project_key=record.project_key,
                story_id=record.story_id,
                run_id=record.run_id or "",
                session_id=record.session_id or "",
                expected_ownership_epoch=expected_ownership_epoch,
            )
        # AG3-054 run-scoping: the binding INSERT is run-scoped at the real store
        # (raises if the session is bound to a DIFFERENT run). Mirror it so the
        # fake catches a foreign-run overwrite and rolls back (raise BEFORE any
        # state mutation -> no orphan op/binding/lock/event).
        if binding is not None:
            _fake_run_scoped_save_binding(self._state, binding)
        if ownership_record_to_insert is not None:
            self._state.insert_ownership(ownership_record_to_insert)
        if execution_contract_digest_to_insert is not None:
            # AG3-143: mirrors the real ``execution_contract_digests`` primary
            # key (project_key, story_id, run_id) -- a duplicate identity is a
            # fail-closed bug (read-only after insert), never a silent
            # overwrite.
            identity = (
                execution_contract_digest_to_insert.project_key,
                execution_contract_digest_to_insert.story_id,
                execution_contract_digest_to_insert.run_id,
            )
            if identity in self._state.execution_contract_digests:
                raise ValueError(
                    f"duplicate execution_contract_digest identity {identity!r}"
                )
            self._state.execution_contract_digests[identity] = (
                execution_contract_digest_to_insert
            )
        self._state.operations[record.op_id] = record
        if binding is not None:
            self._state.bindings[binding.session_id] = binding
        for lock in locks:
            self._state.locks[
                (lock.project_key, lock.story_id, lock.run_id, lock.lock_type)
            ] = lock
        self._state.events.extend(events)
        return True

    def commit_with_side_effects(
        self,
        record: ControlPlaneOperationRecord,
        *,
        binding_to_save: SessionRunBindingRecord | None,
        binding_to_delete: BindingDeleteScope | None,
        locks: tuple[StoryExecutionLockRecord, ...],
        events: tuple[ExecutionEventRecord, ...],
        expected_ownership_epoch: int | None = None,
    ) -> None:
        # ERROR-2 (#2): the conditional op-row upsert (collision gate FIRST) and the
        # mutation's side effects apply ATOMICALLY. Mirrors the real store: a LIVE
        # ``claimed`` row makes the op-row upsert raise
        # ``ControlPlaneClaimCollisionError`` BEFORE any side effect is applied, so a
        # collision leaves NO orphan binding/lock/event and the live claim intact.
        from agentkit.backend.exceptions import ControlPlaneClaimCollisionError

        existing = self._state.operations.get(record.op_id)
        if existing is not None and existing.status == "claimed":
            raise ControlPlaneClaimCollisionError(
                f"op_id {record.op_id!r} is held by a live 'claimed' row "
                "(fake store, AG3-054 ERROR-2 atomic commit)",
            )
        # AG3-142 (no TOCTOU): mirrors the real store's fence-FIRST ordering.
        if expected_ownership_epoch is not None:
            _fake_enforce_ownership_fence(
                self._state,
                project_key=record.project_key,
                story_id=record.story_id,
                run_id=record.run_id or "",
                session_id=record.session_id or "",
                expected_ownership_epoch=expected_ownership_epoch,
            )
        # AG3-054 run-scoping: the binding SAVE/DELETE are run-scoped at the real
        # store. Validate BEFORE any mutation so a foreign-run binding raises and the
        # whole "transaction" rolls back (no orphan op/binding/lock/event), mirroring
        # the store's atomicity.
        if binding_to_save is not None:
            _fake_run_scoped_save_binding(self._state, binding_to_save)
        if binding_to_delete is not None:
            _fake_run_scoped_delete_binding(self._state, binding_to_delete)
        # Collision gate passed -> apply the terminal op AND all side effects.
        self._state.operations[record.op_id] = record
        if binding_to_save is not None:
            self._state.bindings[binding_to_save.session_id] = binding_to_save
        for lock in locks:
            self._state.locks[
                (lock.project_key, lock.story_id, lock.run_id, lock.lock_type)
            ] = lock
        self._state.events.extend(events)

    def commit_takeover_confirm(
        self,
        record: ControlPlaneOperationRecord,
        *,
        expected_basis: OwnershipBasis,
        revoked_binding: SessionRunBindingRecord,
        new_binding: SessionRunBindingRecord,
        locks: tuple[StoryExecutionLockRecord, ...],
        transfers: tuple[TakeoverTransferRecord, ...],
        events: tuple[ExecutionEventRecord, ...],
        terminal_records: TakeoverConfirmTerminalRecords,
        commands: tuple[EdgeCommandRecord, ...] = (),
    ) -> None:
        del commands
        active = self._state.load_active_ownership(record.project_key, record.story_id)
        owner_binding = self._state.bindings.get(expected_basis.owner_session_id)
        if (
            active is None
            or active.run_id != record.run_id
            or active.owner_session_id != expected_basis.owner_session_id
            or active.ownership_epoch != expected_basis.ownership_epoch
            or owner_binding is None
            or owner_binding.binding_version != expected_basis.binding_version
        ):
            raise OwnershipFenceViolationError(
                "takeover confirm CAS failed in fake store",
                detail={
                    "current_owner_session_id": (
                        active.owner_session_id if active is not None else None
                    ),
                    "current_ownership_epoch": (
                        active.ownership_epoch if active is not None else None
                    ),
                },
            )
        _fake_run_scoped_save_binding(self._state, new_binding)
        ownership_key = (active.project_key, active.story_id, active.run_id)
        self._state.ownership_records[ownership_key] = RunOwnershipRecord(
            project_key=active.project_key,
            story_id=active.story_id,
            run_id=active.run_id,
            owner_session_id=new_binding.session_id,
            ownership_epoch=expected_basis.ownership_epoch + 1,
            status=OwnershipStatus.ACTIVE,
            acquired_via=OwnershipAcquisition.TAKEOVER,
            acquired_at=record.updated_at,
            audit_ref=record.op_id,
        )
        self._state.operations[record.op_id] = record
        self._state.operations[terminal_records.request_op_record.op_id] = (
            terminal_records.request_op_record
        )
        self._state.takeover_challenges[terminal_records.challenge.challenge_id] = (
            terminal_records.challenge
        )
        if terminal_records.approved_approval is not None:
            self._state.takeover_approvals[
                terminal_records.approved_approval.approval_id
            ] = terminal_records.approved_approval
        self._state.bindings[revoked_binding.session_id] = revoked_binding
        self._state.bindings[new_binding.session_id] = new_binding
        for lock in locks:
            self._state.locks[
                (lock.project_key, lock.story_id, lock.run_id, lock.lock_type)
            ] = lock
        self._state.takeover_transfers.extend(transfers)
        self._state.events.extend(events)

    def commit_takeover_reissue(
        self,
        record: ControlPlaneOperationRecord,
        *,
        expected_basis: OwnershipBasis,
        records: TakeoverReissueRecords,
        events: tuple[ExecutionEventRecord, ...],
    ) -> None:
        del expected_basis
        self._state.operations[record.op_id] = record
        self._state.takeover_challenges[
            records.expired_challenge.challenge_id
        ] = records.expired_challenge
        self._state.takeover_challenges[
            records.fresh_challenge.challenge_id
        ] = records.fresh_challenge
        self._state.takeover_approvals[
            records.relinked_approval.approval_id
        ] = records.relinked_approval
        self._state.events.extend(events)

    def reconcile_takeover_confirm_cas_loss(
        self,
        record: ControlPlaneOperationRecord,
        *,
        expected_basis: OwnershipBasis,
        request_op_record: ControlPlaneOperationRecord,
        challenge: TakeoverChallengeRecord,
        invalidated_approval: TakeoverApprovalRecord | None,
        events: tuple[ExecutionEventRecord, ...],
    ) -> str:
        active = self._state.load_active_ownership(record.project_key, record.story_id)
        binding = self._state.bindings.get(expected_basis.owner_session_id)
        current = self._state.takeover_challenges.get(challenge.challenge_id)
        if current is None or current.status != "pending":
            return "terminal_invalidated" if current and current.status == "invalidated" else "challenge_not_pending"
        if (
            active is not None
            and active.owner_session_id == expected_basis.owner_session_id
            and active.ownership_epoch == expected_basis.ownership_epoch
            and binding is not None
            and binding.binding_version == expected_basis.binding_version
        ):
            return "takeover_confirm_cas_lost"
        self.commit_takeover_invalidation(
            record,
            request_op_record=request_op_record,
            challenge=challenge,
            invalidated_approval=invalidated_approval,
            events=events,
        )
        return "invalidated"

    def commit_takeover_expiry(
        self,
        record: ControlPlaneOperationRecord,
        *,
        request_op_record: ControlPlaneOperationRecord,
        challenge: TakeoverChallengeRecord,
        expired_approval: object | None,
        events: tuple[ExecutionEventRecord, ...],
    ) -> None:
        del expired_approval
        self._state.operations[record.op_id] = record
        self._state.operations[request_op_record.op_id] = request_op_record
        self._state.takeover_challenges[challenge.challenge_id] = challenge
        self._state.events.extend(events)

    def commit_takeover_invalidation(
        self,
        record: ControlPlaneOperationRecord,
        *,
        request_op_record: ControlPlaneOperationRecord,
        challenge: TakeoverChallengeRecord,
        invalidated_approval: TakeoverApprovalRecord | None,
        events: tuple[ExecutionEventRecord, ...],
    ) -> None:
        self._state.operations[record.op_id] = record
        self._state.operations[request_op_record.op_id] = request_op_record
        self._state.takeover_challenges[challenge.challenge_id] = challenge
        if invalidated_approval is not None:
            self._state.takeover_approvals[invalidated_approval.approval_id] = (
                invalidated_approval
            )
        self._state.events.extend(events)

    def release(
        self,
        op_id: str,
        *,
        owner_token: str,
        owner_claimed_at: str | None = None,
    ) -> None:
        # Ownership-scoped release: delete iff still claimed by owner_token (and
        # claim instant when given, #4).
        existing = self._state.operations.get(op_id)
        if existing is None or existing.status != "claimed":
            return
        if existing.claimed_by != owner_token:
            return
        if (
            owner_claimed_at is not None
            and _claimed_at_text(existing) != owner_claimed_at
        ):
            return
        self._state.operations.pop(op_id, None)

    def has_committed_for_run(
        self,
        project_key: str,
        story_id: str,
        run_id: str,
    ) -> bool:
        # ERROR-3 (#3): admission evidence must prove an admitted START -- a
        # committed setup ``phase_start`` for THIS exact run. A committed
        # ``phase_complete`` / ``closure_complete`` (or a non-setup start) does
        # NOT admit (mirrors the real store's narrowed SQL).
        return any(
            op.status == "committed"
            and op.operation_kind == "phase_start"
            and op.phase == "setup"
            and op.project_key == project_key
            and op.story_id == story_id
            and op.run_id == run_id
            for op in self._state.operations.values()
        )

    def has_committed_story_exit_for_run(
        self,
        project_key: str,
        story_id: str,
        run_id: str,
    ) -> bool:
        return any(
            op.status == "committed"
            and op.operation_kind == "story_exit"
            and op.project_key == project_key
            and op.story_id == story_id
            and op.run_id == run_id
            for op in self._state.operations.values()
        )

    def has_committed_ownership_invalidating_operation_for_run(
        self,
        project_key: str,
        story_id: str,
        run_id: str,
    ) -> bool:
        return any(
            op.status == "committed"
            and op.operation_kind
            in {"story_exit", "story_reset", "story_split", "closure_complete"}
            and op.project_key == project_key
            and op.story_id == story_id
            and op.run_id == run_id
            for op in self._state.operations.values()
        )

    def save(self, record: ControlPlaneOperationRecord) -> None:
        # ERROR-3 (#3): the legacy upsert REFUSES to overwrite a row that is still
        # LIVE ``claimed`` (a live, owned claim). Mirrors the real store's
        # conditional upsert: a complete/fail reusing a live start's op_id is
        # rejected fail-closed via ``ControlPlaneClaimCollisionError``; a fresh
        # insert and an update of a terminal row are unaffected.
        from agentkit.backend.exceptions import ControlPlaneClaimCollisionError

        existing = self._state.operations.get(record.op_id)
        if existing is not None and existing.status == "claimed":
            raise ControlPlaneClaimCollisionError(
                f"op_id {record.op_id!r} is held by a live 'claimed' row "
                "(fake store, AG3-054 ERROR-3)",
            )
        self._state.operations[record.op_id] = record

    def delete(self, op_id: str) -> None:
        self._state.operations.pop(op_id, None)

    # --- AG3-138 startup-reconcile / admin-abort / repair-lock ports -----------

    def list_orphaned(
        self, backend_instance_id: str, before_incarnation: int
    ) -> tuple[ControlPlaneOperationRecord, ...]:
        # In-memory mirror of the store's identity-fenced orphan scan: only
        # claimed ops of the CALLING instance's own EARLIER incarnations.
        return tuple(
            sorted(
                (
                    op
                    for op in self._state.operations.values()
                    if op.status == "claimed"
                    and op.backend_instance_id == backend_instance_id
                    and op.instance_incarnation is not None
                    and op.instance_incarnation < before_incarnation
                ),
                key=lambda op: op.op_id,
            )
        )

    def finalize_orphaned(
        self,
        *,
        op_id: str,
        backend_instance_id: str,
        status: str,
        response_payload: dict[str, object],
        now: datetime,
        owner_operation_epoch: int,
    ) -> bool:
        # Identity-fenced CAS: apply only when still claimed by the OWN identity AND
        # the observed operation_epoch is unchanged (AG3-138 AC4, mandatory epoch
        # fence -- a NULL-epoch row or a bumped epoch matches nothing, fail-closed).
        from dataclasses import replace

        existing = self._state.operations.get(op_id)
        if (
            existing is None
            or existing.status != "claimed"
            or existing.backend_instance_id != backend_instance_id
            or existing.operation_epoch != owner_operation_epoch
        ):
            return False
        self._state.operations[op_id] = replace(
            existing,
            status=status,
            response_payload=response_payload,
            updated_at=now,
            finalized_at=now,
            operation_epoch=(existing.operation_epoch or 0) + 1,
            claimed_by=None,
            claimed_at=None,
        )
        return True

    def admin_abort(
        self,
        *,
        op_id: str,
        status: str,
        response_payload: dict[str, object],
        now: datetime,
    ) -> bool:
        # CAS-abort ANY currently-claimed op (bumps the epoch fence).
        from dataclasses import replace

        existing = self._state.operations.get(op_id)
        if existing is None or existing.status != "claimed":
            return False
        self._state.operations[op_id] = replace(
            existing,
            status=status,
            response_payload=response_payload,
            updated_at=now,
            finalized_at=now,
            operation_epoch=(existing.operation_epoch or 0) + 1,
            claimed_by=None,
            claimed_at=None,
        )
        return True

    def resolve_repair(
        self,
        *,
        op_id: str,
        response_payload: dict[str, object],
        now: datetime,
    ) -> bool:
        # CAS-resolve an OPEN repair row to 'resolved' (AC10 lock exit); a row not
        # currently in 'repair' matches nothing (409).
        from dataclasses import replace

        existing = self._state.operations.get(op_id)
        if existing is None or existing.status != "repair":
            return False
        self._state.operations[op_id] = replace(
            existing,
            status="resolved",
            response_payload=response_payload,
            updated_at=now,
            finalized_at=now,
        )
        return True

    def has_engine_writes_since(self, story_id: str, since: datetime) -> bool:
        # Deterministic partial-write signal driven by a test-settable map on state
        # (default empty => no partial writes). Claim-window scoped: a recorded
        # engine write for the story at/after ``since`` (the claim's claimed_at).
        write_at = self._state.engine_writes.get(story_id)
        return write_at is not None and write_at >= since

    def has_open_repair_for_story(self, project_key: str, story_id: str) -> bool:
        return any(
            op.status == "repair"
            and op.project_key == project_key
            and op.story_id == story_id
            for op in self._state.operations.values()
        )

    def has_unreconciled_takeover_for_story(
        self, project_key: str, story_id: str
    ) -> bool:
        active = self._state.load_active_ownership(project_key, story_id)
        return active is not None and any(
            transfer.project_key == project_key
            and transfer.story_id == story_id
            and transfer.run_id == active.run_id
            and transfer.ownership_epoch == active.ownership_epoch
            and transfer.reconciled_at is None
            for transfer in self._state.takeover_transfers
        )


def _fake_run_scoped_save_binding(
    state: _RepoState,
    binding: SessionRunBindingRecord,
) -> None:
    """Mirror the store's RUN-scoped binding upsert in the fake (AG3-054 sweep).

    The real ``_insert_session_binding_row`` upserts only when the session is
    unbound or already bound to the SAME ``(project_key, story_id, run_id)``; a live
    binding for a DIFFERENT run raises ``ControlPlaneBindingCollisionError``. The
    fake validates the same invariant BEFORE mutating, so a foreign-run overwrite is
    caught and rolls back the whole "transaction".
    """
    from agentkit.backend.exceptions import ControlPlaneBindingCollisionError

    existing = state.bindings.get(binding.session_id)
    if existing is None:
        return
    if (
        existing.project_key == binding.project_key
        and existing.story_id == binding.story_id
        and existing.run_id == binding.run_id
    ):
        return
    raise ControlPlaneBindingCollisionError(
        f"session {binding.session_id!r} is bound to run {existing.run_id!r}, not "
        f"{binding.run_id!r} (fake store, AG3-054 run-scoping)",
    )


def _fake_run_scoped_delete_binding(
    state: _RepoState,
    scope: BindingDeleteScope,
) -> None:
    """Mirror the store's RUN-scoped binding delete in the fake (AG3-054 sweep).

    Deletes only when the binding matches the closing run; a missing binding is a
    benign no-op; a foreign-run binding raises ``ControlPlaneBindingCollisionError``
    (never tearing down a foreign run's regime).
    """
    from agentkit.backend.exceptions import ControlPlaneBindingCollisionError

    existing = state.bindings.get(scope.session_id)
    if existing is None:
        return
    if (
        existing.project_key == scope.project_key
        and existing.story_id == scope.story_id
        and existing.run_id == scope.run_id
    ):
        state.bindings.pop(scope.session_id, None)
        return
    raise ControlPlaneBindingCollisionError(
        f"session {scope.session_id!r} is bound to run {existing.run_id!r}, not the "
        f"closing run {scope.run_id!r} (fake store, AG3-054 run-scoping)",
    )


def _fake_enforce_ownership_fence(
    state: _RepoState,
    *,
    project_key: str,
    story_id: str,
    run_id: str,
    session_id: str,
    expected_ownership_epoch: int,
) -> None:
    """Mirror ``_enforce_ownership_fence_row`` in the fake (AG3-142, no TOCTOU).

    Raises :class:`OwnershipFenceViolationError` with the SAME ``detail`` shape
    as the real Postgres row function when the story's active ownership record
    no longer matches this exact ``(run_id, session_id, ownership_epoch)``
    snapshot -- ``None`` values in ``detail`` mean no active record exists at
    all for the story (never a genuine transfer).
    """
    active = state.load_active_ownership(project_key, story_id)
    if (
        active is not None
        and active.run_id == run_id
        and active.owner_session_id == session_id
        and active.ownership_epoch == expected_ownership_epoch
    ):
        return
    raise OwnershipFenceViolationError(
        f"ownership fence violated for run {run_id!r} "
        f"(project={project_key!r}, story={story_id!r}, session={session_id!r}, "
        f"expected_ownership_epoch={expected_ownership_epoch!r}) (fake store)",
        detail={
            "current_owner_session_id": (
                active.owner_session_id if active is not None else None
            ),
            "current_ownership_epoch": (
                active.ownership_epoch if active is not None else None
            ),
            "transferred_at": (
                active.acquired_at.isoformat() if active is not None else None
            ),
        },
    )


def _claimed_at_text(record: ControlPlaneOperationRecord) -> str | None:
    """Mirror the store's ``claimed_at`` TEXT column for the ownership CAS (#4).

    The real store persists ``claimed_at`` as ISO-8601 TEXT and the
    ownership-scoped finalize/release CAS (WARNING-4) matches ``owner_claimed_at``
    against that TEXT column. The fake holds records in memory as ``datetime``
    objects, so this reconstructs the TEXT value the store would compare against.
    """
    return record.claimed_at.isoformat() if record.claimed_at is not None else None


def _repository(state: _RepoState) -> ControlPlaneRuntimeRepository:
    def _delete_binding(session_id: str) -> None:
        state.bindings.pop(session_id, None)

    ops = _FakeOps(state)

    return ControlPlaneRuntimeRepository(
        load_active_freezes=lambda story_id: (
            (state.active_freeze,) if state.active_freeze is not None else ()
        ),
        load_operation=state.operations.get,
        save_operation=ops.save,
        claim_operation=ops.claim,
        finalize_operation=ops.finalize,
        finalize_start_phase=ops.finalize_start_phase,
        commit_operation_with_side_effects=ops.commit_with_side_effects,
        release_operation=ops.release,
        has_committed_operation_for_run=ops.has_committed_for_run,
        has_committed_story_exit_operation_for_run=ops.has_committed_story_exit_for_run,
        has_committed_ownership_invalidating_operation_for_run=(
            ops.has_committed_ownership_invalidating_operation_for_run
        ),
        delete_operation=ops.delete,
        load_binding=state.bindings.get,
        save_binding=lambda record: state.bindings.__setitem__(
            record.session_id,
            record,
        ),
        delete_binding=_delete_binding,
        load_lock=lambda project_key, story_id, run_id, lock_type: state.locks.get(
            (project_key, story_id, run_id, lock_type),
        ),
        save_lock=lambda record: state.locks.__setitem__(
            (
                record.project_key,
                record.story_id,
                record.run_id,
                record.lock_type,
            ),
            record,
        ),
        append_event=state.events.append,
        load_story_context=lambda project_key, story_id: state.story_contexts.get(
            (project_key, story_id),
        ),
        list_orphaned_claimed_operations=ops.list_orphaned,
        finalize_orphaned_operation=ops.finalize_orphaned,
        admin_abort_operation=ops.admin_abort,
        resolve_repair_operation=ops.resolve_repair,
        has_engine_writes_since=ops.has_engine_writes_since,
        has_open_repair_for_story=ops.has_open_repair_for_story,
        has_unreconciled_takeover_for_story=ops.has_unreconciled_takeover_for_story,
        load_active_ownership=state.load_active_ownership,
        list_push_freshness=lambda project_key, story_id, run_id: state.push_freshness.get(
            (project_key, story_id, run_id),
            (),
        ),
        list_verified_push_barrier_verdicts_for_run=lambda project_key, story_id, run_id: state.push_barrier_verdicts.get(
            (project_key, story_id, run_id),
            (),
        ),
        commit_takeover_confirm=ops.commit_takeover_confirm,
        commit_takeover_reissue=ops.commit_takeover_reissue,
        reconcile_takeover_confirm_cas_loss=ops.reconcile_takeover_confirm_cas_loss,
        commit_takeover_expiry=ops.commit_takeover_expiry,
        commit_takeover_invalidation=ops.commit_takeover_invalidation,
        load_takeover_challenge=state.takeover_challenges.get,
        insert_takeover_challenge=lambda record: state.takeover_challenges.__setitem__(
            record.challenge_id,
            record,
        ),
        insert_takeover_approval=lambda record: state.takeover_approvals.__setitem__(
            record.approval_id,
            record,
        ),
        load_takeover_approval=state.takeover_approvals.get,
        load_takeover_approval_for_challenge=lambda challenge_id: next(
            (
                approval
                for approval in state.takeover_approvals.values()
                if approval.challenge_ref == challenge_id
            ),
            None,
        ),
        list_pending_takeover_approvals=lambda project_key=None: tuple(
            approval
            for approval in state.takeover_approvals.values()
            if approval.status.value == "pending"
            and (project_key is None or approval.project_key == project_key)
        ),
        list_takeover_history=lambda project_key, story_id: tuple(
            transfer
            for transfer in state.takeover_transfers
            if transfer.project_key == project_key and transfer.story_id == story_id
        ),
        list_open_operation_ids_for_story=lambda project_key, story_id: tuple(
            op.op_id
            for op in state.operations.values()
            if op.project_key == project_key
            and op.story_id == story_id
            and op.status in {"claimed", "pending_human_approval", "offered", "repair"}
        ),
    )


def _story_context(
    *,
    project_key: str,
    story_id: str,
    mode: WireStoryMode,
    story_type: StoryType = StoryType.IMPLEMENTATION,
    project_root: Path | None = None,
    participating_repos: list[str] | None = None,
) -> StoryContext:
    return StoryContext(
        project_key=project_key,
        story_id=story_id,
        story_type=story_type,
        execution_route=StoryMode.EXECUTION,
        mode=mode,
        project_root=project_root,
        participating_repos=participating_repos or [],
    )


def _admitting_service(state: _RepoState) -> ControlPlaneRuntimeService:
    """A runtime service whose fresh-setup-start is admitted by a stub dispatcher.

    A fresh setup start now requires a resolvable, Approved+READY-admitted run
    (FK-20 §20.8.2); the stub dispatcher returns an ``admitted`` dispatch so the
    binding/lock/operation persistence path is exercised without the real engine.
    """
    return ControlPlaneRuntimeService(
        repository=_repository(state),
        phase_dispatcher=_StubDispatcher(_admitted_dispatch()),  # type: ignore[arg-type]
    )


def _resolvable_standard_ctx(state: _RepoState) -> None:
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
        project_root=Path("T:/projects/tenant-a"),
    )


def _seed_admitted_run(
    state: _RepoState,
    *,
    run_id: str,
    session_id: str = "sess-001",
    project_key: str = "tenant-a",
    story_id: str = "AG3-100",
    ownership_epoch: int = INITIAL_OWNERSHIP_EPOCH,
    owner_session_id: str | None = None,
    seed_binding: bool = True,
) -> RunOwnershipRecord:
    """Seed run-ownership admission evidence (AG3-142): the active record.

    AG3-142 (SOLL-014): admission is EXCLUSIVELY the active
    ``run_ownership_records`` row -- a committed op or a session binding is
    NEVER sufficient by itself any more. ``owner_session_id`` defaults to
    ``session_id`` (the common "this session owns its own run" case);
    passing a DIFFERENT ``owner_session_id`` seeds the SOLL-019 contradiction
    scenario (binding still points at ``session_id``, but the record's owner
    is someone else) when ``seed_binding=True`` also materializes a binding
    for ``session_id`` (the binding is a subordinate projection now, never a
    second admission path -- the #9 contradiction test relies on this).

    Returns the seeded :class:`RunOwnershipRecord` so callers can read back
    its ``ownership_epoch`` for a commit-time fence assertion.
    """
    record = RunOwnershipRecord(
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
        owner_session_id=owner_session_id or session_id,
        ownership_epoch=ownership_epoch,
        status=OwnershipStatus.ACTIVE,
        acquired_via=OwnershipAcquisition.SETUP,
        acquired_at=datetime(2026, 4, 22, 10, 0, tzinfo=UTC),
        audit_ref=f"op-seed-{run_id}",
    )
    state.insert_ownership(record)
    if seed_binding:
        state.bindings[session_id] = SessionRunBindingRecord(
            session_id=session_id,
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            principal_type="orchestrator",
            worktree_roots=("T:/worktrees/ag3-100",),
            binding_version="1",
            updated_at=datetime(2026, 4, 22, 10, 0, tzinfo=UTC),
        )
    return record


def _push_freshness(
    *,
    repo_id: str = "backend",
    pushed_sha: str | None = "abc123",
    backlog: bool = False,
) -> PushFreshnessRecord:
    return PushFreshnessRecord(
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        repo_id=repo_id,
        last_reported_head_sha=pushed_sha,
        last_pushed_head_sha=pushed_sha,
        last_reported_at=datetime(2026, 4, 22, 10, 5, tzinfo=UTC),
        last_sync_point_id="sync-1",
        last_command_id="cmd-1",
        backlog=backlog,
        backlog_detail="behind_remote" if backlog else None,
    )


def _push_barrier_verdict(
    *,
    repo_id: str = "backend",
    expected_head_sha: str | None = "abc123",
    status: PushBarrierVerdictStatus = PushBarrierVerdictStatus.PASSED,
) -> PushBarrierVerdict:
    return PushBarrierVerdict(
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        boundary_type=SyncPointBarrierType.PHASE_COMPLETION,
        boundary_id="boundary-1",
        repo_id=repo_id,
        producer="control_plane.push_barrier",
        boundary_epoch=1,
        expected_head_sha=expected_head_sha,
        server_head_sha=expected_head_sha,
        ownership_epoch=1,
        status=status,
        created_at=datetime(2026, 4, 22, 10, 4, tzinfo=UTC),
        updated_at=datetime(2026, 4, 22, 10, 4, tzinfo=UTC),
        resolved_at=datetime(2026, 4, 22, 10, 4, tzinfo=UTC),
    )


def _takeover_confirm_request(
    *,
    op_id: str = "op-takeover-confirm",
    principal_type: str = "human_cli",
    session_id: str = "sess-B",
) -> TakeoverConfirmCommand:
    return TakeoverConfirmCommand(
        request=TakeoverConfirmRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            op_id=op_id,
            challenge_id="challenge-op-request",
            reason="previous owner is unavailable",
        ),
        confirmed_by_session_id=session_id,
        confirmed_by_principal=Principal(principal_type),
    )


def _seed_takeover_challenge(
    state: _RepoState,
    *,
    expires_at: datetime = datetime(2099, 4, 22, 10, 20, tzinfo=UTC),
    requesting_session_id: str = "sess-requester",
    requesting_principal_type: str = "human_cli",
    requesting_worktree_roots: tuple[str, ...] = ("T:/worktrees/ag3-100-requester",),
) -> None:
    issued_at = min(
        datetime(2026, 4, 22, 10, 0, tzinfo=UTC),
        expires_at - timedelta(minutes=15),
    )
    state.operations["op-request"] = ControlPlaneOperationRecord(
        op_id="op-request",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        session_id=requesting_session_id,
        operation_kind="ownership_takeover_request",
        phase="ownership",
        status="offered",
        response_payload={"status": "offered", "op_id": "op-request"},
        created_at=datetime(2026, 4, 22, 10, 0, tzinfo=UTC),
        updated_at=datetime(2026, 4, 22, 10, 0, tzinfo=UTC),
    )
    state.takeover_challenges["challenge-op-request"] = TakeoverChallengeRecord(
        challenge_id="challenge-op-request",
        request_op_id="op-request",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        requesting_session_id=requesting_session_id,
        requesting_principal_type=requesting_principal_type,
        requesting_worktree_roots=requesting_worktree_roots,
        reason="previous owner is unavailable",
        owner_session_id="sess-001",
        ownership_epoch=1,
        binding_version="1",
        phase_status="ACTIVE",
        issued_at=issued_at,
        expires_at=expires_at,
        repos=(
            TakeoverChallengeRepoRecord(
                repo_id="backend",
                takeover_base_sha="abc123",
                last_push_at=datetime(2026, 4, 22, 10, 5, tzinfo=UTC),
                push_lag_hint=None,
                base_quality="pushed",
            ),
        ),
        open_operation_ids=(),
        takeover_history_refs=(),
    )


def test_takeover_request_returns_challenge_with_pushed_only_evidence() -> None:
    state = _RepoState()
    _seed_admitted_run(state, run_id="run-100", session_id="sess-001")
    state.push_freshness[("tenant-a", "AG3-100", "run-100")] = (
        _push_freshness(repo_id="backend", pushed_sha="abc123"),
    )
    service = ControlPlaneRuntimeService(
        repository=_repository(state),
        now_fn=lambda: datetime(2026, 4, 22, 10, 5, tzinfo=UTC),
    )

    result = service.request_ownership_takeover(
        request=TakeoverRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-B",
            principal_type="human_cli",
            op_id="op-takeover-request",
            reason="previous owner is unavailable",
            worktree_roots=["T:/worktrees/ag3-100-b"],
        ),
    )

    assert result.status == "offered"
    assert result.takeover_challenge is not None
    challenge = result.takeover_challenge
    assert challenge.current_owner_session_id == "sess-001"
    assert challenge.ownership_epoch == 1
    assert challenge.binding_version == "1"
    assert challenge.loss_corridor_notice_key == "pushed_only_loss_corridor"
    assert "Unpushed commits" in challenge.loss_corridor_notice_text
    assert challenge.repos[0].takeover_base_sha == "abc123"
    assert challenge.repos[0].base_quality == "pushed"


def test_agent_takeover_request_persists_pending_approval_through_runtime_port() -> None:
    state = _RepoState()
    _seed_admitted_run(state, run_id="run-100", session_id="sess-001")
    state.push_freshness[("tenant-a", "AG3-100", "run-100")] = (
        _push_freshness(repo_id="backend", pushed_sha="abc123"),
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.request_ownership_takeover(
        request=TakeoverRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-agent",
            principal_type="interactive_agent",
            op_id="op-agent-takeover-request",
            reason="owner unavailable",
            worktree_roots=["T:/worktrees/ag3-100-agent"],
        ),
    )

    assert result.status == "pending_human_approval"
    assert result.pending_human_approval is not None
    approval = state.takeover_approvals[result.pending_human_approval.approval_id]
    assert approval.status is TakeoverApprovalStatus.PENDING
    assert approval.requested_by_session_id == "sess-agent"
    assert approval.requested_by_principal_type == "interactive_agent"


def test_takeover_request_rejects_unknown_principal_fail_closed() -> None:
    state = _RepoState()
    _seed_admitted_run(state, run_id="run-100", session_id="sess-001")
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.request_ownership_takeover(
        request=TakeoverRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-unknown",
            principal_type="agent",
            op_id="op-invalid-principal-request",
            reason="owner unavailable",
            worktree_roots=["T:/worktrees/ag3-100-agent"],
        ),
    )

    assert result.status == "rejected"
    assert result.error_code == "invalid_takeover_principal"
    assert state.takeover_approvals == {}


def test_takeover_confirm_commits_cas_transfer_and_mandated_events() -> None:
    state = _RepoState()
    _seed_admitted_run(state, run_id="run-100", session_id="sess-001")
    state.push_freshness[("tenant-a", "AG3-100", "run-100")] = (
        _push_freshness(repo_id="backend", pushed_sha="abc123"),
    )
    state.push_barrier_verdicts[("tenant-a", "AG3-100", "run-100")] = (
        _push_barrier_verdict(repo_id="backend", expected_head_sha="abc123"),
    )
    _seed_takeover_challenge(state)
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.confirm_ownership_takeover(command=_takeover_confirm_request())

    assert result.status == "committed", result.model_dump(mode="json")
    active = state.load_active_ownership("tenant-a", "AG3-100")
    assert active is not None
    assert active.owner_session_id == "sess-requester"
    assert active.ownership_epoch == 2
    assert active.status is OwnershipStatus.ACTIVE
    assert state.bindings["sess-001"].status == "revoked"
    assert state.bindings["sess-001"].revocation_reason == "ownership_transferred"
    assert state.bindings["sess-requester"].principal_type == "human_cli"
    assert state.bindings["sess-requester"].worktree_roots == (
        "T:/worktrees/ag3-100-requester",
    )
    assert state.locks[("tenant-a", "AG3-100", "run-100", "story_execution")].worktree_roots == (
        "T:/worktrees/ag3-100-requester",
    )
    assert len(state.takeover_transfers) == 1
    assert state.takeover_transfers[0].takeover_base_sha == "abc123"
    assert state.takeover_transfers[0].reconciled_at is None
    assert [event.event_type for event in state.events] == [
        "session_run_binding_transferred",
        "session_disowned",
    ]


def test_takeover_confirm_requires_pushed_head_and_writes_nothing() -> None:
    state = _RepoState()
    _seed_admitted_run(state, run_id="run-100", session_id="sess-001")
    state.push_freshness[("tenant-a", "AG3-100", "run-100")] = (
        _push_freshness(repo_id="backend", pushed_sha=None),
    )
    _seed_takeover_challenge(state)
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.confirm_ownership_takeover(
        command=_takeover_confirm_request(op_id="op-takeover-no-push"),
    )

    assert result.status == "rejected"
    assert result.error_code == "pushed_head_required"
    active = state.load_active_ownership("tenant-a", "AG3-100")
    assert active is not None
    assert active.owner_session_id == "sess-001"
    assert "sess-B" not in state.bindings
    assert state.takeover_transfers == []
    assert state.events == []


def test_takeover_confirm_rejects_empty_push_evidence_and_writes_nothing() -> None:
    state = _RepoState()
    _seed_admitted_run(state, run_id="run-100", session_id="sess-001")
    _seed_takeover_challenge(state)
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.confirm_ownership_takeover(
        command=_takeover_confirm_request(op_id="op-takeover-empty-evidence"),
    )

    assert result.status == "rejected"
    assert result.error_code == "pushed_head_required"
    active = state.load_active_ownership("tenant-a", "AG3-100")
    assert active is not None
    assert active.owner_session_id == "sess-001"
    assert "sess-B" not in state.bindings
    assert state.takeover_transfers == []
    assert state.events == []


def test_takeover_confirm_rejects_mismatched_barrier_head_and_writes_nothing() -> None:
    state = _RepoState()
    _seed_admitted_run(state, run_id="run-100", session_id="sess-001")
    state.push_freshness[("tenant-a", "AG3-100", "run-100")] = (
        _push_freshness(repo_id="backend", pushed_sha="abc123"),
    )
    state.push_barrier_verdicts[("tenant-a", "AG3-100", "run-100")] = (
        _push_barrier_verdict(repo_id="backend", expected_head_sha="def456"),
    )
    _seed_takeover_challenge(state)
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.confirm_ownership_takeover(
        command=_takeover_confirm_request(op_id="op-takeover-stale-head"),
    )

    assert result.status == "rejected"
    assert result.error_code == "pushed_head_required"
    active = state.load_active_ownership("tenant-a", "AG3-100")
    assert active is not None
    assert active.owner_session_id == "sess-001"
    assert "sess-B" not in state.bindings
    assert state.takeover_transfers == []
    assert state.events == []


def test_takeover_confirm_rejects_expired_challenge_and_writes_nothing() -> None:
    state = _RepoState()
    _seed_admitted_run(state, run_id="run-100", session_id="sess-001")
    state.push_freshness[("tenant-a", "AG3-100", "run-100")] = (
        _push_freshness(repo_id="backend", pushed_sha="abc123"),
    )
    state.push_barrier_verdicts[("tenant-a", "AG3-100", "run-100")] = (
        _push_barrier_verdict(repo_id="backend", expected_head_sha="abc123"),
    )
    _seed_takeover_challenge(
        state,
        expires_at=datetime(2026, 4, 22, 9, 59, tzinfo=UTC),
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.confirm_ownership_takeover(
        command=_takeover_confirm_request(
            op_id="op-takeover-expired",
        ),
    )

    assert result.status == "rejected"
    assert result.error_code == "challenge_expired"
    active = state.load_active_ownership("tenant-a", "AG3-100")
    assert active is not None
    assert active.owner_session_id == "sess-001"
    assert "sess-B" not in state.bindings
    assert state.takeover_transfers == []
    assert state.operations["op-takeover-expired"].status == "rejected"
    assert state.operations["op-request"].status == "expired"
    assert state.takeover_challenges["challenge-op-request"].status == "expired"
    assert state.events == []


def test_agent_confirm_is_forbidden_and_writes_nothing() -> None:
    state = _RepoState()
    _seed_admitted_run(state, run_id="run-100", session_id="sess-001")
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.confirm_ownership_takeover(
        command=_takeover_confirm_request(
            op_id="op-agent-confirm",
            principal_type="interactive_agent",
        ),
    )

    assert result.status == "rejected"
    assert result.error_code == "agent_confirm_forbidden"
    active = state.load_active_ownership("tenant-a", "AG3-100")
    assert active is not None
    assert active.owner_session_id == "sess-001"
    assert state.events == []


def test_agent_initiated_confirm_resolves_linked_approval_without_client_hint() -> None:
    state = _RepoState()
    _seed_admitted_run(state, run_id="run-100", session_id="sess-001")
    state.push_freshness[("tenant-a", "AG3-100", "run-100")] = (
        _push_freshness(repo_id="backend", pushed_sha="abc123"),
    )
    state.push_barrier_verdicts[("tenant-a", "AG3-100", "run-100")] = (
        _push_barrier_verdict(repo_id="backend", expected_head_sha="abc123"),
    )
    _seed_takeover_challenge(
        state,
        requesting_session_id="sess-agent",
        requesting_principal_type="interactive_agent",
        requesting_worktree_roots=("T:/worktrees/ag3-100-agent",),
    )
    state.takeover_approvals["approval-agent"] = TakeoverApprovalRecord(
        approval_id="approval-agent",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        requested_by_session_id="sess-agent",
        requested_by_principal_type="interactive_agent",
        reason="previous owner is unavailable",
        challenge_ref="challenge-op-request",
        status=TakeoverApprovalStatus.PENDING,
        requested_at=datetime(2026, 4, 22, 10, 0, tzinfo=UTC),
        expires_at=datetime(2026, 4, 22, 12, 0, tzinfo=UTC),
    )
    service = ControlPlaneRuntimeService(
        repository=_repository(state),
        now_fn=lambda: datetime(2026, 4, 22, 10, 5, tzinfo=UTC),
    )

    result = service.confirm_ownership_takeover(
        command=_takeover_confirm_request(op_id="op-agent-missing-approval"),
    )

    assert result.status == "committed", result.model_dump(mode="json")
    active = state.load_active_ownership("tenant-a", "AG3-100")
    assert active is not None
    assert active.owner_session_id == "sess-agent"
    assert state.takeover_approvals["approval-agent"].status is TakeoverApprovalStatus.APPROVED
    assert "sess-agent" in state.bindings
    assert len(state.takeover_transfers) == 1
    assert any(
        event.event_type == EventType.TAKEOVER_APPROVAL_CHANGED.value
        for event in state.events
    )


def test_agent_confirm_linked_approval_scope_mismatch_is_integrity_error() -> None:
    state = _RepoState()
    _seed_admitted_run(state, run_id="run-100", session_id="sess-001")
    _seed_takeover_challenge(
        state,
        requesting_session_id="sess-agent",
        requesting_principal_type="interactive_agent",
        requesting_worktree_roots=("T:/worktrees/ag3-100-agent",),
    )
    state.takeover_approvals["approval-wrong-scope"] = TakeoverApprovalRecord(
        approval_id="approval-wrong-scope",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-foreign",
        requested_by_session_id="sess-agent",
        requested_by_principal_type="interactive_agent",
        reason="previous owner is unavailable",
        challenge_ref="challenge-op-request",
        status=TakeoverApprovalStatus.PENDING,
        requested_at=datetime(2026, 4, 22, 10, 0, tzinfo=UTC),
        expires_at=datetime(2026, 4, 22, 12, 0, tzinfo=UTC),
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    with pytest.raises(RuntimeError, match="violates the stored challenge scope"):
        service.confirm_ownership_takeover(
            command=_takeover_confirm_request(op_id="op-agent-integrity-error"),
        )

    assert "op-agent-integrity-error" not in state.operations
    assert state.takeover_challenges["challenge-op-request"].status == "pending"


def test_start_phase_persists_binding_lock_and_operation() -> None:
    state = _RepoState()
    _resolvable_standard_ctx(state)
    service = _admitting_service(state)

    result = service.start_phase(
        run_id="run-100",
        phase="setup",
        request=PhaseMutationRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-001",
            principal_type="orchestrator",
            worktree_roots=["T:/worktrees/ag3-100"],
            op_id="op-start-persists-001",
        ),
    )

    assert result.operation_kind == "phase_start"
    assert result.edge_bundle is not None
    assert result.edge_bundle.current.operating_mode == "story_execution"
    assert result.edge_bundle.qa_lock is not None
    assert result.edge_bundle.qa_lock.status == "ACTIVE"
    assert "sess-001" in state.bindings
    assert ("tenant-a", "AG3-100", "run-100", "story_execution") in state.locks
    assert ("tenant-a", "AG3-100", "run-100", "qa_artifact_write") in state.locks
    assert "op-" in result.op_id
    assert result.op_id in state.operations
    assert [event.event_type for event in state.events] == [
        "session_run_binding_created",
        "story_execution_regime_activated",
    ]


def test_next_binding_version_is_db_monotone_not_wall_clock() -> None:
    """Codex ERROR §4: the mint derives from the persisted value (+1), never a clock.

    Deterministic and process-independent: no binding -> the initial version;
    an existing binding -> previous + 1. Same input -> same output (no wall-clock
    / process-local counter dependency), so it is a sound CAS foundation
    (FK-56 §56.13a).
    """
    assert _next_binding_version(None) == "1"
    assert _next_binding_version("1") == "2"
    assert _next_binding_version("41") == "42"
    assert _next_binding_version("999") == "1000"
    # Determinism: repeated calls with the same input never drift (no clock).
    assert _next_binding_version("7") == _next_binding_version("7") == "8"


def test_start_then_complete_increments_binding_version_db_monotone() -> None:
    """The persisted binding_version increases DB-monotone across phase mutations.

    A fresh start (no prior binding) mints ``"1"``; the subsequent complete reads
    the persisted ``"1"`` and mints ``"2"`` -- derived from DB state, not a wall
    clock. Proves the real runtime write path uses the DB-monotone mint.
    """
    state = _RepoState()
    _resolvable_standard_ctx(state)
    service = _admitting_service(state)
    base_request = {
        "project_key": "tenant-a",
        "story_id": "AG3-100",
        "session_id": "sess-001",
        "principal_type": "orchestrator",
        "worktree_roots": ["T:/worktrees/ag3-100"],
    }

    service.start_phase(
        run_id="run-100",
        phase="setup",
        request=PhaseMutationRequest(**base_request, op_id="op-start-mono"),
    )
    assert state.bindings["sess-001"].binding_version == "1"

    service.complete_phase(
        run_id="run-100",
        phase="implementation",
        request=PhaseMutationRequest(**base_request, op_id="op-complete-mono"),
    )
    assert state.bindings["sess-001"].binding_version == "2"


def test_repeated_op_id_replays_without_second_mutation() -> None:
    state = _RepoState()
    _resolvable_standard_ctx(state)
    service = _admitting_service(state)
    request = PhaseMutationRequest(
        project_key="tenant-a",
        story_id="AG3-100",
        session_id="sess-001",
        principal_type="orchestrator",
        worktree_roots=["T:/worktrees/ag3-100"],
        op_id="op-fixed-001",
    )

    first = service.start_phase(run_id="run-100", phase="setup", request=request)
    second = service.start_phase(run_id="run-100", phase="setup", request=request)

    assert first.status == "committed"
    assert second.status == "replayed"
    assert len(state.operations) == 1
    assert len(state.events) == 2


# ---------------------------------------------------------------------------
# AG3-140 (Codex r6): terminal-status discrimination on the MUTATING retry path.
# A non-committed terminal row (aborted / repair / failed) must fail a mutating
# retry of the SAME op_id closed as a STABLE 409 conflict (``rejected``), NEVER a
# 201 replay of the terminal payload. The verbatim terminal payload is preserved
# ONLY on the reconcile READ surface (``get_operation``) and the late-owner
# finalize path (``test_late_finalize_after_admin_abort_materializes_no_side_effects``).
# ---------------------------------------------------------------------------


def _retry_request(op_id: str) -> PhaseMutationRequest:
    return PhaseMutationRequest(
        project_key="tenant-a",
        story_id="AG3-100",
        session_id="sess-001",
        principal_type="orchestrator",
        worktree_roots=["T:/worktrees/ag3-100"],
        op_id=op_id,
    )


def _seed_terminal_operation(
    state: _RepoState,
    *,
    op_id: str,
    status: str,
    request: PhaseMutationRequest,
    phase: str = "setup",
    operation_kind: str = "phase_start",
) -> None:
    """Seed a TERMINAL control_plane_operations row (status + MATCHING body-hash).

    The stamped ``request_body_hash`` equals what a ``start_phase`` retry with
    ``request`` computes, so the retry hits the hash-MATCH branch and the outcome
    is decided purely by the terminal STATUS (AG3-140 r6 status discrimination) --
    isolating the status rule from a body-hash mismatch.
    """
    now = datetime(2026, 7, 2, 11, 0, tzinfo=UTC)
    state.operations[op_id] = ControlPlaneOperationRecord(
        op_id=op_id,
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        session_id="sess-001",
        operation_kind=operation_kind,
        phase=phase,
        status=status,
        response_payload={
            "status": status,
            "op_id": op_id,
            "operation_kind": operation_kind,
            "run_id": "run-100",
            "phase": phase,
        },
        created_at=now,
        updated_at=now,
        request_body_hash=_control_plane_request_body_hash(
            request, operation_kind=operation_kind, phase=phase
        ),
    )


def test_start_phase_retry_against_admin_aborted_terminal_is_conflict_not_replay() -> None:
    """AG3-140 r6 MAJOR: a MUTATING retry of the same op_id against an
    admin-aborted terminal row is a STABLE 409 conflict (``rejected``), NEVER a 201
    replay of ``{status: aborted}``. Reproduces the reported scenario exactly: a
    phase-start claim is admin-aborted (real abort path, original hash preserved),
    then the client retries the same start with the same op_id."""
    state = _RepoState()
    _resolvable_standard_ctx(state)
    request = _retry_request("op-abort-retry")
    now = datetime(2026, 7, 2, 11, 0, tzinfo=UTC)
    # A live claim carrying the SAME body-hash the retry computes (phase=setup),
    # with the AG3-138 fencing identity so the real admin-abort path applies.
    state.operations["op-abort-retry"] = ControlPlaneOperationRecord(
        op_id="op-abort-retry",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        session_id="sess-001",
        operation_kind="phase_start",
        phase="setup",
        status="claimed",
        response_payload={},
        created_at=now,
        updated_at=now,
        claimed_by="owner-live",
        claimed_at=now,
        operation_epoch=1,
        backend_instance_id="inst-me",
        instance_incarnation=1,
        declared_serialization_scope="tenant-a:AG3-100",
        request_body_hash=_control_plane_request_body_hash(
            request, operation_kind="phase_start", phase="setup"
        ),
    )
    service = _admitting_service(state)

    aborted = service.admin_abort_inflight_operation(
        "op-abort-retry", _admin_abort_request()
    )
    assert aborted.status == "aborted"
    assert state.operations["op-abort-retry"].status == "aborted"

    retry = service.start_phase(run_id="run-100", phase="setup", request=request)

    assert retry.status == "rejected", (
        "a mutating retry against an aborted terminal must be a 409 conflict, "
        "never a 201 replay of the aborted payload"
    )
    assert retry.edge_bundle is None
    # No second mutation / side effect; the aborted terminal row is untouched.
    assert state.operations["op-abort-retry"].status == "aborted"
    assert state.bindings == {}
    assert state.events == []


@pytest.mark.parametrize("terminal_status", ["aborted", "repair", "failed"])
def test_start_phase_retry_against_noncommitted_terminal_is_conflict(
    terminal_status: str,
) -> None:
    """AG3-140 r6: every non-committed terminal (aborted / repair / failed) rejects
    a matching-hash mutating retry as a stable conflict, never a cross-status
    replay."""
    state = _RepoState()
    _resolvable_standard_ctx(state)
    op_id = f"op-{terminal_status}-retry"
    request = _retry_request(op_id)
    _seed_terminal_operation(
        state, op_id=op_id, status=terminal_status, request=request
    )
    service = _admitting_service(state)

    retry = service.start_phase(run_id="run-100", phase="setup", request=request)

    assert retry.status == "rejected"
    assert retry.edge_bundle is None
    # The terminal row is neither replayed-as-success nor overwritten.
    assert state.operations[op_id].status == terminal_status
    assert state.bindings == {}
    assert state.events == []


def test_terminal_committed_start_op_id_reused_for_complete_is_mismatch() -> None:
    """AG3-140 (Codex r7 PATH 3 P3): reusing a COMMITTED ``phase_start`` op_id for a
    DIFFERENT mutating operation (``complete``) with an otherwise-identical body is a
    stable 409 ``idempotency_mismatch`` -- NEVER a cross-operation replay.

    The control-plane folds ``operation_kind``+``phase`` into the request-body hash
    (``_control_plane_request_body_hash``), so a ``phase_complete`` retry against a
    committed ``phase_start`` terminal row computes a different hash and is
    classified as a mismatch in ``_load_existing_operation`` -- before any admission
    or side effect. This isolates the operation_kind discriminator on a TERMINAL row
    (distinct from the live-claimed-collision path, which the
    ``*_reusing_live_claimed_start_op_id_*`` tests cover).
    """
    from agentkit.backend.story_context_manager.errors import IdempotencyMismatchError

    state = _RepoState()
    _resolvable_standard_ctx(state)
    op_id = "op-kind-mismatch-complete"
    request = _retry_request(op_id)
    # A COMMITTED phase_start terminal row owns the op_id (its stored hash folds
    # operation_kind="phase_start", phase="setup").
    _seed_terminal_operation(
        state,
        op_id=op_id,
        status="committed",
        request=request,
        operation_kind="phase_start",
        phase="setup",
    )
    service = _admitting_service(state)

    # Retry the SAME op_id as a DIFFERENT operation (complete) on the SAME phase and
    # an otherwise-identical body: operation_kind differs -> folded hash differs ->
    # stable 409 mismatch, never a cross-operation replay of the start result.
    with pytest.raises(IdempotencyMismatchError):
        service.complete_phase(run_id="run-100", phase="setup", request=request)

    # The committed start row is untouched; no cross-shape side effect leaked.
    stored = state.operations[op_id]
    assert stored.operation_kind == "phase_start"
    assert stored.status == "committed"
    assert state.bindings == {}
    assert state.events == []


@pytest.mark.parametrize("terminal_status", ["aborted", "repair", "failed"])
def test_get_operation_reconcile_returns_noncommitted_terminal_verbatim(
    terminal_status: str,
) -> None:
    """AG3-140 r6 (preservation): the reconcile READ surface (``get_operation`` /
    GET /operations/{op_id}, FK-91 Rule 17) STILL returns a non-committed terminal
    VERBATIM -- the mutating-retry conflict fix must not change the read path."""
    state = _RepoState()
    op_id = f"op-{terminal_status}-read"
    request = _retry_request(op_id)
    _seed_terminal_operation(
        state, op_id=op_id, status=terminal_status, request=request
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.get_operation(op_id)

    assert result is not None
    assert result.status == terminal_status, (
        "the reconcile read surface must surface the terminal status verbatim, "
        "never rewritten to 'replayed' or 'rejected'"
    )


def test_complete_closure_unbinds_and_returns_tombstone_roots() -> None:
    state = _RepoState()
    # AG3-142: closure now requires the active run-ownership record as
    # admission evidence (a binding alone is a subordinate projection, never
    # admission by itself).
    _seed_admitted_run(state, run_id="run-100")
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.complete_closure(
        run_id="run-100",
        request=ClosureCompleteRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-001",
            op_id="op-closure-tombstone-001",
        ),
    )

    assert result.edge_bundle is not None
    assert result.edge_bundle.current.operating_mode == "ai_augmented"
    assert result.edge_bundle.tombstone_worktree_roots == ["T:/worktrees/ag3-100"]
    assert result.edge_bundle.qa_lock is not None
    assert result.edge_bundle.qa_lock.status == "INACTIVE"
    assert "sess-001" not in state.bindings
    assert [event.event_type for event in state.events] == [
        "session_run_binding_removed",
        "story_execution_regime_deactivated",
    ]


def test_complete_closure_fast_story_is_a_no_op() -> None:
    """AG3-018 FIX-2 (FK-24 §24.3.4): fast closure creates no locks / no events.

    A fast story never activated story-scoped guards, so its closure must be a
    true no-op: no ``story_execution`` / ``qa_artifact_write`` lock-records are
    created and no story-execution deactivation events are emitted. It returns an
    ``ai_augmented`` bundle with no session and no locks.
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.FAST,
    )
    # ERROR-6 (#6): closure now requires a PRIOR admitted run. A fast story's
    # admitted setup leaves a committed start operation for the run (it never
    # creates a binding/lock), so seed that admission evidence; the fast no-op is
    # preserved WHEN there was a prior admitted run.
    _seed_admitted_run(state, run_id="run-100")
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.complete_closure(
        run_id="run-100",
        request=ClosureCompleteRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-001",
            op_id="op-closure-fast-noop-001",
        ),
    )

    # No story/QA lock-records were created during the fast teardown.
    assert state.locks == {}
    # No story-execution deactivation (or any lifecycle) events were emitted.
    assert state.events == []
    # The bundle resolves to ai_augmented with no session / no locks.
    assert result.operation_kind == "closure_complete"
    assert result.edge_bundle is not None
    assert result.edge_bundle.current.operating_mode == "ai_augmented"
    assert result.edge_bundle.session is None
    assert result.edge_bundle.lock is None
    assert result.edge_bundle.qa_lock is None


def test_complete_closure_fast_story_replays_idempotently() -> None:
    """A repeated fast-closure op_id replays without a second mutation."""
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.FAST,
    )
    # ERROR-6 (#6): closure requires a prior admitted run; seed it (see above).
    _seed_admitted_run(state, run_id="run-100")
    service = ControlPlaneRuntimeService(repository=_repository(state))
    request = ClosureCompleteRequest(
        project_key="tenant-a",
        story_id="AG3-100",
        session_id="sess-001",
        op_id="op-fast-closure-001",
    )

    first = service.complete_closure(run_id="run-100", request=request)
    second = service.complete_closure(run_id="run-100", request=request)

    assert first.status == "committed"
    assert second.status == "replayed"
    assert len(state.operations) == 1
    assert state.locks == {}
    assert state.events == []


def test_complete_closure_standard_story_still_deactivates_locks() -> None:
    """Standard closure is unchanged: INACTIVE locks + deactivation events fire."""
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    _seed_admitted_run(state, run_id="run-100")
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.complete_closure(
        run_id="run-100",
        request=ClosureCompleteRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-001",
            op_id="op-closure-standard-locks-001",
        ),
    )

    assert result.edge_bundle is not None
    assert result.edge_bundle.current.operating_mode == "ai_augmented"
    assert result.edge_bundle.tombstone_worktree_roots == ["T:/worktrees/ag3-100"]
    assert ("tenant-a", "AG3-100", "run-100", "story_execution") in state.locks
    assert ("tenant-a", "AG3-100", "run-100", "qa_artifact_write") in state.locks
    assert "sess-001" not in state.bindings
    assert [event.event_type for event in state.events] == [
        "session_run_binding_removed",
        "story_execution_regime_deactivated",
    ]


def test_project_edge_sync_without_binding_returns_ai_augmented() -> None:
    state = _RepoState()
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.sync_project_edge(
        ProjectEdgeSyncRequest(
            project_key="tenant-a", session_id="sess-001", op_id="op-sync-no-binding-001"
        ),
    )

    assert result.status == "synced"
    assert result.edge_bundle is not None
    assert result.edge_bundle.current.operating_mode == "ai_augmented"


def test_project_edge_sync_with_missing_lock_returns_binding_invalid() -> None:
    state = _RepoState()
    state.bindings["sess-001"] = SessionRunBindingRecord(
        session_id="sess-001",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        principal_type="orchestrator",
        worktree_roots=("T:/worktrees/ag3-100",),
        binding_version="1",
        updated_at=datetime(2026, 4, 22, 10, 0, tzinfo=UTC),
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.sync_project_edge(
        ProjectEdgeSyncRequest(
            project_key="tenant-a", session_id="sess-001", op_id="op-sync-missing-lock-001"
        ),
    )

    assert result.edge_bundle is not None
    assert result.edge_bundle.current.operating_mode == "binding_invalid"
    assert result.run_id == "run-100"


def test_project_edge_sync_with_revoked_binding_returns_binding_invalid() -> None:
    """AC8 (SOLL-034 behaviour, server-side part): the server-side binding
    resolution (``_resolve_operating_mode``, mirrored by
    ``ProjectEdgeResolver.resolve()`` on the edge) surfaces a REVOKED binding
    as ``binding_invalid`` -- even when its lock is still ACTIVE, never
    re-classified as ``story_execution``. The revocation reason is carried
    verbatim on the synced ``session`` view (the local edge derives its own
    ``block_reason`` from it).
    """
    state = _RepoState()
    state.bindings["sess-001"] = SessionRunBindingRecord(
        session_id="sess-001",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        principal_type="orchestrator",
        worktree_roots=("T:/worktrees/ag3-100",),
        binding_version="1",
        updated_at=datetime(2026, 4, 22, 10, 0, tzinfo=UTC),
        status="revoked",
        revocation_reason="ownership_transferred",
    )
    state.locks[("tenant-a", "AG3-100", "run-100", "story_execution")] = StoryExecutionLockRecord(
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        lock_type="story_execution",
        status="ACTIVE",
        worktree_roots=("T:/worktrees/ag3-100",),
        binding_version="1",
        activated_at=datetime(2026, 4, 22, 10, 0, tzinfo=UTC),
        updated_at=datetime(2026, 4, 22, 10, 0, tzinfo=UTC),
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.sync_project_edge(
        ProjectEdgeSyncRequest(
            project_key="tenant-a", session_id="sess-001", op_id="op-sync-revoked-001"
        ),
    )

    assert result.edge_bundle is not None
    assert result.edge_bundle.current.operating_mode == "binding_invalid"
    assert result.edge_bundle.session is not None
    assert result.edge_bundle.session.status == "revoked"
    assert result.edge_bundle.session.revocation_reason == "ownership_transferred"


def test_project_edge_sync_genericizes_unknown_revocation_reason_in_bundle() -> None:
    """R3-3: sync never exposes an unknown non-empty revocation reason."""
    state = _RepoState()
    state.bindings["sess-001"] = SessionRunBindingRecord(
        session_id="sess-001",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        principal_type="orchestrator",
        worktree_roots=("T:/worktrees/ag3-100",),
        binding_version="1",
        updated_at=datetime(2026, 4, 22, 10, 0, tzinfo=UTC),
        status="revoked",
        revocation_reason="future_untrusted_reason",
    )
    state.locks[("tenant-a", "AG3-100", "run-100", "story_execution")] = (
        StoryExecutionLockRecord(
            project_key="tenant-a",
            story_id="AG3-100",
            run_id="run-100",
            lock_type="story_execution",
            status="ACTIVE",
            worktree_roots=("T:/worktrees/ag3-100",),
            binding_version="1",
            activated_at=datetime(2026, 4, 22, 10, 0, tzinfo=UTC),
            updated_at=datetime(2026, 4, 22, 10, 0, tzinfo=UTC),
        )
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.sync_project_edge(
        ProjectEdgeSyncRequest(
            project_key="tenant-a",
            session_id="sess-001",
            op_id="op-sync-unknown-revocation-r3",
        ),
    )

    assert result.edge_bundle is not None
    assert result.edge_bundle.current.operating_mode == "binding_invalid"
    assert result.edge_bundle.session is not None
    assert result.edge_bundle.session.status == "revoked"
    assert result.edge_bundle.session.revocation_reason == "session_binding_mismatch"


def test_get_operation_returns_replayed_result() -> None:
    state = _RepoState()
    _resolvable_standard_ctx(state)
    service = _admitting_service(state)
    created = service.start_phase(
        run_id="run-100",
        phase="setup",
        request=PhaseMutationRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-001",
            principal_type="orchestrator",
            worktree_roots=["T:/worktrees/ag3-100"],
            op_id="op-fixed-001",
        ),
    )

    replayed = service.get_operation("op-fixed-001")

    assert created.status == "committed"
    assert replayed is not None
    assert replayed.status == "replayed"
    assert replayed.op_id == "op-fixed-001"


def _fast_request() -> PhaseMutationRequest:
    return PhaseMutationRequest(
        project_key="tenant-a",
        story_id="AG3-100",
        session_id="sess-001",
        principal_type="orchestrator",
        worktree_roots=["T:/worktrees/ag3-100"],
        op_id="op-fast-001",
    )


def test_fast_story_skips_story_scoped_session_and_locks() -> None:
    """AG3-018 AC3/AC5: a fast story materializes no session/locks.

    ERROR-1 (#1) / AG3-142: a non-setup start requires the run to be ADMITTED
    (the active run-ownership record); otherwise it is fail-closed REJECTED.
    This AG3-018 mode-resolution test exercises the legitimate ADMITTED
    non-setup path, so it seeds run-ownership admission evidence WITHOUT a
    binding (a fast start materializes no binding), keeping the AC3/AC5 "no
    story-scoped state" assertions exact.
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.FAST,
    )
    _seed_admitted_run(state, run_id="run-100", seed_binding=False)
    # AG3-123: the workspace is resolvable (admitted stub dispatch) so this test
    # isolates the mode-resolution materialization, not the workspace anchor.
    service = _admitting_service(state)

    result = service.start_phase(
        run_id="run-100",
        phase="implementation",
        request=_fast_request(),
    )

    # No story-scoped session binding and no locks were materialized.
    assert state.bindings == {}
    assert state.locks == {}
    # The edge bundle resolves to ai_augmented with no session/lock so the
    # local edge runs only the baseline guards (BranchGuard et al.).
    assert result.edge_bundle is not None
    assert result.edge_bundle.current.operating_mode == "ai_augmented"
    assert result.edge_bundle.session is None
    assert result.edge_bundle.lock is None
    assert result.edge_bundle.qa_lock is None
    # No story_execution regime is entered, so no regime/ binding events fire.
    assert state.events == []


def test_standard_story_still_materializes_session_and_locks() -> None:
    """Standard stories are unchanged: full session + both locks materialized.

    ERROR-1 (#1) / AG3-142: the legitimate non-setup path requires an ADMITTED
    run, so seed the active run-ownership record before the implementation
    start.
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    _seed_admitted_run(state, run_id="run-100", seed_binding=False)
    # AG3-123: the workspace is resolvable (admitted stub dispatch) so this test
    # isolates the mode-resolution materialization, not the workspace anchor.
    service = _admitting_service(state)

    result = service.start_phase(
        run_id="run-100",
        phase="implementation",
        request=_fast_request(),
    )

    assert result.edge_bundle is not None
    assert result.edge_bundle.current.operating_mode == "story_execution"
    assert "sess-001" in state.bindings
    assert ("tenant-a", "AG3-100", "run-100", "story_execution") in state.locks
    assert ("tenant-a", "AG3-100", "run-100", "qa_artifact_write") in state.locks
    assert [event.event_type for event in state.events] == [
        "session_run_binding_created",
        "story_execution_regime_activated",
    ]


def test_agent_supplied_mode_cannot_override_authoritative_store() -> None:
    """The store wins: an agent-forgeable mode field is not even consulted.

    ``PhaseMutationRequest`` carries no ``mode`` (no forgeable input). Even when
    a caller smuggles ``mode=fast`` into the free-form ``detail`` map, the store
    record (standard) is authoritative and full materialization happens.

    ERROR-1 (#1) / AG3-142: the legitimate non-setup path requires an ADMITTED
    run, so seed the active run-ownership record.
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    _seed_admitted_run(state, run_id="run-100", seed_binding=False)
    # AG3-123: the workspace is resolvable (admitted stub dispatch) so this test
    # isolates the mode-resolution materialization, not the workspace anchor.
    service = _admitting_service(state)

    result = service.start_phase(
        run_id="run-100",
        phase="implementation",
        request=PhaseMutationRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-001",
            principal_type="orchestrator",
            worktree_roots=["T:/worktrees/ag3-100"],
            detail={"mode": "fast"},
            op_id="op-mode-authoritative-001",
        ),
    )

    # Store says standard -> story-scoped state IS materialized regardless of
    # the agent-supplied detail.mode.
    assert result.edge_bundle is not None
    assert result.edge_bundle.current.operating_mode == "story_execution"
    assert result.edge_bundle.lock is not None
    assert ("tenant-a", "AG3-100", "run-100", "story_execution") in state.locks


def test_unresolvable_mode_for_code_story_fails_closed() -> None:
    """Fail-closed: no authoritative StoryContext -> guards stay active.

    A missing store record must NEVER silently skip story-scoped guards; the
    run is treated as standard (full materialization), so a code story can never
    lose its guards on a lookup gap.

    ERROR-1 (#1) / AG3-142: the unresolvable-MODE concern (fail-closed-to-standard)
    is distinct from the unresolvable-CTX run-admission concern. This test isolates
    the MODE concern on the legitimate ADMITTED non-setup path: it seeds the active
    run-ownership record so the run is admitted, then proves that an unresolvable
    StoryContext still materializes the FULL standard regime (guards active). The
    UN-admitted unresolvable-ctx non-setup REJECT path is covered by
    ``test_non_setup_unresolvable_ctx_unadmitted_rejects_fail_closed``.
    """
    state = _RepoState()  # no story_contexts entry => unresolvable mode
    _seed_admitted_run(state, run_id="run-100", seed_binding=False)
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.start_phase(
        run_id="run-100",
        phase="implementation",
        request=_fast_request(),
    )

    assert result.edge_bundle is not None
    assert result.edge_bundle.current.operating_mode == "story_execution"
    assert result.edge_bundle.lock is not None
    assert ("tenant-a", "AG3-100", "run-100", "story_execution") in state.locks
    assert ("tenant-a", "AG3-100", "run-100", "qa_artifact_write") in state.locks


class _StubDispatcher:
    """A minimal :class:`PhaseDispatcher`-shaped stub for runtime dispatch tests.

    Returns a fixed normalized result so the runtime's fail-closed admission
    short-circuit can be exercised without standing up the real engine /
    pre-start-guard composition. Records the calls so a test can assert it was
    (or was not) consulted.
    """

    def __init__(self, result: PhaseDispatchResult) -> None:
        self._result = result
        self.calls: list[str] = []
        #: AG3-054 ERROR-1: the run-scoped admission flag the runtime threads in.
        self.run_admitted_calls: list[bool] = []

    def dispatch(
        self,
        *,
        ctx: StoryContext,
        phase: str,
        run_id: str,
        run_admitted: bool,
        detail: dict[str, object] | None = None,
    ) -> PhaseDispatchResult:
        del ctx, run_id, detail
        self.calls.append(phase)
        self.run_admitted_calls.append(run_admitted)
        return self._result


def _rejected_dispatch(reason: str) -> PhaseDispatchResult:
    return PhaseDispatchResult(
        phase="setup",
        status="rejected",
        reaction="rejected",
        dispatched=False,
        rejection_reason=reason,
    )


def _admitted_dispatch() -> PhaseDispatchResult:
    return PhaseDispatchResult(
        phase="setup",
        status="phase_completed",
        reaction="advance",
        dispatched=True,
        next_phase="implementation",
    )


def test_guard_rejected_setup_start_materializes_no_state() -> None:
    """AG3-054 (FK-20 §20.8.2): a REJECTED fresh-run setup start is fail-closed.

    When the pre-start guard rejects a fresh setup start, the control plane must
    NOT materialize the run's story-scoped guard regime: no session binding, no
    story/QA lock-records, and NO committed operation may be persisted (so a
    later retry re-evaluates). The result is the rejection itself, with no edge
    bundle.
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
        project_root=Path("T:/projects/tenant-a"),
    )
    dispatcher = _StubDispatcher(
        _rejected_dispatch("StoryStatus is not Approved (Tor 1)."),
    )
    service = ControlPlaneRuntimeService(
        repository=_repository(state),
        phase_dispatcher=dispatcher,  # type: ignore[arg-type]
    )

    result = service.start_phase(
        run_id="run-100",
        phase="setup",
        request=PhaseMutationRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-001",
            principal_type="orchestrator",
            worktree_roots=["T:/worktrees/ag3-100"],
            op_id="op-rejected-001",
        ),
    )

    # The result IS the rejection -- no success that activates the run.
    assert result.status == "rejected"
    assert result.edge_bundle is None
    assert result.phase_dispatch is not None
    assert result.phase_dispatch.dispatched is False
    assert result.phase_dispatch.status == "rejected"
    # Probe the repository state: NO story-scoped state was materialized.
    assert state.bindings == {}, "rejection must persist no session binding"
    assert state.locks == {}, "rejection must persist no lock-records"
    assert state.events == [], "rejection must emit no lifecycle events"
    # NO committed operation was stored for this op_id (retry re-evaluates).
    assert "op-rejected-001" not in state.operations
    assert state.operations == {}


def test_admitted_start_after_rejection_materializes_state() -> None:
    """A later admitted start for the same story succeeds and materializes state.

    Proves the earlier rejection did not poison the path: because the rejection
    stored no committed op, a fresh op_id (once Approved+READY) re-evaluates,
    is admitted, and DOES materialize the full story-scoped regime.
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
        project_root=Path("T:/projects/tenant-a"),
    )
    rejecting = ControlPlaneRuntimeService(
        repository=_repository(state),
        phase_dispatcher=_StubDispatcher(  # type: ignore[arg-type]
            _rejected_dispatch("not READY (Tor 2)."),
        ),
    )
    rejected = rejecting.start_phase(
        run_id="run-100",
        phase="setup",
        request=PhaseMutationRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-001",
            principal_type="orchestrator",
            worktree_roots=["T:/worktrees/ag3-100"],
            op_id="op-rejected-002",
        ),
    )
    assert rejected.status == "rejected"
    assert state.operations == {}

    # Now Approved+READY -> a fresh dispatcher admits the same story's start.
    admitting = ControlPlaneRuntimeService(
        repository=_repository(state),
        phase_dispatcher=_StubDispatcher(_admitted_dispatch()),  # type: ignore[arg-type]
    )
    admitted = admitting.start_phase(
        run_id="run-100",
        phase="setup",
        request=PhaseMutationRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-001",
            principal_type="orchestrator",
            worktree_roots=["T:/worktrees/ag3-100"],
            op_id="op-admitted-001",
        ),
    )

    assert admitted.status == "committed"
    assert admitted.edge_bundle is not None
    assert admitted.edge_bundle.current.operating_mode == "story_execution"
    assert admitted.phase_dispatch is not None
    assert admitted.phase_dispatch.dispatched is True
    # The admitted start materialized the full story-scoped regime.
    assert "sess-001" in state.bindings
    assert ("tenant-a", "AG3-100", "run-100", "story_execution") in state.locks
    assert ("tenant-a", "AG3-100", "run-100", "qa_artifact_write") in state.locks
    assert "op-admitted-001" in state.operations


def _setup_request(op_id: str = "op-fresh-setup-001") -> PhaseMutationRequest:
    return PhaseMutationRequest(
        project_key="tenant-a",
        story_id="AG3-100",
        session_id="sess-001",
        principal_type="orchestrator",
        worktree_roots=["T:/worktrees/ag3-100"],
        op_id=op_id,
    )


def test_fresh_setup_start_with_no_story_context_rejects_fail_closed() -> None:
    """ERROR-1 (FK-20 §20.8.2): unresolvable ctx (None) rejects a fresh setup start.

    A fresh setup start whose ``StoryContext`` cannot be resolved (no store row)
    could not have its Approved+READY run-admission evaluated. The control plane
    must REJECT fail-closed and materialize NOTHING: no binding, no locks, no
    events, no edge bundle, and NO stored operation (a later retry re-evaluates).
    """
    state = _RepoState()  # no story_contexts entry => ctx is None
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.start_phase(
        run_id="run-100",
        phase="setup",
        request=_setup_request(),
    )

    assert result.status == "rejected"
    assert result.edge_bundle is None
    assert result.phase_dispatch is not None
    assert result.phase_dispatch.dispatched is False
    assert result.phase_dispatch.status == "rejected"
    # Repository probe: NOTHING was materialized.
    assert state.bindings == {}, "rejection must persist no session binding"
    assert state.locks == {}, "rejection must persist no lock-records"
    assert state.events == [], "rejection must emit no lifecycle events"
    assert state.operations == {}, "rejection must store no operation"


def test_fresh_setup_start_with_unresolvable_workspace_rejects_fail_closed() -> None:
    """AG3-123 AC3/AC4: a fresh setup start with an unresolvable workspace rejects.

    Run-admission is decoupled from ``project_root``; the FS anchor is resolved
    Backend-side via the ``StoryWorkspaceLocator``. When the locator cannot resolve
    the workspace, the REAL ``PhaseDispatcher.dispatch`` fails closed (structured
    :class:`StoryWorkspaceUnresolvedError` -> rejected) BEFORE the engine / guard
    is ever built, and the runtime materializes NOTHING (no binding / lock / event
    / operation). Driven through the real ``ControlPlaneRuntimeService`` path.
    """
    from agentkit.backend.control_plane.dispatch import PhaseDispatcher, PreStartGuard
    from agentkit.backend.control_plane.workspace_locator import (
        StoryWorkspace,
        StoryWorkspaceUnresolvedError,
    )

    class _UnresolvableLocator:
        def resolve(
            self, project_key: str, story_id: str, run_id: str
        ) -> StoryWorkspace:
            raise StoryWorkspaceUnresolvedError(
                "no project_registry entry (fail-closed)",
                detail={
                    "project_key": project_key,
                    "story_id": story_id,
                    "run_id": run_id,
                },
            )

    def _engine_factory(ctx: StoryContext, workspace: StoryWorkspace) -> PipelineEngine:
        raise AssertionError("engine must not build on an unresolvable workspace")

    def _guard_factory(workspace: StoryWorkspace) -> PreStartGuard:
        raise AssertionError("guard must not build on an unresolvable workspace")

    dispatcher = PhaseDispatcher(
        workspace_locator=_UnresolvableLocator(),
        engine_factory=_engine_factory,
        guard_factory=_guard_factory,
    )
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    service = ControlPlaneRuntimeService(
        repository=_repository(state),
        phase_dispatcher=dispatcher,
    )

    result = service.start_phase(
        run_id="run-100",
        phase="setup",
        request=_setup_request("op-fresh-setup-002"),
    )

    assert result.status == "rejected"
    assert result.edge_bundle is None
    assert result.phase_dispatch is not None
    assert result.phase_dispatch.dispatched is False
    assert state.bindings == {}
    assert state.locks == {}
    assert state.events == []
    assert state.operations == {}


def test_non_setup_unresolvable_ctx_unadmitted_rejects_fail_closed() -> None:
    """ERROR-1 (#1): a fresh, UN-admitted, NON-setup start with unresolvable ctx.

    This CORRECTS the prior (wrong) fail-open assertion. The round-8 run-scoped
    first-call enforcement lives inside ``PhaseDispatcher.dispatch``, but
    ``_dispatch_phase`` returns ``None`` when the StoryContext is unresolvable (ctx
    None AND project_root None) BEFORE the dispatcher runs. The run-scoped
    first-call must therefore hold in the RUNTIME on this path too: a non-setup
    start for a run that was NEVER admitted (no committed setup phase_start, no
    run-matched binding) must be fail-closed REJECTED and materialize NOTHING --
    NOT fall through to a standard materialization. An un-admitted run can NEVER
    materialize state via a non-setup start, regardless of ctx resolvability.
    """
    state = _RepoState()  # no story_contexts => unresolvable; no admission evidence
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.start_phase(
        run_id="run-100",
        phase="implementation",
        request=_fast_request(),
    )

    assert result.status == "rejected"
    assert result.edge_bundle is None
    assert result.phase_dispatch is not None
    assert result.phase_dispatch.dispatched is False
    # Repository probe: NOTHING was materialized for the un-admitted run.
    assert state.bindings == {}, "rejection must persist no session binding"
    assert state.locks == {}, "rejection must persist no lock-records"
    assert state.events == [], "rejection must emit no lifecycle events"
    assert state.operations == {}, "rejection must store no operation"


def test_non_setup_unresolvable_ctx_admitted_run_still_materializes() -> None:
    """ERROR-1 (#1) positive: the ADMITTED non-setup path still works.

    The legitimate non-setup path is preserved: when the run WAS admitted (a prior
    committed setup phase_start for THIS run), a non-setup start with an
    unresolvable ctx keeps the AG3-018 fail-closed-to-standard behavior (full
    story-scoped materialization, guards ACTIVE). Only the UN-admitted run is
    rejected.
    """
    state = _RepoState()  # no story_contexts entry => unresolvable ctx/mode
    _seed_admitted_run(state, run_id="run-100", seed_binding=False)
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.start_phase(
        run_id="run-100",
        phase="implementation",
        request=_fast_request(),
    )

    assert result.status == "committed"
    assert result.edge_bundle is not None
    assert result.edge_bundle.current.operating_mode == "story_execution"
    assert result.edge_bundle.lock is not None
    assert ("tenant-a", "AG3-100", "run-100", "story_execution") in state.locks
    assert ("tenant-a", "AG3-100", "run-100", "qa_artifact_write") in state.locks


def test_replay_returns_same_phase_dispatch_and_dispatches_once() -> None:
    """ERROR-2 (AC7): a replay returns the SAME phase_dispatch; dispatch runs once.

    The first start carries ``phase_dispatch``; a replay of the same op_id must
    return a stored record IDENTICAL to the first response (full equality, not
    just ``status == "replayed"``) and must NOT invoke the dispatcher again.
    """
    state = _RepoState()
    _resolvable_standard_ctx(state)
    dispatcher = _StubDispatcher(_admitted_dispatch())
    service = ControlPlaneRuntimeService(
        repository=_repository(state),
        phase_dispatcher=dispatcher,  # type: ignore[arg-type]
    )
    request = _setup_request("op-replay-dispatch-001")

    first = service.start_phase(run_id="run-100", phase="setup", request=request)
    replay = service.start_phase(run_id="run-100", phase="setup", request=request)

    assert first.status == "committed"
    assert first.phase_dispatch is not None
    assert replay.status == "replayed"
    # Full equality of the carried dispatch outcome (no lost phase_dispatch).
    assert replay.phase_dispatch == first.phase_dispatch
    assert replay.phase_dispatch == _admitted_dispatch()
    # The dispatcher was invoked EXACTLY ONCE across both calls (no re-dispatch).
    assert dispatcher.calls == ["setup"]
    assert len(state.operations) == 1
    # The PERSISTED record is the full first result (no field dropped before store).
    assert (
        state.operations["op-replay-dispatch-001"].response_payload
        == first.model_dump(mode="json")
    )


def test_mutation_result_success_status_requires_edge_bundle() -> None:
    """A non-rejected ControlPlaneMutationResult MUST carry an edge_bundle.

    The field was widened to optional ONLY for fail-closed rejections (AG3-054).
    A committed / replayed / synced result with ``edge_bundle=None`` would let the
    project-edge client silently skip publishing an authoritative bundle (a
    fail-open activation gap) -- the model rejects it at the boundary.
    """
    for status in ("committed", "replayed", "synced"):
        with pytest.raises(ValidationError):
            ControlPlaneMutationResult(
                status=status,  # type: ignore[arg-type]
                op_id="op-x",
                operation_kind="phase_start",
                edge_bundle=None,
            )


def test_mutation_result_rejected_must_not_carry_edge_bundle() -> None:
    """A 'rejected' result materialized no guard regime and must carry no bundle."""
    state = _RepoState()
    _resolvable_standard_ctx(state)
    service = ControlPlaneRuntimeService(
        repository=_repository(state),
        phase_dispatcher=_StubDispatcher(_admitted_dispatch()),  # type: ignore[arg-type]
    )
    committed = service.start_phase(
        run_id="run-100", phase="setup", request=_setup_request("op-bundle-src"),
    )
    assert committed.edge_bundle is not None  # a real bundle to misuse below

    with pytest.raises(ValidationError):
        ControlPlaneMutationResult(
            status="rejected",
            op_id="op-y",
            operation_kind="phase_start",
            edge_bundle=committed.edge_bundle,
        )


# ---------------------------------------------------------------------------
# ERROR-3: complete/fail require a prior admitted run
# ---------------------------------------------------------------------------


def _phase_request(op_id: str) -> PhaseMutationRequest:
    return PhaseMutationRequest(
        project_key="tenant-a",
        story_id="AG3-100",
        session_id="sess-001",
        principal_type="orchestrator",
        worktree_roots=["T:/worktrees/ag3-100"],
        op_id=op_id,
    )


def test_complete_phase_without_admitted_run_rejects_and_materializes_nothing() -> None:
    """ERROR-3: a first-ever complete with no prior admitted start is fail-closed.

    No prior committed start operation, no persisted phase-state, no session
    binding -> the completion must NOT materialize any story-scoped state and must
    store no committed op.
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
        project_root=Path("T:/projects/tenant-a"),
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.complete_phase(
        run_id="run-100",
        phase="setup",
        request=_phase_request("op-complete-unadmitted"),
    )

    assert result.status == "rejected"
    assert result.operation_kind == "phase_complete"
    assert result.edge_bundle is None
    assert result.phase_dispatch is not None
    assert result.phase_dispatch.dispatched is False
    assert "no prior admitted start" in (result.phase_dispatch.rejection_reason or "")
    assert state.bindings == {}
    assert state.locks == {}
    assert state.events == []
    assert state.operations == {}


def test_fail_phase_without_admitted_run_rejects() -> None:
    """ERROR-3: a first-ever fail with no prior admitted start is fail-closed too."""
    state = _RepoState()
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.fail_phase(
        run_id="run-100",
        phase="implementation",
        request=_phase_request("op-fail-unadmitted"),
    )

    assert result.status == "rejected"
    assert result.operation_kind == "phase_fail"
    assert result.edge_bundle is None
    assert state.operations == {}


def test_complete_phase_with_only_a_binding_is_not_admitted() -> None:
    """AG3-142 (SOLL-014/SOLL-019): a session binding ALONE is NEVER admission.

    The binding is a subordinate, session-side projection of the active
    ownership record -- never a second admission path. A binding for THIS
    run with NO active ``run_ownership_records`` row must fail-closed reject
    (no committed op, no side effect), which is the exact opposite of the
    pre-AG3-142 behaviour this test used to pin.
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    now = datetime(2026, 4, 22, 10, 0, tzinfo=UTC)
    state.bindings["sess-001"] = SessionRunBindingRecord(
        session_id="sess-001",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        principal_type="orchestrator",
        worktree_roots=("T:/worktrees/ag3-100",),
        binding_version="1",
        updated_at=now,
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.complete_phase(
        run_id="run-100",
        phase="implementation",
        request=_phase_request("op-complete-admitted"),
    )

    assert result.status == "rejected"
    assert "op-complete-admitted" not in state.operations


def test_complete_phase_with_prior_binding_and_record_is_admitted() -> None:
    """The legitimate admitted path: binding + active record both present."""
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    _seed_admitted_run(state, run_id="run-100")
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.complete_phase(
        run_id="run-100",
        phase="implementation",
        request=_phase_request("op-complete-admitted"),
    )

    assert result.status == "committed"
    assert result.operation_kind == "phase_complete"
    assert result.edge_bundle is not None
    assert "op-complete-admitted" in state.operations


def test_complete_phase_reusing_live_claimed_start_op_id_does_not_clobber() -> None:
    """ERROR-3 (#3): complete/fail reusing a LIVE claimed start op_id is rejected.

    A ``complete_phase`` whose op_id is currently held as a LIVE ``claimed``
    ``start_phase`` claim must NOT overwrite the claimed row and steal/destroy the
    start's ownership. The conditional save refuses fail-closed; the runtime
    surfaces a ``rejected`` result and the claimed start row is left intact.
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    now = datetime(2026, 4, 22, 10, 0, tzinfo=UTC)
    # Admitted run (a session binding for THIS run lets the completion be admitted).
    state.bindings["sess-001"] = SessionRunBindingRecord(
        session_id="sess-001",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        principal_type="orchestrator",
        worktree_roots=("T:/worktrees/ag3-100",),
        binding_version="1",
        updated_at=now,
    )
    op_id = "op-shared-with-live-start"
    # A LIVE claimed start claim holds the SAME op_id (owner-A, mid-dispatch).
    state.operations[op_id] = ControlPlaneOperationRecord(
        op_id=op_id,
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        session_id="sess-001",
        operation_kind="phase_start",
        phase="setup",
        status="claimed",
        response_payload={},
        created_at=now,
        updated_at=now,
        claimed_by="owner-A",
        claimed_at=now,
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.complete_phase(
        run_id="run-100",
        phase="implementation",
        request=_phase_request(op_id),
    )

    assert result.status == "rejected", "a collision with a live claim must reject"
    # The live claimed start row is intact -- ownership NOT stolen/destroyed.
    stored = state.operations[op_id]
    assert stored.status == "claimed"
    assert stored.claimed_by == "owner-A"
    assert stored.operation_kind == "phase_start"
    # ERROR-2 (#2): the rejection is ATOMIC -- NO orphan side effect was written.
    # The pre-existing admission binding is untouched (NOT recreated/overwritten by
    # a second materialization) and no NEW lock / event leaked before the collision.
    assert state.bindings["sess-001"].binding_version == "1"
    assert state.locks == {}, "no orphan lock may be written on a rejected complete"
    assert state.events == [], "no orphan event may be emitted on a rejected complete"
    # The collision rejection stored only the live claimed start row (no committed op).
    assert set(state.operations) == {op_id}


def test_complete_closure_reusing_live_claimed_start_op_id_is_atomic() -> None:
    """ERROR-2 (#2): a closure reusing a LIVE claimed start op_id has NO side effects.

    A ``complete_closure`` whose op_id is currently held as a LIVE ``claimed``
    ``start_phase`` claim must be fail-closed REJECTED and the rejection must be
    ATOMIC: the standard teardown's INACTIVE locks, the binding DELETION and the
    deactivation events must NOT be applied (the prior code committed those side
    effects in separate transactions BEFORE the conditional op-row upsert detected
    the collision -> orphan teardown while the live claim survived). The live
    claimed start row must remain intact.
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    now = datetime(2026, 4, 22, 10, 0, tzinfo=UTC)
    # Admitted run: a session binding for THIS run (also the closure teardown target).
    state.bindings["sess-001"] = SessionRunBindingRecord(
        session_id="sess-001",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        principal_type="orchestrator",
        worktree_roots=("T:/worktrees/ag3-100",),
        binding_version="1",
        updated_at=now,
    )
    op_id = "op-closure-shared-with-live-start"
    # A LIVE claimed start claim holds the SAME op_id (owner-A, mid-dispatch).
    state.operations[op_id] = ControlPlaneOperationRecord(
        op_id=op_id,
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        session_id="sess-001",
        operation_kind="phase_start",
        phase="setup",
        status="claimed",
        response_payload={},
        created_at=now,
        updated_at=now,
        claimed_by="owner-A",
        claimed_at=now,
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.complete_closure(
        run_id="run-100",
        request=ClosureCompleteRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-001",
            op_id=op_id,
        ),
    )

    assert result.status == "rejected", "a closure colliding with a live claim rejects"
    # ERROR-2 (#2): ATOMIC rejection -- NO orphan teardown side effect.
    assert "sess-001" in state.bindings, "the binding must NOT be deleted on collision"
    assert state.bindings["sess-001"].run_id == "run-100"
    assert state.locks == {}, "no INACTIVE lock may be written on a rejected closure"
    assert state.events == [], "no deactivation event may fire on a rejected closure"
    # The live claimed start row is intact -- ownership NOT stolen/destroyed.
    stored = state.operations[op_id]
    assert stored.status == "claimed"
    assert stored.claimed_by == "owner-A"
    assert stored.operation_kind == "phase_start"
    assert set(state.operations) == {op_id}


def test_complete_phase_with_binding_for_different_run_is_rejected() -> None:
    """ERROR-2 (#2): a binding for a DIFFERENT run does not admit a completion.

    The admission must match the run EXACTLY: a session binding that merely reuses
    the same ``session_id`` for a DIFFERENT project/story/run is NOT admission
    evidence for this run. A completion for ``run-100`` while the only binding
    under ``sess-001`` belongs to ``run-999`` (a different story) is fail-closed
    REJECTED and materializes nothing.
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    now = datetime(2026, 4, 22, 10, 0, tzinfo=UTC)
    # A stale binding under the SAME session_id but a DIFFERENT story + run.
    state.bindings["sess-001"] = SessionRunBindingRecord(
        session_id="sess-001",
        project_key="tenant-a",
        story_id="AG3-999",
        run_id="run-999",
        principal_type="orchestrator",
        worktree_roots=("T:/worktrees/ag3-999",),
        binding_version="999",
        updated_at=now,
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.complete_phase(
        run_id="run-100",
        phase="implementation",
        request=_phase_request("op-complete-wrong-run"),
    )

    assert result.status == "rejected"
    assert result.operation_kind == "phase_complete"
    assert result.edge_bundle is None
    assert "op-complete-wrong-run" not in state.operations
    # The unrelated binding is untouched (no materialization for the wrong run).
    assert state.bindings["sess-001"].run_id == "run-999"
    assert state.locks == {}
    assert state.events == []


def test_complete_closure_for_unadmitted_run_is_rejected() -> None:
    """ERROR-6 (#6): closure for a run with NO prior admitted start is rejected.

    Consistent with complete/fail admission: a closure for an unadmitted run (no
    persisted phase-state and no run-matched binding) must NOT commit. Fail-closed
    -- it materializes no tombstone state and stores no op.
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.complete_closure(
        run_id="run-100",
        request=ClosureCompleteRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-001",
            op_id="op-closure-unadmitted",
        ),
    )

    assert result.status == "rejected"
    assert result.operation_kind == "closure_complete"
    assert result.edge_bundle is None
    assert state.operations == {}
    assert state.locks == {}
    assert state.events == []


def test_complete_closure_for_different_run_binding_is_rejected() -> None:
    """ERROR-6/#2: a closure admitted only by a binding for ANOTHER run is rejected."""
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    now = datetime(2026, 4, 22, 10, 0, tzinfo=UTC)
    state.bindings["sess-001"] = SessionRunBindingRecord(
        session_id="sess-001",
        project_key="tenant-a",
        story_id="AG3-999",
        run_id="run-999",
        principal_type="orchestrator",
        worktree_roots=("T:/worktrees/ag3-999",),
        binding_version="999",
        updated_at=now,
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.complete_closure(
        run_id="run-100",
        request=ClosureCompleteRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-001",
            op_id="op-closure-wrong-run",
        ),
    )

    assert result.status == "rejected"
    assert result.operation_kind == "closure_complete"
    assert state.operations == {}
    assert state.bindings["sess-001"].run_id == "run-999"


# ---------------------------------------------------------------------------
# AG3-054 run-scoping sweep: a stale/late op for an OLD run (admitted via its
# OWN committed setup op) must not clobber/delete a DIFFERENT (NEW) run's live
# binding that has since rebound the same session_id.
# ---------------------------------------------------------------------------


def _new_run_binding(state: _RepoState, *, run_id: str = "run-NEW") -> None:
    """Bind ``sess-001`` to a NEW run (the live regime that must be protected)."""
    state.bindings["sess-001"] = SessionRunBindingRecord(
        session_id="sess-001",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id=run_id,
        principal_type="orchestrator",
        worktree_roots=("T:/worktrees/ag3-100-new",),
        binding_version="500",
        updated_at=datetime(2026, 4, 22, 12, 0, tzinfo=UTC),
    )


def _committed_setup_op(state: _RepoState, *, run_id: str, op_id: str) -> None:
    """Seed a COMMITTED setup phase_start op admitting ``run_id`` (run-matched).

    This is the OLD run's own admission evidence: it was legitimately set up, so
    complete/fail/closure for it pass admission. The run-scoping protection must
    then still keep it from touching the NEW run's live binding.
    """
    now = datetime(2026, 4, 22, 9, 0, tzinfo=UTC)
    state.operations[op_id] = ControlPlaneOperationRecord(
        op_id=op_id,
        project_key="tenant-a",
        story_id="AG3-100",
        run_id=run_id,
        session_id="sess-001",
        operation_kind="phase_start",
        phase="setup",
        status="committed",
        response_payload={
            "status": "committed",
            "op_id": op_id,
            "operation_kind": "phase_start",
            "run_id": run_id,
            "phase": "setup",
        },
        created_at=now,
        updated_at=now,
    )


def test_complete_phase_old_run_does_not_overwrite_new_runs_binding() -> None:
    """AG3-054 sweep: an OLD run's complete must not clobber a NEW run's binding.

    Run-OLD is admitted by its OWN committed setup phase_start, so admission
    passes. But ``sess-001`` is now bound to run-NEW (the session was rebound). The
    standard complete would (pre-fix) upsert ``ON CONFLICT (session_id)`` and
    OVERWRITE run-NEW's live binding. The run-scoped save refuses fail-closed: the
    completion is REJECTED, run-NEW's binding is UNCHANGED, and NO op / lock / event
    is written.
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    _new_run_binding(state, run_id="run-NEW")
    _committed_setup_op(state, run_id="run-OLD", op_id="op-old-setup")
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.complete_phase(
        run_id="run-OLD",
        phase="implementation",
        request=_phase_request("op-old-complete"),
    )

    assert result.status == "rejected"
    assert result.operation_kind == "phase_complete"
    # run-NEW's live binding is UNCHANGED (run_id + version intact).
    assert state.bindings["sess-001"].run_id == "run-NEW"
    assert state.bindings["sess-001"].binding_version == "500"
    # No committed completion op, no lock change, no events for the old run.
    assert "op-old-complete" not in state.operations
    assert state.locks == {}
    assert state.events == []


def test_fail_phase_old_run_does_not_overwrite_new_runs_binding() -> None:
    """AG3-054 sweep: an OLD run's fail must not clobber a NEW run's binding."""
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    _new_run_binding(state, run_id="run-NEW")
    _committed_setup_op(state, run_id="run-OLD", op_id="op-old-setup")
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.fail_phase(
        run_id="run-OLD",
        phase="implementation",
        request=_phase_request("op-old-fail"),
    )

    assert result.status == "rejected"
    assert result.operation_kind == "phase_fail"
    assert state.bindings["sess-001"].run_id == "run-NEW"
    assert state.bindings["sess-001"].binding_version == "500"
    assert "op-old-fail" not in state.operations
    assert state.locks == {}
    assert state.events == []


def test_standard_closure_old_run_does_not_delete_new_runs_binding() -> None:
    """AG3-054 sweep: an OLD run's standard closure must not delete a NEW binding.

    Run-OLD is admitted by its committed setup op AND resolves to a standard story,
    so the standard teardown path runs. But ``sess-001`` is bound to run-NEW. The
    pre-fix code deleted by ``session_id`` only (clobbering run-NEW) and derived the
    tombstone from whatever binding existed (run-NEW's). The run-scoped teardown
    refuses fail-closed: closure is REJECTED, run-NEW's binding is NOT deleted, and
    NO INACTIVE locks / deactivation events are written for the old run.
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    _new_run_binding(state, run_id="run-NEW")
    _committed_setup_op(state, run_id="run-OLD", op_id="op-old-setup")
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.complete_closure(
        run_id="run-OLD",
        request=ClosureCompleteRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-001",
            op_id="op-old-closure",
        ),
    )

    assert result.status == "rejected"
    assert result.operation_kind == "closure_complete"
    # run-NEW's binding survives untouched.
    assert state.bindings["sess-001"].run_id == "run-NEW"
    assert state.bindings["sess-001"].binding_version == "500"
    # No INACTIVE locks and no deactivation events for the foreign run.
    assert state.locks == {}
    assert state.events == []
    assert "op-old-closure" not in state.operations


def test_fast_closure_old_run_does_not_delete_new_runs_binding() -> None:
    """AG3-054 sweep: an OLD fast run's closure must not delete a NEW run's binding.

    Run-OLD resolves to a FAST story (no locks/events of its own) but is admitted by
    its committed setup op. Its fast closure still issues a run-scoped binding
    delete; because ``sess-001`` is bound to run-NEW, the delete refuses fail-closed:
    closure is REJECTED and run-NEW's binding survives. (A fast closure for a session
    it truly owns -- or no binding at all -- remains a benign no-op; see the existing
    fast-closure tests.)
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.FAST,
    )
    _new_run_binding(state, run_id="run-NEW")
    _committed_setup_op(state, run_id="run-OLD", op_id="op-old-setup")
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.complete_closure(
        run_id="run-OLD",
        request=ClosureCompleteRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-001",
            op_id="op-old-fast-closure",
        ),
    )

    assert result.status == "rejected"
    assert result.operation_kind == "closure_complete"
    assert state.bindings["sess-001"].run_id == "run-NEW"
    assert state.bindings["sess-001"].binding_version == "500"
    assert state.locks == {}
    assert state.events == []
    assert "op-old-fast-closure" not in state.operations


def test_complete_phase_owning_run_still_works_atomically() -> None:
    """Positive: a complete for the run that OWNS the current binding still commits.

    The run-scoping guard only rejects FOREIGN-run writes; the owning run's
    completion upserts its own binding (same run), writes its locks/events and
    commits the op atomically.
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    _seed_admitted_run(state, run_id="run-100")
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.complete_phase(
        run_id="run-100",
        phase="implementation",
        request=_phase_request("op-own-complete"),
    )

    assert result.status == "committed"
    assert result.operation_kind == "phase_complete"
    assert "op-own-complete" in state.operations
    assert state.bindings["sess-001"].run_id == "run-100"
    assert ("tenant-a", "AG3-100", "run-100", "story_execution") in state.locks


def test_standard_closure_owning_run_still_tears_down() -> None:
    """Positive: closure for the run that OWNS the binding still tears it down."""
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    _seed_admitted_run(state, run_id="run-100")
    _committed_setup_op(state, run_id="run-100", op_id="op-own-setup")
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.complete_closure(
        run_id="run-100",
        request=ClosureCompleteRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-001",
            op_id="op-own-closure",
        ),
    )

    assert result.status == "committed"
    assert "sess-001" not in state.bindings
    assert ("tenant-a", "AG3-100", "run-100", "story_execution") in state.locks
    assert [event.event_type for event in state.events] == [
        "session_run_binding_removed",
        "story_execution_regime_deactivated",
    ]


# ---------------------------------------------------------------------------
# ERROR-4: atomic op claim -- dispatcher runs at most once per op_id
# ---------------------------------------------------------------------------


def test_same_op_id_concurrent_starts_dispatch_once() -> None:
    """ERROR-4: two same-op_id starts run the dispatcher EXACTLY once.

    Simulates the race where both callers pass the pre-check before either stores
    a result: the atomic claim (insert-if-absent) lets only ONE dispatch; the
    loser takes the replay path and never re-runs the dispatcher side effects.
    """
    state = _RepoState()
    _resolvable_standard_ctx(state)
    dispatcher = _StubDispatcher(_admitted_dispatch())
    service = ControlPlaneRuntimeService(
        repository=_repository(state),
        phase_dispatcher=dispatcher,  # type: ignore[arg-type]
    )
    request = _setup_request("op-race-001")

    first = service.start_phase(run_id="run-100", phase="setup", request=request)
    second = service.start_phase(run_id="run-100", phase="setup", request=request)

    assert first.status == "committed"
    assert second.status == "replayed"
    # The dispatcher ran EXACTLY ONCE across both same-op_id calls.
    assert dispatcher.calls == ["setup"]
    assert len(state.operations) == 1


def test_stale_claim_placeholder_with_no_claimed_at_is_rejected_not_reclaimed() -> (
    None
):
    """AG3-139: a stale ``claimed`` placeholder (no ``claimed_at``) is NOT reclaimed.

    A winner that CRASHED mid-claim (process killed before its terminal commit or
    its except-path release) can leave a stale ``claimed`` row, possibly with no
    ``claimed_at`` at all (a legacy/malformed placeholder). Previously such a row
    was treated as fail-closed EXPIRED and auto-reclaimed via CAS takeover.
    AG3-139 removed that entirely: ownership never ends by wall clock / TTL /
    lease (FK-91 §91.1a Rule 16), so this is just an ordinary foreign in-flight
    claim -- it is rejected, never dispatched into, and remains until ended via
    the AG3-138 startup reconciliation or an explicit
    ``admin_abort_inflight_operation``.
    """
    state = _RepoState()
    _resolvable_standard_ctx(state)
    now = datetime(2026, 4, 22, 10, 0, tzinfo=UTC)
    state.operations["op-stale-claim"] = ControlPlaneOperationRecord(
        op_id="op-stale-claim",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        session_id="sess-001",
        operation_kind="phase_start",
        phase="setup",
        status="claimed",
        response_payload={},
        created_at=now,
        updated_at=now,
    )
    dispatcher = _StubDispatcher(_admitted_dispatch())
    service = ControlPlaneRuntimeService(
        repository=_repository(state),
        phase_dispatcher=dispatcher,  # type: ignore[arg-type]
    )

    result = service.start_phase(
        run_id="run-100", phase="setup", request=_setup_request("op-stale-claim")
    )

    # The stale claim is rejected, never reclaimed/dispatched into.
    assert result.status == "rejected"
    assert dispatcher.calls == []
    assert state.operations["op-stale-claim"].status == "claimed"


def test_exception_after_claim_releases_claim_and_leaves_op_reclaimable() -> None:
    """ERROR-1 (#1): an exception after a successful claim releases the claim.

    If the dispatch (or the terminal mutation) raises AFTER the atomic claim and
    BEFORE a terminal op is durably stored, the claim MUST be released so the
    op_id is never stranded "in flight" forever, and no half-applied state is
    left. The exception propagates (NO ERROR BYPASSING), but the op_id is left
    CLEAN -- a subsequent retry re-claims and succeeds.
    """
    state = _RepoState()
    _resolvable_standard_ctx(state)

    class _ExplodingThenAdmittedDispatcher:
        def __init__(self) -> None:
            self.calls = 0

        def dispatch(
            self,
            *,
            ctx: StoryContext,
            phase: str,
            run_id: str,
            run_admitted: bool,
            detail: dict[str, object] | None = None,
        ) -> PhaseDispatchResult:
            del ctx, run_id, run_admitted, detail
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("dispatch boom (mid-flight)")
            return _admitted_dispatch()

    dispatcher = _ExplodingThenAdmittedDispatcher()
    service = ControlPlaneRuntimeService(
        repository=_repository(state),
        phase_dispatcher=dispatcher,  # type: ignore[arg-type]
    )
    request = _setup_request("op-boom")

    # First call: the dispatch raises after the claim -> the claim is released
    # and the exception propagates. NOTHING half-applied, and NO op is stored.
    with pytest.raises(RuntimeError, match="dispatch boom"):
        service.start_phase(run_id="run-100", phase="setup", request=request)
    assert "op-boom" not in state.operations, (
        "the claim must be released on an exception (no stranded op_id)"
    )
    assert state.bindings == {}, "no half-applied session binding"
    assert state.locks == {}, "no half-applied lock-records"
    assert state.events == [], "no half-applied lifecycle events"

    # Retry: the op_id is reclaimable; the retry dispatches and commits.
    result = service.start_phase(run_id="run-100", phase="setup", request=request)
    assert result.status == "committed"
    assert dispatcher.calls == 2
    assert state.operations["op-boom"].status == "committed"


# ---------------------------------------------------------------------------
# ERROR-6: status-rewrite to "replayed" re-runs the model invariant
# ---------------------------------------------------------------------------


def test_replay_revalidates_edge_bundle_invariant() -> None:
    """ERROR-6: a tampered stored payload (replayed + edge_bundle None) is rejected.

    ``model_copy(update={"status": "replayed"})`` would NOT re-run validators, so a
    stored ``committed`` payload that was tampered to drop its ``edge_bundle``
    could be silently surfaced as a valid ``replayed`` success. The hardened
    rebuild revalidates via ``model_validate``, so the edge_bundle/status invariant
    is re-enforced and the tampered payload raises.
    """
    state = _RepoState()
    now = datetime(2026, 4, 22, 10, 0, tzinfo=UTC)
    # A tampered stored payload: a (formerly committed) success with NO edge_bundle.
    state.operations["op-tampered"] = ControlPlaneOperationRecord(
        op_id="op-tampered",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        session_id="sess-001",
        operation_kind="phase_start",
        phase="setup",
        status="committed",
        response_payload={
            "status": "committed",
            "op_id": "op-tampered",
            "operation_kind": "phase_start",
            "run_id": "run-100",
            "phase": "setup",
            "edge_bundle": None,
        },
        created_at=now,
        updated_at=now,
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    with pytest.raises(ValidationError):
        service.get_operation("op-tampered")


# ---------------------------------------------------------------------------
# AG3-054 PART A: owner-scoped claim (claim/CAS protocol)
# ---------------------------------------------------------------------------


class _Clock:
    """A deterministic, injectable claim clock (advanceable in tests)."""

    def __init__(self, start: datetime) -> None:
        self._now = start

    def __call__(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta


def _owner_token(label: str) -> str:
    """Build a deterministic, UUID-shaped owner token from a readable label (#5).

    WARNING-5 (#5) validates the minted owner token at the seam: it must be a
    non-empty, UUID-shaped token. Tests still want stable, readable owner labels,
    so this derives a deterministic ``owner-<uuid5(label)>`` -- distinct labels map
    to distinct tokens, and the same label maps to the same token across a test.
    """
    import uuid as _uuid

    return f"owner-{_uuid.uuid5(_uuid.NAMESPACE_OID, label).hex}"


class _TokenSequence:
    """A deterministic owner-token factory (one fixed token per service).

    Tokens are passed as readable labels and converted to UUID-shaped owner
    tokens (#5) so the seam validation accepts them while tests stay readable.
    """

    def __init__(self, *labels: str) -> None:
        self._tokens = [_owner_token(label) for label in labels]
        self._idx = 0

    def __call__(self) -> str:
        token = self._tokens[min(self._idx, len(self._tokens) - 1)]
        self._idx += 1
        return token


def _claim_service(
    state: _RepoState,
    *,
    token: str,
    clock: _Clock,
    dispatcher: _StubDispatcher | None = None,
) -> ControlPlaneRuntimeService:
    return ControlPlaneRuntimeService(
        repository=_repository(state),
        phase_dispatcher=(dispatcher or _StubDispatcher(_admitted_dispatch())),  # type: ignore[arg-type]
        now_fn=clock,
        token_factory=_TokenSequence(token),
    )


def test_concurrent_claims_one_wins_loser_gets_in_flight_rejection_mid_dispatch() -> (
    None
):
    """PART A: two same-op_id claims -> ONE wins, the loser is rejected in-flight.

    The winner is simulated as STILL mid-dispatch (its claim not yet finalized):
    the loser must get a fail-closed "operation in flight, retry" rejection and
    must NOT steal the claim or dispatch (no double dispatch). The winner's claim
    row is left intact for it to finalize.
    """
    state = _RepoState()
    _resolvable_standard_ctx(state)
    clock = _Clock(datetime(2026, 6, 7, 10, 0, tzinfo=UTC))

    # Winner A wins the claim but is held mid-dispatch (we do not finalize it):
    # simulate by directly placing A's live claim, then a real B start_phase.
    winner_claim = ControlPlaneOperationRecord(
        op_id="op-race-live",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        session_id="sess-001",
        operation_kind="phase_start",
        phase="setup",
        status="claimed",
        response_payload={},
        created_at=clock(),
        updated_at=clock(),
        claimed_by="owner-A",
        claimed_at=clock(),
    )
    state.operations["op-race-live"] = winner_claim

    loser_dispatcher = _StubDispatcher(_admitted_dispatch())
    loser = _claim_service(
        state, token="owner-B", clock=clock, dispatcher=loser_dispatcher
    )

    result = loser.start_phase(
        run_id="run-100", phase="setup", request=_setup_request("op-race-live")
    )

    # The loser is rejected in-flight; it never dispatched and never stole.
    assert result.status == "rejected"
    assert result.phase_dispatch is not None
    assert "in flight" in (result.phase_dispatch.rejection_reason or "").lower()
    assert loser_dispatcher.calls == [], "the loser must NOT dispatch"
    # The winner's live claim is untouched (owner-A still holds it).
    assert state.operations["op-race-live"].claimed_by == "owner-A"
    assert state.operations["op-race-live"].status == "claimed"


def test_winner_finalizes_then_loser_retry_replays_terminal_result() -> None:
    """PART A: winner finalizes -> a later same-op_id call replays the terminal row."""
    state = _RepoState()
    _resolvable_standard_ctx(state)
    clock = _Clock(datetime(2026, 6, 7, 10, 0, tzinfo=UTC))
    winner = _claim_service(state, token="owner-A", clock=clock)

    committed = winner.start_phase(
        run_id="run-100", phase="setup", request=_setup_request("op-finalize-replay")
    )
    assert committed.status == "committed"
    assert state.operations["op-finalize-replay"].status == "committed"
    # The finalized terminal row carries NO live owner anymore.
    assert state.operations["op-finalize-replay"].claimed_by is None

    loser_dispatcher = _StubDispatcher(_admitted_dispatch())
    loser = _claim_service(
        state, token="owner-B", clock=clock, dispatcher=loser_dispatcher
    )
    replay = loser.start_phase(
        run_id="run-100", phase="setup", request=_setup_request("op-finalize-replay")
    )

    assert replay.status == "replayed"
    assert replay.op_id == "op-finalize-replay"
    assert loser_dispatcher.calls == [], "a replay never re-dispatches"


def test_owner_release_is_ownership_scoped_and_does_not_delete_foreign_claim() -> None:
    """PART A: owner A's release deletes ONLY A's claim; B's claim/row is untouched.

    B holds a live claim that A never owned. A's stale release/finalize (a wrong
    owner token) must be a no-op (CAS rowcount 0) and must NOT delete B's row or
    result.
    """
    state = _RepoState()
    repo = _repository(state)
    clock = _Clock(datetime(2026, 6, 7, 10, 0, tzinfo=UTC))

    # B holds the live claim.
    b_claim = ControlPlaneOperationRecord(
        op_id="op-ownership",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        session_id="sess-001",
        operation_kind="phase_start",
        phase="setup",
        status="claimed",
        response_payload={},
        created_at=clock(),
        updated_at=clock(),
        claimed_by="owner-B",
        claimed_at=clock(),
    )
    state.operations["op-ownership"] = b_claim

    # A (a stale former owner) tries an ownership-scoped release: it is a no-op.
    repo.release_operation("op-ownership", owner_token="owner-A")
    assert "op-ownership" in state.operations, "A must not delete B's claim"
    assert state.operations["op-ownership"].claimed_by == "owner-B"

    # A's ownership-scoped finalize is also a no-op (CAS rowcount 0).
    a_terminal = ControlPlaneOperationRecord(
        op_id="op-ownership",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        session_id="sess-001",
        operation_kind="phase_start",
        phase="setup",
        status="committed",
        response_payload={"forged": "by-A"},
        created_at=clock(),
        updated_at=clock(),
    )
    assert repo.finalize_operation(a_terminal, owner_token="owner-A") is False
    assert state.operations["op-ownership"].status == "claimed"
    assert state.operations["op-ownership"].claimed_by == "owner-B"


def test_foreign_claim_of_any_age_is_never_taken_over() -> None:
    """AG3-139: a foreign in-flight claim is rejected regardless of its age.

    Ownership never ends by wall clock / TTL / lease (FK-91 §91.1a Rule 16). A
    foreign ``claimed`` row -- whether 1 minute old or well past the FORMER
    5-minute TTL -- is ALWAYS a fail-closed in-flight rejection; there is no CAS
    takeover path left to exercise. An orphaned claim ends only via the AG3-138
    startup reconciliation or an explicit ``admin_abort_inflight_operation``.
    """
    state = _RepoState()
    _resolvable_standard_ctx(state)
    start = datetime(2026, 6, 7, 10, 0, tzinfo=UTC)

    def _seed_foreign_claim(op_id: str, *, claimed_at: datetime) -> None:
        state.operations[op_id] = ControlPlaneOperationRecord(
            op_id=op_id,
            project_key="tenant-a",
            story_id="AG3-100",
            run_id="run-100",
            session_id="sess-001",
            operation_kind="phase_start",
            phase="setup",
            status="claimed",
            response_payload={},
            created_at=claimed_at,
            updated_at=claimed_at,
            claimed_by="owner-crashed",
            claimed_at=claimed_at,
        )

    for op_id, age in (
        ("op-live-1m", timedelta(minutes=1)),
        ("op-old-10m", timedelta(minutes=10)),  # past the FORMER 5-minute TTL
        ("op-ancient-30d", timedelta(days=30)),
    ):
        _seed_foreign_claim(op_id, claimed_at=start)
        dispatcher = _StubDispatcher(_admitted_dispatch())
        result = _claim_service(
            state, token="owner-new", clock=_Clock(start + age), dispatcher=dispatcher
        ).start_phase(run_id="run-100", phase="setup", request=_setup_request(op_id))

        assert result.status == "rejected", (
            f"{op_id} (age={age}) must be rejected, never taken over"
        )
        assert dispatcher.calls == [], "a foreign claim must never be dispatched into"
        assert state.operations[op_id].claimed_by == "owner-crashed", (
            f"{op_id} must remain owned by the original claimant"
        )
        assert state.operations[op_id].status == "claimed"


def test_exception_after_claim_releases_only_my_claim_and_retry_succeeds() -> None:
    """PART A: an exception after the claim releases MY claim; a retry then commits.

    No half-applied binding/lock/event survives, and the released claim is
    reclaimable by the same owner-token-injected service on retry.
    """
    state = _RepoState()
    _resolvable_standard_ctx(state)
    clock = _Clock(datetime(2026, 6, 7, 10, 0, tzinfo=UTC))

    class _ExplodingThenAdmitted:
        def __init__(self) -> None:
            self.calls = 0

        def dispatch(
            self,
            *,
            ctx: StoryContext,
            phase: str,
            run_id: str,
            run_admitted: bool,
            detail: dict[str, object] | None = None,
        ) -> PhaseDispatchResult:
            del ctx, run_id, run_admitted, detail
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("dispatch boom (claimed)")
            return _admitted_dispatch()

    dispatcher = _ExplodingThenAdmitted()
    service = ControlPlaneRuntimeService(
        repository=_repository(state),
        phase_dispatcher=dispatcher,  # type: ignore[arg-type]
        now_fn=clock,
        token_factory=_TokenSequence("owner-A", "owner-A"),
    )
    request = _setup_request("op-claimed-boom")

    with pytest.raises(RuntimeError, match="dispatch boom"):
        service.start_phase(run_id="run-100", phase="setup", request=request)
    # MY claim was released -- no stranded op, no half-applied state.
    assert "op-claimed-boom" not in state.operations
    assert state.bindings == {}
    assert state.locks == {}
    assert state.events == []

    # Retry reclaims and commits.
    result = service.start_phase(run_id="run-100", phase="setup", request=request)
    assert result.status == "committed"
    assert dispatcher.calls == 2
    assert state.operations["op-claimed-boom"].status == "committed"


# ---------------------------------------------------------------------------
# AG3-054 PART C (#3): admission evidence is RUN-scoped, not story-scoped
# ---------------------------------------------------------------------------


def _committed_op_for_run(
    *,
    op_id: str,
    run_id: str,
    project_key: str = "tenant-a",
    story_id: str = "AG3-100",
) -> ControlPlaneOperationRecord:
    now = datetime(2026, 6, 7, 10, 0, tzinfo=UTC)
    return ControlPlaneOperationRecord(
        op_id=op_id,
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
        session_id="sess-001",
        operation_kind="phase_start",
        phase="setup",
        status="committed",
        response_payload={},
        created_at=now,
        updated_at=now,
    )


def test_new_run_not_admitted_by_old_runs_evidence_for_same_story() -> None:
    """PART C (#3): a NEW run is NOT admitted by an OLD run's committed op/binding.

    Admission is RUN-scoped: a committed start op for ``run-OLD`` (same story) and a
    binding for ``run-OLD`` must NOT admit a complete/fail/closure for ``run-NEW``.
    The prior story-scoped phase-state evidence is gone, so a new run with only
    old-run evidence is fail-closed REJECTED.
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    # Only OLD-run evidence exists (committed op + binding for run-OLD).
    state.operations["op-old"] = _committed_op_for_run(op_id="op-old", run_id="run-OLD")
    _seed_admitted_run(state, run_id="run-OLD")
    service = ControlPlaneRuntimeService(repository=_repository(state))

    completed = service.complete_phase(
        run_id="run-NEW",
        phase="implementation",
        request=_phase_request("op-complete-new-run"),
    )
    failed = service.fail_phase(
        run_id="run-NEW",
        phase="implementation",
        request=_phase_request("op-fail-new-run"),
    )
    closed = service.complete_closure(
        run_id="run-NEW",
        request=ClosureCompleteRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-001",
            op_id="op-closure-new-run",
        ),
    )

    assert completed.status == "rejected"
    assert failed.status == "rejected"
    assert closed.status == "rejected"
    assert "op-complete-new-run" not in state.operations
    assert "op-fail-new-run" not in state.operations
    assert "op-closure-new-run" not in state.operations


def test_committed_op_for_that_run_no_longer_admits() -> None:
    """AG3-142 (IMPL-021, SOLL-014, AC2): the positive committed-op heuristic is GONE.

    Pre-AG3-142, a committed start op for THIS run was (by itself) sufficient
    run-scoped admission evidence for complete/fail/closure -- exactly the
    ``has_committed_operation_for_run`` positive evidence this story retires
    ENTIRELY. A committed op with NO active ``run_ownership_records`` row must
    now fail-closed reject: no side effect, no stored op (the inverse of the
    old assertion this test used to pin).
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    state.operations["op-new-start"] = _committed_op_for_run(
        op_id="op-new-start", run_id="run-NEW"
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    completed = service.complete_phase(
        run_id="run-NEW",
        phase="implementation",
        request=_phase_request("op-complete-admitted-by-op"),
    )

    assert completed.status == "rejected"
    assert "op-complete-admitted-by-op" not in state.operations
    assert state.locks == {}
    assert state.events == []


def test_ended_ownership_record_blocks_same_run_admission_without_exit_fence() -> None:
    """AG3-149: ended record status is the sole post-exit admission barrier."""

    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    _seed_admitted_run(state, run_id="run-100")
    state.operations["op-start"] = _committed_op_for_run(
        op_id="op-start",
        run_id="run-100",
    )
    active = state.ownership_records[("tenant-a", "AG3-100", "run-100")]
    state.ownership_records[("tenant-a", "AG3-100", "run-100")] = RunOwnershipRecord(
        project_key=active.project_key,
        story_id=active.story_id,
        run_id=active.run_id,
        owner_session_id=active.owner_session_id,
        ownership_epoch=active.ownership_epoch,
        status=OwnershipStatus.ENDED,
        acquired_via=active.acquired_via,
        acquired_at=active.acquired_at,
        audit_ref=active.audit_ref,
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    completed = service.complete_phase(
        run_id="run-100",
        phase="implementation",
        request=_phase_request("op-complete-after-exit"),
    )
    closed = service.complete_closure(
        run_id="run-100",
        request=ClosureCompleteRequest(
            project_key="tenant-a",
            story_id="AG3-100",
            session_id="sess-001",
            op_id="op-closure-after-exit",
        ),
    )

    assert completed.status == "rejected"
    assert closed.status == "rejected"
    assert "op-complete-after-exit" not in state.operations
    assert "op-closure-after-exit" not in state.operations
    assert state.bindings["sess-001"].run_id == "run-100"


def _committed_op(
    *,
    op_id: str,
    run_id: str,
    operation_kind: str,
    phase: str | None,
) -> ControlPlaneOperationRecord:
    now = datetime(2026, 6, 7, 10, 0, tzinfo=UTC)
    return ControlPlaneOperationRecord(
        op_id=op_id,
        project_key="tenant-a",
        story_id="AG3-100",
        run_id=run_id,
        session_id="sess-001",
        operation_kind=operation_kind,
        phase=phase,
        status="committed",
        response_payload={},
        created_at=now,
        updated_at=now,
    )


def test_committed_phase_complete_alone_does_not_admit_run() -> None:
    """ERROR-3 (#3): a committed phase_complete (no committed setup start) is no proof.

    Admission evidence must prove an admitted START. A committed ``phase_complete``
    for the run with NO committed setup ``phase_start`` must NOT bootstrap admission
    -- a later complete/fail/closure for the run is fail-closed REJECTED.
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    # Only a committed phase_complete exists -- NO committed setup phase_start.
    state.operations["op-stray-complete"] = _committed_op(
        op_id="op-stray-complete",
        run_id="run-NEW",
        operation_kind="phase_complete",
        phase="implementation",
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    rejected = service.complete_phase(
        run_id="run-NEW",
        phase="implementation",
        request=_phase_request("op-complete-not-admitted"),
    )

    assert rejected.status == "rejected"
    assert "op-complete-not-admitted" not in state.operations


def test_committed_setup_phase_start_alone_no_longer_admits_run() -> None:
    """AG3-142 (IMPL-021, SOLL-014, AC2): a committed setup op alone is NOT admission.

    A committed setup ``phase_start`` for the run with NO active
    ``run_ownership_records`` row is retired admission evidence (the inverse
    of the pre-AG3-142 assertion this test used to pin) -- only the active
    ownership record admits.
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    state.operations["op-setup-start"] = _committed_op(
        op_id="op-setup-start",
        run_id="run-NEW",
        operation_kind="phase_start",
        phase="setup",
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    completed = service.complete_phase(
        run_id="run-NEW",
        phase="implementation",
        request=_phase_request("op-complete-admitted-by-setup"),
    )

    assert completed.status == "rejected"
    assert "op-complete-admitted-by-setup" not in state.operations


# ---------------------------------------------------------------------------
# ERROR-1 (#1): a loser whose claim was ended by admin-abort writes NO side
# effects (AG3-139: there is no CAS takeover left to exercise here).
# ---------------------------------------------------------------------------


def test_late_finalize_after_admin_abort_materializes_no_side_effects() -> None:
    """ERROR-1 (#1): a late finalize after an admin-abort writes NO side effects.

    AG3-139: a foreign in-flight claim is never taken over via CAS -- an
    orphaned/stuck claim ends ONLY via an explicit
    ``admin_abort_inflight_operation`` (or the AG3-138 startup reconciliation).
    When owner A's dispatch is stuck and an operator admin-aborts A's claim
    (bumping the fencing epoch, AC4), A's late finalize CAS affects ZERO rows
    (status is no longer ``claimed`` AND the epoch changed), so A materializes NO
    binding, NO locks and NO events. A's late return surfaces the aborted
    terminal row verbatim (AG3-138 AC5, FK-91 §91.1a Rule 17: an ``aborted``
    result is never rewritten to ``replayed``).
    """
    state = _RepoState()
    _resolvable_standard_ctx(state)
    clock = _Clock(datetime(2026, 6, 7, 10, 0, tzinfo=UTC))
    a_token = _owner_token("A")
    op_id = "op-abort-loser"
    request = _setup_request(op_id)

    # A wins the claim, then is held mid-dispatch (seed A's live claim placeholder
    # directly, simulating A stuck mid-dispatch).
    a_claimed_at = clock()
    placeholder = ControlPlaneOperationRecord(
        op_id=op_id,
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        session_id="sess-001",
        operation_kind="phase_start",
        phase="setup",
        status="claimed",
        response_payload={},
        created_at=a_claimed_at,
        updated_at=a_claimed_at,
        claimed_by=a_token,
        claimed_at=a_claimed_at,
        operation_epoch=1,
    )
    state.operations[op_id] = placeholder

    # An operator admin-aborts A's stuck claim (the AG3-138 end-way): bumps the
    # fencing epoch and clears the owner (AC4).
    repo = _repository(state)
    abort_now = datetime(2026, 6, 7, 10, 10, tzinfo=UTC)
    abort_result = ControlPlaneMutationResult(
        status="aborted",
        op_id=op_id,
        operation_kind="phase_start",
        run_id="run-100",
        phase="setup",
        edge_bundle=None,
        phase_dispatch=None,
        admin_note="admin_abort_inflight_operation by test: reason='stuck dispatch'.",
    )
    assert (
        repo.admin_abort_operation(
            op_id=op_id,
            status="aborted",
            response_payload=abort_result.model_dump(mode="json"),
            now=abort_now,
        )
        is True
    )
    assert state.operations[op_id].status == "aborted"
    assert state.operations[op_id].claimed_by is None
    assert state.operations[op_id].operation_epoch == 2

    # A finally returns to finalize its (now-aborted) claim. Its CAS affects zero
    # rows, so it materializes NOTHING and surfaces the aborted row verbatim.
    a_service = ControlPlaneRuntimeService(
        repository=repo,
        phase_dispatcher=_StubDispatcher(_admitted_dispatch()),  # type: ignore[arg-type]
        now_fn=clock,
        token_factory=_TokenSequence("A"),
    )
    a_result = a_service._finalize_start_phase(  # noqa: SLF001 -- drive the late path
        run_id="run-100",
        phase="setup",
        request=request,
        owner_token=a_token,
        owner_claimed_at=a_claimed_at.isoformat(),
        owner_operation_epoch=1,
        phase_dispatch=_admitted_dispatch(),
        # AG3-142: A's original dispatch was a genuinely fresh setup (no active
        # ownership record exists for run-100 in this test) -- mints, mirroring
        # what the real ``_start_phase_after_claim`` would have computed before
        # the admin-abort raced it. The claim-CAS loss below (operation_epoch
        # bumped by the abort) means the ownership INSERT is never reached
        # either -- the fake's ``_still_owned`` gate runs first.
        mints_ownership_record=True,
        # AG3-143: mirrors what ``_start_phase_after_claim`` would have formed
        # for the same genuinely-fresh setup before the digest is even a
        # candidate for insertion -- the claim-CAS loss below means this,
        # like ``ownership_record_to_insert``, is never reached either.
        execution_contract_digest="a" * 64,
    )

    assert a_result.status == "aborted", (
        "the late finalize surfaces the aborted row verbatim, never 'replayed'"
    )
    # NO side effects were materialized by A.
    assert "sess-001" not in state.bindings
    assert ("tenant-a", "AG3-100", "run-100", "story_execution") not in state.locks
    assert state.events == []
    # The aborted terminal op is untouched.
    assert state.operations[op_id].status == "aborted"


# ---------------------------------------------------------------------------
# ERROR-2 (#2): fresh-setup-start is RUN-scoped, not story-scoped
# ---------------------------------------------------------------------------


def test_new_run_setup_with_only_old_run_evidence_is_fresh_and_rejected() -> None:
    """ERROR-2 (#2): run-NEW setup is FRESH (guard fires) despite run-OLD evidence.

    A new run's setup whose ``StoryContext`` is unresolvable (admission cannot be
    evaluated) and that carries ONLY run-OLD evidence (a committed setup start +
    binding for run-OLD of the SAME story) must be classified FRESH -> the pre-start
    Approved+READY guard fires -> fail-closed REJECTED. The OLD-run evidence must
    NOT make run-NEW "not fresh" (the FAIL-OPEN this fix closes).
    """
    state = _RepoState()  # no story_contexts entry => dispatch returns None
    # Only run-OLD evidence: a committed setup start + a binding for run-OLD.
    state.operations["op-old-start"] = _committed_op(
        op_id="op-old-start",
        run_id="run-OLD",
        operation_kind="phase_start",
        phase="setup",
    )
    _seed_admitted_run(state, run_id="run-OLD")
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.start_phase(
        run_id="run-NEW",
        phase="setup",
        request=_setup_request("op-new-run-setup"),
    )

    assert result.status == "rejected", "run-NEW with only old-run evidence is FRESH"
    assert result.edge_bundle is None
    assert result.phase_dispatch is not None
    assert result.phase_dispatch.dispatched is False
    # Fail-closed: nothing materialized, no op stored for run-NEW.
    assert "op-new-run-setup" not in state.operations
    # The run-OLD binding under sess-001 is for a DIFFERENT run -> not run-NEW
    # evidence; it is left untouched.
    assert state.bindings["sess-001"].run_id == "run-OLD"


def test_run_mismatch_fences_out_before_the_dispatcher_is_ever_consulted() -> None:
    """AG3-142 (SOLL-015): a RUN_MISMATCH is fenced OUT before dispatch runs at all.

    The reset-escalation hazard, exercised through the resolvable-ctx path (where
    the real dispatcher would otherwise run): a story whose OLD run left an
    ACTIVE run-ownership record gets a NEW run posting setup. AG3-142 raises the
    ownership check ahead of the pre-start guard entirely: the story's active
    record belongs to run-OLD, not run-NEW, so ``_evaluate_run_admission``
    classifies this ``RUN_MISMATCH`` and the runtime rejects fail-closed WITHOUT
    ever invoking the dispatcher (unlike the pre-AG3-142 wiring, which threaded
    ``run_admitted=False`` into the dispatcher's own pre-start guard). Either way
    the OLD run's record must NEVER flip run-NEW to admitted, and nothing is
    materialized for run-NEW.
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
        project_root=Path("T:/projects/tenant-a"),
    )
    # Only run-OLD evidence exists: the story's ACTIVE ownership record.
    _seed_admitted_run(state, run_id="run-OLD")
    # The stub would record ``run_admitted`` if ever consulted; AG3-142's early
    # RUN_MISMATCH fence means it never is.
    dispatcher = _StubDispatcher(
        _rejected_dispatch("StoryStatus is not Approved (Tor 1)."),
    )
    service = ControlPlaneRuntimeService(
        repository=_repository(state),
        phase_dispatcher=dispatcher,  # type: ignore[arg-type]
    )

    result = service.start_phase(
        run_id="run-NEW",
        phase="setup",
        request=_setup_request("op-new-run-resolvable"),
    )

    # The ownership fence rejected BEFORE the dispatcher was ever consulted.
    assert dispatcher.run_admitted_calls == []
    assert result.status == "rejected"
    assert "op-new-run-resolvable" not in state.operations
    assert state.bindings.get("sess-001") is not None  # the OLD run's binding only
    assert state.bindings["sess-001"].run_id == "run-OLD"


def test_runtime_threads_run_admitted_true_for_its_own_committed_start() -> None:
    """ERROR-1 / AG3-142: an admitted run gets ``run_admitted=True`` threaded in.

    When THIS run already has an active run-ownership record (record-based
    admission, AG3-142), the runtime threads ``run_admitted=True`` so the
    dispatcher does NOT re-guard it.
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
        project_root=Path("T:/projects/tenant-a"),
    )
    _seed_admitted_run(state, run_id="run-100", seed_binding=False)
    dispatcher = _StubDispatcher(_admitted_dispatch())
    service = ControlPlaneRuntimeService(
        repository=_repository(state),
        phase_dispatcher=dispatcher,  # type: ignore[arg-type]
    )

    result = service.start_phase(
        run_id="run-100",
        phase="setup",
        request=_setup_request("op-readmit-this-run"),
    )

    assert dispatcher.run_admitted_calls == [True]
    assert result.status == "committed"


def test_new_run_setup_with_its_own_committed_start_is_not_fresh() -> None:
    """ERROR-2 (#2) / AG3-142: a run with its OWN active record is not re-guarded.

    When THIS run already has an active run-ownership record (record-based
    admission), the setup start is NOT fresh, so even an unresolvable ctx does
    NOT re-fire the fresh-setup rejection -- it keeps the AG3-018
    fail-closed-to-standard path (admitted run, no double guard).
    """
    state = _RepoState()  # unresolvable ctx => dispatch returns None
    _seed_admitted_run(state, run_id="run-100", seed_binding=False)
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.start_phase(
        run_id="run-100",
        phase="setup",
        request=_setup_request("op-not-fresh-setup"),
    )

    # Not fresh -> no fresh-setup rejection; the run was already admitted, so the
    # AG3-018 fail-closed-to-standard materialization runs and commits.
    assert result.status == "committed"
    assert result.edge_bundle is not None
    assert result.edge_bundle.current.operating_mode == "story_execution"


# ---------------------------------------------------------------------------
# WARNING-4 (#4): a naive / malformed claimed_at never crashes; AG3-139: it is
# never a takeover trigger either (there is no expiry judgement left at all).
# ---------------------------------------------------------------------------


def test_naive_or_malformed_claimed_at_foreign_claim_is_rejected_not_taken_over() -> (
    None
):
    """AG3-139: a foreign claim with a NAIVE ``claimed_at`` is still rejected.

    A ``claimed`` row whose ``claimed_at`` is tz-NAIVE (e.g. an imported/foreign
    write) must NOT crash. Previously such a row was judged EXPIRED (older than
    the wall-clock TTL) and taken over via CAS; AG3-139 removed that
    interpretation entirely -- a claim's age/format is never evaluated, so a
    foreign ``claimed`` row is ALWAYS a fail-closed rejection regardless of the
    shape of its ``claimed_at``.
    """
    state = _RepoState()
    _resolvable_standard_ctx(state)
    naive_old = datetime(2026, 6, 7, 9, 0)  # tz-NAIVE, far in the "past"
    state.operations["op-naive-claim"] = ControlPlaneOperationRecord(
        op_id="op-naive-claim",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        session_id="sess-001",
        operation_kind="phase_start",
        phase="setup",
        status="claimed",
        response_payload={},
        created_at=naive_old,
        updated_at=naive_old,
        claimed_by="owner-crashed-naive",
        claimed_at=naive_old,
    )
    clock = _Clock(datetime(2026, 6, 7, 10, 0, tzinfo=UTC))
    dispatcher = _StubDispatcher(_admitted_dispatch())
    service = _claim_service(state, token="new-owner", clock=clock, dispatcher=dispatcher)

    result = service.start_phase(
        run_id="run-100", phase="setup", request=_setup_request("op-naive-claim")
    )

    assert result.status == "rejected"
    assert dispatcher.calls == [], "a foreign claim must never be dispatched into"
    assert state.operations["op-naive-claim"].claimed_by == "owner-crashed-naive"
    assert state.operations["op-naive-claim"].status == "claimed"


def test_malformed_claimed_at_via_mapper_maps_to_none() -> None:
    """AG3-139: an unparseable claimed_at maps to None (no audit instant), no crash."""
    from agentkit.backend.state_backend.persistence_mappers import control_plane_op_row_to_record

    row = {
        "op_id": "op-bad-claimed-at",
        "project_key": "tenant-a",
        "story_id": "AG3-100",
        "run_id": "run-100",
        "session_id": "sess-001",
        "operation_kind": "phase_start",
        "phase": "setup",
        "status": "claimed",
        "response_json": "{}",
        "created_at": "2026-06-07T10:00:00+00:00",
        "updated_at": "2026-06-07T10:00:00+00:00",
        "claimed_by": "owner-x",
        "claimed_at": "not-a-timestamp",
    }

    record = control_plane_op_row_to_record(row)

    # Malformed claim instant -> None (no audit instant), never a raise.
    assert record.claimed_at is None


def test_aware_non_utc_claimed_at_is_normalized_to_utc() -> None:
    """WARNING-4 (#4): an aware non-UTC claimed_at is converted to aware UTC."""
    from agentkit.backend.state_backend.persistence_mappers import control_plane_op_row_to_record

    row = {
        "op_id": "op-offset-claimed-at",
        "project_key": "tenant-a",
        "story_id": "AG3-100",
        "run_id": "run-100",
        "session_id": "sess-001",
        "operation_kind": "phase_start",
        "phase": "setup",
        "status": "claimed",
        "response_json": "{}",
        "created_at": "2026-06-07T12:00:00+02:00",
        "updated_at": "2026-06-07T12:00:00+02:00",
        "claimed_by": "owner-x",
        "claimed_at": "2026-06-07T12:00:00+02:00",
    }

    record = control_plane_op_row_to_record(row)

    assert record.claimed_at is not None
    assert record.claimed_at.tzinfo is not None
    assert record.claimed_at.utcoffset() == timedelta(0)
    assert record.claimed_at == datetime(2026, 6, 7, 10, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# WARNING-5 (#5): the owner token is validated at the seam (no cross-match)
# ---------------------------------------------------------------------------


def test_invalid_owner_token_is_rejected_at_the_seam() -> None:
    """WARNING-5 (#5): an empty / non-UUID-shaped owner token is rejected fail-closed."""
    from agentkit.backend.exceptions import ConfigError

    state = _RepoState()
    _resolvable_standard_ctx(state)

    for bad_token in ("", "   ", "owner-A", "not-a-uuid", "owner-"):
        service = ControlPlaneRuntimeService(
            repository=_repository(state),
            phase_dispatcher=_StubDispatcher(_admitted_dispatch()),  # type: ignore[arg-type]
            token_factory=lambda token=bad_token: token,
        )
        with pytest.raises(ConfigError, match="owner token is invalid"):
            service.start_phase(
                run_id="run-100",
                phase="setup",
                request=_setup_request(f"op-bad-token-{bad_token or 'empty'}"),
            )
    # No op was ever claimed/committed under an invalid token.
    assert state.operations == {}


def test_valid_uuid_shaped_owner_token_is_accepted() -> None:
    """WARNING-5 (#5): a valid UUID-shaped token (bare or owner-prefixed) is accepted."""
    import uuid as _uuid

    state = _RepoState()
    _resolvable_standard_ctx(state)
    bare_uuid = _uuid.uuid4().hex
    service = ControlPlaneRuntimeService(
        repository=_repository(state),
        phase_dispatcher=_StubDispatcher(_admitted_dispatch()),  # type: ignore[arg-type]
        token_factory=lambda: bare_uuid,
    )

    result = service.start_phase(
        run_id="run-100", phase="setup", request=_setup_request("op-valid-bare-uuid")
    )

    assert result.status == "committed"


def test_distinct_claims_cannot_cross_match_on_ownership() -> None:
    """WARNING-5 (#5): two distinct owner tokens cannot cross-match a foreign claim.

    With unique, UUID-shaped tokens, owner A's ownership-scoped release/finalize CAS
    can never match owner B's live claim -- B's claim row is untouched.
    """
    state = _RepoState()
    repo = _repository(state)
    clock = _Clock(datetime(2026, 6, 7, 10, 0, tzinfo=UTC))
    a_token = _owner_token("A")
    b_token = _owner_token("B")
    assert a_token != b_token

    # B holds the live claim.
    state.operations["op-cross"] = ControlPlaneOperationRecord(
        op_id="op-cross",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        session_id="sess-001",
        operation_kind="phase_start",
        phase="setup",
        status="claimed",
        response_payload={},
        created_at=clock(),
        updated_at=clock(),
        claimed_by=b_token,
        claimed_at=clock(),
    )

    # A's release is a no-op (distinct token) -> B's claim survives.
    repo.release_operation("op-cross", owner_token=a_token)
    assert state.operations["op-cross"].claimed_by == b_token
    # A's finalize-start-phase is also a no-op and writes NO side effects.
    a_terminal = ControlPlaneOperationRecord(
        op_id="op-cross",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        session_id="sess-001",
        operation_kind="phase_start",
        phase="setup",
        status="committed",
        response_payload={"forged": "by-A"},
        created_at=clock(),
        updated_at=clock(),
    )
    assert (
        repo.finalize_start_phase(
            a_terminal, owner_token=a_token, binding=None, locks=(), events=()
        )
        is False
    )
    assert state.operations["op-cross"].claimed_by == b_token
    assert state.operations["op-cross"].status == "claimed"
    assert state.bindings == {}
    assert state.events == []


# ---------------------------------------------------------------------------
# AG3-138 — admin_abort, operation_epoch fence, repair mutation-lock
# ---------------------------------------------------------------------------


def _admin_abort_request(reason: str = "hung operation") -> AdminAbortRequest:
    return AdminAbortRequest(
        session_id="admin-sess",
        principal_type="admin_service",
        reason=reason,
    )


def _seed_live_claim(
    state: _RepoState,
    *,
    op_id: str,
    story_id: str = "AG3-100",
    run_id: str = "run-100",
    operation_epoch: int = 1,
    backend_instance_id: str = "inst-me",
    instance_incarnation: int = 1,
) -> None:
    """Seed a live ``claimed`` in-flight operation (the admin-abort target)."""
    now = datetime(2026, 7, 2, 11, 0, tzinfo=UTC)
    state.operations[op_id] = ControlPlaneOperationRecord(
        op_id=op_id,
        project_key="tenant-a",
        story_id=story_id,
        run_id=run_id,
        session_id="sess-001",
        operation_kind="phase_start",
        phase="implementation",
        status="claimed",
        response_payload={},
        created_at=now,
        updated_at=now,
        claimed_by="owner-live",
        claimed_at=now,
        operation_epoch=operation_epoch,
        backend_instance_id=backend_instance_id,
        instance_incarnation=instance_incarnation,
        declared_serialization_scope="tenant-a:AG3-100",
    )


def test_admin_abort_of_live_claim_returns_aborted_and_bumps_epoch() -> None:
    """AC6: admin-abort of a server-owned live claim -> aborted, epoch bumped."""
    state = _RepoState()
    _seed_live_claim(state, op_id="op-abort-1", operation_epoch=1)
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.admin_abort_inflight_operation("op-abort-1", _admin_abort_request())

    assert result.status == "aborted"
    assert result.admin_note is not None
    assert "admin_abort_inflight_operation" in result.admin_note
    stored = state.operations["op-abort-1"]
    assert stored.status == "aborted"
    assert stored.operation_epoch == 2  # bumped for the epoch fence


def test_admin_abort_unknown_op_raises_not_found() -> None:
    """AC6: an unknown op_id -> OperationNotFoundError (HTTP 404)."""
    state = _RepoState()
    service = ControlPlaneRuntimeService(repository=_repository(state))
    with pytest.raises(OperationNotFoundError):
        service.admin_abort_inflight_operation("op-missing", _admin_abort_request())


def test_admin_abort_terminal_op_raises_not_abortable() -> None:
    """AC6: a terminal (non-claimed) op -> OperationNotAbortableError (HTTP 409)."""
    state = _RepoState()
    now = datetime(2026, 7, 2, 11, 0, tzinfo=UTC)
    state.operations["op-done"] = ControlPlaneOperationRecord(
        op_id="op-done",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        session_id="sess-001",
        operation_kind="phase_start",
        phase="setup",
        status="committed",
        response_payload={},
        created_at=now,
        updated_at=now,
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))
    with pytest.raises(OperationNotAbortableError):
        service.admin_abort_inflight_operation("op-done", _admin_abort_request())


def test_admin_abort_with_partial_writes_goes_to_repair() -> None:
    """AC5/IMPL-005: an abort target with engine writes -> repair, not aborted."""
    state = _RepoState()
    _seed_live_claim(state, op_id="op-abort-repair", story_id="AG3-100", run_id="run-100")
    #: An engine write persisted at the claim's own claimed_at (>= since) -> detected.
    state.engine_writes["AG3-100"] = datetime(2026, 7, 2, 11, 0, tzinfo=UTC)
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.admin_abort_inflight_operation(
        "op-abort-repair", _admin_abort_request()
    )

    assert result.status == "repair"
    assert state.operations["op-abort-repair"].status == "repair"


def test_late_executor_finalize_after_abort_fails_epoch_fence() -> None:
    """AC4: a finalize with a stale operation_epoch after an admin-abort is fenced."""
    state = _RepoState()
    _seed_live_claim(state, op_id="op-late", operation_epoch=1)
    ops = _FakeOps(state)

    service = ControlPlaneRuntimeService(repository=_repository(state))
    service.admin_abort_inflight_operation("op-late", _admin_abort_request())
    assert state.operations["op-late"].status == "aborted"

    # The abort cleared claimed_by/status, so a late finalize with the OLD epoch
    # (1) and the old owner token matches nothing: the fence holds deterministically.
    late_terminal = ControlPlaneOperationRecord(
        op_id="op-late",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        session_id="sess-001",
        operation_kind="phase_start",
        phase="implementation",
        status="committed",
        response_payload={"forged": "late"},
        created_at=state.operations["op-late"].created_at,
        updated_at=datetime(2026, 7, 2, 12, 0, tzinfo=UTC),
    )
    applied = ops.finalize(
        late_terminal,
        owner_token="owner-live",
        owner_claimed_at=None,
        owner_operation_epoch=1,
    )
    assert applied is False
    assert state.operations["op-late"].status == "aborted"
    assert state.operations["op-late"].response_payload != {"forged": "late"}


def test_get_operation_surfaces_repair_state_verbatim() -> None:
    """AC5: GET operations/{op_id} shows the true repair state (not 'replayed')."""
    state = _RepoState()
    _seed_live_claim(state, op_id="op-visible-repair", run_id="run-100")
    state.engine_writes["AG3-100"] = datetime(2026, 7, 2, 11, 0, tzinfo=UTC)
    service = ControlPlaneRuntimeService(repository=_repository(state))
    service.admin_abort_inflight_operation("op-visible-repair", _admin_abort_request())

    view = service.get_operation("op-visible-repair")

    assert view is not None
    assert view.status == "repair"  # NOT rewritten to 'replayed'
    assert view.admin_note is not None


def test_mutating_dispatch_against_story_in_repair_is_rejected() -> None:
    """AC10 negative path: a mutating start against a repair-locked story -> 409."""
    state = _RepoState()
    _resolvable_standard_ctx(state)
    now = datetime(2026, 7, 2, 11, 0, tzinfo=UTC)
    state.operations["op-repair-open"] = ControlPlaneOperationRecord(
        op_id="op-repair-open",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-old",
        session_id="sess-001",
        operation_kind="phase_start",
        phase="implementation",
        status="repair",
        response_payload={
            "status": "repair",
            "op_id": "op-repair-open",
            "operation_kind": "phase_start",
        },
        created_at=now,
        updated_at=now,
    )
    service = ControlPlaneRuntimeService(
        repository=_repository(state),
        phase_dispatcher=_StubDispatcher(_admitted_dispatch()),  # type: ignore[arg-type]
    )

    result = service.start_phase(
        run_id="run-new", phase="setup", request=_setup_request("op-new-mut")
    )

    assert result.status == "rejected"
    assert result.edge_bundle is None
    assert result.phase_dispatch is not None
    assert result.error_code == "repair_lock_required"
    assert "reconcile/repair state" in (result.phase_dispatch.rejection_reason or "")
    assert "op-new-mut" not in state.operations


def test_mutating_dispatch_against_unreconciled_takeover_is_rejected_distinctly() -> None:
    state = _RepoState()
    _resolvable_standard_ctx(state)
    _seed_admitted_run(state, run_id="run-100", session_id="sess-001")
    state.takeover_transfers.append(
        TakeoverTransferRecord(
            project_key="tenant-a",
            story_id="AG3-100",
            run_id="run-100",
            ownership_epoch=1,
            repo_id="backend",
            takeover_base_sha="abc123",
            last_push_at=datetime(2026, 4, 22, 10, 5, tzinfo=UTC),
            push_lag_hint=None,
            base_quality="verified_pushed",
            challenge_ref="challenge-1",
            confirm_ref="confirm-1",
        )
    )
    service = ControlPlaneRuntimeService(
        repository=_repository(state),
        phase_dispatcher=_StubDispatcher(_admitted_dispatch()),  # type: ignore[arg-type]
    )

    result = service.start_phase(
        run_id="run-new", phase="setup", request=_setup_request("op-takeover-block")
    )

    assert result.status == "rejected"
    assert result.edge_bundle is None
    assert result.error_code == "takeover_reconcile_required"
    assert result.phase_dispatch is not None
    assert "unreconciled takeover transfer" in (
        result.phase_dispatch.rejection_reason or ""
    )
    assert "op-takeover-block" not in state.operations


def test_repair_lock_is_reversible_via_admin_abort_resolve_service_path() -> None:
    """AC10: the repair mutation-lock has a PRODUCTIVE exit via a real service path.

    The exit is NOT a fake state edit: the repair is resolved by invoking the
    productive ``admin_abort_inflight_operation`` service path against the open
    ``repair`` operation, which CAS-transitions it to ``resolved``. Because the
    story-scoped lock is a pure function of an OPEN ``repair`` record
    (``has_open_repair_for_story``), that transition lifts the lock and re-admits a
    fresh mutating start. This proves there IS a productive way out of repair, so
    even an over-conservative repair can never be a permanent story deadlock (E1/E2).
    """
    state = _RepoState()
    _resolvable_standard_ctx(state)
    now = datetime(2026, 7, 2, 11, 0, tzinfo=UTC)
    state.operations["op-repair-open"] = ControlPlaneOperationRecord(
        op_id="op-repair-open",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-old",
        session_id="sess-001",
        operation_kind="phase_start",
        phase="implementation",
        status="repair",
        response_payload={"status": "repair", "op_id": "op-repair-open"},
        created_at=now,
        updated_at=now,
    )
    service = ControlPlaneRuntimeService(
        repository=_repository(state),
        phase_dispatcher=_StubDispatcher(_admitted_dispatch()),  # type: ignore[arg-type]
    )

    # (1) while the repair is open, a fresh mutating start is rejected.
    locked = service.start_phase(
        run_id="run-new", phase="setup", request=_setup_request("op-locked")
    )
    assert locked.status == "rejected"
    assert "op-locked" not in state.operations

    # (2) resolve the repair via the REAL service path (admin-abort of the repair op).
    resolved = service.admin_abort_inflight_operation(
        "op-repair-open", _admin_abort_request()
    )
    assert resolved.status == "resolved"
    assert resolved.admin_note is not None
    assert state.operations["op-repair-open"].status == "resolved"

    # (3) the same story's fresh start now commits again -- no deadlock.
    unlocked = service.start_phase(
        run_id="run-new", phase="setup", request=_setup_request("op-after-repair")
    )
    assert unlocked.status == "committed"
    assert "op-after-repair" in state.operations


def test_admin_abort_of_resolved_op_is_not_abortable() -> None:
    """AC6: a second admin-abort of an already-``resolved`` op -> 409 (idempotent)."""
    state = _RepoState()
    now = datetime(2026, 7, 2, 11, 0, tzinfo=UTC)
    state.operations["op-resolved"] = ControlPlaneOperationRecord(
        op_id="op-resolved",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        session_id="sess-001",
        operation_kind="phase_start",
        phase="implementation",
        status="resolved",
        response_payload={"status": "resolved", "op_id": "op-resolved"},
        created_at=now,
        updated_at=now,
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))
    with pytest.raises(OperationNotAbortableError):
        service.admin_abort_inflight_operation("op-resolved", _admin_abort_request())


def test_claim_stamps_instance_identity_and_operation_epoch() -> None:
    """AC3: every newly-acquired claim carries the instance identity + epoch."""
    identity = BackendInstanceIdentityRecord(
        backend_instance_id="inst-explicit",
        instance_incarnation=7,
        updated_at=datetime(2026, 7, 2, 12, 0, tzinfo=UTC),
    )
    placeholder = _build_claim_placeholder(
        _setup_request("op-probe"),
        run_id="run-100",
        phase="setup",
        owner_token="owner-x",
        now=datetime(2026, 7, 2, 12, 0, tzinfo=UTC),
        instance_identity=identity,
    )
    assert placeholder.backend_instance_id == "inst-explicit"
    assert placeholder.instance_incarnation == 7
    assert placeholder.operation_epoch == 1
    assert placeholder.declared_serialization_scope == "tenant-a:AG3-100"
    assert placeholder.status == "claimed"


def test_default_store_resolves_identity_from_store_never_invents_it() -> None:
    """A default-store service resolves its identity from the authoritative store.

    AG3-138 AC3 / trap (own vs foreign identity): the instance identity is never
    invented and never foreign -- it is resolved from the Postgres session-
    ownership store (``backend_instance_identity``), mirroring the class's
    ``_require_postgres_backend_on_first_use`` lazy-first-use pattern. When that
    store is unavailable (no Postgres backend configured) resolution fails CLOSED
    rather than stamping a fabricated identity onto a claim (K5, Postgres-only).
    The serving path never hits this lazily: ``serve_control_plane`` runs the
    pre-serve startup hook (identity resolution + orphan reconciliation) before
    the listener accepts any request (AC1/AC9), so the identity is bound there.
    """
    from agentkit.backend.exceptions import ConfigError

    service = ControlPlaneRuntimeService()
    # No Postgres backend configured here -> fail closed (K5), never a fabricated
    # identity.
    with pytest.raises(ConfigError, match="Postgres state backend"):
        service._current_instance_identity()


def test_di_service_binds_a_deterministic_identity_without_explicit_injection() -> None:
    """A DI-injected repository binds a deterministic identity in __init__.

    The test / alternative-wiring seam never needs Postgres to stamp claims: when
    a caller injects a repository but no explicit identity, a deterministic
    default identity is bound so the claim stamp stays well-formed (NOT a
    production fallback -- production uses the default store + startup hook).
    """
    state = _RepoState()
    service = ControlPlaneRuntimeService(repository=_repository(state))
    identity = service._current_instance_identity()
    assert identity.backend_instance_id.strip()
    assert identity.instance_incarnation >= 1


def test_custom_repository_without_push_barrier_port_fails_closed_for_push_gated_story() -> None:
    """AG3-147/ARCH-26: custom repository wiring must not skip the push barrier."""
    state = _RepoState()
    ctx = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
        project_root=Path("T:/projects/tenant-a"),
        participating_repos=["api"],
    )
    state.story_contexts[("tenant-a", "AG3-100")] = ctx
    service = ControlPlaneRuntimeService(repository=_repository(state))

    with pytest.raises(AssertionError, match="push_barrier_evidence"):
        service._collect_push_barrier_inputs(
            project_key="tenant-a",
            story_id="AG3-100",
            run_id="run-100",
        )


def test_injected_push_barrier_factory_is_used_and_memoized() -> None:
    """AG3-147/ARCH-26: the runtime consumes a DI factory, not bootstrap lookup."""

    class _Evidence:
        def collect_repo_inputs(self, **_kwargs: object) -> tuple[object, ...]:
            return ()

    evidence = _Evidence()
    calls = 0

    def _factory() -> _Evidence:
        nonlocal calls
        calls += 1
        return evidence

    service = ControlPlaneRuntimeService(push_barrier_evidence_factory=_factory)

    assert service._resolve_push_barrier_evidence(require_wired=True) is evidence
    assert service._resolve_push_barrier_evidence(require_wired=True) is evidence
    assert calls == 1


def test_push_barrier_factory_returning_none_fails_closed_for_push_gated_story() -> None:
    """AG3-147/ARCH-26: a None factory result must not skip a push-gated barrier."""
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
        project_root=Path("T:/projects/tenant-a"),
        participating_repos=["api"],
    )
    service = ControlPlaneRuntimeService(
        repository=_repository(state),
        push_barrier_evidence_factory=lambda: None,
    )

    with pytest.raises(AssertionError, match="push_barrier_evidence"):
        service._collect_push_barrier_inputs(
            project_key="tenant-a",
            story_id="AG3-100",
            run_id="run-100",
        )


def test_push_barrier_factory_returning_none_stays_unwired_when_not_required() -> None:
    """Non-push-gated boundaries may remain unwired, but None is not cached."""
    calls = 0

    def _factory() -> None:
        nonlocal calls
        calls += 1
        return None

    service = ControlPlaneRuntimeService(push_barrier_evidence_factory=_factory)

    assert service._resolve_push_barrier_evidence(require_wired=False) is None
    assert service._resolve_push_barrier_evidence(require_wired=False) is None
    assert calls == 2


# ---------------------------------------------------------------------------
# AG3-140 / Codex finding 3: op_id reuse with a DIFFERENT body must NOT replay
# the stored result -- it fails closed with ``409 idempotency_mismatch`` (the
# body-hash is stamped on the terminal/claim row and compared on replay). A
# reuse with the IDENTICAL body still replays. Covers a phase mutation AND a
# closure.
# ---------------------------------------------------------------------------


def _mismatch_phase_request(*, op_id: str, worktree_root: str) -> PhaseMutationRequest:
    return PhaseMutationRequest(
        project_key="tenant-a",
        story_id="AG3-100",
        session_id="sess-001",
        principal_type="orchestrator",
        worktree_roots=[worktree_root],
        op_id=op_id,
    )


def test_phase_start_reused_op_id_with_different_body_raises_mismatch() -> None:
    """A reused start op_id with a DIFFERENT body is 409 idempotency_mismatch (AG3-140).

    Codex finding 3: the phase-mutation idempotency path previously replayed the
    stored result by op_id ALONE, so a client reusing one op_id for a DIFFERENT
    request body got the wrong stored result. Now the stamped body-hash is
    compared: a different body (here different ``worktree_roots``) fails closed.
    """
    from agentkit.backend.story_context_manager.errors import IdempotencyMismatchError

    state = _RepoState()
    _resolvable_standard_ctx(state)
    service = _admitting_service(state)

    first = service.start_phase(
        run_id="run-100",
        phase="setup",
        request=_mismatch_phase_request(
            op_id="op-mismatch-phase-001", worktree_root="T:/worktrees/a"
        ),
    )
    assert first.status == "committed"

    with pytest.raises(IdempotencyMismatchError) as excinfo:
        service.start_phase(
            run_id="run-100",
            phase="setup",
            request=_mismatch_phase_request(
                op_id="op-mismatch-phase-001", worktree_root="T:/worktrees/DIFFERENT"
            ),
        )
    assert excinfo.value.detail["conflict"] == "body_hash_mismatch"
    assert excinfo.value.detail["op_id"] == "op-mismatch-phase-001"
    # The stored terminal row was NOT overwritten; no second op was created.
    assert len(state.operations) == 1


def test_phase_start_reused_op_id_with_identical_body_replays() -> None:
    """A reused start op_id with the IDENTICAL body still replays (no mismatch)."""
    state = _RepoState()
    _resolvable_standard_ctx(state)
    service = _admitting_service(state)
    request = _mismatch_phase_request(
        op_id="op-replay-phase-001", worktree_root="T:/worktrees/a"
    )

    first = service.start_phase(run_id="run-100", phase="setup", request=request)
    second = service.start_phase(run_id="run-100", phase="setup", request=request)

    assert first.status == "committed"
    assert second.status == "replayed"
    assert len(state.operations) == 1


def test_phase_complete_reused_op_id_with_different_body_raises_mismatch() -> None:
    """A reused complete op_id with a DIFFERENT body is 409 idempotency_mismatch.

    Exercises the ``_mutate_phase`` terminal-write / replay path (distinct from
    the claim-based start path): the same op_id reused for a different body fails
    closed rather than replaying the wrong stored result.
    """
    from agentkit.backend.story_context_manager.errors import IdempotencyMismatchError

    state = _RepoState()
    _resolvable_standard_ctx(state)
    _seed_admitted_run(state, run_id="run-100")
    service = _admitting_service(state)

    first = service.complete_phase(
        run_id="run-100",
        phase="implementation",
        request=_mismatch_phase_request(
            op_id="op-mismatch-complete-001", worktree_root="T:/worktrees/a"
        ),
    )
    assert first.status == "committed"

    with pytest.raises(IdempotencyMismatchError) as excinfo:
        service.complete_phase(
            run_id="run-100",
            phase="implementation",
            request=_mismatch_phase_request(
                op_id="op-mismatch-complete-001",
                worktree_root="T:/worktrees/DIFFERENT",
            ),
        )
    assert excinfo.value.detail["conflict"] == "body_hash_mismatch"


def _closure_request(*, op_id: str, detail: dict[str, object]) -> ClosureCompleteRequest:
    return ClosureCompleteRequest(
        project_key="tenant-a",
        story_id="AG3-100",
        session_id="sess-001",
        op_id=op_id,
        detail=detail,
    )


def test_closure_reused_op_id_with_different_body_raises_mismatch() -> None:
    """A reused closure op_id with a DIFFERENT body is 409 idempotency_mismatch."""
    from agentkit.backend.story_context_manager.errors import IdempotencyMismatchError

    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.FAST,
    )
    _seed_admitted_run(state, run_id="run-100")
    service = ControlPlaneRuntimeService(repository=_repository(state))

    first = service.complete_closure(
        run_id="run-100",
        request=_closure_request(op_id="op-mismatch-closure-001", detail={"k": "v1"}),
    )
    assert first.status == "committed"

    with pytest.raises(IdempotencyMismatchError) as excinfo:
        service.complete_closure(
            run_id="run-100",
            request=_closure_request(
                op_id="op-mismatch-closure-001", detail={"k": "DIFFERENT"}
            ),
        )
    assert excinfo.value.detail["conflict"] == "body_hash_mismatch"
    assert excinfo.value.detail["op_id"] == "op-mismatch-closure-001"
    assert len(state.operations) == 1


def test_closure_reused_op_id_with_identical_body_replays() -> None:
    """A reused closure op_id with the IDENTICAL body still replays (no mismatch)."""
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.FAST,
    )
    _seed_admitted_run(state, run_id="run-100")
    service = ControlPlaneRuntimeService(repository=_repository(state))
    request = _closure_request(op_id="op-replay-closure-001", detail={"k": "v1"})

    first = service.complete_closure(run_id="run-100", request=request)
    second = service.complete_closure(run_id="run-100", request=request)

    assert first.status == "committed"
    assert second.status == "replayed"
    assert len(state.operations) == 1


# ---------------------------------------------------------------------------
# AG3-142: ownership-fencing of the regime paths (SOLL-014/015/016/017/018/019,
# SOLL-042, IMPL-019, IMPL-021). Acceptance-criteria-targeted coverage.
# ---------------------------------------------------------------------------


def test_admission_never_calls_has_committed_operation_for_run() -> None:
    """AC2 code-proof: the retired positive committed-op heuristic is NEVER
    consulted by admission any more (IMPL-021, SOLL-014). Wraps the fake's
    ``has_committed_for_run`` with a call-counting spy and drives every one of
    the five regime paths through a real admitted flow; the spy must stay at
    zero calls throughout.
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    calls: list[tuple[str, str, str]] = []
    repo = _repository(state)
    original = repo.has_committed_operation_for_run

    def _spy(project_key: str, story_id: str, run_id: str) -> bool:
        calls.append((project_key, story_id, run_id))
        return original(project_key, story_id, run_id)

    from dataclasses import replace

    repo = replace(repo, has_committed_operation_for_run=_spy)
    _seed_admitted_run(state, run_id="run-100")
    service = ControlPlaneRuntimeService(repository=repo)

    service.complete_phase(
        run_id="run-100", phase="implementation", request=_phase_request("op-c1")
    )
    service.fail_phase(
        run_id="run-100", phase="implementation", request=_phase_request("op-f1")
    )
    service.complete_closure(
        run_id="run-100",
        request=_closure_request(op_id="op-cl1", detail={}),
    )

    assert calls == [], (
        "admission must never consult has_committed_operation_for_run "
        "(IMPL-021: the positive committed-op heuristic is retired, AC2)"
    )


def _seed_historical_record(
    state: _RepoState,
    *,
    run_id: str,
    status: OwnershipStatus,
    session_id: str = "sess-001",
    project_key: str = "tenant-a",
    story_id: str = "AG3-100",
) -> None:
    """Prepare a NON-active (historical) ownership record via the sanctioned
    AG3-137 single-writer surface (a direct insert, exactly how AG3-137's own
    tests / a real disown/reset writer would produce one) -- AC3: proves a
    historical record is audit-only and NEVER admission evidence.
    """
    state.insert_ownership(
        RunOwnershipRecord(
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            owner_session_id=session_id,
            ownership_epoch=1,
            status=status,
            acquired_via=OwnershipAcquisition.SETUP,
            acquired_at=datetime(2026, 4, 22, 10, 0, tzinfo=UTC),
            audit_ref=f"op-seed-{run_id}",
        ),
    )


@pytest.mark.parametrize(
    "status",
    [OwnershipStatus.ENDED, OwnershipStatus.RESET, OwnershipStatus.SPLIT, OwnershipStatus.CLOSED],
)
def test_historical_record_never_admits_complete_fail_closure_resume(
    status: OwnershipStatus,
) -> None:
    """AC3 (SOLL-014, historical_ownership_records_are_never_admission_evidence):
    a record with any status other than ``active`` is audit-only and never
    admits complete/fail/closure/resume -- deterministically rejected with NO
    side effects (no binding re-materialization, no locks, no events, no
    stored op).
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    _seed_historical_record(state, run_id="run-100", status=status)
    service = ControlPlaneRuntimeService(repository=_repository(state))

    completed = service.complete_phase(
        run_id="run-100", phase="implementation", request=_phase_request("op-c")
    )
    failed = service.fail_phase(
        run_id="run-100", phase="implementation", request=_phase_request("op-f")
    )
    closed = service.complete_closure(
        run_id="run-100", request=_closure_request(op_id="op-cl", detail={})
    )

    assert completed.status == "rejected"
    assert failed.status == "rejected"
    assert closed.status == "rejected"
    assert "op-c" not in state.operations
    assert "op-f" not in state.operations
    assert "op-cl" not in state.operations
    assert state.bindings == {}
    assert state.locks == {}
    assert state.events == []


def test_start_phase_ex_owner_rejected_with_ownership_transferred_payload() -> None:
    """AC4/AC6 path 1 (start_phase): a call from a session that is NOT the
    active record's owner is rejected fail-closed with the structured
    ``ownership_transferred`` payload, BEFORE the engine ever dispatches (no
    state written).
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    # The active record's owner is sess-OWNER; the caller is sess-001.
    _seed_admitted_run(
        state, run_id="run-100", session_id="sess-001", owner_session_id="sess-OWNER",
        seed_binding=False,
    )
    service = _admitting_service(state)

    result = service.start_phase(
        run_id="run-100",
        phase="implementation",
        request=_fast_request(),
    )

    assert result.status == "rejected"
    assert result.error_code == "ownership_transferred"
    assert result.ownership_conflict is not None
    assert result.ownership_conflict.new_owner_session_id == "sess-OWNER"
    assert result.ownership_conflict.new_ownership_epoch == 1
    assert "op-fast-001" not in state.operations
    assert state.bindings == {}
    assert state.locks == {}
    assert state.events == []


def test_complete_phase_ex_owner_rejected_with_ownership_transferred_payload() -> None:
    """AC4/AC6 path 2 (complete_phase): wrong session -> ex-owner rejection."""
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    _seed_admitted_run(
        state, run_id="run-100", session_id="sess-001", owner_session_id="sess-OWNER",
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.complete_phase(
        run_id="run-100", phase="implementation", request=_phase_request("op-complete-exowner")
    )

    assert result.status == "rejected"
    assert result.error_code == "ownership_transferred"
    assert result.ownership_conflict is not None
    assert result.ownership_conflict.new_owner_session_id == "sess-OWNER"
    assert "op-complete-exowner" not in state.operations
    assert state.locks == {}
    assert state.events == []


def test_fail_phase_ex_owner_rejected_with_ownership_transferred_payload() -> None:
    """AC4/AC6 path 3 (fail_phase): wrong session -> ex-owner rejection."""
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    _seed_admitted_run(
        state, run_id="run-100", session_id="sess-001", owner_session_id="sess-OWNER",
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.fail_phase(
        run_id="run-100", phase="implementation", request=_phase_request("op-fail-exowner")
    )

    assert result.status == "rejected"
    assert result.error_code == "ownership_transferred"
    assert result.ownership_conflict is not None
    assert result.ownership_conflict.new_owner_session_id == "sess-OWNER"
    assert "op-fail-exowner" not in state.operations
    assert state.locks == {}
    assert state.events == []


def test_complete_closure_ex_owner_rejected_with_ownership_transferred_payload() -> None:
    """AC4/AC6 path 5 (complete_closure): wrong session -> ex-owner rejection."""
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    _seed_admitted_run(
        state, run_id="run-100", session_id="sess-001", owner_session_id="sess-OWNER",
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.complete_closure(
        run_id="run-100",
        request=_closure_request(op_id="op-closure-exowner", detail={}),
    )

    assert result.status == "rejected"
    assert result.error_code == "ownership_transferred"
    assert result.ownership_conflict is not None
    assert result.ownership_conflict.new_owner_session_id == "sess-OWNER"
    assert "op-closure-exowner" not in state.operations
    assert state.locks == {}
    assert state.events == []


def test_resume_phase_ex_owner_rejected_with_ownership_transferred_payload() -> None:
    """AC4/AC6 path 4 (resume_phase): wrong session -> ex-owner rejection, and
    the engine's resume is NEVER invoked (no double resume, no state written).
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    _seed_admitted_run(
        state, run_id="run-100", session_id="sess-001", owner_session_id="sess-OWNER",
        seed_binding=False,
    )
    dispatcher = _StubDispatcher(_admitted_dispatch())
    service = ControlPlaneRuntimeService(
        repository=_repository(state),
        phase_dispatcher=dispatcher,  # type: ignore[arg-type]
    )

    result = service.resume_phase(
        run_id="run-100",
        phase="implementation",
        request=_phase_request("op-resume-exowner"),
    )

    assert result.status == "rejected"
    assert result.error_code == "ownership_transferred"
    assert result.ownership_conflict is not None
    assert result.ownership_conflict.new_owner_session_id == "sess-OWNER"
    # The dispatcher (and hence PipelineEngine.resume_phase) was never reached.
    assert dispatcher.calls == []
    assert "op-resume-exowner" not in state.operations


def test_get_operation_still_readable_for_ex_owner() -> None:
    """AC7 (FK-91 §91.1a Rule 17/18): reads stay allowed for a dismissed
    (ex-owner) session -- ``GET operations/{op_id}`` reconciles a PRIOR
    mutation regardless of the CURRENT ownership state.
    """
    state = _RepoState()
    _resolvable_standard_ctx(state)
    service = _admitting_service(state)
    created = service.start_phase(
        run_id="run-100",
        phase="setup",
        request=_setup_request("op-ex-owner-read"),
    )
    assert created.status == "committed"
    # Ownership moves on (a transfer, simulated by directly overwriting the
    # story's active record via a fresh insert after ending the old one --
    # the sanctioned single-writer surface): the caller who started the run
    # is no longer the owner.
    del state.ownership_records[("tenant-a", "AG3-100", "run-100")]
    state.insert_ownership(
        RunOwnershipRecord(
            project_key="tenant-a",
            story_id="AG3-100",
            run_id="run-100",
            owner_session_id="sess-NEW-OWNER",
            ownership_epoch=2,
            status=OwnershipStatus.ACTIVE,
            acquired_via=OwnershipAcquisition.TAKEOVER,
            acquired_at=datetime(2026, 4, 22, 11, 0, tzinfo=UTC),
            audit_ref="op-transfer",
        ),
    )

    replayed = service.get_operation("op-ex-owner-read")

    assert replayed is not None
    assert replayed.status == "replayed"
    assert replayed.op_id == "op-ex-owner-read"


def test_binding_record_contradiction_the_record_decides() -> None:
    """AC9 (SOLL-018/019): binding says session A owns run-100, the ACTIVE
    record says session B owns it -- the record decides: A's mutation is
    rejected, and the binding re-materialization path
    (``_mutate_phase``/``_plan_story_scoped_materialization``) is never
    reached for A.
    """
    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a",
        story_id="AG3-100",
        mode=WireStoryMode.STANDARD,
    )
    # Binding: session A ("sess-001") is bound to run-100.
    state.bindings["sess-001"] = SessionRunBindingRecord(
        session_id="sess-001",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-100",
        principal_type="orchestrator",
        worktree_roots=("T:/worktrees/ag3-100",),
        binding_version="1",
        updated_at=datetime(2026, 4, 22, 10, 0, tzinfo=UTC),
    )
    # Active record: session B ("sess-OWNER") owns run-100 (the contradiction).
    state.insert_ownership(
        RunOwnershipRecord(
            project_key="tenant-a",
            story_id="AG3-100",
            run_id="run-100",
            owner_session_id="sess-OWNER",
            ownership_epoch=1,
            status=OwnershipStatus.ACTIVE,
            acquired_via=OwnershipAcquisition.SETUP,
            acquired_at=datetime(2026, 4, 22, 10, 0, tzinfo=UTC),
            audit_ref="op-seed",
        ),
    )
    service = ControlPlaneRuntimeService(repository=_repository(state))

    result = service.complete_phase(
        run_id="run-100",
        phase="implementation",
        request=_phase_request("op-contradiction"),
    )

    assert result.status == "rejected"
    assert result.error_code == "ownership_transferred"
    assert result.ownership_conflict is not None
    assert result.ownership_conflict.new_owner_session_id == "sess-OWNER"
    # A's binding was NEVER re-materialized/overwritten -- it is untouched.
    assert state.bindings["sess-001"].binding_version == "1"
    assert "op-contradiction" not in state.operations
    assert state.locks == {}
    assert state.events == []


def test_committed_results_carry_the_accountability_ownership_epoch() -> None:
    """AC10 (SOLL-017): every committed regime result carries the
    ``ownership_epoch`` it was committed under -- ``1`` for the setup start
    that mints the record; the SAME epoch for the subsequent complete on the
    same run.
    """
    state = _RepoState()
    _resolvable_standard_ctx(state)
    service = _admitting_service(state)

    started = service.start_phase(
        run_id="run-100",
        phase="setup",
        request=_setup_request("op-acct-start"),
    )
    assert started.ownership_epoch == 1

    completed = service.complete_phase(
        run_id="run-100",
        phase="implementation",
        request=_phase_request("op-acct-complete"),
    )
    assert completed.ownership_epoch == 1

    # The lifecycle events materialized along the way also carry it (both the
    # setup start's AND the standard-story complete's re-materialization).
    created_events = [
        event for event in state.events if event.event_type == "session_run_binding_created"
    ]
    assert len(created_events) >= 1
    assert all(event.payload["ownership_epoch"] == 1 for event in created_events)


# ---------------------------------------------------------------------------
# AG3-142 (AC5, no TOCTOU): the COMMIT-TIME fence handlers -- distinct from the
# early-admission ex-owner path. These drive the exact race the fence closes:
# admission PASSES (the caller was the owner at its early check), but the
# co-transactional commit-time fence FAILS (a transfer landed in the window),
# so the store raises ``OwnershipFenceViolationError`` and the runtime's
# per-path ``except`` handler must surface the rich ex-owner rejection with NO
# state written and MY claims released. The store's actual FOR-UPDATE fence SQL
# is proven separately against real Postgres
# (``tests/integration/state_backend/test_ownership_fence_postgres.py`` +
# ``tests/integration/control_plane/test_ownership_fencing_pg.py``); these unit
# tests pin the RUNTIME handler wiring deterministically.
# ---------------------------------------------------------------------------


def _fence_violation_at_commit(
    project_key: str, story_id: str
) -> OwnershipFenceViolationError:
    """The exact error shape the real store's ``_enforce_ownership_fence_row``
    raises when a transfer landed between admission and commit."""
    del project_key, story_id
    return OwnershipFenceViolationError(
        "ownership fence violated at commit time (a takeover landed in the "
        "dispatch->commit window)",
        detail={
            "current_owner_session_id": "sess-NEW-OWNER",
            "current_ownership_epoch": 2,
            "transferred_at": "2026-04-22T11:00:00+00:00",
        },
    )


@pytest.mark.parametrize("operation_kind", ["phase_complete", "phase_fail"])
def test_complete_fail_commit_time_fence_violation_surfaces_ex_owner_rejection(
    operation_kind: str,
) -> None:
    """AC5 (commit-time, complete/fail): admission passes but the co-transactional
    fence fails at commit -> the runtime catches ``OwnershipFenceViolationError``
    and returns the rich ``ownership_transferred`` rejection with no state.
    """
    from dataclasses import replace

    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a", story_id="AG3-100", mode=WireStoryMode.STANDARD
    )
    _seed_admitted_run(state, run_id="run-100")

    def _commit_raises_fence(record: object, **_kwargs: object) -> None:
        raise _fence_violation_at_commit("tenant-a", "AG3-100")

    repo = replace(
        _repository(state), commit_operation_with_side_effects=_commit_raises_fence
    )
    service = ControlPlaneRuntimeService(repository=repo)

    method = service.complete_phase if operation_kind == "phase_complete" else service.fail_phase
    result = method(
        run_id="run-100",
        phase="implementation",
        request=_phase_request("op-race-cf"),
    )

    assert result.status == "rejected"
    assert result.error_code == "ownership_transferred"
    assert result.ownership_conflict is not None
    assert result.ownership_conflict.new_owner_session_id == "sess-NEW-OWNER"
    assert result.ownership_conflict.new_ownership_epoch == 2
    assert "op-race-cf" not in state.operations


def test_closure_commit_time_fence_violation_surfaces_ex_owner_rejection() -> None:
    """AC5 (commit-time, closure): admission passes, the commit fence fails ->
    the ex-owner rejection is surfaced and the object claim is released.
    """
    from dataclasses import replace

    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a", story_id="AG3-100", mode=WireStoryMode.STANDARD
    )
    _seed_admitted_run(state, run_id="run-100")

    def _commit_raises_fence(record: object, **_kwargs: object) -> None:
        raise _fence_violation_at_commit("tenant-a", "AG3-100")

    repo = replace(
        _repository(state), commit_operation_with_side_effects=_commit_raises_fence
    )
    service = ControlPlaneRuntimeService(repository=repo)

    result = service.complete_closure(
        run_id="run-100",
        request=_closure_request(op_id="op-race-closure", detail={}),
    )

    assert result.status == "rejected"
    assert result.error_code == "ownership_transferred"
    assert result.ownership_conflict is not None
    assert result.ownership_conflict.new_owner_session_id == "sess-NEW-OWNER"
    assert "op-race-closure" not in state.operations


def test_resume_commit_time_fence_violation_surfaces_ex_owner_rejection() -> None:
    """AC5 (commit-time, resume): admission passes, the ownership-CAS finalize's
    fence fails at commit -> the ex-owner rejection is surfaced, MY claims are
    released, and no op is stored.
    """
    from dataclasses import replace

    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a", story_id="AG3-100", mode=WireStoryMode.STANDARD
    )
    _seed_admitted_run(state, run_id="run-100", seed_binding=False)

    def _finalize_raises_fence(record: object, **_kwargs: object) -> bool:
        raise _fence_violation_at_commit("tenant-a", "AG3-100")

    repo = replace(_repository(state), finalize_start_phase=_finalize_raises_fence)
    service = ControlPlaneRuntimeService(
        repository=repo,
        phase_dispatcher=_StubDispatcher(_admitted_dispatch()),  # type: ignore[arg-type]
    )

    result = service.resume_phase(
        run_id="run-100",
        phase="implementation",
        request=_phase_request("op-race-resume"),
    )

    assert result.status == "rejected"
    assert result.error_code == "ownership_transferred"
    assert result.ownership_conflict is not None
    assert result.ownership_conflict.new_owner_session_id == "sess-NEW-OWNER"
    assert "op-race-resume" not in state.operations


def test_commit_time_fence_with_no_active_record_is_plain_rejection_not_transfer() -> None:
    """Fail-closed: a commit-time fence violation whose ``detail`` has no current
    owner (the story's active record vanished entirely) is a PLAIN rejection,
    NOT the ``ownership_transferred`` shape -- never a fabricated "new owner".
    """
    from dataclasses import replace

    state = _RepoState()
    state.story_contexts[("tenant-a", "AG3-100")] = _story_context(
        project_key="tenant-a", story_id="AG3-100", mode=WireStoryMode.STANDARD
    )
    _seed_admitted_run(state, run_id="run-100")

    def _commit_raises_empty_fence(record: object, **_kwargs: object) -> None:
        raise OwnershipFenceViolationError(
            "ownership fence violated: no active record at all",
            detail={
                "current_owner_session_id": None,
                "current_ownership_epoch": None,
                "transferred_at": None,
            },
        )

    repo = replace(
        _repository(state), commit_operation_with_side_effects=_commit_raises_empty_fence
    )
    service = ControlPlaneRuntimeService(repository=repo)

    result = service.complete_phase(
        run_id="run-100",
        phase="implementation",
        request=_phase_request("op-race-norecord"),
    )

    assert result.status == "rejected"
    assert result.error_code is None
    assert result.ownership_conflict is None
    assert "op-race-norecord" not in state.operations


def _service_with_real_setup_then_freeze(
    *,
    predecessor_op_id: str,
) -> tuple[_RepoState, ControlPlaneRuntimeService]:
    """Drive the real setup boundary, then activate the fake freeze read port."""

    state = _RepoState()
    _resolvable_standard_ctx(state)
    service = _admitting_service(state)
    predecessor = service.start_phase(
        run_id="run-100",
        phase="setup",
        request=_setup_request(predecessor_op_id),
    )
    assert predecessor.status == "committed"
    state.active_freeze = {
        "kind": "conflict_freeze",
        "freeze_reason": "test hard stop",
        "freeze_epoch": "1",
    }
    return state, service


def _assert_freeze_rejection_without_write(
    state: _RepoState,
    result: ControlPlaneMutationResult,
    *,
    op_id: str,
    baseline_operation_ids: set[str],
) -> None:
    assert result.status == "rejected"
    assert result.error_code == "story_frozen"
    assert result.freeze_conflict is not None
    assert result.freeze_conflict.kind == "conflict_freeze"
    assert set(state.operations) == baseline_operation_ids
    assert op_id not in state.operations
    active = state.load_active_ownership("tenant-a", "AG3-100")
    assert active is not None
    assert active.status is OwnershipStatus.ACTIVE


def test_freeze_blocks_start_boundary_after_real_setup_without_state_write() -> None:
    state, service = _service_with_real_setup_then_freeze(
        predecessor_op_id="op-freeze-start-predecessor"
    )
    baseline = set(state.operations)
    op_id = "op-freeze-start"

    result = service.start_phase(
        run_id="run-100",
        phase="implementation",
        request=_phase_request(op_id),
    )

    _assert_freeze_rejection_without_write(
        state, result, op_id=op_id, baseline_operation_ids=baseline
    )


def test_freeze_blocks_complete_boundary_after_real_setup_without_state_write() -> None:
    state, service = _service_with_real_setup_then_freeze(
        predecessor_op_id="op-freeze-complete-predecessor"
    )
    baseline = set(state.operations)
    op_id = "op-freeze-complete"

    result = service.complete_phase(
        run_id="run-100", phase="setup", request=_phase_request(op_id)
    )

    _assert_freeze_rejection_without_write(
        state, result, op_id=op_id, baseline_operation_ids=baseline
    )


def test_freeze_blocks_fail_boundary_after_real_setup_without_state_write() -> None:
    state, service = _service_with_real_setup_then_freeze(
        predecessor_op_id="op-freeze-fail-predecessor"
    )
    baseline = set(state.operations)
    op_id = "op-freeze-fail"

    result = service.fail_phase(
        run_id="run-100", phase="setup", request=_phase_request(op_id)
    )

    _assert_freeze_rejection_without_write(
        state, result, op_id=op_id, baseline_operation_ids=baseline
    )


def test_freeze_blocks_resume_boundary_after_real_setup_without_state_write() -> None:
    state, service = _service_with_real_setup_then_freeze(
        predecessor_op_id="op-freeze-resume-predecessor"
    )
    baseline = set(state.operations)
    op_id = "op-freeze-resume"

    result = service.resume_phase(
        run_id="run-100", phase="setup", request=_phase_request(op_id)
    )

    _assert_freeze_rejection_without_write(
        state, result, op_id=op_id, baseline_operation_ids=baseline
    )


def test_freeze_blocks_closure_boundary_after_real_setup_without_state_write() -> None:
    state, service = _service_with_real_setup_then_freeze(
        predecessor_op_id="op-freeze-closure-predecessor"
    )
    baseline = set(state.operations)
    op_id = "op-freeze-closure"

    result = service.complete_closure(
        run_id="run-100",
        request=_closure_request(op_id=op_id, detail={}),
    )

    _assert_freeze_rejection_without_write(
        state, result, op_id=op_id, baseline_operation_ids=baseline
    )
