"""Worker health monitor domain surface."""

from __future__ import annotations

from agentkit.implementation.worker_health.engine import apply_post_tool_use
from agentkit.implementation.worker_health.interventions import (
    InterventionResult,
    intervention_decision,
    intervention_decision_result,
)
from agentkit.implementation.worker_health.models import (
    AgentHealthState,
    CommitFailureCategory,
    HookFailure,
    InterventionKind,
    LlmAssessmentStatus,
    PostToolOutcome,
    ScoreComponents,
    ToolCallRecord,
)
from agentkit.implementation.worker_health.scoring import (
    _FAILURE_PATTERNS,
    classify_commit_failure,
    compute_health_score,
)

__all__ = [
    "AgentHealthState",
    "CommitFailureCategory",
    "HookFailure",
    "InterventionKind",
    "InterventionResult",
    "LlmAssessmentStatus",
    "PostToolOutcome",
    "ScoreComponents",
    "ToolCallRecord",
    "_FAILURE_PATTERNS",
    "apply_post_tool_use",
    "classify_commit_failure",
    "compute_health_score",
    "intervention_decision",
    "intervention_decision_result",
]
