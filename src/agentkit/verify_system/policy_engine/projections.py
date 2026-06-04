"""Pure serialisation and projection builders for QA policy artefacts.

Blood group: A (pure — no I/O, no side-effects)
Owner BC:    verify-system / policy-engine

EnvelopeStatus-Werte stammen seit AG3-021 aus ``agentkit.core_types``
und bestehen aus exakt ``PASS``, ``FAIL``, ``WARN``, ``ERROR``.
Die Werteliste ist abschliessend; weitere Kombinationen sind hier nicht
zulaessig (siehe FK-71 fuer das LLM-Mapping im Envelope-Kontext).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.core_types import EnvelopeStatus, PolicyVerdict

if TYPE_CHECKING:
    from agentkit.verify_system.policy_engine.engine import VerifyDecision
    from agentkit.verify_system.protocols import Finding, LayerResult


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
        "status": decision.verdict.value,
        # FK-35 §35.2.4 Dim 4 (DECISION_INVALID): the canonical policy record
        # carries the MAJOR threshold it was decided under (FK-27 §27.7.2).
        "major_threshold": decision.max_major_findings,
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
    """Evaluate PASS semantics for decision envelopes.

    ``PolicyVerdict`` enthaelt seit AG3-021 ausschliesslich ``PASS`` und
    ``FAIL`` (FK-27 §27.7.2); jeder andere Wert ist ungueltig und
    liefert ``False``.
    """

    status = data.get("status")
    return (
        isinstance(status, str)
        and bool(data.get("passed"))
        and status == PolicyVerdict.PASS.value
    )


def envelope_status_from_verdict(verdict: PolicyVerdict) -> EnvelopeStatus:
    """Map a ``PolicyVerdict`` to its ``EnvelopeStatus`` projection.

    Diese Hilfsfunktion bildet das policy-seitige PASS/FAIL auf das
    Envelope-seitige PASS/FAIL ab und ist absichtlich trivial — alle
    Warning-/Concern-Logik sitzt am Envelope-Rand (AG3-022,
    ProducerRegistry).
    """

    if verdict is PolicyVerdict.PASS:
        return EnvelopeStatus.PASS
    return EnvelopeStatus.FAIL
