"""Typed models for the GovernanceObserver subsystem (FK-35 §35.3.6/§35.3.7/§35.3.8).

All model field names are English per ARCH-55.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Signal-type registry (FK-93 §93.6)
# ---------------------------------------------------------------------------

class GovernanceSignalType(StrEnum):
    """Typed signal-type registry for governance risk points (FK-93 §93.6).

    Each member maps to a point weight in :data:`RISK_POINTS`.  The two
    immediate-stop signals (GOVERNANCE_FILE_MANIPULATION / SECRET_ACCESS) are
    separate members with NO point value — they trigger a hard stop path
    before the rolling-window accumulator runs.

    Attributes:
        ORCHESTRATOR_CODE_READ_WRITE: Orchestrator reads/writes code (+10).
        ORCHESTRATOR_BASH_NO_SUBAGENT: Orchestrator Bash without Sub-Agent (+8).
        WRITE_OUTSIDE_STORY_SCOPE: Write outside Story scope (+8).
        QA_FAIL_REPEATED: Three or more identical QA fails (+15).
        NO_PHASE_PROGRESS: No phase progress for 4+ hours (+12).
        HIGH_EDIT_REVERT_CHURN: High edit-revert churn (+10).
        SUBAGENT_REPEATED_FAILURE: Sub-Agent fails multiple times (+12).
        REPEATED_DRIFTS: Repeated architecture/scope drifts (+15).
        GOVERNANCE_FILE_MANIPULATION: Governance files manipulated — immediate stop.
        SECRET_ACCESS: Secret/credential accessed — immediate stop.
    """

    ORCHESTRATOR_CODE_READ_WRITE = "orchestrator_code_read_write"
    ORCHESTRATOR_BASH_NO_SUBAGENT = "orchestrator_bash_no_subagent"
    WRITE_OUTSIDE_STORY_SCOPE = "write_outside_story_scope"
    QA_FAIL_REPEATED = "qa_fail_repeated"
    NO_PHASE_PROGRESS = "no_phase_progress"
    HIGH_EDIT_REVERT_CHURN = "high_edit_revert_churn"
    SUBAGENT_REPEATED_FAILURE = "subagent_repeated_failure"
    REPEATED_DRIFTS = "repeated_drifts"
    # Immediate-stop signals (no point value — hard path)
    GOVERNANCE_FILE_MANIPULATION = "governance_file_manipulation"
    SECRET_ACCESS = "secret_access"


#: Risk-point weights per signal type (FK-93 §93.6).
#: Immediate-stop signals are NOT in this map — callers must check
#: :data:`IMMEDIATE_STOP_SIGNALS` first.
RISK_POINTS: dict[GovernanceSignalType, int] = {
    GovernanceSignalType.ORCHESTRATOR_CODE_READ_WRITE: 10,
    GovernanceSignalType.ORCHESTRATOR_BASH_NO_SUBAGENT: 8,
    GovernanceSignalType.WRITE_OUTSIDE_STORY_SCOPE: 8,
    GovernanceSignalType.QA_FAIL_REPEATED: 15,
    GovernanceSignalType.NO_PHASE_PROGRESS: 12,
    GovernanceSignalType.HIGH_EDIT_REVERT_CHURN: 10,
    GovernanceSignalType.SUBAGENT_REPEATED_FAILURE: 12,
    GovernanceSignalType.REPEATED_DRIFTS: 15,
}

#: Immediate-stop signals that bypass score accumulation and adjudication.
IMMEDIATE_STOP_SIGNALS: frozenset[GovernanceSignalType] = frozenset(
    {
        GovernanceSignalType.GOVERNANCE_FILE_MANIPULATION,
        GovernanceSignalType.SECRET_ACCESS,
    }
)


# ---------------------------------------------------------------------------
# Adjudication schema (FK-35 §35.3.7)
# ---------------------------------------------------------------------------

class AdjudicationIncidentType(StrEnum):
    """Incident classification produced by LLM adjudication (FK-35 §35.3.7)."""

    ROLE_VIOLATION = "role_violation"
    SCOPE_DRIFT = "scope_drift"
    RETRY_LOOP = "retry_loop"
    STAGNATION = "stagnation"
    GOVERNANCE_MANIPULATION = "governance_manipulation"
    SECRET_ACCESS = "secret_access"


class AdjudicationSeverity(StrEnum):
    """Severity level from LLM adjudication (FK-35 §35.3.7).

    Mirrors :class:`~agentkit.failure_corpus.types.IncidentSeverity` wire values
    but is a separate enum owned by the governance BC (not the failure-corpus BC).
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AdjudicationRecommendedAction(StrEnum):
    """Recommended action from LLM adjudication (FK-35 §35.3.7)."""

    LOG_ONLY = "log_only"
    DOCUMENT_INCIDENT = "document_incident"
    INCREASE_MONITORING = "increase_monitoring"
    PAUSE_STORY = "pause_story"
    STOP_PROCESS = "stop_process"


