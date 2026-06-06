"""Pipeline routing rules based on story type."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.story_context_manager.story_model import WireStoryMode
from agentkit.story_context_manager.types import StoryMode, get_profile

if TYPE_CHECKING:
    from agentkit.story_context_manager.models import StoryContext


def _is_fast(context: StoryContext) -> bool:
    """Whether the story runs in fast mode (FK-24 §24.3.3, decoupled axis).

    Fast disables the whole Exploration phase (FK-24 §24.3.4 Mode-Profil
    ``Exploration = OUT``); it is a SEPARATE axis from ``execution_route``.
    """
    return context.mode is WireStoryMode.FAST


def get_phases_for_story(context: StoryContext) -> list[str]:
    profile = get_profile(context.story_type)
    phases = list(profile.phases)

    # AG3-018 (FK-24 §24.3.4): a fast story skips the whole Exploration phase
    # and routes setup -> implementation directly, regardless of execution_route.
    skip_exploration = _is_fast(context) or context.execution_route == StoryMode.EXECUTION
    if skip_exploration and "exploration" in phases:
        phases.remove("exploration")

    return phases


def should_run_exploration(context: StoryContext) -> bool:
    profile = get_profile(context.story_type)
    return (
        not _is_fast(context)
        and context.execution_route == StoryMode.EXPLORATION
        and "exploration" in profile.phases
    )


def should_run_full_qa(context: StoryContext) -> bool:
    return get_profile(context.story_type).uses_full_qa


def requires_worktree(context: StoryContext) -> bool:
    return get_profile(context.story_type).uses_worktree


def requires_merge(context: StoryContext) -> bool:
    return get_profile(context.story_type).uses_merge

__all__ = [
    "get_phases_for_story",
    "requires_merge",
    "requires_worktree",
    "should_run_exploration",
    "should_run_full_qa",
]
