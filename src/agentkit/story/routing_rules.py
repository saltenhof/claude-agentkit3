"""Pipeline routing rules based on story type.

All routing decisions derive from ``StoryTypeProfile`` -- there are no
hardcoded if/else chains. This module provides convenient query functions
that the pipeline engine uses to determine execution behavior.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.story.types import StoryMode, get_profile

if TYPE_CHECKING:
    from agentkit.story.models import StoryContext


def get_phases_for_story(context: StoryContext) -> list[str]:
    """Return ordered list of phases this story will go through.

    For implementation stories in EXECUTION mode, the exploration
    phase is skipped even though it appears in the profile's phase
    list.

    Args:
        context: The story context containing type and mode.

    Returns:
        Ordered list of phase names.
    """
    profile = get_profile(context.story_type)
    phases = list(profile.phases)

    # In EXECUTION mode, skip exploration even if it's in the profile
    if context.mode == StoryMode.EXECUTION and "exploration" in phases:
        phases.remove("exploration")

    return phases


def should_run_exploration(context: StoryContext) -> bool:
    """Whether this story needs an exploration phase.

    Returns ``True`` only for stories whose mode is EXPLORATION and
    whose type profile includes the exploration phase.

    Args:
        context: The story context containing type and mode.

    Returns:
        ``True`` if exploration should run.
    """
    profile = get_profile(context.story_type)
    return (
        context.mode == StoryMode.EXPLORATION
        and "exploration" in profile.phases
    )


def should_run_full_qa(context: StoryContext) -> bool:
    """Whether this story gets full 4-layer QA in verify.

    Args:
        context: The story context containing type and mode.

    Returns:
        ``True`` if full QA should run.
    """
    profile = get_profile(context.story_type)
    return profile.uses_full_qa


def requires_worktree(context: StoryContext) -> bool:
    """Whether this story needs a git worktree.

    Args:
        context: The story context containing type and mode.

    Returns:
        ``True`` if a worktree is needed.
    """
    profile = get_profile(context.story_type)
    return profile.uses_worktree


def requires_merge(context: StoryContext) -> bool:
    """Whether closure includes merge to main.

    Args:
        context: The story context containing type and mode.

    Returns:
        ``True`` if the story's closure phase should merge to main.
    """
    profile = get_profile(context.story_type)
    return profile.uses_merge
