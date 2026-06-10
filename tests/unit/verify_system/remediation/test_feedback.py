"""Tests for remediation feedback building.

Wertebereich seit AG3-021: ``Severity`` ist BLOCKING/MAJOR/MINOR.
"""

from __future__ import annotations

import pytest

from agentkit.verify_system.errors import MandatoryTargetReadError
from agentkit.verify_system.policy_engine.engine import PolicyEngine
from agentkit.verify_system.protocols import Finding, LayerResult, Severity, TrustClass
from agentkit.verify_system.remediation.feedback import (
    RemediationFeedback,
    build_feedback,
    mandatory_target_findings_from_adversarial,
)


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


class TestMandatoryTargetFeedback:
    """FK-38 §38.1.4 mandatory-target feedback mapping."""

    def test_unmet_target_maps_to_real_blocking_finding(self) -> None:
        findings = mandatory_target_findings_from_adversarial(
            {
                "mandatory_target_results": [
                    {
                        "target_id": "target.wrong_phase",
                        "status": "NOT_TESTED",
                        "detail": "no adversarial test covered this target",
                    }
                ]
            }
        )

        assert len(findings) == 1
        finding = findings[0]
        assert finding.layer == "adversarial"
        assert finding.check == "target.wrong_phase"
        assert finding.severity is Severity.BLOCKING
        assert finding.trust_class is TrustClass.VERIFIED_LLM
        assert "NOT_TESTED" in finding.message

    def test_tested_and_unresolvable_targets_do_not_map_to_findings(self) -> None:
        findings = mandatory_target_findings_from_adversarial(
            {
                "mandatory_target_results": [
                    {"target_id": "target.a", "status": "TESTED"},
                    {"target_id": "target.b", "status": "UNRESOLVABLE"},
                ]
            }
        )

        assert findings == ()

    def test_extra_mandatory_target_findings_create_feedback_on_pass(self) -> None:
        decision = PolicyEngine().decide([LayerResult(layer="policy", passed=True)])
        mandatory = mandatory_target_findings_from_adversarial(
            {
                "mandatory_target_results": [
                    {"target_id": "target.a", "status": "FAILED"},
                ]
            }
        )

        feedback = build_feedback(
            decision,
            "TEST-001",
            2,
            extra_blocking_findings=mandatory,
        )

        assert feedback is not None
        assert feedback.blocking_findings[0].check == "target.a"

    def test_absent_key_means_no_targets(self) -> None:
        """A GENUINELY-absent key -> no targets (valid 'no mandatory targets')."""
        assert mandatory_target_findings_from_adversarial({}) == ()
        # Other keys present, but the mandatory_target_results key itself absent.
        assert (
            mandatory_target_findings_from_adversarial({"other": "value"}) == ()
        )

    def test_present_but_non_list_fails_closed(self) -> None:
        """A PRESENT key with a non-list shape -> FAIL-CLOSED (r2)."""
        with pytest.raises(MandatoryTargetReadError) as exc_info:
            mandatory_target_findings_from_adversarial(
                {"mandatory_target_results": {"target_id": "x", "status": "FAILED"}}
            )
        assert "FAIL-CLOSED" in str(exc_info.value)

    def test_present_but_none_value_fails_closed(self) -> None:
        """A PRESENT key with an explicit None value -> FAIL-CLOSED (r2).

        ``None`` is present-but-broken (not a list), NOT a genuinely-absent key.
        """
        with pytest.raises(MandatoryTargetReadError):
            mandatory_target_findings_from_adversarial(
                {"mandatory_target_results": None}
            )

    def test_list_entry_wrong_shape_fails_closed(self) -> None:
        """A list ENTRY that is not a mapping -> FAIL-CLOSED (r2).

        Previously such an entry was silently skipped, which could drop a
        mandatory target. It now fails closed.
        """
        with pytest.raises(MandatoryTargetReadError):
            mandatory_target_findings_from_adversarial(
                {"mandatory_target_results": ["not-a-mapping"]}
            )
