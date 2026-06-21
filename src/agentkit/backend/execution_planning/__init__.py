"""Execution-planning bounded context public surface."""

from __future__ import annotations

from agentkit.backend.execution_planning.dependency_graph import DependencyGraph
from agentkit.backend.execution_planning.entities import (
    BlockingCondition,
    BlockingConditionKind,
    BlockingConditionProvenance,
    ExecutionCapacityBudgets,
    ExecutionFeasibility,
    ExecutionSchedulingPolicy,
    ExecutionWave,
    ExecutionWaveLifecycle,
    ExternalGate,
    GateState,
    HumanGate,
    HumanGateKind,
    ParallelizationConfig,
    PlanDerivation,
    PlannedStory,
    PlanningStatus,
    ReadinessAssessment,
    RePlanChange,
    RePlanChangeKind,
    RePlanTrigger,
    SchedulingHint,
    StoryDependency,
    StoryDependencyKind,
    StoryRefForPlanning,
    WaveStory,
    blocking_condition_status,
    classify_replan_trigger,
    planning_status_from_blockers,
)
from agentkit.backend.execution_planning.lifecycle import (
    add_dependency,
    assess_readiness,
    mark_wave_after_results,
    remove_dependency,
)
from agentkit.backend.execution_planning.readiness import derive_budgets, derive_plan
from agentkit.backend.execution_planning.scheduling import (
    EvaluateSchedulingResult,
    ExecutionInputNext,
    ExecutionInputNextReason,
    ExecutionInputSnapshot,
    ExecutionInputStackCard,
    ExecutionInputStoryRef,
    RepoSlotInfo,
    SchedulingDecisionKind,
    SchedulingTriageReason,
    WhyNotNow,
    evaluate_scheduling,
    next_from_snapshot,
    select_execution_input,
)

# Public re-export surface. Entries are packed several-per-line (a plain list
# literal, not an import block) so this package init stays within the
# module-level LOC budget (PY_MODULE_TOP_LEVEL_MAX_LOC_100); contents are
# identical to the historical one-name-per-line list (no symbol added/removed).
__all__ = [
    "BlockingCondition", "BlockingConditionKind", "BlockingConditionProvenance",
    "DependencyGraph", "EvaluateSchedulingResult", "ExecutionCapacityBudgets",
    "ExecutionFeasibility", "ExecutionInputNext", "ExecutionInputNextReason",
    "ExecutionInputSnapshot", "ExecutionInputStackCard", "ExecutionInputStoryRef",
    "ExecutionSchedulingPolicy", "ExecutionWave", "ExecutionWaveLifecycle",
    "ExternalGate", "GateState", "HumanGate", "HumanGateKind",
    "ParallelizationConfig", "PlanDerivation", "PlannedStory", "PlanningStatus",
    "ReadinessAssessment", "RePlanChange", "RePlanChangeKind", "RePlanTrigger",
    "RepoSlotInfo", "SchedulingDecisionKind", "SchedulingHint",
    "SchedulingTriageReason", "StoryDependency", "StoryDependencyKind",
    "StoryRefForPlanning", "WaveStory", "WhyNotNow", "add_dependency",
    "assess_readiness", "blocking_condition_status", "classify_replan_trigger",
    "derive_budgets", "derive_plan", "evaluate_scheduling", "mark_wave_after_results",
    "next_from_snapshot", "planning_status_from_blockers", "remove_dependency",
    "select_execution_input",
]
