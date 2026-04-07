"""Trust classification for QA findings.

System checks (``TrustClass.SYSTEM``) outweigh worker assertions
(``TrustClass.WORKER_ASSERTION``) in the policy engine. This module
provides the weight mapping and effective severity computation.
"""

from __future__ import annotations

from agentkit.qa.protocols import Finding, Severity, TrustClass

TRUST_WEIGHT: dict[TrustClass, int] = {
    TrustClass.SYSTEM: 3,
    TrustClass.VERIFIED_LLM: 2,
    TrustClass.WORKER_ASSERTION: 1,
}
"""Weight multiplier for each trust class. Higher = more trusted."""

_SEVERITY_SCORE: dict[Severity, int] = {
    Severity.CRITICAL: 100,
    Severity.HIGH: 80,
    Severity.MEDIUM: 50,
    Severity.LOW: 20,
    Severity.INFO: 0,
}
"""Base severity score. Higher = more severe."""


def effective_severity(finding: Finding) -> int:
    """Compute effective severity score (higher = worse).

    Combines the base severity score with the trust class weight.
    A CRITICAL finding from a SYSTEM check scores higher than a
    CRITICAL finding from a WORKER_ASSERTION.

    Args:
        finding: The finding to score.

    Returns:
        Integer score: ``severity_score * trust_weight``.
    """
    return _SEVERITY_SCORE[finding.severity] * TRUST_WEIGHT[finding.trust_class]
