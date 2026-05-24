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


__all__ = ["HookRegistrationError"]
