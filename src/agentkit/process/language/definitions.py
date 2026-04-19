"""Concrete workflow definitions for the four story types."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.exceptions import WorkflowError
from agentkit.process.language.builder import Workflow
from agentkit.process.language.guards import (
    GuardResult,
    exploration_gate_approved,
    guard,
    mode_is_exploration,
    preflight_passed,
    verify_completed,
    verify_needs_remediation,
)
from agentkit.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from agentkit.process.language.model import WorkflowDefinition
    from agentkit.story_context_manager.models import PhaseState, StoryContext


@guard(
    "mode_is_not_exploration",
    description="Checks that the story execution route is NOT EXPLORATION.",
    reads=frozenset({"execution_route"}),
)
def _mode_is_not_exploration(
    ctx: StoryContext,
    state: PhaseState,
) -> GuardResult:
    if ctx.execution_route != StoryMode.EXPLORATION:
        return GuardResult.PASS()
    return GuardResult.FAIL(
        reason=(
            "Story execution route is EXPLORATION: "
            f"execution_route={ctx.execution_route!r}"
        ),
    )


def _build_implementation_workflow() -> WorkflowDefinition:
    return (
        Workflow("implementation")
        .phase("setup")
        .guard(preflight_passed)
        .phase("exploration")
        .yield_to(
            "design_review",
            on="awaiting_design_review",
            resume_triggers=["design_approved", "design_rejected"],
            required_artifacts=["design_artifact"],
        )
        .yield_to(
            "design_challenge",
            on="awaiting_design_challenge",
            resume_triggers=["challenge_resolved"],
        )
        .phase("implementation")
        .phase("verify")
        .max_remediation_rounds(3)
        .phase("closure")
        .substates(["merging", "cleanup", "reporting"])
        .transition("setup", "exploration", guard=mode_is_exploration)
        .transition("setup", "implementation", guard=_mode_is_not_exploration)
        .transition("exploration", "implementation", guard=exploration_gate_approved)
        .transition("implementation", "verify")
        .transition("verify", "closure", guard=verify_completed)
        .transition(
            "verify",
            "implementation",
            guard=verify_needs_remediation,
            resume_policy="remediation",
        )
        .hooks(
            pre_transition=["log_transition"],
            post_transition=["emit_telemetry"],
            on_yield=["notify_yield"],
            on_escalate=["notify_escalation"],
        )
        .build()
    )


def _build_bugfix_workflow() -> WorkflowDefinition:
    return (
        Workflow("bugfix")
        .phase("setup")
        .guard(preflight_passed)
        .phase("implementation")
        .phase("verify")
        .max_remediation_rounds(3)
        .phase("closure")
        .substates(["merging", "cleanup", "reporting"])
        .transition("setup", "implementation")
        .transition("implementation", "verify")
        .transition("verify", "closure", guard=verify_completed)
        .transition(
            "verify",
            "implementation",
            guard=verify_needs_remediation,
            resume_policy="remediation",
        )
        .hooks(
            pre_transition=["log_transition"],
            post_transition=["emit_telemetry"],
            on_escalate=["notify_escalation"],
        )
        .build()
    )


def _build_concept_workflow() -> WorkflowDefinition:
    return (
        Workflow("concept")
        .phase("setup")
        .guard(preflight_passed)
        .phase("implementation")
        .phase("verify")
        .phase("closure")
        .transition("setup", "implementation")
        .transition("implementation", "verify")
        .transition("verify", "closure")
        .hooks(
            pre_transition=["log_transition"],
            post_transition=["emit_telemetry"],
        )
        .build()
    )


def _build_research_workflow() -> WorkflowDefinition:
    return (
        Workflow("research")
        .phase("setup")
        .guard(preflight_passed)
        .phase("implementation")
        .phase("closure")
        .transition("setup", "implementation")
        .transition("implementation", "closure")
        .hooks(
            pre_transition=["log_transition"],
            post_transition=["emit_telemetry"],
        )
        .build()
    )


IMPLEMENTATION_WORKFLOW = _build_implementation_workflow()
BUGFIX_WORKFLOW = _build_bugfix_workflow()
CONCEPT_WORKFLOW = _build_concept_workflow()
RESEARCH_WORKFLOW = _build_research_workflow()

_WORKFLOW_MAP: dict[StoryType, WorkflowDefinition] = {
    StoryType.IMPLEMENTATION: IMPLEMENTATION_WORKFLOW,
    StoryType.BUGFIX: BUGFIX_WORKFLOW,
    StoryType.CONCEPT: CONCEPT_WORKFLOW,
    StoryType.RESEARCH: RESEARCH_WORKFLOW,
}


def resolve_workflow(story_type: StoryType) -> WorkflowDefinition:
    """Return the workflow definition for a given story type."""

    workflow = _WORKFLOW_MAP.get(story_type)
    if workflow is None:
        raise WorkflowError(
            f"No workflow registered for story type: {story_type!r}",
            detail={"story_type": str(story_type)},
        )
    return workflow
