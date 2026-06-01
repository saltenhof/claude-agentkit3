"""Contract-Test: FailureCorpus-Top-Surface (AG3-028 §2.1.7, AK#1/#2).

Pinnt, dass alle SECHS Top-Methoden mit ihren Signaturen existieren und dass
das Paket die geforderten Symbole re-exportiert (AC#1). Reine Introspektion;
kein State-Backend noetig.
"""

from __future__ import annotations

import inspect

from agentkit import failure_corpus
from agentkit.failure_corpus.top import (
    CheckApprovalDecision,
    EffectivenessReport,
    FailureCorpus,
    FailurePattern,
    PatternDecision,
)

_REQUIRED_EXPORTS = (
    "FailureCorpus",
    "IncidentCandidate",
    "Incident",
    "IncidentStatus",
    "IncidentId",
    "PatternId",
    "CheckId",
    "IncidentSeverity",
    "IncidentTriage",
    "IngressCriteria",
    "IncidentNormalizer",
)

_SIX_METHODS = (
    "record_incident",
    "suggest_patterns",
    "confirm_pattern",
    "derive_check",
    "approve_check",
    "report_effectiveness",
)


def test_package_reexports_required_symbols() -> None:
    for name in _REQUIRED_EXPORTS:
        assert hasattr(failure_corpus, name), f"missing export: {name}"


def test_failure_corpus_has_six_methods() -> None:
    for name in _SIX_METHODS:
        assert callable(getattr(FailureCorpus, name)), f"missing method: {name}"


def test_record_incident_signature() -> None:
    sig = inspect.signature(FailureCorpus.record_incident)
    params = list(sig.parameters)
    assert params == ["self", "candidate"]


def test_confirm_pattern_signature_has_decision() -> None:
    sig = inspect.signature(FailureCorpus.confirm_pattern)
    assert "pattern_id" in sig.parameters
    assert "decision" in sig.parameters


def test_approve_check_signature_has_decision() -> None:
    sig = inspect.signature(FailureCorpus.approve_check)
    assert "check_id" in sig.parameters
    assert "decision" in sig.parameters


def test_report_effectiveness_window_default() -> None:
    sig = inspect.signature(FailureCorpus.report_effectiveness)
    assert sig.parameters["window_days"].default == 90


def test_decision_enums_present() -> None:
    assert PatternDecision.ACCEPTED.value == "accepted"
    assert PatternDecision.REJECTED.value == "rejected"
    assert CheckApprovalDecision.APPROVED.value == "approved"
    assert CheckApprovalDecision.REJECTED.value == "rejected"


def test_contract_result_types_present() -> None:
    assert FailurePattern is not None
    assert EffectivenessReport is not None
