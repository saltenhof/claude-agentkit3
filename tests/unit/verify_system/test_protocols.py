"""Tests for QA protocol types -- Finding, LayerResult, Severity, TrustClass."""

from __future__ import annotations

import pytest

from agentkit.verify_system.protocols import Finding, LayerResult, Severity, TrustClass


class TestSeverity:
    """Severity enum values per FK-27 §27.4.2 (BLOCKING/MAJOR/MINOR)."""

    def test_severity_values(self) -> None:
        assert Severity.BLOCKING.value == "BLOCKING"
        assert Severity.MAJOR.value == "MAJOR"
        assert Severity.MINOR.value == "MINOR"

    def test_severity_has_three_members(self) -> None:
        assert len(Severity) == 3

    def test_legacy_values_rejected(self) -> None:
        for legacy in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"):
            with pytest.raises(ValueError):
                Severity(legacy)


class TestTrustClass:
    """TrustClass enum values."""

    def test_trust_class_values(self) -> None:
        assert TrustClass.SYSTEM.value == "A"
        assert TrustClass.VERIFIED_LLM.value == "B"
        assert TrustClass.WORKER_ASSERTION.value == "C"

    def test_trust_class_has_three_members(self) -> None:
        assert len(TrustClass) == 3


class TestFinding:
    """Finding construction and immutability."""

    def test_finding_construction(self) -> None:
        f = Finding(
            layer="structural",
            check="context_exists",
            severity=Severity.BLOCKING,
            message="context.json missing",
            trust_class=TrustClass.SYSTEM,
        )
        assert f.layer == "structural"
        assert f.check == "context_exists"
        assert f.severity == Severity.BLOCKING
        assert f.message == "context.json missing"
        assert f.trust_class == TrustClass.SYSTEM
        assert f.file_path is None
        assert f.line_number is None
        assert f.suggestion is None

    def test_finding_with_optional_fields(self) -> None:
        f = Finding(
            layer="structural",
            check="test",
            severity=Severity.MINOR,
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
            severity=Severity.MINOR,
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

    def test_blocking_findings_filters_correctly(self) -> None:
        findings = (
            Finding(
                layer="s", check="a", severity=Severity.BLOCKING,
                message="block", trust_class=TrustClass.SYSTEM,
            ),
            Finding(
                layer="s", check="b", severity=Severity.MAJOR,
                message="major", trust_class=TrustClass.SYSTEM,
            ),
            Finding(
                layer="s", check="c", severity=Severity.MINOR,
                message="minor", trust_class=TrustClass.SYSTEM,
            ),
        )
        lr = LayerResult(layer="s", passed=False, findings=findings)
        blocking = lr.blocking_findings
        assert len(blocking) == 1
        assert blocking[0].severity == Severity.BLOCKING

    def test_major_findings_filters_major_only(self) -> None:
        findings = (
            Finding(
                layer="s", check="a", severity=Severity.BLOCKING,
                message="block", trust_class=TrustClass.SYSTEM,
            ),
            Finding(
                layer="s", check="b", severity=Severity.MAJOR,
                message="major", trust_class=TrustClass.SYSTEM,
            ),
            Finding(
                layer="s", check="c", severity=Severity.MAJOR,
                message="major2", trust_class=TrustClass.SYSTEM,
            ),
            Finding(
                layer="s", check="d", severity=Severity.MINOR,
                message="minor", trust_class=TrustClass.SYSTEM,
            ),
        )
        lr = LayerResult(layer="s", passed=False, findings=findings)
        major = lr.major_findings
        assert len(major) == 2
        assert all(f.severity == Severity.MAJOR for f in major)

    def test_empty_findings_returns_empty_tuples(self) -> None:
        lr = LayerResult(layer="s", passed=True)
        assert lr.blocking_findings == ()
        assert lr.major_findings == ()