class GovernanceAdjudicationVerdict(BaseModel):
    """Typed response schema for LLM governance adjudication (FK-35 §35.3.7).

    This is the dedicated adjudication schema — NOT a CheckResult (FK-35 §35.3.7
    explicitly forbids reusing the CheckResult-validating StructuredEvaluator path).

    Attributes:
        incident_type: Classified incident type.
        severity: Assessed severity level.
        confidence: Confidence score between 0.0 and 1.0.
        evidence_summary: Human-readable summary of evidence.
        recommended_action: Recommended governance action.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    incident_type: AdjudicationIncidentType
    severity: AdjudicationSeverity
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_summary: str
    recommended_action: AdjudicationRecommendedAction


# ---------------------------------------------------------------------------
# Incident candidate (FK-35 §35.3.6)
# ---------------------------------------------------------------------------

class GovernanceIncidentCandidate(BaseModel):
    """Governance-BC incident candidate (FK-35 §35.3.6).

    Distinct from :class:`~agentkit.failure_corpus.incident.IncidentCandidate`
    (the failure-corpus input type).  This model captures the rolling-window
    episode snapshot from the observer.  An explicit mapper converts it to the
    failure-corpus type for :meth:`FailureCorpus.record_incident`.

    Attributes:
        project_key: Project key scope.
        story_id: Story anchor.
        run_id: Run anchor.
        created_at: UTC creation timestamp.
        risk_score: Summed risk points in the current window.
        event_count: Number of events in the window.
        dominant_signals: Most-frequent signal types in the window.
        evidence_summary: Human-readable summary of the episode.
        time_span_s: Elapsed time in seconds between oldest and newest event.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_key: str
    story_id: str
    run_id: str
    created_at: datetime
    risk_score: int
    event_count: int
    dominant_signals: list[str] = Field(default_factory=list)
    evidence_summary: str
    time_span_s: float


# ---------------------------------------------------------------------------
# Deterministic measures (FK-35 §35.3.8)
# ---------------------------------------------------------------------------

class GovernanceMeasure(StrEnum):
    """Deterministic governance measures (FK-35 §35.3.8).

    Attributes:
        STOP_PROCESS: Immediate hard stop (hard violation or critical+conf>=0.8).
        PAUSE_STORY: Pause the story and notify a human.
        DOCUMENT_INCIDENT_INCREASE_MONITORING: Document incident and lower threshold.
        DOCUMENT_INCIDENT: Document incident in failure corpus.
        GOVERNANCE_LOG_ONLY: Telemetry-only governance log entry.
    """

    STOP_PROCESS = "stop_process"
    PAUSE_STORY = "pause_story"
    DOCUMENT_INCIDENT_INCREASE_MONITORING = "document_incident_increase_monitoring"
    DOCUMENT_INCIDENT = "document_incident"
    GOVERNANCE_LOG_ONLY = "governance_log_only"
