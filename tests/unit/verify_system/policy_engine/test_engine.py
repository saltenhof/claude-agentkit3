"""Tests for PolicyEngine -- deterministic aggregation of QA results.

Wertebereich seit AG3-021: ``Severity`` ist BLOCKING/MAJOR/MINOR,
``PolicyVerdict`` ist PASS/FAIL (kein PASS_WITH_WARNINGS).
"""

from __future__ import annotations

from agentkit.backend.core_types import PolicyVerdict
from agentkit.backend.verify_system.policy_engine.engine import PolicyEngine
from agentkit.backend.verify_system.protocols import Finding, LayerResult, Severity, TrustClass


def _finding(
    severity: Severity = Severity.MINOR,
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
        assert result.verdict is PolicyVerdict.PASS
        assert result.status == "PASS"
        assert result.blocking_findings == ()

    def test_only_minor_findings_returns_pass(self) -> None:
        """MINOR-only findings produzieren PASS — kein PASS_WITH_WARNINGS."""
        engine = PolicyEngine()
        result = engine.decide([
            LayerResult(
                layer="structural",
                passed=True,
                findings=(_finding(Severity.MINOR),),
            ),
        ])
        assert result.passed is True
        assert result.verdict is PolicyVerdict.PASS
        assert result.status == "PASS"

    def test_blocking_system_finding_returns_fail(self) -> None:
        engine = PolicyEngine()
        result = engine.decide([
            LayerResult(
                layer="structural",
                passed=False,
                findings=(
                    _finding(Severity.BLOCKING, TrustClass.SYSTEM),
                ),
            ),
        ])
        assert result.passed is False
        assert result.verdict is PolicyVerdict.FAIL
        assert result.status == "FAIL"
        assert len(result.blocking_findings) == 1

    def test_major_system_finding_returns_fail_at_threshold_zero(self) -> None:
        """Mit max_major=0 wird jeder MAJOR-Befund blockend."""
        engine = PolicyEngine(max_major_findings=0)
        result = engine.decide([
            LayerResult(
                layer="structural",
                passed=False,
                findings=(
                    _finding(Severity.MAJOR, TrustClass.SYSTEM),
                ),
            ),
        ])
        assert result.passed is False
        assert result.verdict is PolicyVerdict.FAIL

    def test_multiple_minor_findings_returns_pass(self) -> None:
        engine = PolicyEngine()
        findings = tuple(_finding(Severity.MINOR) for _ in range(5))
        result = engine.decide([
            LayerResult(layer="structural", passed=True, findings=findings),
        ])
        assert result.passed is True
        assert result.verdict is PolicyVerdict.PASS

    def test_empty_layer_list_returns_pass(self) -> None:
        engine = PolicyEngine()
        result = engine.decide([])
        assert result.passed is True
        assert result.verdict is PolicyVerdict.PASS

    def test_mixed_layers_one_fail_one_pass(self) -> None:
        engine = PolicyEngine()
        result = engine.decide([
            LayerResult(layer="structural", passed=True),
            LayerResult(
                layer="semantic",
                passed=False,
                findings=(
                    _finding(Severity.BLOCKING, TrustClass.SYSTEM, layer="semantic"),
                ),
            ),
        ])
        assert result.passed is False
        assert result.verdict is PolicyVerdict.FAIL
        assert len(result.blocking_findings) == 1

    def test_major_system_findings_exceed_threshold_fail(self) -> None:
        """When max_major_findings=0, even one MAJOR SYSTEM finding blocks."""
        engine = PolicyEngine(max_major_findings=0)
        result = engine.decide([
            LayerResult(
                layer="test",
                passed=False,
                findings=(
                    _finding(Severity.MAJOR, TrustClass.SYSTEM),
                ),
            ),
        ])
        assert result.passed is False
        assert result.verdict is PolicyVerdict.FAIL

    def test_major_worker_finding_never_blocks_even_over_threshold(self) -> None:
        """Trust-C (WORKER_ASSERTION) MAJOR never blocks, even past threshold.

        DK-04 §4.2 / FK-33 §33.5.2 Kernregel "Klasse C darf nie blocking sein"
        (FK-07-008): a worker self-report must not be able to pass — or fail —
        its own check. Even at ``max_major_findings=0`` a MAJOR finding from
        ``WORKER_ASSERTION`` is filtered out before the MAJOR-threshold rule and
        cannot drive a FAIL. Only SYSTEM/VERIFIED_LLM MAJOR findings count.
        """
        engine = PolicyEngine(max_major_findings=0)
        result = engine.decide([
            LayerResult(
                layer="test",
                passed=True,
                findings=(
                    _finding(Severity.MAJOR, TrustClass.WORKER_ASSERTION),
                ),
            ),
        ])
        assert result.passed is True
        assert result.verdict is PolicyVerdict.PASS
        assert result.blocking_findings == ()

    def test_blocking_worker_finding_never_blocks(self) -> None:
        """E1-fix negative test: Trust-C BLOCKING does NOT block.

        DK-04 §4.2 / FK-33 §33.5.2 (FK-07-008): Klasse C darf nie blocking
        sein. Even a ``Severity.BLOCKING`` finding from ``WORKER_ASSERTION``
        must NOT produce a FAIL — the worker cannot block (nor pass) its own
        check. This is the regression test for the over-broad E1 fix that
        blocked *any* BLOCKING finding regardless of trust class.
        """
        engine = PolicyEngine()
        result = engine.decide([
            LayerResult(
                layer="test",
                passed=True,
                findings=(
                    _finding(Severity.BLOCKING, TrustClass.WORKER_ASSERTION),
                ),
            ),
        ])
        assert result.passed is True
        assert result.verdict is PolicyVerdict.PASS
        assert result.blocking_findings == ()

    def test_layer2_llm_fail_blocks_independent_of_high_major_threshold(self) -> None:
        """E1 negative test: a single Layer-2 LLM FAIL blocks HARD even when
        ``max_major_findings`` is generous (FK-33 §33.8.2 / FK-34 §34.2.5).

        A Layer-2 role FAIL is mapped to a Trust-B (VERIFIED_LLM) BLOCKING
        finding. BLOCKING is the unconditional, threshold-independent severity:
        the engine MUST FAIL regardless of ``max_major_findings``. Before the
        E1 fix the FAIL was a threshold-gated MAJOR and would have passed here.
        """
        engine = PolicyEngine(max_major_findings=5)
        result = engine.decide([
            LayerResult(
                layer="qa_review",
                passed=False,
                findings=(
                    _finding(
                        Severity.BLOCKING,
                        TrustClass.VERIFIED_LLM,
                        layer="qa_review",
                        check="ac_fulfilled",
                    ),
                ),
            ),
        ])
        assert result.passed is False
        assert result.verdict is PolicyVerdict.FAIL
        assert len(result.blocking_findings) == 1
        assert result.blocking_findings[0].trust_class is TrustClass.VERIFIED_LLM

    def test_major_system_within_threshold_passes(self) -> None:
        """When max_major_findings=2, one MAJOR SYSTEM finding is not blocking."""
        engine = PolicyEngine(max_major_findings=2)
        result = engine.decide([
            LayerResult(
                layer="test",
                passed=True,
                findings=(
                    _finding(Severity.MAJOR, TrustClass.SYSTEM),
                ),
            ),
        ])
        # MAJOR from a blocking-eligible trust, count (1) <= max_major (2)
        # -> not blocking. A BLOCKING-severity finding would still block.
        assert result.passed is True
        assert result.verdict is PolicyVerdict.PASS

    def test_summary_contains_counts(self) -> None:
        engine = PolicyEngine()
        result = engine.decide([
            LayerResult(
                layer="test",
                passed=False,
                findings=(
                    _finding(Severity.BLOCKING, TrustClass.SYSTEM),
                    _finding(Severity.MAJOR, TrustClass.SYSTEM),
                ),
            ),
        ])
        assert "1 blocking" in result.summary
        assert "1 major" in result.summary

    def test_all_findings_flattened_across_layers(self) -> None:
        engine = PolicyEngine()
        result = engine.decide([
            LayerResult(
                layer="a",
                passed=True,
                findings=(_finding(Severity.MINOR, layer="a"),),
            ),
            LayerResult(
                layer="b",
                passed=True,
                findings=(_finding(Severity.MINOR, layer="b"),),
            ),
        ])
        assert len(result.all_findings) == 2

    def test_verify_decision_is_frozen(self) -> None:
        engine = PolicyEngine()
        result = engine.decide([])
        import pytest

        with pytest.raises(AttributeError):
            result.passed = False  # type: ignore[misc]

    def test_verdict_is_always_pass_or_fail(self) -> None:
        """PolicyVerdict kennt seit AG3-021 ausschliesslich PASS/FAIL."""
        engine = PolicyEngine()
        for findings in (
            (),
            (_finding(Severity.MINOR),),
            (_finding(Severity.MAJOR, TrustClass.WORKER_ASSERTION),),
            (_finding(Severity.BLOCKING, TrustClass.SYSTEM),),
        ):
            decision = engine.decide([
                LayerResult(
                    layer="x", passed=not findings, findings=findings,
                ),
            ])
            assert decision.verdict in {PolicyVerdict.PASS, PolicyVerdict.FAIL}
