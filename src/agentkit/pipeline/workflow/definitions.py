"""Concrete workflow definitions for the four story types.

Each story type (implementation, bugfix, concept, research) has a
predefined workflow definition constructed via the builder API.
``resolve_workflow`` maps a ``StoryType`` to the appropriate workflow.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.exceptions import WorkflowError
from agentkit.pipeline.workflow.builder import Workflow
from agentkit.pipeline.workflow.guards import (
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
    from agentkit.pipeline.workflow.model import WorkflowDefinition
    from agentkit.story_context_manager.models import PhaseState, StoryContext

# ---------------------------------------------------------------------------
# Local guard: inverse of mode_is_exploration
# ---------------------------------------------------------------------------


@guard(
    "mode_is_not_exploration",
    description="Checks that the story mode is NOT EXPLORATION.",
    reads=frozenset({"mode"}),
)
def _mode_is_not_exploration(
    ctx: StoryContext,
    state: PhaseState,
) -> GuardResult:
    """Check whether the story is NOT running in exploration mode.

    This guard is the inverse of ``mode_is_exploration``. It passes
    when the story mode is EXECUTION or NOT_APPLICABLE, allowing
    the pipeline to skip the exploration phase entirely.

    Args:
        ctx: The story context to inspect for mode.
        state: The current phase state (unused but required by signature).

    Returns:
        ``GuardResult.PASS()`` if mode is not EXPLORATION, ``FAIL`` otherwise.
    """
    if ctx.mode != StoryMode.EXPLORATION:
        return GuardResult.PASS()
    return GuardResult.FAIL(
        reason=f"Story mode is EXPLORATION: mode={ctx.mode!r}",
    )


# ---------------------------------------------------------------------------
# Implementation Workflow
# ---------------------------------------------------------------------------

IMPLEMENTATION_WORKFLOW: WorkflowDefinition = (
    Workflow("implementation")
    # --- Phases ---
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
    # --- Transitions ---
    .transition("setup", "exploration", guard=mode_is_exploration)
    .transition("setup", "implementation", guard=_mode_is_not_exploration)
    .transition("exploration", "implementation", guard=exploration_gate_approved)
    .transition("implementation", "verify")
    .transition("verify", "closure", guard=verify_completed)
    .transition(
        "verify", "implementation",
        guard=verify_needs_remediation,
        resume_policy="remediation",
    )
    # --- Hooks ---
    .hooks(
        pre_transition=["log_transition"],
        post_transition=["emit_telemetry"],
        on_yield=["notify_yield"],
        on_escalate=["notify_escalation"],
    )
    .build()
)
"""Workflow for implementation stories (5 phases, full pipeline)."""

# ---------------------------------------------------------------------------
# Bugfix Workflow
# ---------------------------------------------------------------------------

BUGFIX_WORKFLOW: WorkflowDefinition = (
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
        "verify", "implementation",
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
"""Workflow for bugfix stories (4 phases, no exploration)."""

# ---------------------------------------------------------------------------
# Concept Workflow
# ---------------------------------------------------------------------------

CONCEPT_WORKFLOW: WorkflowDefinition = (
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
"""Workflow for concept stories (4 phases, simple verify, no remediation loop)."""

# ---------------------------------------------------------------------------
# Research Workflow
# ---------------------------------------------------------------------------

RESEARCH_WORKFLOW: WorkflowDefinition = (
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
"""Workflow for research stories (3 phases, no verify, no merge)."""

# ---------------------------------------------------------------------------
# Workflow resolution
# ---------------------------------------------------------------------------

_WORKFLOW_MAP: dict[StoryType, WorkflowDefinition] = {
    StoryType.IMPLEMENTATION: IMPLEMENTATION_WORKFLOW,
    StoryType.BUGFIX: BUGFIX_WORKFLOW,
    StoryType.CONCEPT: CONCEPT_WORKFLOW,
    StoryType.RESEARCH: RESEARCH_WORKFLOW,
}


def resolve_workflow(story_type: StoryType) -> WorkflowDefinition:
    """Return the workflow definition for a given story type.

    Args:
        story_type: The story type to resolve.

    Returns:
        The matching ``WorkflowDefinition``.

    Raises:
        WorkflowError: If no workflow is registered for the story type.
    """
    workflow = _WORKFLOW_MAP.get(story_type)
    if workflow is None:
        raise WorkflowError(
            f"No workflow registered for story type: {story_type!r}",
            detail={"story_type": str(story_type)},
        )
    return workflow
