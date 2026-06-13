"""Mapper: GovernanceIncidentCandidate + verdict -> failure_corpus.IncidentCandidate.

This module provides the EXPLICIT conversion required by FK-35 §35.3.9:
governance incidents that reach severity >= medium are handed off to the
Failure Corpus via :meth:`~agentkit.failure_corpus.top.FailureCorpus.record_incident`.
The two models are structurally different and require an explicit field mapping.
"""

from __future__ import annotations

from agentkit.core_types.failure_corpus import FailureCategory
from agentkit.failure_corpus.incident import IncidentCandidate
from agentkit.failure_corpus.types import IncidentRole, IncidentSeverity
from agentkit.governance.governance_observer.models import (
    AdjudicationIncidentType,
    AdjudicationSeverity,
    GovernanceAdjudicationVerdict,
    GovernanceIncidentCandidate,
)

#: Mapping from governance adjudication incident type to FK-41 failure category.
_INCIDENT_TYPE_TO_CATEGORY: dict[AdjudicationIncidentType, FailureCategory] = {
    AdjudicationIncidentType.ROLE_VIOLATION: FailureCategory.POLICY_VIOLATION,
    AdjudicationIncidentType.SCOPE_DRIFT: FailureCategory.SCOPE_DRIFT,
    AdjudicationIncidentType.RETRY_LOOP: FailureCategory.TOOL_MISUSE,
    AdjudicationIncidentType.STAGNATION: FailureCategory.TOOL_MISUSE,
    AdjudicationIncidentType.GOVERNANCE_MANIPULATION: FailureCategory.POLICY_VIOLATION,
    AdjudicationIncidentType.SECRET_ACCESS: FailureCategory.POLICY_VIOLATION,
}

#: Mapping from governance adjudication severity to FK-41 IncidentSeverity.
_SEVERITY_MAP: dict[AdjudicationSeverity, IncidentSeverity] = {
    AdjudicationSeverity.LOW: IncidentSeverity.LOW,
    AdjudicationSeverity.MEDIUM: IncidentSeverity.MEDIUM,
    AdjudicationSeverity.HIGH: IncidentSeverity.HIGH,
    AdjudicationSeverity.CRITICAL: IncidentSeverity.CRITICAL,
}

#: Phase label used for governance incidents.
_GOVERNANCE_PHASE: str = "implementation"
#: Role label for governance incidents (FK-41 §41.3.1).
_GOVERNANCE_ROLE: IncidentRole = IncidentRole.GOVERNANCE
#: Model label when the verdict is LLM-generated (no specific model known here).
_GOVERNANCE_MODEL: str = "governance_adjudicator"


def to_corpus_incident_candidate(
    candidate: GovernanceIncidentCandidate,
    verdict: GovernanceAdjudicationVerdict,
) -> IncidentCandidate:
    """Map a governance incident + verdict to a failure-corpus IncidentCandidate.

    Only call this function when ``verdict.severity >= medium``; the caller
    (GovernanceObserver) is responsible for the severity gate.

    Args:
        candidate: The GovernanceObserver's incident candidate.
        verdict: The LLM adjudication verdict for the candidate.

    Returns:
        A :class:`~agentkit.failure_corpus.incident.IncidentCandidate` ready
        for :meth:`~agentkit.failure_corpus.top.FailureCorpus.record_incident`.
    """
    category = _INCIDENT_TYPE_TO_CATEGORY[verdict.incident_type]
    severity = _SEVERITY_MAP[verdict.severity]
    evidence = _build_evidence(candidate, verdict)
    symptom = _build_symptom(verdict)
    return IncidentCandidate(
        project_key=candidate.project_key,
        story_id=candidate.story_id,
        run_id=candidate.run_id,
        category=category,
        severity=severity,
        phase=_GOVERNANCE_PHASE,
        role=_GOVERNANCE_ROLE,
        model=_GOVERNANCE_MODEL,
        symptom=symptom,
        evidence=evidence,
    )


def _build_symptom(verdict: GovernanceAdjudicationVerdict) -> str:
    """Build the free-text symptom string for the corpus candidate.

    Args:
        verdict: The adjudication verdict.

    Returns:
        Human-readable symptom description.
    """
    return (
        f"Governance incident: {verdict.incident_type.value} "
        f"(severity={verdict.severity.value}, confidence={verdict.confidence:.2f}). "
        f"{verdict.evidence_summary}"
    )


def _build_evidence(
    candidate: GovernanceIncidentCandidate,
    verdict: GovernanceAdjudicationVerdict,
) -> list[str]:
    """Build the evidence list for the corpus candidate.

    Args:
        candidate: The GovernanceObserver incident candidate.
        verdict: The adjudication verdict.

    Returns:
        List of evidence strings (FK-41 §41.4.1).
    """
    return [
        f"risk_score={candidate.risk_score}",
        f"event_count={candidate.event_count}",
        f"time_span_s={candidate.time_span_s:.1f}",
        f"dominant_signals={','.join(candidate.dominant_signals)}",
        f"incident_type={verdict.incident_type.value}",
        f"recommended_action={verdict.recommended_action.value}",
        candidate.evidence_summary,
    ]
