"""Errors for the SonarQube-Green-Gate capability (FK-33 §33.6).

All are fail-closed signals; the gate never fails open.
"""

from __future__ import annotations

from agentkit.verify_system.errors import VerifySystemError


class SonarGateError(VerifySystemError):
    """Base error for the SonarQube-Green-Gate capability."""


class LedgerInvalidError(SonarGateError):
    """An accepted-exception ledger entry/document is structurally invalid."""


class ReconcilerFailClosedError(SonarGateError):
    """The deterministic reconciler could not apply an exception single-match.

    Raised when a ledger entry matches zero or more than one current Sonar
    issue (FK-33 §33.6.4). Fail-closed: renewed six-eyes approval needed.
    """


class ReconcilerApplyError(SonarGateError):
    """Applying a single-matched accepted exception to Sonar failed.

    Raised when the scoped ``Administer Issues`` transition (``do_transition``
    / ``set_tags``, FK-33 §33.6.4) could not be carried out — a
    configured-but-unreachable Sonar. Fail-closed: the gate must not pass
    on an exception that was never actually applied.
    """


class AttestationUnreadableError(SonarGateError):
    """A configured-but-unreachable/unreadable attestation (fail-closed).

    Distinct from a deliberately absent Sonar (which resolves
    not-applicable and never reaches the gate). FK-33 §33.6.5.
    """


__all__ = [
    "AttestationUnreadableError",
    "LedgerInvalidError",
    "ReconcilerApplyError",
    "ReconcilerFailClosedError",
    "SonarGateError",
]
