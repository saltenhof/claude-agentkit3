"""Pure serialisation and projection builders for QA policy artefacts.

Blood group: A (pure — no I/O, no side-effects)
Owner BC:    verify-system / policy-engine
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentkit.qa.policy_engine.engine import VerifyDecision
    from agentkit.qa.protocols import Finding, LayerResult


def serialize_finding(finding: Finding) -> dict[str, object]:
    """Serialize a finding into the canonical JSON envelope."""

    return {
        "layer": finding.layer,
        "check": finding.check,
        "severity": finding.severity.value,
        "message": finding.message,
        "trust_class": finding.trust_class.value,
        "file_path": finding.file_path,
        "line_number": finding.line_number,
        "suggestion": finding.suggestion,
    }


def serialize_layer_result(
    layer_result: LayerResult,
    *,
    attempt_nr: int,
) -> dict[str, object]:
    """Serialize one QA layer result into the canonical artifact shape."""

    return {
        "layer": layer_result.layer,
        "passed": layer_result.passed,
        "attempt_nr": attempt_nr,
        "findings": [
            serialize_finding(finding)
            for finding in layer_result.findings
        ],
        "metadata": layer_result.metadata,
    }


def build_verify_decision_artifact(
    decision: VerifyDecision,
    *,
    attempt_nr: int,
) -> dict[str, object]:
    """Build the canonical verify-decision artifact payload."""

    return {
        "passed": decision.passed,
        "status": decision.status,
        "layers": [
            {
                "layer": layer_result.layer,
                "passed": layer_result.passed,
                "findings_count": len(layer_result.findings),
                "metadata": layer_result.metadata,
            }
            for layer_result in decision.layer_results
        ],
        "blocking_findings": [
            {
                "layer": finding.layer,
                "check": finding.check,
                "severity": finding.severity.value,
                "message": finding.message,
            }
            for finding in decision.blocking_findings
        ],
        "all_findings_count": len(decision.all_findings),
        "summary": decision.summary,
        "attempt_nr": attempt_nr,
    }


def verify_decision_passed(data: dict[str, object]) -> bool:
    """Evaluate PASS/PASS_WITH_WARNINGS semantics for decision envelopes."""

    status = data.get("status")
    return (
        isinstance(status, str)
        and bool(data.get("passed"))
        and status in ("PASS", "PASS_WITH_WARNINGS")
    )
