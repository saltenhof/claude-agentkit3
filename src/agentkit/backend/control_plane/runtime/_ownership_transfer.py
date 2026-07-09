"""Ownership-transfer takeover request and confirm runtime block."""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from typing import TYPE_CHECKING

from agentkit.backend.control_plane import ownership_transfer as transfer_core
from agentkit.backend.control_plane.models import (
    ControlPlaneMutationResult,
    PendingHumanApprovalResponse,
    TakeoverApprovalView,
    TakeoverChallenge,
    TakeoverChallengeEchoRequest,
    TakeoverRepoChallenge,
    TakeoverRequest,
)
from agentkit.backend.control_plane.ownership import (
    OWNERSHIP_TRANSFERRED_REVOCATION_REASON,
    BindingStatus,
    TakeoverApprovalStatus,
)
from agentkit.backend.control_plane.records import (
    SessionRunBindingRecord,
    TakeoverApprovalRecord,
    TakeoverTransferRecord,
)
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

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from agentkit.backend.control_plane import object_claims
    from agentkit.backend.control_plane.push_sync import (
        PushBarrierVerdict,
        PushFreshnessRecord,
    )
    from agentkit.backend.control_plane.records import ControlPlaneOperationRecord, RunOwnershipRecord
    from agentkit.backend.control_plane.repository import ControlPlaneRuntimeRepository

logger = logging.getLogger(__name__)

