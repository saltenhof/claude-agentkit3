"""Pipeline routing rules based on story type."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.story_context_manager.types import StoryMode, get_profile

if TYPE_CHECKING:
    from agentkit.story_context_manager.models import StoryContext


def get_phases_for_story(context: StoryContext) -> list[str]:
    profile = get_profile(context.story_type)
    phases = list(profile.phases)

    if context.mode == StoryMode.EXECUTION and "exploration" in phases:
        phases.remove("exploration")

    return phases


def should_run_exploration(context: StoryContext) -> bool:
    profile = get_profile(context.story_type)
    return context.mode == StoryMode.EXPLORATION and "exploration" in profile.phases


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
