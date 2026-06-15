"""Pipeline routing rules based on story type.

AG3-069 (AC8): Extended to read ``implementation_contract`` for the
integration_stabilization special routing path (FK-05 §5.6).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.story_context_manager.story_model import WireStoryMode
from agentkit.story_context_manager.types import ImplementationContract, StoryMode, get_profile

if TYPE_CHECKING:
    from agentkit.story_context_manager.models import StoryContext


def _is_fast(context: StoryContext) -> bool:
    """Whether the story runs in fast mode (FK-24 §24.3.3, decoupled axis).

    Fast disables the whole Exploration phase (FK-24 §24.3.4 Mode-Profil
    ``Exploration = OUT``); it is a SEPARATE axis from ``execution_route``.
    """
    return context.mode is WireStoryMode.FAST


def _is_integration_stabilization(context: StoryContext) -> bool:
    """Whether the story uses the integration_stabilization contract.

    AG3-069 (FK-05 §5.6): integration_stabilization always mandates
    exploration and forbids execution-routing before manifest approval.
    """
    return (
        context.implementation_contract
        is ImplementationContract.INTEGRATION_STABILIZATION
    )


def get_phases_for_story(context: StoryContext) -> list[str]:
    profile = get_profile(context.story_type)
    phases = list(profile.phases)

    # AG3-069 (FK-05 §5.6): integration_stabilization ALWAYS keeps exploration
    # in the pipeline — skip_exploration is suppressed for this contract type.
    if _is_integration_stabilization(context):
        # Exploration is mandatory; never removed regardless of execution_route.
        if "exploration" not in phases:
            phases.insert(1, "exploration")
        return phases

    # AG3-018 (FK-24 §24.3.4): a fast story skips the whole Exploration phase
    # and routes setup -> implementation directly, regardless of execution_route.
    skip_exploration = (
        _is_fast(context) or context.execution_route == StoryMode.EXECUTION
    )
    if skip_exploration and "exploration" in phases:
        phases.remove("exploration")

    return phases


def should_run_exploration(context: StoryContext) -> bool:
    profile = get_profile(context.story_type)
    # AG3-069 (FK-05 §5.6): integration_stabilization mandates exploration.
    if _is_integration_stabilization(context) and "exploration" in profile.phases:
        return True
    return (
        not _is_fast(context)
        and context.execution_route == StoryMode.EXPLORATION
        and "exploration" in profile.phases
    )


def is_execution_routing_blocked(context: StoryContext) -> bool:
    """Return True iff execution-routing is blocked for this context.

    AG3-069 (FK-05 §5.6): for integration_stabilization, execution-routing
    is always blocked at setup time (the manifest must be approved via the
    exploration phase before execution proceeds).

    This is a named, typed predicate consumed by the setup-routing layer.
    The guard does NOT attempt to load the approval record itself; the caller
    supplies the context and the approval-record check is a separate
    precondition (``preconditions.check_approval_present``).

    Args:
        context: Story context to check.

    Returns:
        True iff execution-routing must be blocked for this context.
    """
    return _is_integration_stabilization(context)


def should_run_full_qa(context: StoryContext) -> bool:
    return get_profile(context.story_type).uses_full_qa


def requires_worktree(context: StoryContext) -> bool:
    return get_profile(context.story_type).uses_worktree


def requires_merge(context: StoryContext) -> bool:
    return get_profile(context.story_type).uses_merge


__all__ = [
    "get_phases_for_story",
    "is_execution_routing_blocked",
    "requires_merge",
    "requires_worktree",
    "should_run_exploration",
    "should_run_full_qa",
]
