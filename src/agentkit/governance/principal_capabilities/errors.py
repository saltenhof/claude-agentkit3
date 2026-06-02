"""Exceptions for the principal-capability model (FK-55).

All exceptions inherit from :class:`PrincipalCapabilityError`. They are raised
only for *programming* / wiring faults (e.g. a corrupt freeze export). Capability
*decisions* are NEVER exceptions — an unknown principal/path/operation or a
missing matrix triple resolves fail-closed to a ``DENY``
:class:`~agentkit.governance.principal_capabilities.matrix.CapabilityVerdict`
(FK-55 §55.3a, §55.10.2). Keeping decisions return-based mirrors the
``GuardVerdict`` discipline of the surrounding GuardSystem (ARCH-20).
"""

from __future__ import annotations


class PrincipalCapabilityError(Exception):
    """Base class for principal-capability wiring/persistence faults."""


class FreezePersistenceError(PrincipalCapabilityError):
    """Raised when the conflict-freeze dual persistence is inconsistent.

    FK-55 §55.10.5 / FK-31 §31.2.7 require the freeze to exist BOTH as a
    canonical backend record AND as a local hook-readable export with a matching
    ``freeze_version``. A corrupt or unreadable export is a fault, not a soft
    fallback (FAIL-CLOSED).
    """


__all__ = [
    "FreezePersistenceError",
    "PrincipalCapabilityError",
]
