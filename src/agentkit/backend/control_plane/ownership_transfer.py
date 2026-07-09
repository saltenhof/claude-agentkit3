"""Ownership-transfer challenge, approval, and CAS decision core.

Blood-type A: pure value assembly and decisions over caller-provided records.
No persistence, clock, HTTP, SQL, or event emission lives here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Literal

from agentkit.backend.control_plane.ownership import OwnershipStatus, TakeoverApprovalStatus

if TYPE_CHECKING:
    from datetime import datetime

    from agentkit.backend.control_plane.records import (
        RunOwnershipRecord,
        SessionRunBindingRecord,
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


InvalidationReason = Literal["transfer", "exit", "reset", "split", "closure"]


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
class TakeoverChallengeEcho:
    """CAS-signature echoed by a confirm request."""

    challenge_id: str
    owner_session_id: str
    ownership_epoch: int
    binding_version: str

    def __post_init__(self) -> None:
        if not self.challenge_id.strip() or not self.owner_session_id.strip():
            raise ValueError("challenge_id and owner_session_id must not be empty")
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


def evaluate_takeover_confirm(
    *,
    active_record: RunOwnershipRecord | None,
    owner_binding: SessionRunBindingRecord | None,
    echo: TakeoverChallengeEcho,
    now: datetime,
    challenge_expires_at: datetime | None,
    approval_status: TakeoverApprovalStatus | None,
    approval_required: bool,
    repo_evidence: tuple[TakeoverRepoChallenge, ...],
) -> TakeoverConfirmDecision:
    """Evaluate the technology-free confirm preconditions before the row CAS."""

    if challenge_expires_at is not None and now >= challenge_expires_at:
        return TakeoverConfirmDecision(False, TakeoverConfirmFailure.CHALLENGE_EXPIRED)
    if active_record is None or active_record.status is not OwnershipStatus.ACTIVE:
        return TakeoverConfirmDecision(False, TakeoverConfirmFailure.OWNERSHIP_NOT_ACTIVE)
    if active_record.owner_session_id != echo.owner_session_id:
        return TakeoverConfirmDecision(False, TakeoverConfirmFailure.OWNER_SESSION_MISMATCH)
    if active_record.ownership_epoch != echo.ownership_epoch:
        return TakeoverConfirmDecision(False, TakeoverConfirmFailure.OWNERSHIP_EPOCH_MISMATCH)
    if owner_binding is None or owner_binding.binding_version != echo.binding_version:
        return TakeoverConfirmDecision(False, TakeoverConfirmFailure.BINDING_VERSION_MISMATCH)
    if approval_required and approval_status is None:
        return TakeoverConfirmDecision(False, TakeoverConfirmFailure.APPROVAL_REQUIRED)
    if approval_required and approval_status is not TakeoverApprovalStatus.APPROVED:
        return TakeoverConfirmDecision(False, TakeoverConfirmFailure.APPROVAL_NOT_APPROVED)
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


def requires_human_approval(principal_type: str) -> bool:
    """Return whether a request path must wait for a human approval."""

    return principal_type in {"interactive_agent", "orchestrator"}
