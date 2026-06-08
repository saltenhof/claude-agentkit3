"""Concrete workflow definitions for the four story types."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.exceptions import WorkflowError
from agentkit.process.language.builder import Workflow
from agentkit.process.language.gates import (
    ExplorationGateStage,
    ExplorationGateStageSpec,
)
from agentkit.process.language.guards import (
    GuardResult,
    exploration_gate_approved,
    guard,
    implementation_completed,
    mode_is_exploration,
    preflight_passed,
)
from agentkit.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from agentkit.pipeline_engine.phase_executor import PhaseState
    from agentkit.process.language.model import WorkflowDefinition
    from agentkit.story_context_manager.models import StoryContext


@guard(
    "mode_is_not_exploration",
    description="Checks that the story routes setup directly to implementation.",
    reads=frozenset({"execution_route", "mode"}),
)
def _mode_is_not_exploration(
    ctx: StoryContext,
    state: PhaseState,
) -> GuardResult:
    # AG3-018 (FK-24 §24.3.4): a fast story ALWAYS routes setup -> implementation
    # (Exploration=OUT), regardless of execution_route. The fast/standard mode
    # axis is decoupled from execution_route (FK-24 §24.3.3).
    from agentkit.story_context_manager.story_model import WireStoryMode

    if ctx.mode is WireStoryMode.FAST:
        return GuardResult.PASS()
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
            # FK-23 §23.5.2: Stage 2a design-review is a required gate stage; a
            # FAIL rolls the change-frame back to an editable draft (FK-25
            # §25.4.2) for the next remediation round (AG3-046).
            gate_stage=ExplorationGateStageSpec(
                stage_id=ExplorationGateStage.DESIGN_REVIEW,
                yield_point="design_review",
                required=True,
                rollback_on_fail=True,
            ),
        )
        .yield_to(
            "design_challenge",
            on="awaiting_design_challenge",
            resume_triggers=["challenge_resolved"],
            # FK-23 §23.5.3: Stage 2b design-challenge is the OPTIONAL third
            # stage (mandate-gated; activation deferred to AG3-047). It does not
            # roll the change-frame back by itself.
            gate_stage=ExplorationGateStageSpec(
                stage_id=ExplorationGateStage.DESIGN_CHALLENGE,
                yield_point="design_challenge",
                required=False,
                rollback_on_fail=False,
            ),
        )
        .phase("implementation")
        .max_remediation_rounds(3)
        .phase("closure")
        .substates(["merging", "cleanup", "reporting"])
        .transition("setup", "exploration", guard=mode_is_exploration)
        .transition("setup", "implementation", guard=_mode_is_not_exploration)
        .transition("exploration", "implementation", guard=exploration_gate_approved)
        .transition("implementation", "closure", guard=implementation_completed)
        .hooks(
            pre_transition=["log_transition"],
            post_transition=["emit_telemetry"],
            on_yield=["notify_yield"],
            on_escalate=["notify_escalation"],
        )
        .build()
    )


def _build_bugfix_workflow() -> WorkflowDefinition:
    """Build the workflow definition for bugfix stories.

    AG3-057 (FK-23 §23.1): a bugfix can run in Exploration mode when one of
    the four triggers fires.  The workflow therefore mirrors the implementation
    workflow: setup can route to exploration OR directly to implementation
    depending on ``execution_route``.  The routing is determined by the same
    ``mode_is_exploration`` / ``_mode_is_not_exploration`` guards used by the
    implementation workflow; ``routing_rules.get_phases_for_story`` will then
    remove the ``exploration`` phase for EXECUTION-mode bugfixes (same
    mechanism as for implementation stories — no separate code path needed).
    """
    return (
        Workflow("bugfix")
        .phase("setup")
        .guard(preflight_passed)
        .phase("exploration")
        .yield_to(
            "design_review",
            on="awaiting_design_review",
            resume_triggers=["design_approved", "design_rejected"],
            required_artifacts=["design_artifact"],
            # FK-23 §23.5.2: Stage 2a design-review is a required gate stage.
            gate_stage=ExplorationGateStageSpec(
                stage_id=ExplorationGateStage.DESIGN_REVIEW,
                yield_point="design_review",
                required=True,
                rollback_on_fail=True,
            ),
        )
        .yield_to(
            "design_challenge",
            on="awaiting_design_challenge",
            resume_triggers=["challenge_resolved"],
            # FK-23 §23.5.3: Stage 2b design-challenge is optional.
            gate_stage=ExplorationGateStageSpec(
                stage_id=ExplorationGateStage.DESIGN_CHALLENGE,
                yield_point="design_challenge",
                required=False,
                rollback_on_fail=False,
            ),
        )
        .phase("implementation")
        .max_remediation_rounds(3)
        .phase("closure")
        .substates(["merging", "cleanup", "reporting"])
        .transition("setup", "exploration", guard=mode_is_exploration)
        .transition("setup", "implementation", guard=_mode_is_not_exploration)
        .transition("exploration", "implementation", guard=exploration_gate_approved)
        .transition("implementation", "closure", guard=implementation_completed)
        .hooks(
            pre_transition=["log_transition"],
            post_transition=["emit_telemetry"],
            on_yield=["notify_yield"],
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
        .phase("closure")
        .transition("setup", "implementation")
        .transition("implementation", "closure")
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