_TAKEOVER_REQUEST = "ownership_takeover_request"
_TAKEOVER_CONFIRM = "ownership_takeover_confirm"
_TAKEOVER_PHASE = "ownership"
_CHALLENGE_TTL = timedelta(minutes=15)
_APPROVAL_TTL = timedelta(hours=2)
_AGENT_PRINCIPAL_TYPES = frozenset({"interactive_agent", "orchestrator", "agent"})


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
        existing = self._load_takeover_existing_operation(
            request,
            operation_kind=_TAKEOVER_REQUEST,
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
        existing = self._load_takeover_existing_operation(
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
                self._takeover_operation_record(request, result=result, now=now)
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
                self._takeover_operation_record(
                    request,
                    result=result,
                    now=now,
                    run_id=active.run_id,
                )
            )
            return result
        challenge = self._build_takeover_challenge(
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
            from agentkit.backend.control_plane.repository import (
                TakeoverApprovalRepository,
            )

            TakeoverApprovalRepository().insert_approval(approval)
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
            self._takeover_operation_record(
                request,
                result=result,
                now=now,
                run_id=active.run_id,
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
        active = self._repo.load_active_ownership(request.project_key, request.story_id)
        owner_binding = (
            self._repo.load_binding(request.challenge_echo.owner_session_id)
            if active is not None
            else None
        )
        repo_evidence = self._repo_evidence(
            request.project_key,
            request.story_id,
            active.run_id if active is not None else "",
        )
        approval_status = None
        approval = None
        approved_approval = None
        approval_repo = None
        if request.approval_id is not None:
            from agentkit.backend.control_plane.repository import (
                TakeoverApprovalRepository,
            )

            approval_repo = TakeoverApprovalRepository()
            approval = approval_repo.load_approval(request.approval_id)
            if approval is not None:
                approval_status = transfer_core.approval_status_after_expiry(
                    current_status=approval.status,
                    now=now,
                    expires_at=approval.expires_at,
                )
                if approval_status is not approval.status:
                    approval = TakeoverApprovalRecord(
                        approval_id=approval.approval_id,
                        project_key=approval.project_key,
                        story_id=approval.story_id,
                        run_id=approval.run_id,
                        requested_by_session_id=approval.requested_by_session_id,
                        requested_by_principal_type=(
                            approval.requested_by_principal_type
                        ),
                        reason=approval.reason,
                        challenge_ref=approval.challenge_ref,
                        status=approval_status,
                        requested_at=approval.requested_at,
                        expires_at=approval.expires_at,
                        decided_at=now,
                        decision_reason="approval_expired",
                    )
                elif approval.status is TakeoverApprovalStatus.PENDING:
                    approval_status = TakeoverApprovalStatus.APPROVED
                    approved_approval = TakeoverApprovalRecord(
                        approval_id=approval.approval_id,
                        project_key=approval.project_key,
                        story_id=approval.story_id,
                        run_id=approval.run_id,
                        requested_by_session_id=approval.requested_by_session_id,
                        requested_by_principal_type=(
                            approval.requested_by_principal_type
                        ),
                        reason=approval.reason,
                        challenge_ref=approval.challenge_ref,
                        status=TakeoverApprovalStatus.APPROVED,
                        requested_at=approval.requested_at,
                        expires_at=approval.expires_at,
                        decided_at=now,
                        decided_by_session_id=request.session_id,
                        decision_reason="human_confirm",
                    )
        core_echo = transfer_core.TakeoverChallengeEcho(
            challenge_id=request.challenge_echo.challenge_id,
            owner_session_id=request.challenge_echo.owner_session_id,
            ownership_epoch=request.challenge_echo.ownership_epoch,
            binding_version=request.challenge_echo.binding_version,
        )
        decision = transfer_core.evaluate_takeover_confirm(
            active_record=active,
            owner_binding=owner_binding,
            echo=core_echo,
            now=now,
            challenge_expires_at=request.challenge_echo.expires_at,
            approval_status=approval_status,
            approval_required=request.approval_id is not None,
            repo_evidence=repo_evidence,
        )
        if not decision.accepted:
            if (
                decision.failure
                is transfer_core.TakeoverConfirmFailure.APPROVAL_NOT_APPROVED
                and approval is not None
                and approval.status is TakeoverApprovalStatus.EXPIRED
            ):
                assert approval_repo is not None
                approval_repo.update_status(approval)
                self._repo.append_event(
                    _lifecycle_event_record(
                        event_type=EventType.TAKEOVER_APPROVAL_CHANGED,
                        project_key=request.project_key,
                        story_id=request.story_id,
                        run_id=approval.run_id,
                        source_component=request.source_component,
                        payload=_approval_changed_payload(approval),
                        now=now,
                        phase=_TAKEOVER_PHASE,
                    )
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
            session_id=request.session_id,
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=active.run_id,
            principal_type=request.principal_type,
            worktree_roots=tuple(request.worktree_roots),
            binding_version=new_binding_version,
            updated_at=now,
        )
        lock = StoryExecutionLockRecord(
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=active.run_id,
            lock_type="story_execution",
            status="ACTIVE",
            worktree_roots=tuple(request.worktree_roots),
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
                challenge_ref=request.challenge_echo.challenge_id,
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
        record = self._takeover_operation_record(
            request,
            result=result,
            now=now,
            run_id=active.run_id,
        )
        event_specs: tuple[tuple[EventType, dict[str, object]], ...] = (
            (
                EventType.SESSION_RUN_BINDING_TRANSFERRED,
                {
                    "previous_owner_session_id": owner_binding.session_id,
                    "new_owner_session_id": request.session_id,
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
        if approved_approval is not None:
            event_specs += (
                (
                    EventType.TAKEOVER_APPROVAL_CHANGED,
                    _approval_changed_payload(approved_approval),
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
            approved_approval=approved_approval,
        )
        return result

    def _build_takeover_challenge(
        self,
        *,
        request: TakeoverRequest,
        active_record: RunOwnershipRecord,
        owner_binding: SessionRunBindingRecord,
        expires_at: datetime,
    ) -> transfer_core.TakeoverChallenge:
        lock = self._repo.load_lock(
            request.project_key,
            request.story_id,
            active_record.run_id,
            "story_execution",
        )
        repos = self._repo_evidence(
            request.project_key,
            request.story_id,
            active_record.run_id,
            allow_unpushed=True,
        )
        return transfer_core.build_takeover_challenge(
            challenge_id=f"takeover-{request.op_id}",
            active_record=active_record,
            owner_binding=owner_binding,
            requesting_session_id=request.session_id,
            requesting_principal_type=request.principal_type,
            phase_status=lock.status if lock is not None else "unknown",
            last_owner_api_contact_at=owner_binding.updated_at,
            open_operation_ids=(),
            takeover_history_refs=(),
            repos=repos,
            reason=request.reason,
            expires_at=expires_at,
        )

    def _repo_evidence(
        self,
        project_key: str,
        story_id: str,
        run_id: str,
        *,
        allow_unpushed: bool = False,
    ) -> tuple[transfer_core.TakeoverRepoChallenge, ...]:
        if not run_id:
            return ()
        records = self._repo.list_push_freshness(project_key, story_id, run_id)
        if not allow_unpushed:
            freshness_by_repo = {record.repo_id: record for record in records}
            verdicts = self._repo.list_verified_push_barrier_verdicts_for_run(
                project_key,
                story_id,
                run_id,
            )
            evidence = tuple(
                _repo_challenge_from_verified_barrier(verdict, freshness_by_repo)
                for verdict in verdicts
            )
            verdict_repo_ids = {repo.repo_id for repo in evidence}
            missing_repos = sorted(set(freshness_by_repo) - verdict_repo_ids)
            if missing_repos:
                evidence += tuple(
                    transfer_core.TakeoverRepoChallenge(
                        repo_id=repo_id,
                        takeover_base_sha=None,
                        last_push_at=freshness_by_repo[repo_id].last_reported_at,
                        push_lag_hint="missing_verified_push_barrier",
                        base_quality="missing_verified_push_barrier",
                    )
                    for repo_id in missing_repos
                )
            return evidence
        return tuple(
            _repo_challenge_from_freshness(record, allow_unpushed=allow_unpushed)
            for record in records
        )

    def _load_takeover_existing_operation(
        self,
        request: TakeoverRequest | TakeoverChallengeEchoRequest,
        *,
        operation_kind: str,
    ) -> ControlPlaneMutationResult | None:
        stored = self._repo.load_operation(request.op_id)
        if stored is None or stored.status == "claimed":
            return None
        stored_hash = stored.request_body_hash
        if stored_hash is not None:
            incoming = _takeover_body_hash(request, operation_kind=operation_kind)
            if incoming != stored_hash:
                from agentkit.backend.story_context_manager.errors import (
                    IdempotencyMismatchError,
                )

                raise IdempotencyMismatchError(
                    f"op_id {request.op_id!r} was previously used with a "
                    "different takeover request body",
                    detail={"op_id": request.op_id, "conflict": "body_hash_mismatch"},
                )
        return ControlPlaneMutationResult.model_validate(stored.response_payload)

    def _takeover_operation_record(
        self,
        request: TakeoverRequest | TakeoverChallengeEchoRequest,
        *,
        result: ControlPlaneMutationResult,
        now: datetime,
        run_id: str | None = None,
    ) -> ControlPlaneOperationRecord:
        return _operation_record(
            op_id=request.op_id,
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=run_id,
            session_id=request.session_id,
            operation_kind=result.operation_kind,
            phase=_TAKEOVER_PHASE,
            result=result,
            now=now,
            request_body_hash=_takeover_body_hash(
                request,
                operation_kind=result.operation_kind,
            ),
        )


def _takeover_body_hash(
    request: TakeoverRequest | TakeoverChallengeEchoRequest,
    *,
    operation_kind: str,
) -> str:
    payload = dict(request.model_dump(mode="json"))
    payload["__operation_kind"] = operation_kind
    payload["__phase"] = _TAKEOVER_PHASE
    return compute_body_hash(payload)


def _takeover_rejection(
    *,
    op_id: str,
    operation_kind: str,
    reason: str,
    error_code: str,
    run_id: str | None = None,
) -> ControlPlaneMutationResult:
    result = _rejection_result(
        op_id=op_id,
        operation_kind=operation_kind,
        run_id=run_id,
        phase=_TAKEOVER_PHASE,
        reason=reason,
        dispatch_phase=_TAKEOVER_PHASE,
    )
    return ControlPlaneMutationResult.model_validate(
        {**result.model_dump(mode="json"), "error_code": error_code}
    )


def _approval_view(record: TakeoverApprovalRecord) -> TakeoverApprovalView:
    return TakeoverApprovalView(
        approval_id=record.approval_id,
        project_key=record.project_key,
        story_id=record.story_id,
        run_id=record.run_id,
        requested_by_session_id=record.requested_by_session_id,
        requested_by_principal_type=record.requested_by_principal_type,
        reason=record.reason,
        challenge_ref=record.challenge_ref,
        status=record.status.value,
        requested_at=record.requested_at,
        expires_at=record.expires_at,
        decided_at=record.decided_at,
        decided_by_session_id=record.decided_by_session_id,
        decision_reason=record.decision_reason,
    )


def _approval_changed_payload(record: TakeoverApprovalRecord) -> dict[str, object]:
    return {
        "project_key": record.project_key,
        "story_id": record.story_id,
        "approval_id": record.approval_id,
        "approval": _approval_view(record).model_dump(mode="json"),
    }


def _challenge_view(challenge: transfer_core.TakeoverChallenge) -> TakeoverChallenge:
    return TakeoverChallenge(
        challenge_id=challenge.challenge_id,
        project_key=challenge.project_key,
        story_id=challenge.story_id,
        run_id=challenge.run_id,
        requesting_session_id=challenge.requesting_session_id,
        requesting_principal_type=challenge.requesting_principal_type,
        current_owner_session_id=challenge.current_owner_session_id,
        ownership_epoch=challenge.ownership_epoch,
        binding_version=challenge.binding_version,
        phase_status=challenge.phase_status,
        owner_principal_type=challenge.owner_principal_type,
        owner_bound_since=challenge.owner_bound_since,
        last_owner_api_contact_at=challenge.last_owner_api_contact_at,
        last_owner_api_contact_note=challenge.last_owner_api_contact_note,
        open_operation_ids=list(challenge.open_operation_ids),
        takeover_history_refs=list(challenge.takeover_history_refs),
        repos=[
            TakeoverRepoChallenge(
                repo_id=repo.repo_id,
                takeover_base_sha=repo.takeover_base_sha,
                last_push_at=repo.last_push_at,
                push_lag_hint=repo.push_lag_hint,
                base_quality=repo.base_quality,
            )
            for repo in challenge.repos
        ],
        reason=challenge.reason,
        loss_corridor_notice_key=challenge.loss_corridor_notice_key,
        loss_corridor_notice_text=challenge.loss_corridor_notice_text,
        expires_at=challenge.expires_at,
    )


def _repo_challenge_from_freshness(
    record: PushFreshnessRecord,
    *,
    allow_unpushed: bool,
) -> transfer_core.TakeoverRepoChallenge:
    pushed_sha = record.last_pushed_head_sha
    if pushed_sha is None and allow_unpushed:
        base_quality = "unpushed"
    elif pushed_sha is None:
        base_quality = "missing_pushed_head"
    elif record.backlog:
        base_quality = "pushed_with_backlog"
    else:
        base_quality = "pushed"
    return transfer_core.TakeoverRepoChallenge(
        repo_id=record.repo_id,
        takeover_base_sha=pushed_sha,
        last_push_at=record.last_reported_at if pushed_sha is not None else None,
        push_lag_hint=record.backlog_detail,
        base_quality=base_quality,
    )


def _repo_challenge_from_verified_barrier(
    verdict: PushBarrierVerdict,
    freshness_by_repo: dict[str, PushFreshnessRecord],
) -> transfer_core.TakeoverRepoChallenge:
    freshness = freshness_by_repo.get(verdict.repo_id)
    expected_head_sha = verdict.expected_head_sha
    if freshness is None:
        return transfer_core.TakeoverRepoChallenge(
            repo_id=verdict.repo_id,
            takeover_base_sha=expected_head_sha,
            last_push_at=verdict.resolved_at or verdict.updated_at,
            push_lag_hint=None,
            base_quality="verified_pushed",
        )
    # PushFreshnessRecord is a read projection. Confirm accepts its head only
    # after it matches the server+edge verified PushBarrierVerdict head.
    if freshness.last_pushed_head_sha != expected_head_sha:
        return transfer_core.TakeoverRepoChallenge(
            repo_id=verdict.repo_id,
            takeover_base_sha=None,
            last_push_at=freshness.last_reported_at,
            push_lag_hint="push_freshness_barrier_head_mismatch",
            base_quality="push_freshness_barrier_head_mismatch",
        )
    return transfer_core.TakeoverRepoChallenge(
        repo_id=verdict.repo_id,
        takeover_base_sha=expected_head_sha,
        last_push_at=freshness.last_reported_at,
        push_lag_hint=freshness.backlog_detail,
        base_quality="verified_pushed",
    )


__all__ = ["_OwnershipTransferMixin"]
