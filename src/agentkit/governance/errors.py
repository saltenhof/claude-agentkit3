"""Governance-specific exception types.

All governance exceptions derive from ``agentkit.exceptions.GovernanceError``.
"""

from __future__ import annotations

from agentkit.exceptions import GovernanceError


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


__all__ = ["HookRegistrationError", "LockRecordNotFoundError"]
