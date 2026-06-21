"""Governance-specific exception types.

All governance exceptions derive from ``agentkit.backend.exceptions.GovernanceError``.
"""

from __future__ import annotations

from agentkit.backend.exceptions import GovernanceError


class HookRegistrationError(GovernanceError):
    """Raised when a hook cannot be registered.

    Produced by ``Governance.register_hooks`` and stored inside
    ``RegistrationResult.errors`` for non-fatal failures, or raised
    directly for fatal backend errors.
    """


class LockRecordNotFoundError(GovernanceError):
    """Raised when no lock records are found for a story_id.

    FK-30 §30.6.0 fail-closed: ``Governance.deactivate_locks`` must not
    silently ignore an unknown story_id — the Closure-Phase cannot forget
    a lock.  Raised by ``LockRecordRepository.deactivate_locks_for_story``
    when the story has no known lock records.

    AG3-031 Pass-3 FK-30-Korrektur 2026-05-24 (Fix E6).
    """


class ModeLockConflictError(GovernanceError):
    """Atomic mode-lock ``acquire`` failed: the opposite mode is held.

    FK-24 §24.3.3 (AG3-018): the enforcement half of the Fast/Standard
    between-modes mutex. Raised by
    ``ModeLockRepository.acquire`` (the last-writer CAS, behind Preflight
    Check 10) when a fast story tries to start while a standard mode is held
    (or vice versa). A governance concept, so it lives here -- the
    state-backend repository imports it from this module, the same pattern as
    ``LockRecordNotFoundError`` (governance owns the error; state_backend.store
    never owns governance semantics).
    """


class StoryModeResolutionError(GovernanceError):
    """The authoritative story ``mode`` could not be resolved at Setup (fail-closed).

    FK-24 §24.3.3/§24.3.4 (AG3-018, FIX-1): Setup derives the operative
    fast/standard ``mode`` from the AUTHORITATIVE ``StoryService`` record, NOT
    from GitHub labels (GitHub fields are setup INPUT, not operative truth,
    CLAUDE.md). Raised when the story cannot be found in the authoritative store,
    so Setup fails closed instead of silently falling back to a label-derived or
    default mode (an unverifiable mode would let an invalid Fast/Standard run
    proceed).
    """


__all__ = [
    "HookRegistrationError",
    "LockRecordNotFoundError",
    "ModeLockConflictError",
    "StoryModeResolutionError",
]
