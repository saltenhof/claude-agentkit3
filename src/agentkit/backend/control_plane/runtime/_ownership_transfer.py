"""Ownership-transfer takeover request and confirm runtime block."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.backend.control_plane import ownership_transfer as transfer_core
from agentkit.backend.control_plane.disown import build_disown_plan
from agentkit.backend.control_plane.models import (
    ControlPlaneMutationResult,
    PendingHumanApprovalResponse,
    TakeoverChallenge,
    TakeoverConfirmRequest,
    TakeoverRequest,
)
from agentkit.backend.control_plane.ownership import (
    BindingRevocationReason,
    TakeoverApprovalStatus,
)
from agentkit.backend.control_plane.records import (
    SessionRunBindingRecord,
    TakeoverApprovalRecord,
    TakeoverChallengeRecord,
    TakeoverConfirmTerminalRecords,
    TakeoverReissueRecords,
    TakeoverTransferRecord,
)
from agentkit.backend.exceptions import OwnershipFenceViolationError
from agentkit.backend.governance.guard_system.records import StoryExecutionLockRecord
from agentkit.backend.governance.principal_capabilities.principals import Principal
from agentkit.backend.telemetry.events import EventType

from ._edge_bundles import _build_edge_bundle, _next_binding_version
from ._operation_records import (
    _lifecycle_event_record,
    _object_claim_busy_rejection,
)
from ._ownership_transfer_support import (
    _APPROVAL_TTL,
    _CANONICAL_PRINCIPAL_TYPES,
    _CHALLENGE_TTL,
    _TAKEOVER_CONFIRM,
    _TAKEOVER_PHASE,
    _TAKEOVER_REQUEST,
    _approval_changed_payload,
    _approval_view,
    _build_takeover_challenge,
    _challenge_record_from_core,
    _challenge_view,
    _confirm_approval_state,
    _ConfirmApprovalState,
    _invalidated_approval_record,
    _load_pending_takeover_challenge,
    _load_takeover_existing_operation,
    _maybe_reissue_expired_challenge,
    _repo_evidence,
    _takeover_operation_record,
    _takeover_rejection,
    _terminal_challenge_record,
    _terminal_request_operation_record,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from agentkit.backend.control_plane import object_claims
    from agentkit.backend.control_plane.records import RunOwnershipRecord
    from agentkit.backend.control_plane.repository import (
        ControlPlaneRuntimeRepository,
    )
    from agentkit.backend.control_plane.runtime._ownership_transfer_commands import (
        TakeoverConfirmCommand,
    )
    from agentkit.backend.telemetry.contract.records import ExecutionEventRecord

logger = logging.getLogger(__name__)


def _current_epoch_disown_context(
    repo: ControlPlaneRuntimeRepository,
    active: RunOwnershipRecord | None,
) -> tuple[str | None, bool]:
    """Resolve the current-epoch disowned identity from transfer+challenge rows."""

    if active is None:
        return None, False
    current = tuple(
        record
        for record in repo.list_takeover_history(active.project_key, active.story_id)
        if record.run_id == active.run_id
        and record.ownership_epoch == active.ownership_epoch
    )
    if not current:
        return None, False
    challenge_refs = {
        record.challenge_ref for record in current if record.challenge_ref is not None
    }
    owner_ids = {
        challenge.owner_session_id
        for challenge_ref in challenge_refs
        if (challenge := repo.load_takeover_challenge(challenge_ref)) is not None
    }
    return (next(iter(owner_ids)) if len(owner_ids) == 1 else None), True


@dataclass(frozen=True)
class _TakeoverInvalidationCandidate:
    challenge: TakeoverChallengeRecord
    approval: TakeoverApprovalRecord | None


class _OwnershipTransferMixin:
    """Challenge-confirm-CAS takeover runtime surface."""

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

    def request_ownership_takeover(
        self,
        *,
        request: TakeoverRequest,
    ) -> ControlPlaneMutationResult:
        """Offer a takeover challenge or persist a pending human approval."""
        existing = _load_takeover_existing_operation(
            self._repo,
            request,
            operation_kind=_TAKEOVER_REQUEST,
        )
        if existing is not None:
            return existing
        if request.principal_type not in _CANONICAL_PRINCIPAL_TYPES:
            return _takeover_rejection(
                op_id=request.op_id,
                operation_kind=_TAKEOVER_REQUEST,
                reason="invalid_takeover_principal",
                error_code="invalid_takeover_principal",
            )
        conflict = self._acquire_object_claim(
            project_key=request.project_key,
            story_id=request.story_id,
            op_id=request.op_id,
        )
        if conflict is not None:
            return _object_claim_busy_rejection(
                op_id=request.op_id,
                operation_kind=_TAKEOVER_REQUEST,
                run_id=None,
                phase=_TAKEOVER_PHASE,
                conflict=conflict,
            )
        try:
            result = self._request_ownership_takeover_under_claim(request)
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

    def confirm_ownership_takeover(
        self,
        *,
        command: TakeoverConfirmCommand,
    ) -> ControlPlaneMutationResult:
        """Confirm a stored challenge with boundary-attested human identity."""
        request = command.request
        if command.confirmed_by_principal is not Principal.HUMAN_CLI:
            return _takeover_rejection(
                op_id=request.op_id,
                operation_kind=_TAKEOVER_CONFIRM,
                reason="agent_confirm_forbidden",
                error_code="agent_confirm_forbidden",
            )
        existing = _load_takeover_existing_operation(
            self._repo,
            command,
            operation_kind=_TAKEOVER_CONFIRM,
        )
        if existing is not None:
            return existing
        conflict = self._acquire_object_claim(
            project_key=request.project_key,
            story_id=request.story_id,
            op_id=request.op_id,
        )
        if conflict is not None:
            return _object_claim_busy_rejection(
                op_id=request.op_id,
                operation_kind=_TAKEOVER_CONFIRM,
                run_id=None,
                phase=_TAKEOVER_PHASE,
                conflict=conflict,
            )
        committed = False
        try:
            result = self._confirm_ownership_takeover_under_claim(command)
            committed = result.status in {"committed", "challenge_reissued"}
            self._release_object_claim(
                project_key=request.project_key,
                story_id=request.story_id,
                op_id=request.op_id,
            )
            return result
        except OwnershipFenceViolationError:
            try:
                result = _reconcile_takeover_confirm_cas_loss(
                    self._repo,
                    command=command,
                    now=self._now_fn(),
                )
            except BaseException:
                self._release_object_claim_best_effort(
                    project_key=request.project_key,
                    story_id=request.story_id,
                    op_id=request.op_id,
                )
                raise
            self._release_object_claim(
                project_key=request.project_key,
                story_id=request.story_id,
                op_id=request.op_id,
            )
            return result
        except BaseException:
            if not committed:
                self._release_object_claim_best_effort(
                    project_key=request.project_key,
                    story_id=request.story_id,
                    op_id=request.op_id,
                )
            raise

    def _request_ownership_takeover_under_claim(
        self,
        request: TakeoverRequest,
    ) -> ControlPlaneMutationResult:
        now = self._now_fn()
        active = self._repo.load_active_ownership(request.project_key, request.story_id)
        if active is None:
            result = _takeover_rejection(
                op_id=request.op_id,
                operation_kind=_TAKEOVER_REQUEST,
                reason="active_ownership_required",
                error_code="active_ownership_required",
            )
            self._repo.save_operation(
                _takeover_operation_record(request, result=result, now=now)
            )
            return result
        owner_binding = self._repo.load_binding(active.owner_session_id)
        if owner_binding is None:
            result = _takeover_rejection(
                op_id=request.op_id,
                operation_kind=_TAKEOVER_REQUEST,
                reason="owner_binding_required",
                error_code="owner_binding_required",
            )
            self._repo.save_operation(
                _takeover_operation_record(
                    request,
                    result=result,
                    now=now,
                    run_id=active.run_id,
                )
            )
            return result
        disowned_session_id, current_epoch_was_takeover = _current_epoch_disown_context(
            self._repo,
            active,
        )
        self_rebind = transfer_core.is_self_rebind_identity(
            requesting_session_id=request.session_id,
            orphaned_owner_session_id=active.owner_session_id,
        )
        barrier_failure = transfer_core.evaluate_disowned_session_takeover_barrier(
            current_epoch_disowned_session_id=None,
            beneficiary_session_id=request.session_id,
            requesting_principal_type=request.principal_type,
            request_reason=request.reason,
            current_epoch_was_takeover=(
                current_epoch_was_takeover
                and not self_rebind
                and request.session_id != disowned_session_id
            ),
        )
        if barrier_failure is not None:
            result = _takeover_rejection(
                op_id=request.op_id,
                operation_kind=_TAKEOVER_REQUEST,
                reason=barrier_failure.value,
                error_code=barrier_failure.value,
                run_id=active.run_id,
            )
            self._repo.save_operation(
                _takeover_operation_record(request, result=result, now=now),
            )
            return result
        challenge = _build_takeover_challenge(
                self._repo,
            request=request,
            active_record=active,
            owner_binding=owner_binding,
            expires_at=now + _CHALLENGE_TTL,
        )
        if transfer_core.requires_human_approval(
            request.principal_type,
            requesting_session_id=request.session_id,
            orphaned_owner_session_id=active.owner_session_id,
        ):
            approval = TakeoverApprovalRecord(
                approval_id=f"approval-{uuid.uuid4().hex}",
                project_key=request.project_key,
                story_id=request.story_id,
                run_id=active.run_id,
                requested_by_session_id=request.session_id,
                requested_by_principal_type=request.principal_type,
                reason=request.reason,
                challenge_ref=challenge.challenge_id,
                status=TakeoverApprovalStatus.PENDING,
                requested_at=now,
                expires_at=now + _APPROVAL_TTL,
            )
            # AG3-149/151 hardening follow-up: request persists approval/operation/
            # challenge in separate writes; confirm/deny own the atomicity contract.
            self._repo.insert_takeover_approval(approval)
            result = ControlPlaneMutationResult(
                status="pending_human_approval",
                op_id=request.op_id,
                operation_kind=_TAKEOVER_REQUEST,
                run_id=active.run_id,
                phase=_TAKEOVER_PHASE,
                pending_human_approval=PendingHumanApprovalResponse(
                    op_id=request.op_id,
                    approval_id=approval.approval_id,
                    message="pending_human_approval",
                    approval=_approval_view(approval),
                ),
            )
            event_specs: tuple[tuple[EventType, dict[str, object]], ...] = (
                (
                    EventType.RUN_OWNERSHIP_TAKEOVER_APPROVAL_REQUESTED,
                    {
                        "approval_id": approval.approval_id,
                        "requesting_session_id": request.session_id,
                        "status": approval.status.value,
                        "reason": request.reason,
                    },
                ),
                (
                    EventType.TAKEOVER_APPROVAL_CHANGED,
                    _approval_changed_payload(approval),
                ),
            )
        else:
            result = ControlPlaneMutationResult(
                status="offered",
                op_id=request.op_id,
                operation_kind=_TAKEOVER_REQUEST,
                run_id=active.run_id,
                phase=_TAKEOVER_PHASE,
                takeover_challenge=_challenge_view(challenge),
            )
            event_specs = (
                (
                    EventType.RUN_OWNERSHIP_TAKEOVER_OFFERED,
                    {
                        "challenge_id": challenge.challenge_id,
                        "requesting_session_id": request.session_id,
                        "self_rebind": self_rebind,
                    },
                ),
            )
        self._repo.save_operation(
            _takeover_operation_record(
                request,
                result=result,
                now=now,
                run_id=active.run_id,
            )
        )
        self._repo.insert_takeover_challenge(
            _challenge_record_from_core(
                challenge,
                request_op_id=request.op_id,
                issued_at=now,
                requesting_worktree_roots=tuple(request.worktree_roots),
            )
        )
        for event_type, event_payload in event_specs:
            self._repo.append_event(
                _lifecycle_event_record(
                    event_type=event_type,
                    project_key=request.project_key,
                    story_id=request.story_id,
                    run_id=active.run_id,
                    source_component=request.source_component,
                    payload=event_payload,
                    now=now,
                    phase=_TAKEOVER_PHASE,
                )
            )
        return result

    def _confirm_ownership_takeover_under_claim(
        self,
        command: TakeoverConfirmCommand,
    ) -> ControlPlaneMutationResult:
        request = command.request
        now = self._now_fn()
        challenge_lookup = _load_pending_takeover_challenge(self._repo, request)
        if challenge_lookup.rejection is not None:
            return challenge_lookup.rejection
        assert challenge_lookup.challenge is not None
        stored_challenge = challenge_lookup.challenge
        active = self._repo.load_active_ownership(request.project_key, request.story_id)
        owner_binding = (
            self._repo.load_binding(stored_challenge.owner_session_id)
            if active is not None
            else None
        )
        repo_evidence = _repo_evidence(
            self._repo,
            request.project_key,
            request.story_id,
            active.run_id if active is not None else "",
        )
        approval_required = transfer_core.requires_human_approval(
            stored_challenge.requesting_principal_type,
            requesting_session_id=stored_challenge.requesting_session_id,
            orphaned_owner_session_id=(
                active.owner_session_id if active is not None else None
            ),
        )
        approval_state = _confirm_approval_state(
            self._repo,
            command,
            now,
            challenge=stored_challenge,
            approval_required=approval_required,
        )
        invalidation = _transition_invalidation_candidate(
            self._repo,
            command,
            stored_challenge,
            approval_state,
        )
        if invalidation is not None:
            return _commit_takeover_invalidation(
                self._repo,
                command=command,
                challenge=invalidation.challenge,
                approval=invalidation.approval,
                now=now,
            )
        reissue_result = self._takeover_reissue_result(
            command=command,
            stored_challenge=stored_challenge,
            active=active,
            approval_state=approval_state,
            now=now,
        )
        if reissue_result is not None:
            return reissue_result
        active_basis = transfer_core.ownership_basis_of_active(active, owner_binding)
        challenge_basis = transfer_core.ownership_basis_of_challenge(stored_challenge)
        if not transfer_core.ownership_basis_unchanged(active_basis, challenge_basis):
            return _commit_takeover_invalidation(
                self._repo,
                command=command,
                challenge=stored_challenge,
                approval=approval_state.approval,
                now=now,
            )
        expired = self._expired_takeover_confirm_result(
            command=command,
            challenge=stored_challenge,
            approval_state=approval_state,
            now=now,
        )
        if expired is not None:
            return expired
        disowned_session_id, current_epoch_was_takeover = _current_epoch_disown_context(
            self._repo,
            active,
        )
        self_rebind = transfer_core.is_self_rebind_identity(
            requesting_session_id=stored_challenge.requesting_session_id,
            orphaned_owner_session_id=(
                active.owner_session_id if active is not None else None
            ),
        )
        decision = transfer_core.evaluate_takeover_confirm(
            active_basis=active_basis,
            challenge_basis=challenge_basis,
            now=now,
            challenge_expires_at=stored_challenge.expires_at,
            approval_status=approval_state.status,
            approval_required=approval_required,
            repo_evidence=repo_evidence,
            current_epoch_disowned_session_id=disowned_session_id,
            beneficiary_session_id=stored_challenge.requesting_session_id,
            requesting_principal_type=stored_challenge.requesting_principal_type,
            request_reason=stored_challenge.reason,
            current_epoch_was_takeover=(
                current_epoch_was_takeover and not self_rebind
            ),
        )
        if not decision.accepted:
            if decision.failure is transfer_core.TakeoverConfirmFailure.CHALLENGE_INVALIDATED:
                return _commit_takeover_invalidation(
                    self._repo,
                    command=command,
                    challenge=stored_challenge,
                    approval=approval_state.approval,
                    now=now,
                )
            return _takeover_rejection(
                op_id=request.op_id,
                operation_kind=_TAKEOVER_CONFIRM,
                reason=str(decision.failure),
                error_code=str(decision.failure),
                run_id=active.run_id if active is not None else None,
            )
        assert active is not None
        assert owner_binding is not None
        new_epoch = active.ownership_epoch + 1
        new_binding_version = _next_binding_version(owner_binding.binding_version)
        disown_plan = build_disown_plan(
            owner_binding,
            BindingRevocationReason.OWNERSHIP_TRANSFERRED,
            now,
        )
        new_binding = SessionRunBindingRecord(
            session_id=stored_challenge.requesting_session_id,
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=active.run_id,
            principal_type=stored_challenge.requesting_principal_type,
            worktree_roots=stored_challenge.requesting_worktree_roots,
            binding_version=new_binding_version,
            updated_at=now,
        )
        lock = StoryExecutionLockRecord(
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=active.run_id,
            lock_type="story_execution",
            status="ACTIVE",
            worktree_roots=stored_challenge.requesting_worktree_roots,
            binding_version=new_binding_version,
            activated_at=now,
            updated_at=now,
        )
        transfer_records = tuple(
            TakeoverTransferRecord(
                project_key=request.project_key,
                story_id=request.story_id,
                run_id=active.run_id,
                ownership_epoch=new_epoch,
                repo_id=repo.repo_id,
                takeover_base_sha=repo.takeover_base_sha,
                last_push_at=repo.last_push_at,
                push_lag_hint=repo.push_lag_hint,
                base_quality=repo.base_quality,
                challenge_ref=stored_challenge.challenge_id,
                confirm_ref=request.op_id,
            )
            for repo in repo_evidence
        )
        bundle = _build_edge_bundle(
            binding=new_binding,
            lock=lock,
            sync_class="mutation",
            now=now,
            tombstone_worktree_roots=disown_plan.tombstone_worktree_roots,
        )
        result = ControlPlaneMutationResult(
            status="committed",
            op_id=request.op_id,
            operation_kind=_TAKEOVER_CONFIRM,
            run_id=active.run_id,
            phase=_TAKEOVER_PHASE,
            edge_bundle=bundle,
            ownership_epoch=new_epoch,
        )
        record = _takeover_operation_record(
            command,
            result=result,
            now=now,
            run_id=active.run_id,
        )
        request_result = ControlPlaneMutationResult(
            status="approved",
            op_id=stored_challenge.request_op_id,
            operation_kind=_TAKEOVER_REQUEST,
            run_id=active.run_id,
            phase=_TAKEOVER_PHASE,
        )
        request_record = _terminal_request_operation_record(
            self._repo.load_operation(stored_challenge.request_op_id),
            response_payload=request_result.model_dump(mode="json"),
            status="approved",
            now=now,
        )
        if request_record is None:
            return _takeover_rejection(
                op_id=request.op_id,
                operation_kind=_TAKEOVER_CONFIRM,
                reason="takeover_request_operation_required",
                error_code="takeover_request_operation_required",
                run_id=active.run_id,
            )
        terminal_challenge = _terminal_challenge_record(
            stored_challenge,
            status="confirmed",
            terminal_op_id=request.op_id,
            now=now,
        )
        event_specs: tuple[tuple[EventType, dict[str, object]], ...] = (
            (
                EventType.SESSION_RUN_BINDING_TRANSFERRED,
                {
                    "previous_owner_session_id": owner_binding.session_id,
                    "new_owner_session_id": stored_challenge.requesting_session_id,
                    "ownership_epoch": new_epoch,
                },
            ),
            (
                EventType.SESSION_DISOWNED,
                disown_plan.audit_payload,
            ),
        )
        if approval_state.approved_approval is not None:
            event_specs += (
                (
                    EventType.TAKEOVER_APPROVAL_CHANGED,
                    _approval_changed_payload(approval_state.approved_approval),
                ),
            )
        events = tuple(
            _lifecycle_event_record(
                event_type=event_type,
                project_key=request.project_key,
                story_id=request.story_id,
                run_id=active.run_id,
                source_component=request.source_component,
                payload=payload,
                now=now,
                phase=_TAKEOVER_PHASE,
            )
            for event_type, payload in event_specs
        )
        self._repo.commit_takeover_confirm(
            record,
            expected_basis=challenge_basis,
            revoked_binding=disown_plan.revoked_binding,
            new_binding=new_binding,
            locks=(lock,),
            transfers=transfer_records,
            events=events,
            terminal_records=TakeoverConfirmTerminalRecords(
                challenge=terminal_challenge,
                request_op_record=request_record,
                approved_approval=approval_state.approved_approval,
            ),
        )
        return result

    def _takeover_reissue_result(
        self,
        *,
        command: TakeoverConfirmCommand,
        stored_challenge: TakeoverChallengeRecord,
        active: RunOwnershipRecord | None,
        approval_state: _ConfirmApprovalState,
        now: datetime,
    ) -> ControlPlaneMutationResult | None:
        reissue = _maybe_reissue_expired_challenge(
            self._repo,
            command=command,
            stored_challenge=stored_challenge,
            active=active,
            approval_state=approval_state,
            now=now,
        )
        if reissue.rejection is not None:
            if reissue.rejection.error_code != "challenge_invalidated":
                return reissue.rejection
            return _commit_takeover_invalidation(
                self._repo,
                command=command,
                challenge=stored_challenge,
                approval=approval_state.approval,
                now=now,
            )
        if reissue.challenge_to_insert is None:
            return None
        assert reissue.challenge_to_expire is not None
        assert reissue.approval_state.approved_approval is not None
        assert reissue.fresh_challenge_view is not None
        return _commit_takeover_reissue(
            self._repo,
            command=command,
            active=active,
            owner_binding=reissue.owner_binding,
            expired_challenge=reissue.challenge_to_expire,
            fresh_challenge=reissue.challenge_to_insert,
            fresh_challenge_view=reissue.fresh_challenge_view,
            relinked_approval=reissue.approval_state.approved_approval,
            now=now,
        )

    def _expired_takeover_confirm_result(
        self,
        *,
        command: TakeoverConfirmCommand,
        challenge: TakeoverChallengeRecord,
        approval_state: _ConfirmApprovalState,
        now: datetime,
    ) -> ControlPlaneMutationResult | None:
        if (
            approval_state.approval is not None
            and approval_state.approval.status is TakeoverApprovalStatus.EXPIRED
        ):
            return self._commit_takeover_expiry(
                command=command,
                challenge=challenge,
                expired_approval=approval_state.approval,
                now=now,
                reason="approval_not_approved",
                error_code="approval_not_approved",
            )
        if (
            now < challenge.expires_at
            or approval_state.approved_approval is not None
            or (
                approval_state.approval is not None
                and approval_state.approval.status is TakeoverApprovalStatus.APPROVED
            )
        ):
            return None
        return self._commit_takeover_expiry(
            command=command,
            challenge=challenge,
            expired_approval=None,
            now=now,
            reason="challenge_expired",
            error_code="challenge_expired",
        )

    def _commit_takeover_expiry(
        self,
        *,
        command: TakeoverConfirmCommand,
        challenge: TakeoverChallengeRecord,
        expired_approval: TakeoverApprovalRecord | None,
        now: datetime,
        reason: str,
        error_code: str,
    ) -> ControlPlaneMutationResult:
        request = command.request
        result = _takeover_rejection(
            op_id=request.op_id,
            operation_kind=_TAKEOVER_CONFIRM,
            reason=reason,
            error_code=error_code,
            run_id=challenge.run_id,
        )
        request_result = ControlPlaneMutationResult(
            status="expired",
            op_id=challenge.request_op_id,
            operation_kind=_TAKEOVER_REQUEST,
            run_id=challenge.run_id,
            phase=_TAKEOVER_PHASE,
        )
        request_record = _terminal_request_operation_record(
            self._repo.load_operation(challenge.request_op_id),
            response_payload=request_result.model_dump(mode="json"),
            status="expired",
            now=now,
        )
        if request_record is None:
            return _takeover_rejection(
                op_id=request.op_id,
                operation_kind=_TAKEOVER_CONFIRM,
                reason="takeover_request_operation_required",
                error_code="takeover_request_operation_required",
                run_id=challenge.run_id,
            )
        events: tuple[tuple[EventType, dict[str, object]], ...] = ()
        if expired_approval is not None:
            events = (
                (
                    EventType.TAKEOVER_APPROVAL_CHANGED,
                    _approval_changed_payload(expired_approval),
                ),
            )
        self._repo.commit_takeover_expiry(
            _takeover_operation_record(
                command,
                result=result,
                now=now,
                run_id=challenge.run_id,
            ),
            request_op_record=request_record,
            challenge=_terminal_challenge_record(
                challenge,
                status="expired",
                terminal_op_id=request.op_id,
                now=now,
            ),
            expired_approval=expired_approval,
            events=tuple(
                _lifecycle_event_record(
                    event_type=event_type,
                    project_key=request.project_key,
                    story_id=request.story_id,
                    run_id=challenge.run_id,
                    source_component=request.source_component,
                    payload=payload,
                    now=now,
                    phase=_TAKEOVER_PHASE,
                )
                for event_type, payload in events
            ),
        )
        return result

def _transition_invalidation_candidate(
    repo: ControlPlaneRuntimeRepository,
    command: TakeoverConfirmCommand,
    challenge: TakeoverChallengeRecord,
    approval_state: _ConfirmApprovalState,
) -> _TakeoverInvalidationCandidate | None:
    request = command.request
    if not _has_invalidating_transition(repo, request, challenge):
        return None
    return _TakeoverInvalidationCandidate(
        challenge=challenge,
        approval=approval_state.approval,
    )


def _commit_takeover_reissue(
    repo: ControlPlaneRuntimeRepository,
    *,
    command: TakeoverConfirmCommand,
    active: RunOwnershipRecord | None,
    owner_binding: SessionRunBindingRecord | None,
    expired_challenge: TakeoverChallengeRecord,
    fresh_challenge: TakeoverChallengeRecord,
    fresh_challenge_view: TakeoverChallenge,
    relinked_approval: TakeoverApprovalRecord,
    now: datetime,
) -> ControlPlaneMutationResult:
    request = command.request
    active_basis = transfer_core.ownership_basis_of_active(active, owner_binding)
    if active_basis is None:
        return _challenge_invalidated_rejection(request, run_id=expired_challenge.run_id)
    result = ControlPlaneMutationResult(
        status="challenge_reissued",
        op_id=request.op_id,
        operation_kind=_TAKEOVER_CONFIRM,
        run_id=expired_challenge.run_id,
        phase=_TAKEOVER_PHASE,
        takeover_challenge=fresh_challenge_view,
    )
    event = _lifecycle_event_record(
        event_type=EventType.TAKEOVER_APPROVAL_CHANGED,
        project_key=request.project_key,
        story_id=request.story_id,
        run_id=expired_challenge.run_id,
        source_component=request.source_component,
        payload=_approval_changed_payload(relinked_approval),
        now=now,
        phase=_TAKEOVER_PHASE,
    )
    repo.commit_takeover_reissue(
        _takeover_operation_record(
            command,
            result=result,
            now=now,
            run_id=expired_challenge.run_id,
        ),
        expected_basis=active_basis,
        records=TakeoverReissueRecords(
            expired_challenge=expired_challenge,
            fresh_challenge=fresh_challenge,
            relinked_approval=relinked_approval,
        ),
        events=(event,),
    )
    return result


def _reconcile_takeover_confirm_cas_loss(
    repo: ControlPlaneRuntimeRepository,
    *,
    command: TakeoverConfirmCommand,
    now: datetime,
) -> ControlPlaneMutationResult:
    request = command.request
    challenge = repo.load_takeover_challenge(request.challenge_id)
    if challenge is None:
        return _takeover_rejection(
            op_id=request.op_id,
            operation_kind=_TAKEOVER_CONFIRM,
            reason="challenge_not_found",
            error_code="challenge_not_found",
        )
    approval = repo.load_takeover_approval_for_challenge(challenge.challenge_id)
    invalidated_approval = _takeover_invalidated_approval(
        approval,
        command=command,
        now=now,
    )
    result = _challenge_invalidated_rejection(request, run_id=challenge.run_id)
    request_result = ControlPlaneMutationResult(
        status="invalidated",
        op_id=challenge.request_op_id,
        operation_kind=_TAKEOVER_REQUEST,
        run_id=challenge.run_id,
        phase=_TAKEOVER_PHASE,
        error_code="challenge_invalidated",
        pending_human_approval=_invalidated_pending_approval_response(
            challenge,
            invalidated_approval=invalidated_approval,
        ),
    )
    request_record = _terminal_request_operation_record(
        repo.load_operation(challenge.request_op_id),
        response_payload=request_result.model_dump(mode="json"),
        status="invalidated",
        now=now,
    )
    if request_record is None:
        raise RuntimeError("takeover CAS-loss reconcile requires the request operation")
    outcome = repo.reconcile_takeover_confirm_cas_loss(
        _takeover_operation_record(
            command,
            result=result,
            now=now,
            run_id=challenge.run_id,
        ),
        expected_basis=transfer_core.ownership_basis_of_challenge(challenge),
        request_op_record=request_record,
        challenge=_terminal_challenge_record(
            challenge,
            status="invalidated",
            terminal_op_id=request.op_id,
            now=now,
        ),
        invalidated_approval=invalidated_approval,
        events=_takeover_invalidation_events(
            command,
            challenge=challenge,
            invalidated_approval=invalidated_approval,
            now=now,
        ),
    )
    if outcome == "invalidated":
        return result
    error_code = (
        "challenge_invalidated" if outcome == "terminal_invalidated" else outcome
    )
    return _takeover_rejection(
        op_id=request.op_id,
        operation_kind=_TAKEOVER_CONFIRM,
        reason=error_code,
        error_code=error_code,
        run_id=challenge.run_id,
    )


def _commit_takeover_invalidation(
    repo: ControlPlaneRuntimeRepository,
    *,
    command: TakeoverConfirmCommand,
    challenge: TakeoverChallengeRecord,
    approval: TakeoverApprovalRecord | None,
    now: datetime,
) -> ControlPlaneMutationResult:
    request = command.request
    result = _challenge_invalidated_rejection(request, run_id=challenge.run_id)
    invalidated_approval = _takeover_invalidated_approval(
        approval,
        command=command,
        now=now,
    )
    request_result = ControlPlaneMutationResult(
        status="invalidated",
        op_id=challenge.request_op_id,
        operation_kind=_TAKEOVER_REQUEST,
        run_id=challenge.run_id,
        phase=_TAKEOVER_PHASE,
        error_code="challenge_invalidated",
        pending_human_approval=_invalidated_pending_approval_response(
            challenge,
            invalidated_approval=invalidated_approval,
        ),
    )
    request_record = _terminal_request_operation_record(
        repo.load_operation(challenge.request_op_id),
        response_payload=request_result.model_dump(mode="json"),
        status="invalidated",
        now=now,
    )
    if request_record is None:
        return _takeover_rejection(
            op_id=request.op_id,
            operation_kind=_TAKEOVER_CONFIRM,
            reason="takeover_request_operation_required",
            error_code="takeover_request_operation_required",
            run_id=challenge.run_id,
        )
    events = _takeover_invalidation_events(
        command,
        challenge=challenge,
        invalidated_approval=invalidated_approval,
        now=now,
    )
    repo.commit_takeover_invalidation(
        _takeover_operation_record(
            command,
            result=result,
            now=now,
            run_id=challenge.run_id,
        ),
        request_op_record=request_record,
        challenge=_terminal_challenge_record(
            challenge,
            status="invalidated",
            terminal_op_id=request.op_id,
            now=now,
        ),
        invalidated_approval=invalidated_approval,
        events=events,
    )
    return result


def _takeover_invalidated_approval(
    approval: TakeoverApprovalRecord | None,
    *,
    command: TakeoverConfirmCommand,
    now: datetime,
) -> TakeoverApprovalRecord | None:
    if approval is None or approval.status is not TakeoverApprovalStatus.PENDING:
        return None
    return _invalidated_approval_record(approval, command=command, now=now)


def _invalidated_pending_approval_response(
    challenge: TakeoverChallengeRecord,
    *,
    invalidated_approval: TakeoverApprovalRecord | None,
) -> PendingHumanApprovalResponse | None:
    if invalidated_approval is None:
        return None
    return PendingHumanApprovalResponse(
        op_id=challenge.request_op_id,
        approval_id=invalidated_approval.approval_id,
        message="challenge_invalidated",
        approval=_approval_view(invalidated_approval),
    )


def _takeover_invalidation_events(
    command: TakeoverConfirmCommand,
    *,
    challenge: TakeoverChallengeRecord,
    invalidated_approval: TakeoverApprovalRecord | None,
    now: datetime,
) -> tuple[ExecutionEventRecord, ...]:
    request = command.request
    if invalidated_approval is None:
        return ()
    return (
        _lifecycle_event_record(
            event_type=EventType.TAKEOVER_APPROVAL_CHANGED,
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=challenge.run_id,
            source_component=request.source_component,
            payload=_approval_changed_payload(invalidated_approval),
            now=now,
            phase=_TAKEOVER_PHASE,
        ),
    )


def _has_invalidating_transition(
    repo: ControlPlaneRuntimeRepository,
    request: TakeoverConfirmRequest,
    challenge: TakeoverChallengeRecord,
) -> bool:
    return repo.has_committed_ownership_invalidating_operation_for_run(
        request.project_key,
        request.story_id,
        challenge.run_id,
    )


def _challenge_invalidated_rejection(
    request: TakeoverConfirmRequest,
    *,
    run_id: str,
) -> ControlPlaneMutationResult:
    return _takeover_rejection(
        op_id=request.op_id,
        operation_kind=_TAKEOVER_CONFIRM,
        reason="challenge_invalidated",
        error_code="challenge_invalidated",
        run_id=run_id,
    )
