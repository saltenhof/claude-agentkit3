"""Tests for remediation feedback building.

Wertebereich seit AG3-021: ``Severity`` ist BLOCKING/MAJOR/MINOR.
"""

from __future__ import annotations

from agentkit.verify_system.policy_engine.engine import PolicyEngine
from agentkit.verify_system.protocols import Finding, LayerResult, Severity, TrustClass
from agentkit.verify_system.remediation.feedback import RemediationFeedback, build_feedback


def _finding(
    severity: Severity = Severity.BLOCKING,
    trust: TrustClass = TrustClass.SYSTEM,
    check: str = "test_check",
) -> Finding:
    """Helper to build a Finding with defaults."""
    return Finding(
        layer="structural",
        check=check,
        severity=severity,
        message=f"{severity.value} finding from {check}",
        trust_class=trust,
    )


class TestBuildFeedback:
    """build_feedback function tests."""

    def test_fail_decision_produces_feedback(self) -> None:
        engine = PolicyEngine()
        decision = engine.decide([
            LayerResult(
                layer="structural",
                passed=False,
                findings=(_finding(Severity.BLOCKING),),
            ),
        ])
        feedback = build_feedback(decision, "TEST-001", round_nr=1)
        assert feedback is not None
        assert isinstance(feedback, RemediationFeedback)
        assert feedback.story_id == "TEST-001"
        assert feedback.round_nr == 1
        assert len(feedback.blocking_findings) == 1

    def test_pass_decision_returns_none(self) -> None:
        engine = PolicyEngine()
        decision = engine.decide([
            LayerResult(layer="structural", passed=True),
        ])
        feedback = build_feedback(decision, "TEST-001", round_nr=1)
        assert feedback is None

    def test_feedback_separates_blocking_and_advisory(self) -> None:
        engine = PolicyEngine()
        decision = engine.decide([
            LayerResult(
                layer="structural",
                passed=False,
                findings=(
                    _finding(Severity.BLOCKING, check="a"),
                    _finding(Severity.MAJOR, check="b"),
                    _finding(Severity.MINOR, check="c"),
                ),
            ),
        ])
        feedback = build_feedback(decision, "TEST-001", round_nr=2)
        assert feedback is not None
        assert len(feedback.blocking_findings) >= 1
        # MAJOR and MINOR should be advisory; BLOCKING never advisory.
        advisory_severities = {f.severity for f in feedback.advisory_findings}
        assert Severity.BLOCKING not in advisory_severities


class TestRemediationFeedbackPrompt:
    """to_prompt_text formatting tests."""

    def test_prompt_text_contains_finding_details(self) -> None:
        fb = RemediationFeedback(
            story_id="TEST-001",
            round_nr=1,
            blocking_findings=(
                _finding(Severity.BLOCKING, check="context_exists"),
            ),
            advisory_findings=(),
            summary="1 blocking finding",
        )
        text = fb.to_prompt_text()
        assert "Remediation Feedback" in text
        assert "Round 1" in text
        assert "TEST-001" in text
        assert "BLOCKING" in text
        assert "context_exists" in text

    def test_prompt_text_includes_file_path(self) -> None:
        f = Finding(
            layer="structural",
            check="test",
            severity=Severity.BLOCKING,
            message="msg",
            trust_class=TrustClass.SYSTEM,
            file_path="/some/path.json",
        )
        fb = RemediationFeedback(
            story_id="TEST-001",
            round_nr=1,
            blocking_findings=(f,),
            advisory_findings=(),
            summary="test",
        )
        text = fb.to_prompt_text()
        assert "/some/path.json" in text

    def test_prompt_text_includes_suggestion(self) -> None:
        f = Finding(
            layer="structural",
            check="test",
            severity=Severity.BLOCKING,
            message="msg",
            trust_class=TrustClass.SYSTEM,
            suggestion="Fix this thing",
        )
        fb = RemediationFeedback(
            story_id="TEST-001",
            round_nr=1,
            blocking_findings=(f,),
            advisory_findings=(),
            summary="test",
        )
        text = fb.to_prompt_text()
        assert "Fix this thing" in text

    def test_feedback_is_frozen(self) -> None:
        import pytest

        fb = RemediationFeedback(
            story_id="TEST-001",
            round_nr=1,
            blocking_findings=(),
            advisory_findings=(),
            summary="test",
        )
        with pytest.raises(AttributeError):
            fb.round_nr = 2  # type: ignore[misc]


class TestFindingResolutionInFeedback:
    """AG3-041 §2.1.6/§2.1.5: finding_resolution + has_open_findings."""

    def test_has_open_findings_true_when_not_resolved(self) -> None:
        from agentkit.verify_system.remediation.finding_resolution import (
            FindingResolutionStatus,
        )

        fb = RemediationFeedback(
            story_id="TEST-001",
            round_nr=2,
            blocking_findings=(),
            advisory_findings=(),
            summary="test",
            finding_resolution={
                ("structural", "c1"): FindingResolutionStatus.NOT_RESOLVED,
            },
        )
        assert fb.has_open_findings() is True
        assert "Unresolved Previous Findings" in fb.to_prompt_text()

    def test_has_open_findings_true_when_partially_resolved(self) -> None:
        """E7 (AG3-041 / FK-34): PARTIALLY_RESOLVED is open/blocking too."""
        from agentkit.verify_system.remediation.finding_resolution import (
            FindingResolutionStatus,
        )

        fb = RemediationFeedback(
            story_id="TEST-001",
            round_nr=2,
            blocking_findings=(),
            advisory_findings=(),
            summary="test",
            finding_resolution={
                ("structural", "c1"): FindingResolutionStatus.PARTIALLY_RESOLVED,
            },
        )
        assert fb.has_open_findings() is True
        # The prompt surfaces it as an unresolved previous finding.
        assert "PARTIALLY_RESOLVED" in fb.to_prompt_text()

    def test_has_open_findings_false_when_resolved(self) -> None:
        from agentkit.verify_system.remediation.finding_resolution import (
            FindingResolutionStatus,
        )

        fb = RemediationFeedback(
            story_id="TEST-001",
            round_nr=2,
            blocking_findings=(),
            advisory_findings=(),
            summary="test",
            finding_resolution={
                ("structural", "c1"): FindingResolutionStatus.FULLY_RESOLVED,
            },
        )
        assert fb.has_open_findings() is False

    def test_has_open_findings_false_when_empty(self) -> None:
        fb = RemediationFeedback(
            story_id="TEST-001",
            round_nr=1,
            blocking_findings=(),
            advisory_findings=(),
            summary="test",
        )
        assert fb.has_open_findings() is False

    def test_build_feedback_carries_resolution_map(self) -> None:
        from agentkit.verify_system.remediation.finding_resolution import (
            FindingResolutionStatus,
        )

        result = LayerResult(
            layer="structural", passed=False, findings=(_finding(),)
        )
        decision = PolicyEngine().decide([result])
        resolution = {("structural", "c1"): FindingResolutionStatus.NOT_RESOLVED}
        fb = build_feedback(decision, "TEST-001", 2, finding_resolution=resolution)
        assert fb is not None
        assert fb.has_open_findings() is True
