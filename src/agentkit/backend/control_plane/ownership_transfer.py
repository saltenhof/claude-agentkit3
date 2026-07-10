"""Ownership-transfer challenge, approval, and CAS decision core.

Blood-type A: pure value assembly and decisions over caller-provided records.
No persistence, clock, HTTP, SQL, or event emission lives here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Literal

from agentkit.backend.control_plane.ownership import OwnershipStatus, TakeoverApprovalStatus
from agentkit.backend.core_types.freeze import (
    ActiveFreezeState,
    command_resolves_freeze,
)

if TYPE_CHECKING:
    from datetime import datetime

    from agentkit.backend.control_plane.records import (
        RunOwnershipRecord,
        SessionRunBindingRecord,
        TakeoverChallengeRecord,
    )

LOSS_CORRIDOR_TEXT = (
    "Only the pushed state at the listed takeover_base_sha is transferred. "
    "Unpushed commits, uncommitted changes, and untracked files of the previous "
    "session are not transferred; they may be quarantined locally, but they are "
    "not an AgentKit handover object."
)


class TakeoverConfirmFailure(StrEnum):
    """Machine-readable confirm failure causes."""

    CHALLENGE_EXPIRED = "challenge_expired"
    CHALLENGE_INVALIDATED = "challenge_invalidated"
    OWNERSHIP_EPOCH_MISMATCH = "ownership_epoch_mismatch"
    BINDING_VERSION_MISMATCH = "binding_version_mismatch"
    OWNER_SESSION_MISMATCH = "owner_session_mismatch"
    OWNERSHIP_NOT_ACTIVE = "ownership_not_active"
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_NOT_APPROVED = "approval_not_approved"
    PUSHED_HEAD_REQUIRED = "pushed_head_required"
    DISOWNED_SESSION_CANNOT_IMMEDIATELY_RECLAIM = (
        "disowned_session_cannot_immediately_reclaim"
    )
    REPEAT_TRANSFER_REQUIRES_PRIVILEGED_PRINCIPAL_AND_REASON = (
        "repeat_transfer_requires_privileged_principal_and_reason"
    )
    STORY_NOT_TAKEOVER_ADMISSIBLE = "story_not_takeover_admissible"


InvalidationReason = Literal["transfer", "exit", "reset", "split", "closure", "freeze"]


@dataclass(frozen=True)
class OwnershipBasis:
    """Canonical CAS basis of a takeover decision (FK-56 §56.13a)."""

    owner_session_id: str
    ownership_epoch: int
    binding_version: str

    def __post_init__(self) -> None:
        if not self.owner_session_id.strip():
            raise ValueError("owner_session_id must not be empty")
        if self.ownership_epoch < 1:
            raise ValueError("ownership_epoch must be >= 1")
        if not self.binding_version.strip():
            raise ValueError("binding_version must not be empty")


@dataclass(frozen=True)
class TakeoverRepoChallenge:
    """Per-repository pushed-only handover evidence shown in the challenge."""

    repo_id: str
    takeover_base_sha: str | None
    last_push_at: datetime | None
    push_lag_hint: str | None
    base_quality: str

    def __post_init__(self) -> None:
        if not self.repo_id.strip():
            raise ValueError("repo_id must not be empty")
        if not self.base_quality.strip():
            raise ValueError("base_quality must not be empty")


@dataclass(frozen=True)
class TakeoverChallenge:
    """Versioned decision basis for a takeover request."""

    challenge_id: str
    project_key: str
    story_id: str
    run_id: str
    requesting_session_id: str
    requesting_principal_type: str
    current_owner_session_id: str
    ownership_epoch: int
    binding_version: str
    phase_status: str
    owner_principal_type: str
    owner_bound_since: datetime | None
    last_owner_api_contact_at: datetime | None
    last_owner_api_contact_note: str
    open_operation_ids: tuple[str, ...]
    takeover_history_refs: tuple[str, ...]
    repos: tuple[TakeoverRepoChallenge, ...]
    reason: str
    loss_corridor_notice_key: str
    loss_corridor_notice_text: str
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        for value_name in (
            "challenge_id",
            "project_key",
            "story_id",
            "run_id",
            "requesting_session_id",
            "requesting_principal_type",
            "current_owner_session_id",
            "binding_version",
            "phase_status",
            "owner_principal_type",
            "reason",
            "loss_corridor_notice_key",
            "loss_corridor_notice_text",
        ):
            if not str(getattr(self, value_name)).strip():
                raise ValueError(f"{value_name} must not be empty")
        if self.ownership_epoch < 1:
            raise ValueError("ownership_epoch must be >= 1")


@dataclass(frozen=True)
class TakeoverConfirmDecision:
    """Pure CAS decision result for takeover confirm."""

    accepted: bool
    failure: TakeoverConfirmFailure | None = None


def build_takeover_challenge(
    *,
    challenge_id: str,
    active_record: RunOwnershipRecord,
    owner_binding: SessionRunBindingRecord,
    requesting_session_id: str,
    requesting_principal_type: str,
    phase_status: str,
    last_owner_api_contact_at: datetime | None,
    open_operation_ids: tuple[str, ...],
    takeover_history_refs: tuple[str, ...],
    repos: tuple[TakeoverRepoChallenge, ...],
    reason: str,
    expires_at: datetime | None,
) -> TakeoverChallenge:
    """Assemble the versioned challenge from owner-BC records supplied by ports."""

    return TakeoverChallenge(
        challenge_id=challenge_id,
        project_key=active_record.project_key,
        story_id=active_record.story_id,
        run_id=active_record.run_id,
        requesting_session_id=requesting_session_id,
        requesting_principal_type=requesting_principal_type,
        current_owner_session_id=active_record.owner_session_id,
        ownership_epoch=active_record.ownership_epoch,
        binding_version=owner_binding.binding_version,
        phase_status=phase_status,
        owner_principal_type=owner_binding.principal_type,
        owner_bound_since=owner_binding.updated_at,
        last_owner_api_contact_at=last_owner_api_contact_at,
        last_owner_api_contact_note="last_owner_api_contact_is_observational_not_diagnostic",
        open_operation_ids=open_operation_ids,
        takeover_history_refs=takeover_history_refs,
        repos=repos,
        reason=reason,
        loss_corridor_notice_key="pushed_only_loss_corridor",
        loss_corridor_notice_text=LOSS_CORRIDOR_TEXT,
        expires_at=expires_at,
    )


def ownership_basis_of_active(
    active_record: RunOwnershipRecord | None,
    owner_binding: SessionRunBindingRecord | None,
) -> OwnershipBasis | None:
    """Return the current full basis, failing closed on any scope mismatch."""

    if active_record is None or active_record.status is not OwnershipStatus.ACTIVE:
        return None
    if owner_binding is None or owner_binding.status != "active":
        return None
    if (
        owner_binding.session_id != active_record.owner_session_id
        or owner_binding.project_key != active_record.project_key
        or owner_binding.story_id != active_record.story_id
        or owner_binding.run_id != active_record.run_id
    ):
        return None
    return OwnershipBasis(
        owner_session_id=active_record.owner_session_id,
        ownership_epoch=active_record.ownership_epoch,
        binding_version=owner_binding.binding_version,
    )


def ownership_basis_of_challenge(challenge: TakeoverChallengeRecord) -> OwnershipBasis:
    """Return the immutable full basis persisted on a takeover challenge."""

    return OwnershipBasis(
        owner_session_id=challenge.owner_session_id,
        ownership_epoch=challenge.ownership_epoch,
        binding_version=challenge.binding_version,
    )


def ownership_basis_unchanged(
    active_basis: OwnershipBasis | None,
    challenge_basis: OwnershipBasis,
) -> bool:
    """Compare the complete confirm-CAS basis."""

    return active_basis == challenge_basis


def ownership_anchor_unchanged(
    active_basis: OwnershipBasis | None,
    challenge_basis: OwnershipBasis,
) -> bool:
    """Compare only owner and epoch for expired-challenge reissue eligibility."""

    return (
        active_basis is not None
        and active_basis.owner_session_id == challenge_basis.owner_session_id
        and active_basis.ownership_epoch == challenge_basis.ownership_epoch
    )


def evaluate_takeover_confirm(
    *,
    active_basis: OwnershipBasis | None,
    challenge_basis: OwnershipBasis,
    now: datetime,
    challenge_expires_at: datetime | None,
    approval_status: TakeoverApprovalStatus | None,
    approval_required: bool,
    repo_evidence: tuple[TakeoverRepoChallenge, ...],
    current_epoch_disowned_session_id: str | None,
    beneficiary_session_id: str,
    requesting_principal_type: str,
    request_reason: str,
    current_epoch_was_takeover: bool,
    active_freezes: tuple[ActiveFreezeState, ...] = (),
) -> TakeoverConfirmDecision:
    """Evaluate the technology-free confirm preconditions before the row CAS."""

    admissibility_failure = evaluate_takeover_admissibility(active_freezes)
    if admissibility_failure is not None:
        return TakeoverConfirmDecision(False, admissibility_failure)
    if not ownership_basis_unchanged(active_basis, challenge_basis):
        return TakeoverConfirmDecision(False, TakeoverConfirmFailure.CHALLENGE_INVALIDATED)
    if challenge_expires_at is not None and now >= challenge_expires_at:
        return TakeoverConfirmDecision(False, TakeoverConfirmFailure.CHALLENGE_EXPIRED)
    if approval_required and approval_status is None:
        return TakeoverConfirmDecision(False, TakeoverConfirmFailure.APPROVAL_REQUIRED)
    if approval_required and approval_status is not TakeoverApprovalStatus.APPROVED:
        return TakeoverConfirmDecision(False, TakeoverConfirmFailure.APPROVAL_NOT_APPROVED)
    ping_pong_failure = evaluate_disowned_session_takeover_barrier(
        current_epoch_disowned_session_id=current_epoch_disowned_session_id,
        beneficiary_session_id=beneficiary_session_id,
        requesting_principal_type=requesting_principal_type,
        request_reason=request_reason,
        current_epoch_was_takeover=current_epoch_was_takeover,
    )
    if ping_pong_failure is not None:
        return TakeoverConfirmDecision(False, ping_pong_failure)
    if not repo_evidence:
        return TakeoverConfirmDecision(False, TakeoverConfirmFailure.PUSHED_HEAD_REQUIRED)
    if any(repo.takeover_base_sha is None or not repo.takeover_base_sha.strip() for repo in repo_evidence):
        return TakeoverConfirmDecision(False, TakeoverConfirmFailure.PUSHED_HEAD_REQUIRED)
    return TakeoverConfirmDecision(True)


def approval_status_after_expiry(
    *,
    current_status: TakeoverApprovalStatus,
    now: datetime,
    expires_at: datetime,
) -> TakeoverApprovalStatus:
    """Materialize lazy expiry as a DENIED-family terminal state."""

    if current_status is TakeoverApprovalStatus.PENDING and now >= expires_at:
        return TakeoverApprovalStatus.EXPIRED
    return current_status


def challenge_invalidated_by_transition(reason: InvalidationReason) -> TakeoverConfirmFailure:
    """Return the stable invalidation result for ownership-boundary transitions."""

    del reason
    return TakeoverConfirmFailure.CHALLENGE_INVALIDATED


def evaluate_takeover_admissibility(
    active_freezes: tuple[ActiveFreezeState, ...],
) -> TakeoverConfirmFailure | None:
    """Apply the Rule-8 takeover precondition independently of ownership basis."""

    if any(
        not command_resolves_freeze("ownership_takeover_confirm", freeze)
        for freeze in active_freezes
    ):
        return TakeoverConfirmFailure.STORY_NOT_TAKEOVER_ADMISSIBLE
    return None


def evaluate_disowned_session_takeover_barrier(
    *,
    current_epoch_disowned_session_id: str | None,
    beneficiary_session_id: str,
    requesting_principal_type: str,
    request_reason: str,
    current_epoch_was_takeover: bool,
) -> TakeoverConfirmFailure | None:
    """Evaluate both epoch-scoped ping-pong prongs from explicit inputs."""

    privileged_with_reason = (
        requesting_principal_type in {"human_cli", "admin_service"}
        and bool(request_reason.strip())
    )
    if (
        current_epoch_disowned_session_id is not None
        and current_epoch_disowned_session_id == beneficiary_session_id
        and not privileged_with_reason
    ):
        return TakeoverConfirmFailure.DISOWNED_SESSION_CANNOT_IMMEDIATELY_RECLAIM
    if current_epoch_was_takeover and not privileged_with_reason:
        return (
            TakeoverConfirmFailure.REPEAT_TRANSFER_REQUIRES_PRIVILEGED_PRINCIPAL_AND_REASON
        )
    return None


def requires_human_approval(principal_type: str) -> bool:
    """Return whether a request path must wait for a human approval."""

    return principal_type in {"interactive_agent", "orchestrator"}
