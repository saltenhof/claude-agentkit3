"""Shared process language for pipelines and component flows."""

from __future__ import annotations

from agentkit.process.language.builder import Workflow, WorkflowBuilder
from agentkit.process.language.definitions import (
    BUGFIX_WORKFLOW,
    CONCEPT_WORKFLOW,
    IMPLEMENTATION_WORKFLOW,
    RESEARCH_WORKFLOW,
    resolve_workflow,
)
from agentkit.process.language.gates import Gate, GateStage
from agentkit.process.language.guards import (
    GuardFn,
    GuardResult,
    exploration_gate_approved,
    guard,
    mode_is_exploration,
    preflight_passed,
    verify_completed,
    verify_needs_remediation,
)
from agentkit.process.language.model import (
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
from agentkit.process.language.recovery import (
    DEFAULT_RECOVERY_CONTRACT,
    FieldSource,
    RecoveryContract,
    RehydrationRule,
)
from agentkit.process.language.validators import ValidationError, WorkflowValidator

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
