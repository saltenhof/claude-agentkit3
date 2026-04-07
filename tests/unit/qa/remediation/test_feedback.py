"""Tests for remediation feedback building."""

from __future__ import annotations

from agentkit.qa.policy_engine.engine import PolicyEngine
from agentkit.qa.protocols import Finding, LayerResult, Severity, TrustClass
from agentkit.qa.remediation.feedback import RemediationFeedback, build_feedback


def _finding(
    severity: Severity = Severity.CRITICAL,
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
                findings=(_finding(Severity.CRITICAL),),
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
                    _finding(Severity.CRITICAL, check="a"),
                    _finding(Severity.MEDIUM, check="b"),
                    _finding(Severity.LOW, check="c"),
                ),
            ),
        ])
        feedback = build_feedback(decision, "TEST-001", round_nr=2)
        assert feedback is not None
        assert len(feedback.blocking_findings) >= 1
        # MEDIUM and LOW should be advisory
        advisory_severities = {f.severity for f in feedback.advisory_findings}
        assert Severity.CRITICAL not in advisory_severities


class TestRemediationFeedbackPrompt:
    """to_prompt_text formatting tests."""

    def test_prompt_text_contains_finding_details(self) -> None:
        fb = RemediationFeedback(
            story_id="TEST-001",
            round_nr=1,
            blocking_findings=(
                _finding(Severity.CRITICAL, check="context_exists"),
            ),
            advisory_findings=(),
            summary="1 critical finding",
        )
        text = fb.to_prompt_text()
        assert "Remediation Feedback" in text
        assert "Round 1" in text
        assert "TEST-001" in text
        assert "CRITICAL" in text
        assert "context_exists" in text

    def test_prompt_text_includes_file_path(self) -> None:
        f = Finding(
            layer="structural",
            check="test",
            severity=Severity.HIGH,
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
            severity=Severity.HIGH,
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
