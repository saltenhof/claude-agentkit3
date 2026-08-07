"""Lock-deactivation data models for the governance BC.

Defines ``LockRecordId`` and ``DeactivationResult`` as the canonical typed
surface for ``Governance.deactivate_locks``.

Sources:
- FK-30 §30.6.0 — ``Governance.deactivate_locks`` top-surface
- FK-29 §29.5   — Closure-Pfad (ClosureSequence calls deactivate_locks)

AG3-239: the result is pure canonical state. The three filesystem-reporting
fields it used to carry are gone -- see ``DeactivationResult``.
"""

from __future__ import annotations

from typing import NewType

from pydantic import BaseModel, ConfigDict

LockRecordId = NewType("LockRecordId", str)
"""Opaque identifier for a single story-execution lock record."""


class DeactivationResult(BaseModel):
    """Result of a ``deactivate_locks`` call.

    Attributes:
        deactivated_locks: IDs of lock records set to INACTIVE in the backend.
        guards_deactivated: True when the canonical lock state now says the
            story holds no active lock -- the condition under which branch
            guard, orchestrator guard and QA protection stop applying (FK-30
            §30.6.0). True for an already-deactivated story (idempotent
            re-entry); False only when the story is unknown to the lock
            repository, because then nothing was proven about its guards.
        errors: Non-fatal errors encountered during deactivation (including
            LockRecordNotFoundError surfaced by the repository).
            Critical DB errors are raised, not stored here.

    AG3-239: three fields describing developer-machine files are gone --
    ``removed_edge_bundles``, ``removed_lock_exports`` and the old
    ``restored_to_ai_augmented``. They reported on writes the CORE made into
    ``_temp/governance/**``, which is the EDGE's local projection directory
    (FK-30 §30.6.1 reads ``_temp/governance/current.json`` in the hook process).
    Those writes only ever worked because both sides ran on one machine, and
    ``restored_to_ai_augmented`` was true only when a CWD-relative legacy
    directory happened to exist. Story exit gated on that flag, so on a core
    host it would have rejected every exit. The mode restoration on the edge is
    carried by the tombstone projection (AG3-145 sub-step D, FK-10 §10.2.4a),
    not by the backend.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    deactivated_locks: list[LockRecordId] = []
    guards_deactivated: bool = False
    errors: list[str] = []


__all__ = [
    "DeactivationResult",
    "LockRecordId",
]
