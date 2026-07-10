"""Support helpers for ownership takeover runtime orchestration."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from agentkit.backend.control_plane import ownership_transfer as transfer_core
from agentkit.backend.control_plane.models import (
    ControlPlaneMutationResult,
    TakeoverApprovalView,
    TakeoverChallenge,
    TakeoverChallengeEchoRequest,
    TakeoverDenyRequest,
    TakeoverRepoChallenge,
    TakeoverRequest,
)
from agentkit.backend.control_plane.ownership import TakeoverApprovalStatus
from agentkit.backend.control_plane.records import (
    ControlPlaneOperationRecord,
    SessionRunBindingRecord,
    TakeoverApprovalRecord,
    TakeoverChallengeRecord,
    TakeoverChallengeRepoRecord,
    TakeoverTransferRecord,
)
from agentkit.backend.state_backend.store.inflight_idempotency_guard import (
    compute_body_hash,
)

from ._operation_records import _operation_record, _rejection_result

if TYPE_CHECKING:
    from datetime import datetime

    from agentkit.backend.control_plane.push_sync import (
        PushBarrierVerdict,
        PushFreshnessRecord,
    )
    from agentkit.backend.control_plane.records import RunOwnershipRecord
    from agentkit.backend.control_plane.repository import (
        ControlPlaneRuntimeRepository,
        TakeoverApprovalRepository,
    )

_TAKEOVER_REQUEST = "ownership_takeover_request"
_TAKEOVER_CONFIRM = "ownership_takeover_confirm"
_TAKEOVER_DENY = "ownership_takeover_deny"
_TAKEOVER_PHASE = "ownership"
_CHALLENGE_TTL = timedelta(minutes=15)
_APPROVAL_TTL = timedelta(hours=2)
_AGENT_PRINCIPAL_TYPES = frozenset({"interactive_agent", "orchestrator"})
_CANONICAL_PRINCIPAL_TYPES = frozenset(
    {
        "interactive_agent",
        "orchestrator",
        "worker",
        "qa_reader",
        "adversarial_writer",
        "llm_evaluator",
        "pipeline_deterministic",
        "human_cli",
        "admin_service",
    }
)


@dataclass(frozen=True)
class _ConfirmApprovalState:
    status: TakeoverApprovalStatus | None
    approval: TakeoverApprovalRecord | None
    approved_approval: TakeoverApprovalRecord | None
    repo: TakeoverApprovalRepository | None


@dataclass(frozen=True)
class _StoredChallengeLookup:
    challenge: TakeoverChallengeRecord | None
    rejection: ControlPlaneMutationResult | None


@dataclass(frozen=True)
class _ChallengeReissueResult:
    effective_challenge: TakeoverChallengeRecord
    challenge_to_insert: TakeoverChallengeRecord | None
    challenge_to_expire: TakeoverChallengeRecord | None
    approval_state: _ConfirmApprovalState
    owner_binding: SessionRunBindingRecord | None
    rejection: ControlPlaneMutationResult | None


def _load_pending_takeover_challenge(
    repo: ControlPlaneRuntimeRepository,
    request: TakeoverChallengeEchoRequest,
) -> _StoredChallengeLookup:
    challenge = repo.load_takeover_challenge(request.challenge_echo.challenge_id)
    if challenge is None:
        return _StoredChallengeLookup(
            None,
            _takeover_rejection(
                op_id=request.op_id,
                operation_kind=_TAKEOVER_CONFIRM,
                reason="challenge_not_found",
                error_code="challenge_not_found",
            ),
        )
    if challenge.project_key != request.project_key or challenge.story_id != request.story_id:
        return _StoredChallengeLookup(
            None,
            _takeover_rejection(
                op_id=request.op_id,
                operation_kind=_TAKEOVER_CONFIRM,
                reason="challenge_scope_mismatch",
                error_code="challenge_scope_mismatch",
                run_id=challenge.run_id,
            ),
        )
    if challenge.status != "pending":
        return _StoredChallengeLookup(
            None,
            _takeover_rejection(
                op_id=request.op_id,
                operation_kind=_TAKEOVER_CONFIRM,
                reason="challenge_not_pending",
                error_code="challenge_not_pending",
                run_id=challenge.run_id,
            ),
        )
    return _StoredChallengeLookup(challenge, None)


def _maybe_reissue_expired_challenge(
    repo: ControlPlaneRuntimeRepository,
    *,
    request: TakeoverChallengeEchoRequest,
    stored_challenge: TakeoverChallengeRecord,
    active: RunOwnershipRecord | None,
    approval_state: _ConfirmApprovalState,
    now: datetime,
) -> _ChallengeReissueResult:
    if now < stored_challenge.expires_at or approval_state.approved_approval is None:
        return _ChallengeReissueResult(
            stored_challenge,
            None,
            None,
            approval_state,
            None,
            None,
        )
    if active is None:
        return _ChallengeReissueResult(
            stored_challenge,
            None,
            None,
            approval_state,
            None,
            _takeover_rejection(
                op_id=request.op_id,
                operation_kind=_TAKEOVER_CONFIRM,
                reason="active_ownership_required",
                error_code="active_ownership_required",
                run_id=stored_challenge.run_id,
            ),
        )
    if (
        active.owner_session_id != stored_challenge.owner_session_id
        or active.ownership_epoch != stored_challenge.ownership_epoch
    ):
        return _ChallengeReissueResult(
            stored_challenge,
            None,
            None,
            approval_state,
            None,
            _takeover_rejection(
                op_id=request.op_id,
                operation_kind=_TAKEOVER_CONFIRM,
                reason="challenge_invalidated",
                error_code="challenge_invalidated",
                run_id=stored_challenge.run_id,
            ),
        )
    owner_binding = repo.load_binding(active.owner_session_id)
    if owner_binding is None:
        return _ChallengeReissueResult(
            stored_challenge,
            None,
            None,
            approval_state,
            None,
            _takeover_rejection(
                op_id=request.op_id,
                operation_kind=_TAKEOVER_CONFIRM,
                reason="owner_binding_required",
                error_code="owner_binding_required",
                run_id=stored_challenge.run_id,
            ),
        )
    fresh_core = _build_takeover_challenge(
        repo,
        request=TakeoverRequest(
            project_key=request.project_key,
            story_id=request.story_id,
            session_id=stored_challenge.requesting_session_id,
            principal_type=stored_challenge.requesting_principal_type,
            op_id=stored_challenge.request_op_id,
            reason=stored_challenge.reason,
            worktree_roots=list(stored_challenge.requesting_worktree_roots),
            source_component=request.source_component,
        ),
        active_record=active,
        owner_binding=owner_binding,
        expires_at=now + _CHALLENGE_TTL,
    )
    fresh_challenge = _challenge_record_from_core(
        fresh_core,
        request_op_id=stored_challenge.request_op_id,
        issued_at=now,
        requesting_worktree_roots=stored_challenge.requesting_worktree_roots,
    )
    fresh_approval_state = _ConfirmApprovalState(
        approval_state.status,
        approval_state.approval,
        _approval_with_challenge_ref(
            approval_state.approved_approval,
            challenge_ref=fresh_challenge.challenge_id,
        ),
        approval_state.repo,
    )
    return _ChallengeReissueResult(
        fresh_challenge,
        fresh_challenge,
        _terminal_challenge_record(
            stored_challenge,
            status="expired",
            terminal_op_id=request.op_id,
            now=now,
        ),
        fresh_approval_state,
        owner_binding,
        None,
    )


def _build_takeover_challenge(
    repo: ControlPlaneRuntimeRepository,
    *,
    request: TakeoverRequest,
    active_record: RunOwnershipRecord,
    owner_binding: SessionRunBindingRecord,
    expires_at: datetime,
) -> transfer_core.TakeoverChallenge:
    lock = repo.load_lock(
        request.project_key,
        request.story_id,
        active_record.run_id,
        "story_execution",
    )
    repos = _repo_evidence(
        repo,
        request.project_key,
        request.story_id,
        active_record.run_id,
        allow_unpushed=True,
    )
    return transfer_core.build_takeover_challenge(
        challenge_id=f"takeover-challenge-{uuid.uuid4().hex}",
        active_record=active_record,
        owner_binding=owner_binding,
        requesting_session_id=request.session_id,
        requesting_principal_type=request.principal_type,
        phase_status=lock.status if lock is not None else "unknown",
        last_owner_api_contact_at=owner_binding.updated_at,
        open_operation_ids=tuple(
            op_id
            for op_id in repo.list_open_operation_ids_for_story(
                request.project_key,
                request.story_id,
            )
            if op_id != request.op_id
        ),
        takeover_history_refs=_takeover_history_refs(
            repo.list_takeover_history(request.project_key, request.story_id),
        ),
        repos=repos,
        reason=request.reason,
        expires_at=expires_at,
    )

def _repo_evidence(
    repo: ControlPlaneRuntimeRepository,
    project_key: str,
    story_id: str,
    run_id: str,
    *,
    allow_unpushed: bool = False,
) -> tuple[transfer_core.TakeoverRepoChallenge, ...]:
    if not run_id:
        return ()
    records = repo.list_push_freshness(project_key, story_id, run_id)
    if not allow_unpushed:
        freshness_by_repo = {record.repo_id: record for record in records}
        verdicts = repo.list_verified_push_barrier_verdicts_for_run(
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
    repo: ControlPlaneRuntimeRepository,
    request: TakeoverRequest | TakeoverChallengeEchoRequest | TakeoverDenyRequest,
    *,
    operation_kind: str,
) -> ControlPlaneMutationResult | None:
    stored = repo.load_operation(request.op_id)
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
    request: TakeoverRequest | TakeoverChallengeEchoRequest | TakeoverDenyRequest,
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
    request: TakeoverRequest | TakeoverChallengeEchoRequest | TakeoverDenyRequest,
    *,
    operation_kind: str,
) -> str:
    payload = dict(request.model_dump(mode="json"))
    payload["__operation_kind"] = operation_kind
    payload["__phase"] = _TAKEOVER_PHASE
    return compute_body_hash(payload)


def _confirm_approval_state(
    repo: ControlPlaneRuntimeRepository,
    request: TakeoverChallengeEchoRequest,
    now: datetime,
    *,
    challenge: TakeoverChallengeRecord,
    approval_required: bool,
) -> _ConfirmApprovalState:
    if request.approval_id is None:
        if not approval_required:
            return _ConfirmApprovalState(None, None, None, None)
        return _ConfirmApprovalState(None, None, None, None)
    approval = repo.load_takeover_approval(request.approval_id)
    if approval is None:
        return _ConfirmApprovalState(None, None, None, None)
    if (
        approval.project_key != request.project_key
        or approval.story_id != request.story_id
        or approval.run_id != challenge.run_id
        or approval.challenge_ref != challenge.challenge_id
        or approval.requested_by_session_id != challenge.requesting_session_id
        or approval.requested_by_principal_type != challenge.requesting_principal_type
    ):
        return _ConfirmApprovalState(None, None, None, None)
    approval_status = transfer_core.approval_status_after_expiry(
        current_status=approval.status,
        now=now,
        expires_at=approval.expires_at,
    )
    if approval_status is not approval.status:
        expired = _expired_approval_record(approval, now=now)
        return _ConfirmApprovalState(approval_status, expired, None, None)
    if approval.status is TakeoverApprovalStatus.PENDING:
        approved = _approved_approval_record(approval, request=request, now=now)
        return _ConfirmApprovalState(
            TakeoverApprovalStatus.APPROVED,
            approval,
            approved,
            None,
        )
    return _ConfirmApprovalState(approval_status, approval, None, None)


def _expired_approval_record(
    approval: TakeoverApprovalRecord,
    *,
    now: datetime,
) -> TakeoverApprovalRecord:
    return TakeoverApprovalRecord(
        approval_id=approval.approval_id,
        project_key=approval.project_key,
        story_id=approval.story_id,
        run_id=approval.run_id,
        requested_by_session_id=approval.requested_by_session_id,
        requested_by_principal_type=approval.requested_by_principal_type,
        reason=approval.reason,
        challenge_ref=approval.challenge_ref,
        status=TakeoverApprovalStatus.EXPIRED,
        requested_at=approval.requested_at,
        expires_at=approval.expires_at,
        decided_at=now,
        decision_reason="approval_expired",
    )


def _approved_approval_record(
    approval: TakeoverApprovalRecord,
    *,
    request: TakeoverChallengeEchoRequest,
    now: datetime,
) -> TakeoverApprovalRecord:
    return TakeoverApprovalRecord(
        approval_id=approval.approval_id,
        project_key=approval.project_key,
        story_id=approval.story_id,
        run_id=approval.run_id,
        requested_by_session_id=approval.requested_by_session_id,
        requested_by_principal_type=approval.requested_by_principal_type,
        reason=approval.reason,
        challenge_ref=approval.challenge_ref,
        status=TakeoverApprovalStatus.APPROVED,
        requested_at=approval.requested_at,
        expires_at=approval.expires_at,
        decided_at=now,
        decided_by_session_id=request.session_id,
        decision_reason="human_confirm",
    )


def _approval_with_challenge_ref(
    approval: TakeoverApprovalRecord,
    *,
    challenge_ref: str,
) -> TakeoverApprovalRecord:
    return TakeoverApprovalRecord(
        approval_id=approval.approval_id,
        project_key=approval.project_key,
        story_id=approval.story_id,
        run_id=approval.run_id,
        requested_by_session_id=approval.requested_by_session_id,
        requested_by_principal_type=approval.requested_by_principal_type,
        reason=approval.reason,
        challenge_ref=challenge_ref,
        status=approval.status,
        requested_at=approval.requested_at,
        expires_at=approval.expires_at,
        decided_at=approval.decided_at,
        decided_by_session_id=approval.decided_by_session_id,
        decision_reason=approval.decision_reason,
    )


def _denied_approval_record(
    approval: TakeoverApprovalRecord,
    *,
    request: TakeoverDenyRequest,
    now: datetime,
) -> TakeoverApprovalRecord:
    return TakeoverApprovalRecord(
        approval_id=approval.approval_id,
        project_key=approval.project_key,
        story_id=approval.story_id,
        run_id=approval.run_id,
        requested_by_session_id=approval.requested_by_session_id,
        requested_by_principal_type=approval.requested_by_principal_type,
        reason=approval.reason,
        challenge_ref=approval.challenge_ref,
        status=TakeoverApprovalStatus.DENIED,
        requested_at=approval.requested_at,
        expires_at=approval.expires_at,
        decided_at=now,
        decided_by_session_id=request.session_id,
        decision_reason=request.reason,
    )


def _denied_request_operation_record(
    operation: ControlPlaneOperationRecord,
    *,
    response_payload: dict[str, object],
    now: datetime,
) -> ControlPlaneOperationRecord:
    return ControlPlaneOperationRecord(
        op_id=operation.op_id,
        project_key=operation.project_key,
        story_id=operation.story_id,
        run_id=operation.run_id,
        session_id=operation.session_id,
        operation_kind=operation.operation_kind,
        phase=operation.phase,
        status="denied",
        response_payload=response_payload,
        created_at=operation.created_at,
        updated_at=now,
        claimed_by=operation.claimed_by,
        claimed_at=operation.claimed_at,
        operation_epoch=operation.operation_epoch,
        backend_instance_id=operation.backend_instance_id,
        instance_incarnation=operation.instance_incarnation,
        declared_serialization_scope=operation.declared_serialization_scope,
        finalized_at=now,
        request_body_hash=operation.request_body_hash,
    )


def _terminal_request_operation_record(
    operation: ControlPlaneOperationRecord | None,
    *,
    response_payload: dict[str, object],
    status: str,
    now: datetime,
) -> ControlPlaneOperationRecord | None:
    if operation is None:
        return None
    return ControlPlaneOperationRecord(
        op_id=operation.op_id,
        project_key=operation.project_key,
        story_id=operation.story_id,
        run_id=operation.run_id,
        session_id=operation.session_id,
        operation_kind=operation.operation_kind,
        phase=operation.phase,
        status=status,
        response_payload=response_payload,
        created_at=operation.created_at,
        updated_at=now,
        claimed_by=operation.claimed_by,
        claimed_at=operation.claimed_at,
        operation_epoch=operation.operation_epoch,
        backend_instance_id=operation.backend_instance_id,
        instance_incarnation=operation.instance_incarnation,
        declared_serialization_scope=operation.declared_serialization_scope,
        finalized_at=now,
        request_body_hash=operation.request_body_hash,
    )


def _terminal_challenge_record(
    challenge: TakeoverChallengeRecord,
    *,
    status: str,
    terminal_op_id: str,
    now: datetime,
) -> TakeoverChallengeRecord:
    return TakeoverChallengeRecord(
        challenge_id=challenge.challenge_id,
        request_op_id=challenge.request_op_id,
        project_key=challenge.project_key,
        story_id=challenge.story_id,
        run_id=challenge.run_id,
        requesting_session_id=challenge.requesting_session_id,
        requesting_principal_type=challenge.requesting_principal_type,
        requesting_worktree_roots=challenge.requesting_worktree_roots,
        reason=challenge.reason,
        owner_session_id=challenge.owner_session_id,
        ownership_epoch=challenge.ownership_epoch,
        binding_version=challenge.binding_version,
        phase_status=challenge.phase_status,
        issued_at=challenge.issued_at,
        expires_at=challenge.expires_at,
        repos=challenge.repos,
        open_operation_ids=challenge.open_operation_ids,
        takeover_history_refs=challenge.takeover_history_refs,
        status=status,
        decided_at=now,
        terminal_op_id=terminal_op_id,
    )


def _challenge_record_from_core(
    challenge: transfer_core.TakeoverChallenge,
    *,
    request_op_id: str,
    issued_at: datetime,
    requesting_worktree_roots: tuple[str, ...],
) -> TakeoverChallengeRecord:
    return TakeoverChallengeRecord(
        challenge_id=challenge.challenge_id,
        request_op_id=request_op_id,
        project_key=challenge.project_key,
        story_id=challenge.story_id,
        run_id=challenge.run_id,
        requesting_session_id=challenge.requesting_session_id,
        requesting_principal_type=challenge.requesting_principal_type,
        requesting_worktree_roots=requesting_worktree_roots,
        reason=challenge.reason,
        owner_session_id=challenge.current_owner_session_id,
        ownership_epoch=challenge.ownership_epoch,
        binding_version=challenge.binding_version,
        phase_status=challenge.phase_status,
        issued_at=issued_at,
        expires_at=challenge.expires_at or issued_at + _CHALLENGE_TTL,
        repos=tuple(
            TakeoverChallengeRepoRecord(
                repo_id=repo.repo_id,
                takeover_base_sha=repo.takeover_base_sha,
                last_push_at=repo.last_push_at,
                push_lag_hint=repo.push_lag_hint,
                base_quality=repo.base_quality,
            )
            for repo in challenge.repos
        ),
        open_operation_ids=challenge.open_operation_ids,
        takeover_history_refs=challenge.takeover_history_refs,
    )


def _takeover_history_refs(records: tuple[TakeoverTransferRecord, ...]) -> tuple[str, ...]:
    refs: list[str] = []
    for record in records:
        if record.confirm_ref is not None:
            refs.append(record.confirm_ref)
        elif record.challenge_ref is not None:
            refs.append(record.challenge_ref)
    return tuple(dict.fromkeys(refs))


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
