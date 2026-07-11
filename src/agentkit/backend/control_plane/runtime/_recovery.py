"""Explicit human crash-recovery acquisition runtime block."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from agentkit.backend.control_plane import recovery as recovery_core
from agentkit.backend.control_plane.disown import build_disown_plan
from agentkit.backend.control_plane.models import ControlPlaneMutationResult
from agentkit.backend.control_plane.ownership import (
    INITIAL_OWNERSHIP_EPOCH,
    BindingRevocationReason,
    OwnershipAcquisition,
    OwnershipStatus,
)
from agentkit.backend.control_plane.records import (
    RunOwnershipRecord,
    SessionRunBindingRecord,
)
from agentkit.backend.core_types.freeze import active_freeze_state_from_record
from agentkit.backend.exceptions import OwnershipFenceViolationError
from agentkit.backend.governance.guard_system.records import StoryExecutionLockRecord
from agentkit.backend.state_backend.store.inflight_idempotency_guard import (
    compute_body_hash,
)
from agentkit.backend.telemetry.events import EventType

from ._edge_bundles import _build_edge_bundle, _next_binding_version
from ._operation_records import (
    _lifecycle_event_record,
    _object_claim_busy_rejection,
    _operation_record,
    _rejection_result,
)
from ._ownership_transfer import _current_epoch_disown_context

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from agentkit.backend.control_plane import object_claims
    from agentkit.backend.control_plane.repository import ControlPlaneRuntimeRepository
    from agentkit.backend.control_plane.runtime._recovery_commands import RecoveryCommand

_RECOVERY = "ownership_recovery"
_RECOVERY_PHASE = "ownership"


def _recovery_body_hash(command: RecoveryCommand) -> str:
    payload = dict(command.request.model_dump(mode="json"))
    payload["superseded_run_id"] = command.superseded_run_id
    payload["actor_session_id"] = command.actor_session_id
    payload["actor_principal_type"] = command.actor_principal_type
    payload["__operation_kind"] = _RECOVERY
    return compute_body_hash(payload)


def _recovery_rejection(
    command: RecoveryCommand,
    failure: recovery_core.RecoveryFailure | str,
) -> ControlPlaneMutationResult:
    code = failure.value if isinstance(failure, recovery_core.RecoveryFailure) else failure
    result = _rejection_result(
        op_id=command.request.op_id,
        operation_kind=_RECOVERY,
        run_id=command.superseded_run_id,
        phase=_RECOVERY_PHASE,
        reason=code,
        dispatch_phase=_RECOVERY_PHASE,
    )
    return result.model_copy(update={"error_code": code})


class _RecoveryMixin:
    """Acquire a new run by atomically superseding one orphaned active run."""

    if TYPE_CHECKING:
        _repo: ControlPlaneRuntimeRepository
        _now_fn: Callable[[], datetime]

        def _acquire_object_claim(
            self, *, project_key: str, story_id: str, op_id: str
        ) -> object_claims.ObjectClaimConflict | None: ...

        def _release_object_claim(
            self, *, project_key: str, story_id: str, op_id: str
        ) -> None: ...

        def _release_object_claim_best_effort(
            self, *, project_key: str, story_id: str, op_id: str
        ) -> None: ...

    def recover_ownership(self, *, command: RecoveryCommand) -> ControlPlaneMutationResult:
        """Execute a human-only recovery through capability and story fences."""

        request = command.request
        existing = self._repo.load_operation(request.op_id)
        incoming_hash = _recovery_body_hash(command)
        if existing is not None:
            if existing.status == "claimed":
                return _recovery_rejection(command, "operation_in_flight")
            if existing.request_body_hash != incoming_hash:
                from agentkit.backend.story_context_manager.errors import (
                    IdempotencyMismatchError,
                )

                raise IdempotencyMismatchError(
                    f"op_id {request.op_id!r} was previously used with a different recovery request body",
                    detail={"op_id": request.op_id, "conflict": "body_hash_mismatch"},
                )
            return ControlPlaneMutationResult.model_validate(existing.response_payload)

        initial_capability = recovery_core.evaluate_recovery_capability(
            principal_type=command.actor_principal_type,
            beneficiary_session_id=command.actor_session_id,
            reason=request.reason,
            current_epoch_disowned_session_id=None,
            current_epoch_was_takeover=False,
        )
        if initial_capability is not None:
            result = _recovery_rejection(command, initial_capability)
            self._save_recovery_result(command, result)
            return result

        conflict = self._acquire_object_claim(
            project_key=request.project_key,
            story_id=request.story_id,
            op_id=request.op_id,
        )
        if conflict is not None:
            return _object_claim_busy_rejection(
                op_id=request.op_id,
                operation_kind=_RECOVERY,
                run_id=command.superseded_run_id,
                phase=_RECOVERY_PHASE,
                conflict=conflict,
            )
        try:
            result = self._recover_under_claim(command)
            self._release_object_claim(
                project_key=request.project_key,
                story_id=request.story_id,
                op_id=request.op_id,
            )
            return result
        except OwnershipFenceViolationError:
            result = self._recovery_rejection_after_fence_loss(command)
            self._save_recovery_result(command, result)
            self._release_object_claim(
                project_key=request.project_key,
                story_id=request.story_id,
                op_id=request.op_id,
            )
            return result
        except BaseException:
            self._release_object_claim_best_effort(
                project_key=request.project_key,
                story_id=request.story_id,
                op_id=request.op_id,
            )
            raise

    def _recover_under_claim(self, command: RecoveryCommand) -> ControlPlaneMutationResult:
        request = command.request
        active_records = self._repo.load_all_active_ownership(
            request.project_key,
            request.story_id,
        )
        active = active_records[0] if len(active_records) == 1 else None
        disowned_session_id, was_takeover = _current_epoch_disown_context(
            self._repo, active
        )
        capability = recovery_core.evaluate_recovery_capability(
            principal_type=command.actor_principal_type,
            beneficiary_session_id=command.actor_session_id,
            reason=request.reason,
            current_epoch_disowned_session_id=disowned_session_id,
            current_epoch_was_takeover=was_takeover,
        )
        if capability is not None:
            result = _recovery_rejection(command, capability)
            self._save_recovery_result(command, result)
            return result
        active_freezes = tuple(
            active_freeze_state_from_record(record)
            for record in self._repo.load_active_freezes(request.story_id)
        )
        decision = recovery_core.evaluate_recovery_admissibility(
            active_records=active_records,
            superseded_run_id=command.superseded_run_id,
            active_freezes=active_freezes,
            has_unreconciled_takeover=self._repo.has_unreconciled_takeover_for_story(
                request.project_key, request.story_id
            ),
        )
        if not decision.admitted:
            assert decision.failure is not None
            result = _recovery_rejection(command, decision.failure)
            self._save_recovery_result(command, result)
            return result
        assert decision.superseded_record is not None
        return self._commit_recovery(command, decision.superseded_record)

    def _commit_recovery(
        self,
        command: RecoveryCommand,
        superseded: RunOwnershipRecord,
    ) -> ControlPlaneMutationResult:
        request = command.request
        owner_binding = self._repo.load_binding(superseded.owner_session_id)
        if owner_binding is None:
            result = _recovery_rejection(command, "owner_binding_required")
            self._save_recovery_result(command, result)
            return result
        now = self._now_fn()
        disown_plan = build_disown_plan(
            owner_binding,
            BindingRevocationReason.RECOVERY_SUPERSEDED,
            now,
        )
        new_run_id = f"run-{uuid.uuid4().hex}"
        actor_binding = self._repo.load_binding(command.actor_session_id)
        new_binding = SessionRunBindingRecord(
            session_id=command.actor_session_id,
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=new_run_id,
            principal_type=command.actor_principal_type,
            worktree_roots=owner_binding.worktree_roots,
            binding_version=_next_binding_version(
                actor_binding.binding_version if actor_binding is not None else None
            ),
            updated_at=now,
        )
        recovery_ownership = RunOwnershipRecord(
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=new_run_id,
            owner_session_id=command.actor_session_id,
            ownership_epoch=INITIAL_OWNERSHIP_EPOCH,
            status=OwnershipStatus.ACTIVE,
            acquired_via=OwnershipAcquisition.RECOVERY,
            acquired_at=now,
            audit_ref=request.op_id,
        )
        lock = StoryExecutionLockRecord(
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=new_run_id,
            lock_type="story_execution",
            status="ACTIVE",
            worktree_roots=owner_binding.worktree_roots,
            binding_version=new_binding.binding_version,
            activated_at=now,
            updated_at=now,
        )
        result = ControlPlaneMutationResult(
            status="committed",
            op_id=request.op_id,
            operation_kind=_RECOVERY,
            run_id=new_run_id,
            phase=_RECOVERY_PHASE,
            edge_bundle=_build_edge_bundle(
                binding=new_binding,
                lock=lock,
                sync_class="mutation",
                now=now,
                tombstone_worktree_roots=disown_plan.tombstone_worktree_roots,
            ),
            ownership_epoch=INITIAL_OWNERSHIP_EPOCH,
        )
        audit = {
            **disown_plan.audit_payload,
            "op_id": request.op_id,
            "operation_class": "admin_transition",
            "operator_reason": request.reason,
            "superseded_run_id": superseded.run_id,
            "recovery_run_id": new_run_id,
        }
        events = (
            _lifecycle_event_record(
                event_type=EventType.SESSION_DISOWNED,
                project_key=request.project_key,
                story_id=request.story_id,
                run_id=new_run_id,
                source_component=request.source_component,
                payload=audit,
                now=now,
                phase=_RECOVERY_PHASE,
            ),
            _lifecycle_event_record(
                event_type=EventType.SESSION_RUN_BINDING_CREATED,
                project_key=request.project_key,
                story_id=request.story_id,
                run_id=new_run_id,
                source_component=request.source_component,
                payload={
                    "owner_session_id": command.actor_session_id,
                    "acquired_via": OwnershipAcquisition.RECOVERY.value,
                    "op_id": request.op_id,
                    "operation_class": "admin_transition",
                    "reason": request.reason,
                },
                now=now,
                phase=_RECOVERY_PHASE,
            ),
        )
        self._repo.commit_recovery_acquisition(
            _operation_record(
                op_id=request.op_id,
                project_key=request.project_key,
                story_id=request.story_id,
                run_id=new_run_id,
                session_id=command.actor_session_id,
                operation_kind=_RECOVERY,
                phase=_RECOVERY_PHASE,
                result=result,
                now=now,
                request_body_hash=_recovery_body_hash(command),
            ),
            expected_active=superseded,
            recovery_ownership=recovery_ownership,
            revoked_binding=disown_plan.revoked_binding,
            new_binding=new_binding,
            locks=(lock,),
            events=events,
        )
        return result

    def _recovery_rejection_after_fence_loss(
        self, command: RecoveryCommand
    ) -> ControlPlaneMutationResult:
        request = command.request
        active_records = self._repo.load_all_active_ownership(
            request.project_key,
            request.story_id,
        )
        decision = recovery_core.evaluate_recovery_admissibility(
            active_records=active_records,
            superseded_run_id=command.superseded_run_id,
            active_freezes=tuple(
                active_freeze_state_from_record(record)
                for record in self._repo.load_active_freezes(request.story_id)
            ),
            has_unreconciled_takeover=self._repo.has_unreconciled_takeover_for_story(
                request.project_key, request.story_id
            ),
        )
        return _recovery_rejection(
            command,
            decision.failure or "recovery_fence_changed",
        )

    def _save_recovery_result(
        self, command: RecoveryCommand, result: ControlPlaneMutationResult
    ) -> None:
        request = command.request
        self._repo.save_operation(
            _operation_record(
                op_id=request.op_id,
                project_key=request.project_key,
                story_id=request.story_id,
                run_id=result.run_id,
                session_id=command.actor_session_id,
                operation_kind=_RECOVERY,
                phase=_RECOVERY_PHASE,
                result=result,
                now=self._now_fn(),
                request_body_hash=_recovery_body_hash(command),
            )
        )


__all__ = ["_RecoveryMixin"]
