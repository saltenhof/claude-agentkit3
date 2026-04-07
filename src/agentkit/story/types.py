"""Story type definitions and pipeline routing profiles.

Defines the four story types (implementation, bugfix, concept, research)
and their characteristics that determine pipeline routing.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from agentkit.exceptions import StoryError


class StoryType(StrEnum):
    """The four story types that AgentKit processes.

    Each type determines which pipeline phases are executed,
    whether a git worktree is needed, and how QA is performed.
    """

    IMPLEMENTATION = "implementation"
    BUGFIX = "bugfix"
    CONCEPT = "concept"
    RESEARCH = "research"


class StoryMode(StrEnum):
    """Execution mode -- determines whether exploration phase runs.

    Attributes:
        EXECUTION: Skip exploration, go straight to implementation.
        EXPLORATION: Run exploration phase first (design artifact).
        NOT_APPLICABLE: For concept/research -- no code execution.
    """

    EXECUTION = "execution"
    EXPLORATION = "exploration"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class StoryTypeProfile:
    """Characteristics of a story type for pipeline routing.

    Each story type has a fixed profile that determines which pipeline
    phases it goes through, whether it uses a worktree, and how QA
    is performed.

    Args:
        story_type: The story type this profile describes.
        uses_worktree: Whether a git worktree is created for this story.
        uses_full_qa: Whether full 4-layer QA runs in the verify phase.
        uses_merge: Whether closure includes a git merge to main.
        allowed_modes: Tuple of execution modes valid for this story type.
        default_mode: The default execution mode if none is specified.
        phases: Ordered tuple of phase names this story type goes through.
    """

    story_type: StoryType
    uses_worktree: bool
    uses_full_qa: bool
    uses_merge: bool
    allowed_modes: tuple[StoryMode, ...]
    default_mode: StoryMode
    phases: tuple[str, ...]


PROFILES: dict[StoryType, StoryTypeProfile] = {
    StoryType.IMPLEMENTATION: StoryTypeProfile(
        story_type=StoryType.IMPLEMENTATION,
        uses_worktree=True,
        uses_full_qa=True,
        uses_merge=True,
        allowed_modes=(StoryMode.EXECUTION, StoryMode.EXPLORATION),
        default_mode=StoryMode.EXPLORATION,
        phases=(
            "setup",
            "exploration",
            "implementation",
            "verify",
            "closure",
        ),
    ),
    StoryType.BUGFIX: StoryTypeProfile(
        story_type=StoryType.BUGFIX,
        uses_worktree=True,
        uses_full_qa=True,
        uses_merge=True,
        allowed_modes=(StoryMode.EXECUTION,),
        default_mode=StoryMode.EXECUTION,
        phases=(
            "setup",
            "implementation",
            "verify",
            "closure",
        ),
    ),
    StoryType.CONCEPT: StoryTypeProfile(
        story_type=StoryType.CONCEPT,
        uses_worktree=False,
        uses_full_qa=False,
        uses_merge=False,
        allowed_modes=(StoryMode.NOT_APPLICABLE,),
        default_mode=StoryMode.NOT_APPLICABLE,
        phases=(
            "setup",
            "implementation",
            "verify",
            "closure",
        ),
    ),
    StoryType.RESEARCH: StoryTypeProfile(
        story_type=StoryType.RESEARCH,
        uses_worktree=False,
        uses_full_qa=False,
        uses_merge=False,
        allowed_modes=(StoryMode.NOT_APPLICABLE,),
        default_mode=StoryMode.NOT_APPLICABLE,
        phases=(
            "setup",
            "implementation",
            "closure",
        ),
    ),
}
"""Mapping of each story type to its pipeline routing profile."""


def get_profile(story_type: StoryType) -> StoryTypeProfile:
    """Return the pipeline routing profile for a story type.

    Args:
        story_type: The story type to look up.

    Returns:
        The corresponding ``StoryTypeProfile``.

    Raises:
        StoryError: If the story type has no registered profile.
    """
    profile = PROFILES.get(story_type)
    if profile is None:
        raise StoryError(
            f"No profile registered for story type: {story_type!r}",
            detail={"story_type": str(story_type)},
        )
    return profile
