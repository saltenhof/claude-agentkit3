"""Pure recovery capability and admissibility decisions (blood-type A).

The caller supplies already-read ownership, freeze, and reconcile facts. This
module performs no I/O, SQL, clock access, or identifier minting.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from agentkit.backend.control_plane.ownership import OwnershipStatus
from agentkit.backend.control_plane.ownership_transfer import (
    evaluate_disowned_session_takeover_barrier,
)

if TYPE_CHECKING:
    from agentkit.backend.control_plane.records import RunOwnershipRecord
    from agentkit.backend.core_types.freeze import ActiveFreezeState


class RecoveryFailure(StrEnum):
    """Stable fail-closed recovery rejection reasons."""

    RECOVERY_REQUIRES_HUMAN_CLI = "recovery_requires_human_cli"
    RECOVERY_REASON_REQUIRED = "recovery_reason_required"
    NOTHING_TO_RECOVER = "nothing_to_recover"
    MULTIPLE_ACTIVE_OWNERSHIP_RECORDS = "multiple_active_ownership_records"
    COMPETING_ACTIVE_OWNERSHIP = "competing_active_ownership"
    RECOVERY_BLOCKED_BY_FREEZE = "recovery_blocked_by_freeze"
    TAKEOVER_RECONCILE_REQUIRED = "takeover_reconcile_required"
    DISOWNED_SESSION_CANNOT_IMMEDIATELY_RECLAIM = (
        "disowned_session_cannot_immediately_reclaim"
    )
    REPEAT_TRANSFER_REQUIRES_PRIVILEGED_PRINCIPAL_AND_REASON = (
        "repeat_transfer_requires_privileged_principal_and_reason"
    )


@dataclass(frozen=True)
class RecoveryDecision:
    """Pure recovery decision and the one record it may supersede."""

    admitted: bool
    superseded_record: RunOwnershipRecord | None = None
    failure: RecoveryFailure | None = None


def evaluate_recovery_capability(
    *,
    principal_type: str,
    beneficiary_session_id: str,
    reason: str,
    current_epoch_disowned_session_id: str | None,
    current_epoch_was_takeover: bool,
) -> RecoveryFailure | None:
    """Enforce the human-only gate and the shared AG3-149 ping-pong barrier."""

    if principal_type != "human_cli":
        return RecoveryFailure.RECOVERY_REQUIRES_HUMAN_CLI
    if not reason.strip():
        return RecoveryFailure.RECOVERY_REASON_REQUIRED
    barrier = evaluate_disowned_session_takeover_barrier(
        current_epoch_disowned_session_id=current_epoch_disowned_session_id,
        beneficiary_session_id=beneficiary_session_id,
        requesting_principal_type=principal_type,
        request_reason=reason,
        current_epoch_was_takeover=current_epoch_was_takeover,
    )
    if barrier is None:
        return None
    return RecoveryFailure(barrier.value)


def evaluate_recovery_admissibility(
    *,
    active_records: tuple[RunOwnershipRecord, ...],
    superseded_run_id: str,
    active_freezes: tuple[ActiveFreezeState, ...],
    has_unreconciled_takeover: bool,
) -> RecoveryDecision:
    """Admit only an exact one-active-record supersede with no blockers."""

    active = tuple(
        record for record in active_records if record.status is OwnershipStatus.ACTIVE
    )
    if not active:
        return RecoveryDecision(False, failure=RecoveryFailure.NOTHING_TO_RECOVER)
    if len(active) != 1:
        return RecoveryDecision(
            False,
            failure=RecoveryFailure.MULTIPLE_ACTIVE_OWNERSHIP_RECORDS,
        )
    superseded = active[0]
    if superseded.run_id != superseded_run_id:
        return RecoveryDecision(
            False,
            failure=RecoveryFailure.COMPETING_ACTIVE_OWNERSHIP,
        )
    if active_freezes:
        return RecoveryDecision(
            False,
            failure=RecoveryFailure.RECOVERY_BLOCKED_BY_FREEZE,
        )
    if has_unreconciled_takeover:
        return RecoveryDecision(
            False,
            failure=RecoveryFailure.TAKEOVER_RECONCILE_REQUIRED,
        )
    return RecoveryDecision(True, superseded_record=superseded)


__all__ = (
    "RecoveryDecision",
    "RecoveryFailure",
    "evaluate_recovery_admissibility",
    "evaluate_recovery_capability",
)
