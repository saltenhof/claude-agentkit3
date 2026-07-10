"""Ownership admission A-core (FK-56 §56.8a, blood-type A: pure domain rules).

Answers exactly one question, technology-free: given the story's active
:class:`~agentkit.backend.control_plane.records.RunOwnershipRecord` (already
loaded by the caller) and the mutating call's ``(run_id, session_id)``, is the
call admitted? This is the SINGLE replacement for the retired committed-op
admission heuristic (``_run_admission_evidence``, IMPL-021): a historical
record (any ``status`` other than ``active``) is never admission evidence
(``historical_ownership_records_are_never_admission_evidence``), and the
session-side binding is never consulted here -- on a contradiction between the
binding and the active record, the record decides (FK-56 §56.7/§56.8, SOLL-019).

No I/O, no transactions (AT-free): the persistence layer loads the record; this
module only classifies it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from agentkit.backend.core_types.freeze import (
    ERROR_CODE_STORY_FROZEN,
    ActiveFreezeState,
    command_resolves_freeze,
)

if TYPE_CHECKING:
    from agentkit.backend.control_plane.records import RunOwnershipRecord

__all__ = (
    "ERROR_CODE_OWNERSHIP_TRANSFERRED",
    "ERROR_CODE_STORY_FROZEN",
    "OwnershipAdmission",
    "OwnershipRejectionReason",
    "evaluate_ownership_admission",
)

#: FK-91 §91.1a Rule 8/18: the stable, machine-readable ``error_code`` for the
#: ex-owner rejection (``ControlPlaneMutationResult.error_code``).
ERROR_CODE_OWNERSHIP_TRANSFERRED = "ownership_transferred"


class OwnershipRejectionReason(StrEnum):
    """Closed classification of why a mutation was NOT admitted.

    ``STORY_EXITED`` is the AG3-058 transition-protection short-circuit (the
    exit-fence negative check kept as an explicit reason so callers can build a
    plain "run is terminal" message rather than an ``ownership_transferred``
    one). ``NO_ACTIVE_RECORD`` covers both "never admitted" (setup never
    committed) and "historical" (the story's ownership ended/reset/split/closed
    -- ``load_active_ownership`` returns ``None`` for any non-``active``
    status). ``RUN_MISMATCH`` is the active record belonging to a DIFFERENT run
    of the same story. ``OWNERSHIP_TRANSFERRED`` is the genuine ex-owner case:
    an active record for THIS run exists but its ``owner_session_id`` is not
    the caller's -- the only reason that carries the FK-91 §91.1a Rule 18
    structured payload.
    """

    STORY_EXITED = "story_exited"
    NO_ACTIVE_RECORD = "no_active_record"
    RUN_MISMATCH = "run_mismatch"
    OWNERSHIP_TRANSFERRED = "ownership_transferred"
    FREEZE_ACTIVE = "freeze_active"


@dataclass(frozen=True)
class OwnershipAdmission:
    """The admission verdict for one mutating call.

    ``active_record`` is carried through even on a rejection (when one was
    loaded) so the caller can build the ``ownership_transferred`` detail
    payload (new owner, transfer instant) without a second read.
    """

    admitted: bool
    active_record: RunOwnershipRecord | None
    rejection_reason: OwnershipRejectionReason | None
    blocking_freeze: ActiveFreezeState | None = None


def evaluate_ownership_admission(
    *,
    active_record: RunOwnershipRecord | None,
    run_id: str,
    session_id: str,
    active_freezes: tuple[ActiveFreezeState, ...] = (),
    command_id: str = "",
) -> OwnershipAdmission:
    """Classify admission from an already-loaded active ownership record.

    Args:
        active_record: The story's active :class:`RunOwnershipRecord`, or
            ``None`` when none exists (never admitted, or the story's
            ownership has ended/reset/split/closed -- audit-only records are
            never returned as "active").
        run_id: The authoritative run id of the mutating call.
        session_id: The caller's session id.

    Returns:
        The :class:`OwnershipAdmission` verdict. Admitted iff an active record
        exists for THIS run and its ``owner_session_id`` matches the caller.
    """
    for freeze in active_freezes:
        if not command_resolves_freeze(command_id, freeze):
            return OwnershipAdmission(
                admitted=False,
                active_record=active_record,
                rejection_reason=OwnershipRejectionReason.FREEZE_ACTIVE,
                blocking_freeze=freeze,
            )
    if active_record is None:
        return OwnershipAdmission(
            admitted=False,
            active_record=None,
            rejection_reason=OwnershipRejectionReason.NO_ACTIVE_RECORD,
        )
    if active_record.run_id != run_id:
        return OwnershipAdmission(
            admitted=False,
            active_record=active_record,
            rejection_reason=OwnershipRejectionReason.RUN_MISMATCH,
        )
    if active_record.owner_session_id != session_id:
        return OwnershipAdmission(
            admitted=False,
            active_record=active_record,
            rejection_reason=OwnershipRejectionReason.OWNERSHIP_TRANSFERRED,
        )
    return OwnershipAdmission(admitted=True, active_record=active_record, rejection_reason=None)
