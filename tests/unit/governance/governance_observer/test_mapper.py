"""Tests for GovernanceIncidentCandidate -> IncidentCandidate mapper (FK-35 §35.3.9).

Covers AC7 (mapper correctness and failure-corpus handoff gate).
"""

from __future__ import annotations

from datetime import UTC, datetime

from agentkit.governance.governance_observer.mapper import to_corpus_incident_candidate
from agentkit.governance.governance_observer.models import (
    AdjudicationIncidentType,
    AdjudicationRecommendedAction,
    AdjudicationSeverity,
    GovernanceAdjudicationVerdict,
    GovernanceIncidentCandidate,
)


def _make_candidate(
    risk_score: int = 40,
    event_count: int = 5,
) -> GovernanceIncidentCandidate:
    return GovernanceIncidentCandidate(
        project_key="PRJ",
        story_id="AG3-085",
        run_id="run-001",
        created_at=datetime.now(UTC),
        risk_score=risk_score,
        event_count=event_count,
        dominant_signals=["orchestrator_code_read_write"],
        evidence_summary="Orchestrator wrote code.",
        time_span_s=120.0,
    )


def _make_verdict(
    severity: AdjudicationSeverity = AdjudicationSeverity.MEDIUM,
    incident_type: AdjudicationIncidentType = AdjudicationIncidentType.ROLE_VIOLATION,
) -> GovernanceAdjudicationVerdict:
    return GovernanceAdjudicationVerdict(
        incident_type=incident_type,
        severity=severity,
        confidence=0.75,
        evidence_summary="Test evidence.",
        recommended_action=AdjudicationRecommendedAction.DOCUMENT_INCIDENT,
    )


def test_mapper_fills_mandatory_fields() -> None:
    """Mapper produces an IncidentCandidate with all mandatory FK-41 fields (AC7)."""
    candidate = _make_candidate()
    verdict = _make_verdict()
    result = to_corpus_incident_candidate(candidate, verdict)

    assert result.project_key == "PRJ"
    assert result.story_id == "AG3-085"
    assert result.run_id == "run-001"
    assert result.category is not None
    assert result.severity is not None
    assert result.phase == "implementation"
    assert result.role is not None
    assert result.model == "governance_adjudicator"
    assert isinstance(result.symptom, str) and result.symptom
    assert isinstance(result.evidence, list) and len(result.evidence) > 0


def test_mapper_severity_propagated_correctly() -> None:
    """Mapper maps adjudication severity to IncidentSeverity wire value."""
    from agentkit.failure_corpus.types import IncidentSeverity

    for adj_sev, expected_inc_sev in [
        (AdjudicationSeverity.MEDIUM, IncidentSeverity.MEDIUM),
        (AdjudicationSeverity.HIGH, IncidentSeverity.HIGH),
        (AdjudicationSeverity.CRITICAL, IncidentSeverity.CRITICAL),
    ]:
        result = to_corpus_incident_candidate(_make_candidate(), _make_verdict(severity=adj_sev))
        assert result.severity == expected_inc_sev, (
            f"adj={adj_sev!r} should map to {expected_inc_sev!r}, got {result.severity!r}"
        )


def test_mapper_scope_drift_maps_to_scope_drift_category() -> None:
    """scope_drift incident type maps to SCOPE_DRIFT failure category."""
    from agentkit.core_types.failure_corpus import FailureCategory

    result = to_corpus_incident_candidate(
        _make_candidate(),
        _make_verdict(incident_type=AdjudicationIncidentType.SCOPE_DRIFT),
    )
    assert result.category == FailureCategory.SCOPE_DRIFT


def test_mapper_evidence_list_contains_risk_score() -> None:
    """Evidence list includes risk_score string (AC7)."""
    result = to_corpus_incident_candidate(_make_candidate(risk_score=55), _make_verdict())
    assert any("risk_score=55" in e for e in result.evidence)


def test_mapper_evidence_is_list_of_strings() -> None:
    """Evidence must be a list of strings (FK-41 §41.4.1)."""
    result = to_corpus_incident_candidate(_make_candidate(), _make_verdict())
    assert isinstance(result.evidence, list)
    assert all(isinstance(e, str) for e in result.evidence)
