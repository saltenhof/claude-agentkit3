"""Pure disown consequence planning for every official revocation path.

Blood-type A: callers provide an active binding plus the path reason and this
module derives the complete, technology-free consequence plan. Persistence,
runtime orchestration, path services, clocks, and event emission stay at the
edges. The five official callers are ownership transfer, recovery, story exit,
story reset, and story split (FK-56 §56.13h; AG3-149 D1/D3; AG3-154 D1).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from agentkit.backend.control_plane.ownership import (
    BindingRevocationReason,
    BindingStatus,
    OwnershipStatus,
)
from agentkit.backend.control_plane.records import SessionRunBindingRecord

if TYPE_CHECKING:
    from datetime import datetime

__all__ = ("DisownPlan", "build_disown_plan")


_OWNERSHIP_STATUS_TARGETS: dict[BindingRevocationReason, OwnershipStatus | None] = {
    BindingRevocationReason.OWNERSHIP_TRANSFERRED: None,
    BindingRevocationReason.RECOVERY_SUPERSEDED: OwnershipStatus.TRANSFERRED,
    BindingRevocationReason.STORY_ENDED: OwnershipStatus.ENDED,
    BindingRevocationReason.STORY_RESET: OwnershipStatus.RESET,
    BindingRevocationReason.STORY_SPLIT: OwnershipStatus.SPLIT,
}


@dataclass(frozen=True)
class DisownPlan:
    """Uniform consequences of revoking one active session binding."""

    reason: BindingRevocationReason
    revoked_binding: SessionRunBindingRecord
    ownership_status_target: OwnershipStatus | None
    audit_payload: dict[str, object]
    tombstone_worktree_roots: tuple[str, ...]
    reconcile_operating_mode: Literal["binding_invalid"]
    reconcile_reason: str


def build_disown_plan(
    binding: SessionRunBindingRecord,
    path_reason: BindingRevocationReason,
    now: datetime,
) -> DisownPlan:
    """Build the shared revoke/audit/tombstone/reconcile plan.

    Args:
        binding: The active binding being withdrawn.
        path_reason: One of the five official machine-readable path reasons.
        now: Caller-owned timestamp for the revoked projection.

    Returns:
        The complete pure consequence plan consumed by the path transaction.

    Raises:
        ValueError: If the input binding is not active or the reason is outside
            the closed five-path vocabulary.
    """

    if binding.status != BindingStatus.ACTIVE.value:
        raise ValueError("disown requires an active session-run binding")
    try:
        ownership_status_target = _OWNERSHIP_STATUS_TARGETS[path_reason]
    except KeyError as exc:
        raise ValueError(f"unsupported disown path reason: {path_reason!r}") from exc

    revoked_binding = SessionRunBindingRecord(
        session_id=binding.session_id,
        project_key=binding.project_key,
        story_id=binding.story_id,
        run_id=binding.run_id,
        principal_type=binding.principal_type,
        worktree_roots=binding.worktree_roots,
        binding_version=binding.binding_version,
        updated_at=now,
        status=BindingStatus.REVOKED.value,
        revocation_reason=path_reason.value,
    )
    return DisownPlan(
        reason=path_reason,
        revoked_binding=revoked_binding,
        ownership_status_target=ownership_status_target,
        audit_payload={
            "previous_owner_session_id": binding.session_id,
            "reason": path_reason.value,
        },
        tombstone_worktree_roots=binding.worktree_roots,
        reconcile_operating_mode="binding_invalid",
        reconcile_reason=path_reason.value,
    )
