"""Tests for QA protocol types -- Finding, LayerResult, Severity, TrustClass."""

from __future__ import annotations

import pytest

from agentkit.qa.protocols import Finding, LayerResult, Severity, TrustClass


class TestSeverity:
    """Severity enum values."""

    def test_severity_values(self) -> None:
        assert Severity.CRITICAL == "critical"
        assert Severity.HIGH == "high"
        assert Severity.MEDIUM == "medium"
        assert Severity.LOW == "low"
        assert Severity.INFO == "info"

    def test_severity_has_five_members(self) -> None:
        assert len(Severity) == 5


class TestTrustClass:
    """TrustClass enum values."""

    def test_trust_class_values(self) -> None:
        assert TrustClass.SYSTEM == "A"
        assert TrustClass.VERIFIED_LLM == "B"
        assert TrustClass.WORKER_ASSERTION == "C"

    def test_trust_class_has_three_members(self) -> None:
        assert len(TrustClass) == 3


class TestFinding:
    """Finding construction and immutability."""

    def test_finding_construction(self) -> None:
        f = Finding(
            layer="structural",
            check="context_exists",
            severity=Severity.CRITICAL,
            message="context.json missing",
            trust_class=TrustClass.SYSTEM,
        )
        assert f.layer == "structural"
        assert f.check == "context_exists"
        assert f.severity == Severity.CRITICAL
        assert f.message == "context.json missing"
        assert f.trust_class == TrustClass.SYSTEM
        assert f.file_path is None
        assert f.line_number is None
        assert f.suggestion is None

    def test_finding_with_optional_fields(self) -> None:
        f = Finding(
            layer="structural",
            check="test",
            severity=Severity.LOW,
            message="test msg",
            trust_class=TrustClass.SYSTEM,
            file_path="/some/file.py",
            line_number=42,
            suggestion="Fix it",
        )
        assert f.file_path == "/some/file.py"
        assert f.line_number == 42
        assert f.suggestion == "Fix it"

    def test_finding_is_frozen(self) -> None:
        f = Finding(
            layer="structural",
            check="test",
            severity=Severity.LOW,
            message="test",
            trust_class=TrustClass.SYSTEM,
        )
        with pytest.raises(AttributeError):
            f.message = "changed"  # type: ignore[misc]


class TestLayerResult:
    """LayerResult construction and property filters."""

    def test_layer_result_construction(self) -> None:
        lr = LayerResult(layer="structural", passed=True)
        assert lr.layer == "structural"
        assert lr.passed is True
        assert lr.findings == ()
        assert lr.metadata == {}

    def test_critical_findings_filters_correctly(self) -> None:
        findings = (
            Finding(
                layer="s", check="a", severity=Severity.CRITICAL,
                message="crit", trust_class=TrustClass.SYSTEM,
            ),
            Finding(
                layer="s", check="b", severity=Severity.HIGH,
                message="high", trust_class=TrustClass.SYSTEM,
            ),
            Finding(
                layer="s", check="c", severity=Severity.INFO,
                message="info", trust_class=TrustClass.SYSTEM,
            ),
        )
        lr = LayerResult(layer="s", passed=False, findings=findings)
        crit = lr.critical_findings
        assert len(crit) == 1
        assert crit[0].severity == Severity.CRITICAL

    def test_blocking_findings_filters_critical_and_high(self) -> None:
        findings = (
            Finding(
                layer="s", check="a", severity=Severity.CRITICAL,
                message="crit", trust_class=TrustClass.SYSTEM,
            ),
            Finding(
                layer="s", check="b", severity=Severity.HIGH,
                message="high", trust_class=TrustClass.SYSTEM,
            ),
            Finding(
                layer="s", check="c", severity=Severity.MEDIUM,
                message="med", trust_class=TrustClass.SYSTEM,
            ),
            Finding(
                layer="s", check="d", severity=Severity.LOW,
                message="low", trust_class=TrustClass.SYSTEM,
            ),
        )
        lr = LayerResult(layer="s", passed=False, findings=findings)
        blocking = lr.blocking_findings
        assert len(blocking) == 2
        severities = {f.severity for f in blocking}
        assert severities == {Severity.CRITICAL, Severity.HIGH}

    def test_empty_findings_returns_empty_tuples(self) -> None:
        lr = LayerResult(layer="s", passed=True)
        assert lr.critical_findings == ()
        assert lr.blocking_findings == ()
