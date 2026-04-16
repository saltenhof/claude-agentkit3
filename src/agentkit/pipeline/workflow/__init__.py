"""Workflow DSL for the 5-phase pipeline.

Public API for defining workflow topology: phases, transitions,
guards, gates, yield points, hooks, and recovery contracts.
"""

from __future__ import annotations

from agentkit.pipeline.workflow.builder import Workflow, WorkflowBuilder
from agentkit.pipeline.workflow.definitions import (
    BUGFIX_WORKFLOW,
    CONCEPT_WORKFLOW,
    IMPLEMENTATION_WORKFLOW,
    RESEARCH_WORKFLOW,
    resolve_workflow,
)
from agentkit.pipeline.workflow.gates import Gate, GateStage
from agentkit.pipeline.workflow.guards import (
    GuardFn,
    GuardResult,
    exploration_gate_approved,
    guard,
    mode_is_exploration,
    preflight_passed,
    verify_completed,
    verify_needs_remediation,
)
from agentkit.pipeline.workflow.model import (
    EdgeRule,
    ExecutionPolicy,
    FlowDefinition,
    FlowLevel,
    HookPoints,
    NodeDefinition,
    NodeKind,
    OverridePolicy,
    PhaseDefinition,
    Precondition,
    RetryPolicy,
    StepExecutionContext,
    StepResult,
    TransitionRule,
    WorkflowDefinition,
    YieldPoint,
)
from agentkit.pipeline.workflow.recovery import (
    DEFAULT_RECOVERY_CONTRACT,
    FieldSource,
    RecoveryContract,
    RehydrationRule,
)
from agentkit.pipeline.workflow.validators import ValidationError, WorkflowValidator

__all__ = [
    # model
    "WorkflowDefinition",
    "FlowDefinition",
    "FlowLevel",
    "PhaseDefinition",
    "NodeDefinition",
    "NodeKind",
    "TransitionRule",
    "EdgeRule",
    "YieldPoint",
    "HookPoints",
    "Precondition",
    "ExecutionPolicy",
    "RetryPolicy",
    "OverridePolicy",
    "StepExecutionContext",
    "StepResult",
    # guards
    "GuardResult",
    "GuardFn",
    "guard",
    "preflight_passed",
    "exploration_gate_approved",
    "verify_completed",
    "verify_needs_remediation",
    "mode_is_exploration",
    # gates
    "Gate",
    "GateStage",
    # builder
    "WorkflowBuilder",
    "Workflow",
    # validators
    "WorkflowValidator",
    "ValidationError",
    # definitions
    "resolve_workflow",
    "IMPLEMENTATION_WORKFLOW",
    "BUGFIX_WORKFLOW",
    "CONCEPT_WORKFLOW",
    "RESEARCH_WORKFLOW",
    # recovery
    "RecoveryContract",
    "RehydrationRule",
    "FieldSource",
    "DEFAULT_RECOVERY_CONTRACT",
]
