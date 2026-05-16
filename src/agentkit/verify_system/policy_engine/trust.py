"""Trust classification for QA findings.

System checks (``TrustClass.SYSTEM``) outweigh worker assertions
(``TrustClass.WORKER_ASSERTION``) in the policy engine. This module
provides the weight mapping and effective severity computation.

Severity-Skala folgt FK-27 §27.4.2 (BLOCKING/MAJOR/MINOR).
"""

from __future__ import annotations

from agentkit.verify_system.protocols import Finding, Severity, TrustClass

TRUST_WEIGHT: dict[TrustClass, int] = {
    TrustClass.SYSTEM: 3,
    TrustClass.VERIFIED_LLM: 2,
    TrustClass.WORKER_ASSERTION: 1,
}
"""Weight multiplier for each trust class. Higher = more trusted."""

_SEVERITY_SCORE: dict[Severity, int] = {
    Severity.BLOCKING: 100,
    Severity.MAJOR: 50,
    Severity.MINOR: 20,
}
"""Base severity score per FK-27 §27.4.2. Higher = more severe."""


def effective_severity(finding: Finding) -> int:
    """Compute effective severity score (higher = worse).

    Combines the base severity score with the trust class weight.
    A BLOCKING finding from a SYSTEM check scores higher than a
    BLOCKING finding from a WORKER_ASSERTION.

    Args:
        finding: The finding to score.

    Returns:
        Integer score: ``severity_score * trust_weight``.
    """
    return _SEVERITY_SCORE[finding.severity] * TRUST_WEIGHT[finding.trust_class]
