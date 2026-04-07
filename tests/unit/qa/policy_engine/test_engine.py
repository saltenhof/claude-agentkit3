"""Tests for PolicyEngine -- deterministic aggregation of QA results."""

from __future__ import annotations

from agentkit.qa.policy_engine.engine import PolicyEngine, VerifyDecision
from agentkit.qa.protocols import Finding, LayerResult, Severity, TrustClass


def _finding(
    severity: Severity = Severity.INFO,
    trust: TrustClass = TrustClass.SYSTEM,
    layer: str = "test",
    check: str = "test_check",
) -> Finding:
    """Helper to build a Finding with defaults."""
    return Finding(
        layer=layer,
        check=check,
        severity=severity,
        message=f"{severity.value} finding",
        trust_class=trust,
    )


class TestPolicyEngine:
    """PolicyEngine decision tests."""

    def test_no_findings_returns_pass(self) -> None:
        engine = PolicyEngine()
        result = engine.decide([
            LayerResult(layer="structural", passed=True),
        ])
        assert result.passed is True
        assert result.status == "PASS"
        assert result.blocking_findings == ()

    def test_only_info_findings_returns_pass_with_warnings(self) -> None:
        engine = PolicyEngine()
        result = engine.decide([
            LayerResult(
                layer="structural",
                passed=True,
                findings=(_finding(Severity.INFO),),
            ),
        ])
        assert result.passed is True
        assert result.status == "PASS_WITH_WARNINGS"

    def test_only_low_findings_returns_pass_with_warnings(self) -> None:
        engine = PolicyEngine()
        result = engine.decide([
            LayerResult(
                layer="structural",
                passed=True,
                findings=(_finding(Severity.LOW),),
            ),
        ])
        assert result.passed is True
        assert result.status == "PASS_WITH_WARNINGS"

    def test_critical_system_finding_returns_fail(self) -> None:
        engine = PolicyEngine()
        result = engine.decide([
            LayerResult(
                layer="structural",
                passed=False,
                findings=(
                    _finding(Severity.CRITICAL, TrustClass.SYSTEM),
                ),
            ),
        ])
        assert result.passed is False
        assert result.status == "FAIL"
        assert len(result.blocking_findings) == 1

    def test_high_system_finding_returns_fail(self) -> None:
        engine = PolicyEngine()
        result = engine.decide([
            LayerResult(
                layer="structural",
                passed=False,
                findings=(
                    _finding(Severity.HIGH, TrustClass.SYSTEM),
                ),
            ),
        ])
        assert result.passed is False
        assert result.status == "FAIL"

    def test_multiple_medium_findings_returns_pass_with_warnings(self) -> None:
        engine = PolicyEngine()
        findings = tuple(_finding(Severity.MEDIUM) for _ in range(5))
        result = engine.decide([
            LayerResult(layer="structural", passed=True, findings=findings),
        ])
        assert result.passed is True
        assert result.status == "PASS_WITH_WARNINGS"

    def test_empty_layer_list_returns_pass(self) -> None:
        engine = PolicyEngine()
        result = engine.decide([])
        assert result.passed is True
        assert result.status == "PASS"

    def test_mixed_layers_one_fail_one_pass(self) -> None:
        engine = PolicyEngine()
        result = engine.decide([
            LayerResult(layer="structural", passed=True),
            LayerResult(
                layer="semantic",
                passed=False,
                findings=(
                    _finding(Severity.CRITICAL, TrustClass.SYSTEM, layer="semantic"),
                ),
            ),
        ])
        assert result.passed is False
        assert result.status == "FAIL"
        assert len(result.blocking_findings) == 1

    def test_high_worker_findings_exceed_threshold_fail(self) -> None:
        """When max_high_findings=0, even one HIGH finding blocks."""
        engine = PolicyEngine(max_high_findings=0)
        result = engine.decide([
            LayerResult(
                layer="test",
                passed=False,
                findings=(
                    _finding(Severity.HIGH, TrustClass.WORKER_ASSERTION),
                ),
            ),
        ])
        assert result.passed is False
        assert result.status == "FAIL"

    def test_high_worker_within_threshold_passes(self) -> None:
        """When max_high_findings=2, one HIGH finding is not blocking."""
        engine = PolicyEngine(max_high_findings=2)
        result = engine.decide([
            LayerResult(
                layer="test",
                passed=True,
                findings=(
                    _finding(Severity.HIGH, TrustClass.WORKER_ASSERTION),
                ),
            ),
        ])
        # HIGH from WORKER_ASSERTION, and count (1) <= max_high (2)
        # But SYSTEM trust HIGH would still block -- only WORKER here
        assert result.passed is True
        assert result.status == "PASS_WITH_WARNINGS"

    def test_summary_contains_counts(self) -> None:
        engine = PolicyEngine()
        result = engine.decide([
            LayerResult(
                layer="test",
                passed=False,
                findings=(
                    _finding(Severity.CRITICAL, TrustClass.SYSTEM),
                    _finding(Severity.HIGH, TrustClass.SYSTEM),
                ),
            ),
        ])
        assert "1 critical" in result.summary
        assert "1 high" in result.summary

    def test_all_findings_flattened_across_layers(self) -> None:
        engine = PolicyEngine()
        result = engine.decide([
            LayerResult(
                layer="a",
                passed=True,
                findings=(_finding(Severity.LOW, layer="a"),),
            ),
            LayerResult(
                layer="b",
                passed=True,
                findings=(_finding(Severity.INFO, layer="b"),),
            ),
        ])
        assert len(result.all_findings) == 2

    def test_verify_decision_is_frozen(self) -> None:
        engine = PolicyEngine()
        result = engine.decide([])
        import pytest

        with pytest.raises(AttributeError):
            result.passed = False  # type: ignore[misc]
