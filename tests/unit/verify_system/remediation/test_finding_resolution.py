"""Unit tests for FindingResolutionAssessor (FK-34 / DK-04 §4.6, AG3-041 AC5)."""

from __future__ import annotations

from agentkit.core_types import Severity
from agentkit.verify_system.protocols import Finding, TrustClass
from agentkit.verify_system.remediation.finding_resolution import (
    FindingResolutionAssessor,
    FindingResolutionStatus,
)


def _finding(check: str, severity: Severity, *, layer: str = "structural") -> Finding:
    return Finding(
        layer=layer,
        check=check,
        severity=severity,
        message=f"{check} failed",
        trust_class=TrustClass.SYSTEM,
    )


class TestAssess:
    def test_finding_gone_is_fully_resolved(self) -> None:
        previous = (_finding("c1", Severity.BLOCKING),)
        current: tuple[Finding, ...] = ()
        statuses = FindingResolutionAssessor().assess(previous, current)
        assert statuses[("structural", "c1")] is FindingResolutionStatus.FULLY_RESOLVED

    def test_reduced_severity_is_partially_resolved(self) -> None:
        previous = (_finding("c1", Severity.BLOCKING),)
        current = (_finding("c1", Severity.MINOR),)
        statuses = FindingResolutionAssessor().assess(previous, current)
        assert (
            statuses[("structural", "c1")]
            is FindingResolutionStatus.PARTIALLY_RESOLVED
        )

    def test_same_severity_is_not_resolved(self) -> None:
        previous = (_finding("c1", Severity.MAJOR),)
        current = (_finding("c1", Severity.MAJOR),)
        statuses = FindingResolutionAssessor().assess(previous, current)
        assert statuses[("structural", "c1")] is FindingResolutionStatus.NOT_RESOLVED

    def test_higher_severity_is_not_resolved(self) -> None:
        previous = (_finding("c1", Severity.MINOR),)
        current = (_finding("c1", Severity.BLOCKING),)
        statuses = FindingResolutionAssessor().assess(previous, current)
        assert statuses[("structural", "c1")] is FindingResolutionStatus.NOT_RESOLVED

    def test_matching_is_layer_and_check_scoped(self) -> None:
        previous = (_finding("c1", Severity.MAJOR, layer="structural"),)
        # Same check id but different layer -> not a match -> previous is gone.
        current = (_finding("c1", Severity.MAJOR, layer="adversarial"),)
        statuses = FindingResolutionAssessor().assess(previous, current)
        assert (
            statuses[("structural", "c1")] is FindingResolutionStatus.FULLY_RESOLVED
        )

    def test_most_severe_current_decides(self) -> None:
        previous = (_finding("c1", Severity.MAJOR),)
        current = (
            _finding("c1", Severity.MINOR),
            _finding("c1", Severity.MAJOR),
        )
        statuses = FindingResolutionAssessor().assess(previous, current)
        assert statuses[("structural", "c1")] is FindingResolutionStatus.NOT_RESOLVED


class TestHasUnresolved:
    def test_true_when_any_not_resolved(self) -> None:
        previous = (_finding("c1", Severity.MAJOR),)
        current = (_finding("c1", Severity.MAJOR),)
        assert FindingResolutionAssessor().has_unresolved(previous, current) is True

    def test_true_when_partially_resolved(self) -> None:
        """E7 (AG3-041 / FK-34 §34.9.4): PARTIALLY_RESOLVED is open/blocking.

        A reduced-severity (but still present) previous finding counts as
        unresolved — the same open-status SSOT that
        ``resolution_map_has_open_findings`` and
        ``RemediationFeedback.has_open_findings`` use. Previously
        ``has_unresolved`` only matched ``NOT_RESOLVED``, silently treating a
        partially-resolved finding as cleared; this asserts the corrected,
        single-truth semantics.
        """
        previous = (_finding("c1", Severity.BLOCKING),)
        current = (_finding("c1", Severity.MINOR),)
        assert FindingResolutionAssessor().has_unresolved(previous, current) is True

    def test_false_when_all_resolved(self) -> None:
        previous = (_finding("c1", Severity.MAJOR),)
        current: tuple[Finding, ...] = ()
        assert FindingResolutionAssessor().has_unresolved(previous, current) is False
