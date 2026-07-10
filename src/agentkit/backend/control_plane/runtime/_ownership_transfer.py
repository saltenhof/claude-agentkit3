"""Ownership-transfer takeover request and confirm runtime block."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from agentkit.backend.control_plane import ownership_transfer as transfer_core
from agentkit.backend.control_plane.models import (
    ControlPlaneMutationResult,
    PendingHumanApprovalResponse,
    TakeoverChallengeEchoRequest,
    TakeoverDenyRequest,
    TakeoverRequest,
)
from agentkit.backend.control_plane.ownership import (
    OWNERSHIP_TRANSFERRED_REVOCATION_REASON,
    BindingStatus,
    OwnershipStatus,
    TakeoverApprovalStatus,
)
from agentkit.backend.control_plane.records import (
    SessionRunBindingRecord,
    TakeoverApprovalRecord,
    TakeoverChallengeRecord,
    TakeoverConfirmTerminalRecords,
    TakeoverTransferRecord,
)
from agentkit.backend.exceptions import OwnershipFenceViolationError
from agentkit.backend.governance.guard_system.records import StoryExecutionLockRecord
from agentkit.backend.telemetry.events import EventType

from ._edge_bundles import _build_edge_bundle, _next_binding_version
from ._operation_records import (
    _lifecycle_event_record,
    _object_claim_busy_rejection,
)
from ._ownership_transfer_support import (
    _AGENT_PRINCIPAL_TYPES,
    _APPROVAL_TTL,
    _CANONICAL_PRINCIPAL_TYPES,
    _CHALLENGE_TTL,
    _TAKEOVER_CONFIRM,
    _TAKEOVER_DENY,
    _TAKEOVER_PHASE,
    _TAKEOVER_REQUEST,
    _approval_changed_payload,
    _approval_view,
    _build_takeover_challenge,
    _challenge_record_from_core,
    _challenge_view,
    _confirm_approval_state,
    _ConfirmApprovalState,
    _denied_approval_record,
    _denied_request_operation_record,
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

logger = logging.getLogger(__name__)

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
        request: TakeoverChallengeEchoRequest,
    ) -> ControlPlaneMutationResult:
        """Confirm a takeover by challenge echo and commit the ownership CAS."""
        if request.principal_type in _AGENT_PRINCIPAL_TYPES:
            return _takeover_rejection(
                op_id=request.op_id,
                operation_kind=_TAKEOVER_CONFIRM,
                reason="agent_confirm_forbidden",
                error_code="agent_confirm_forbidden",
            )
        existing = _load_takeover_existing_operation(
            self._repo,
            request,
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
            result = self._confirm_ownership_takeover_under_claim(request)
            committed = result.status == "committed"
            self._release_object_claim(
                project_key=request.project_key,
                story_id=request.story_id,
                op_id=request.op_id,
            )
            return result
        except OwnershipFenceViolationError:
            self._release_object_claim(
                project_key=request.project_key,
                story_id=request.story_id,
                op_id=request.op_id,
            )
            return _takeover_rejection(
                op_id=request.op_id,
                operation_kind=_TAKEOVER_CONFIRM,
                reason="takeover_confirm_cas_lost",
                error_code="takeover_confirm_cas_lost",
            )
        except BaseException:
            if not committed:
                self._release_object_claim_best_effort(
                    project_key=request.project_key,
                    story_id=request.story_id,
                    op_id=request.op_id,
                )
            raise

    def deny_ownership_takeover(
        self,
        *,
        request: TakeoverDenyRequest,
    ) -> ControlPlaneMutationResult:
        """Deny a pending agent-initiated takeover approval."""
        existing = _load_takeover_existing_operation(
            self._repo,
            request,
            operation_kind=_TAKEOVER_DENY,
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
                operation_kind=_TAKEOVER_DENY,
                run_id=None,
                phase=_TAKEOVER_PHASE,
                conflict=conflict,
            )
        try:
            result = self._deny_ownership_takeover_under_claim(request)
            self._release_object_claim(
                project_key=request.project_key,
                story_id=request.story_id,
                op_id=request.op_id,
            )
            return result
        except OwnershipFenceViolationError:
            self._release_object_claim(
                project_key=request.project_key,
                story_id=request.story_id,
                op_id=request.op_id,
            )
            return _takeover_rejection(
                op_id=request.op_id,
                operation_kind=_TAKEOVER_DENY,
                reason="takeover_approval_not_pending",
                error_code="takeover_approval_not_pending",
            )
        except BaseException:
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
        challenge = _build_takeover_challenge(
                self._repo,
            request=request,
            active_record=active,
            owner_binding=owner_binding,
            expires_at=now + _CHALLENGE_TTL,
        )
        if transfer_core.requires_human_approval(request.principal_type):
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
        request: TakeoverChallengeEchoRequest,
    ) -> ControlPlaneMutationResult:
        now = self._now_fn()
        challenge_lookup = _load_pending_takeover_challenge(self._repo, request)
        if challenge_lookup.rejection is not None:
            return challenge_lookup.rejection
        assert challenge_lookup.challenge is not None
        stored_challenge = challenge_lookup.challenge
        invalidated = _invalidating_transition_rejection(self._repo, request, stored_challenge)
        if invalidated is not None:
            return invalidated
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
            stored_challenge.requesting_principal_type
        )
        approval_state = _confirm_approval_state(
            self._repo,
            request,
            now,
            challenge=stored_challenge,
            approval_required=approval_required,
        )
        expired = self._expired_takeover_confirm_result(
            request=request,
            challenge=stored_challenge,
            approval_state=approval_state,
            now=now,
        )
        if expired is not None:
            return expired
        reissue = _maybe_reissue_expired_challenge(
            self._repo,
            request=request,
            stored_challenge=stored_challenge,
            active=active,
            approval_state=approval_state,
            now=now,
        )
        if reissue.rejection is not None:
            return reissue.rejection
        if reissue.owner_binding is not None:
            owner_binding = reissue.owner_binding
        approval_state = reissue.approval_state
        effective_challenge = reissue.effective_challenge
        challenge_to_insert = reissue.challenge_to_insert
        challenge_to_expire = reissue.challenge_to_expire
        if _ownership_basis_changed(active, effective_challenge):
            return _challenge_invalidated_rejection(request, run_id=effective_challenge.run_id)
        core_echo = transfer_core.TakeoverChallengeEcho(
            challenge_id=effective_challenge.challenge_id,
            owner_session_id=effective_challenge.owner_session_id,
            ownership_epoch=effective_challenge.ownership_epoch,
            binding_version=effective_challenge.binding_version,
        )
        decision = transfer_core.evaluate_takeover_confirm(
            active_record=active,
            owner_binding=owner_binding,
            echo=core_echo,
            now=now,
            challenge_expires_at=(
                None if challenge_to_insert is not None else effective_challenge.expires_at
            ),
            approval_status=approval_state.status,
            approval_required=approval_required,
            repo_evidence=repo_evidence,
        )
        if not decision.accepted:
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
        revoked_binding = SessionRunBindingRecord(
            session_id=owner_binding.session_id,
            project_key=owner_binding.project_key,
            story_id=owner_binding.story_id,
            run_id=owner_binding.run_id,
            principal_type=owner_binding.principal_type,
            worktree_roots=owner_binding.worktree_roots,
            binding_version=owner_binding.binding_version,
            updated_at=now,
            status=BindingStatus.REVOKED.value,
            revocation_reason=OWNERSHIP_TRANSFERRED_REVOCATION_REASON,
        )
        new_binding = SessionRunBindingRecord(
            session_id=effective_challenge.requesting_session_id,
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=active.run_id,
            principal_type=effective_challenge.requesting_principal_type,
            worktree_roots=effective_challenge.requesting_worktree_roots,
            binding_version=new_binding_version,
            updated_at=now,
        )
        lock = StoryExecutionLockRecord(
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=active.run_id,
            lock_type="story_execution",
            status="ACTIVE",
            worktree_roots=effective_challenge.requesting_worktree_roots,
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
                challenge_ref=effective_challenge.challenge_id,
                confirm_ref=request.op_id,
            )
            for repo in repo_evidence
        )
        bundle = _build_edge_bundle(
            binding=new_binding,
            lock=lock,
            sync_class="mutation",
            now=now,
            tombstone_worktree_roots=owner_binding.worktree_roots,
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
            request,
            result=result,
            now=now,
            run_id=active.run_id,
        )
        request_result = ControlPlaneMutationResult(
            status="approved",
            op_id=effective_challenge.request_op_id,
            operation_kind=_TAKEOVER_REQUEST,
            run_id=active.run_id,
            phase=_TAKEOVER_PHASE,
        )
        request_record = _terminal_request_operation_record(
            self._repo.load_operation(effective_challenge.request_op_id),
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
            effective_challenge,
            status="confirmed",
            terminal_op_id=request.op_id,
            now=now,
        )
        event_specs: tuple[tuple[EventType, dict[str, object]], ...] = (
            (
                EventType.SESSION_RUN_BINDING_TRANSFERRED,
                {
                    "previous_owner_session_id": owner_binding.session_id,
                    "new_owner_session_id": effective_challenge.requesting_session_id,
                    "ownership_epoch": new_epoch,
                },
            ),
            (
                EventType.SESSION_DISOWNED,
                {
                    "previous_owner_session_id": owner_binding.session_id,
                    "reason": "ownership_transferred",
                },
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
            expected_owner_session_id=owner_binding.session_id,
            expected_ownership_epoch=active.ownership_epoch,
            expected_binding_version=owner_binding.binding_version,
            revoked_binding=revoked_binding,
            new_binding=new_binding,
            locks=(lock,),
            transfers=transfer_records,
            events=events,
            terminal_records=TakeoverConfirmTerminalRecords(
                challenge=terminal_challenge,
                request_op_record=request_record,
                challenge_to_insert=challenge_to_insert,
                challenge_to_expire=challenge_to_expire,
                approved_approval=approval_state.approved_approval,
            ),
        )
        return result

    def _expired_takeover_confirm_result(
        self,
        *,
        request: TakeoverChallengeEchoRequest,
        challenge: TakeoverChallengeRecord,
        approval_state: _ConfirmApprovalState,
        now: datetime,
    ) -> ControlPlaneMutationResult | None:
        if (
            approval_state.approval is not None
            and approval_state.approval.status is TakeoverApprovalStatus.EXPIRED
        ):
            return self._commit_takeover_expiry(
                request=request,
                challenge=challenge,
                expired_approval=approval_state.approval,
                now=now,
                reason="approval_not_approved",
                error_code="approval_not_approved",
            )
        if now < challenge.expires_at or approval_state.approved_approval is not None:
            return None
        return self._commit_takeover_expiry(
            request=request,
            challenge=challenge,
            expired_approval=None,
            now=now,
            reason="challenge_expired",
            error_code="challenge_expired",
        )

    def _commit_takeover_expiry(
        self,
        *,
        request: TakeoverChallengeEchoRequest,
        challenge: TakeoverChallengeRecord,
        expired_approval: TakeoverApprovalRecord | None,
        now: datetime,
        reason: str,
        error_code: str,
    ) -> ControlPlaneMutationResult:
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
                request,
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

    def _deny_ownership_takeover_under_claim(
        self,
        request: TakeoverDenyRequest,
    ) -> ControlPlaneMutationResult:
        now = self._now_fn()
        approval = self._repo.load_takeover_approval(request.approval_id)
        if approval is None:
            return _takeover_rejection(
                op_id=request.op_id,
                operation_kind=_TAKEOVER_DENY,
                reason="takeover_approval_not_found",
                error_code="takeover_approval_not_found",
            )
        if approval.project_key != request.project_key or approval.story_id != request.story_id:
            return _takeover_rejection(
                op_id=request.op_id,
                operation_kind=_TAKEOVER_DENY,
                reason="takeover_approval_scope_mismatch",
                error_code="takeover_approval_scope_mismatch",
                run_id=approval.run_id,
            )
        if approval.status is not TakeoverApprovalStatus.PENDING or now >= approval.expires_at:
            return _takeover_rejection(
                op_id=request.op_id,
                operation_kind=_TAKEOVER_DENY,
                reason="takeover_approval_not_pending",
                error_code="takeover_approval_not_pending",
                run_id=approval.run_id,
            )
        challenge = self._repo.load_takeover_challenge(approval.challenge_ref)
        if challenge is None:
            return _takeover_rejection(
                op_id=request.op_id,
                operation_kind=_TAKEOVER_DENY,
                reason="takeover_challenge_required",
                error_code="takeover_challenge_required",
                run_id=approval.run_id,
            )
        request_operation = self._repo.load_operation(challenge.request_op_id)
        if request_operation is None:
            return _takeover_rejection(
                op_id=request.op_id,
                operation_kind=_TAKEOVER_DENY,
                reason="takeover_request_operation_required",
                error_code="takeover_request_operation_required",
                run_id=approval.run_id,
            )
        denied_approval = _denied_approval_record(approval, request=request, now=now)
        result = ControlPlaneMutationResult(
            status="denied",
            op_id=request.op_id,
            operation_kind=_TAKEOVER_DENY,
            run_id=approval.run_id,
            phase=_TAKEOVER_PHASE,
        )
        request_result = ControlPlaneMutationResult(
            status="denied",
            op_id=challenge.request_op_id,
            operation_kind=_TAKEOVER_REQUEST,
            run_id=approval.run_id,
            phase=_TAKEOVER_PHASE,
            pending_human_approval=PendingHumanApprovalResponse(
                op_id=challenge.request_op_id,
                approval_id=approval.approval_id,
                message="takeover_approval_denied",
                approval=_approval_view(denied_approval),
            ),
        )
        event = _lifecycle_event_record(
            event_type=EventType.TAKEOVER_APPROVAL_CHANGED,
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=approval.run_id,
            source_component=request.source_component,
            payload=_approval_changed_payload(denied_approval),
            now=now,
            phase=_TAKEOVER_PHASE,
        )
        self._repo.commit_takeover_deny(
            _takeover_operation_record(
                request,
                result=result,
                now=now,
                run_id=approval.run_id,
            ),
            request_op_record=_denied_request_operation_record(
                request_operation,
                response_payload=request_result.model_dump(mode="json"),
                now=now,
            ),
            denied_approval=denied_approval,
            challenge=_terminal_challenge_record(
                challenge,
                status="denied",
                terminal_op_id=request.op_id,
                now=now,
            ),
            events=(event,),
        )
        return result


def _invalidating_transition_rejection(
    repo: ControlPlaneRuntimeRepository,
    request: TakeoverChallengeEchoRequest,
    challenge: TakeoverChallengeRecord,
) -> ControlPlaneMutationResult | None:
    if not repo.has_committed_ownership_invalidating_operation_for_run(
        request.project_key,
        request.story_id,
        challenge.run_id,
    ):
        return None
    return _challenge_invalidated_rejection(request, run_id=challenge.run_id)


def _ownership_basis_changed(
    active: RunOwnershipRecord | None,
    challenge: TakeoverChallengeRecord,
) -> bool:
    return (
        active is None
        or active.status is not OwnershipStatus.ACTIVE
        or active.owner_session_id != challenge.owner_session_id
        or active.ownership_epoch != challenge.ownership_epoch
    )


def _challenge_invalidated_rejection(
    request: TakeoverChallengeEchoRequest,
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
