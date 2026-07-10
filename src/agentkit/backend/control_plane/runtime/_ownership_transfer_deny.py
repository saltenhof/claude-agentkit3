"""Human-exclusive takeover denial runtime path."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.control_plane.models import (
    ControlPlaneMutationResult,
    PendingHumanApprovalResponse,
)
from agentkit.backend.control_plane.ownership import TakeoverApprovalStatus
from agentkit.backend.exceptions import OwnershipFenceViolationError
from agentkit.backend.governance.principal_capabilities.principals import Principal
from agentkit.backend.telemetry.events import EventType

from ._operation_records import _lifecycle_event_record, _object_claim_busy_rejection
from ._ownership_transfer_support import (
    _TAKEOVER_DENY,
    _TAKEOVER_PHASE,
    _TAKEOVER_REQUEST,
    _approval_changed_payload,
    _approval_view,
    _denied_approval_record,
    _denied_request_operation_record,
    _load_takeover_existing_operation,
    _takeover_operation_record,
    _takeover_rejection,
    _terminal_challenge_record,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from agentkit.backend.control_plane import object_claims
    from agentkit.backend.control_plane.repository import ControlPlaneRuntimeRepository
    from agentkit.backend.control_plane.runtime._ownership_transfer_commands import (
        TakeoverDenyCommand,
    )


class _OwnershipTransferDenyMixin:
    """Deny pending agent takeover approvals using attested human identity."""

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

    def deny_ownership_takeover(
        self,
        *,
        command: TakeoverDenyCommand,
    ) -> ControlPlaneMutationResult:
        """Deny a pending agent-initiated takeover approval."""
        request = command.request
        if command.denied_by_principal is not Principal.HUMAN_CLI:
            return _takeover_rejection(
                op_id=request.op_id,
                operation_kind=_TAKEOVER_DENY,
                reason="agent_deny_forbidden",
                error_code="agent_deny_forbidden",
            )
        existing = _load_takeover_existing_operation(
            self._repo,
            command,
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
            result = self._deny_ownership_takeover_under_claim(command)
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

    def _deny_ownership_takeover_under_claim(
        self,
        command: TakeoverDenyCommand,
    ) -> ControlPlaneMutationResult:
        request = command.request
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
        denied_approval = _denied_approval_record(approval, command=command, now=now)
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
                command,
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


__all__ = ["_OwnershipTransferDenyMixin"]
