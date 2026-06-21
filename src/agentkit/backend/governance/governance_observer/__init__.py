"""GovernanceObserver: rolling-window risk-score + LLM adjudication (FK-35 §35.3).

Public exports of the governance-observer bounded-context sub-package.
"""

from __future__ import annotations

from agentkit.backend.governance.governance_observer.adjudicator import (
    GovernanceAdjudicationError,
    GovernanceAdjudicatorPort,
    HubGovernanceAdjudicator,
    build_adjudication_prompt,
    parse_adjudication_response,
)
from agentkit.backend.governance.governance_observer.cooldown import should_adjudicate
from agentkit.backend.governance.governance_observer.mapper import to_corpus_incident_candidate
from agentkit.backend.governance.governance_observer.measures import select_measure
from agentkit.backend.governance.governance_observer.models import (
    IMMEDIATE_STOP_SIGNALS,
    RISK_POINTS,
    AdjudicationIncidentType,
    AdjudicationRecommendedAction,
    AdjudicationSeverity,
    GovernanceAdjudicationVerdict,
    GovernanceIncidentCandidate,
    GovernanceMeasure,
    GovernanceSignalType,
)
from agentkit.backend.governance.governance_observer.observer import (
    GovernanceObserver,
    lookup_risk_points,
)
from agentkit.backend.governance.governance_observer.reader import (
    StateBackendGovernanceEventReader,
)
from agentkit.backend.governance.governance_observer.score import (
    ExecutionEventReader,
    compute_risk_score,
)

__all__ = [
    # Observer
    "GovernanceObserver",
    "lookup_risk_points",
    # Reader (production ExecutionEventReader implementation)
    "StateBackendGovernanceEventReader",
    # Models
    "AdjudicationIncidentType",
    "AdjudicationRecommendedAction",
    "AdjudicationSeverity",
    "GovernanceAdjudicationVerdict",
    "GovernanceIncidentCandidate",
    "GovernanceMeasure",
    "GovernanceSignalType",
    "IMMEDIATE_STOP_SIGNALS",
    "RISK_POINTS",
    # Score
    "ExecutionEventReader",
    "compute_risk_score",
    # Adjudicator
    "GovernanceAdjudicationError",
    "GovernanceAdjudicatorPort",
    "HubGovernanceAdjudicator",
    "build_adjudication_prompt",
    "parse_adjudication_response",
    # Cooldown
    "should_adjudicate",
    # Mapper
    "to_corpus_incident_candidate",
    # Measures
    "select_measure",
]
