"""Story type definitions and pipeline routing profiles."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from agentkit.exceptions import StoryError


class StoryType(StrEnum):
    IMPLEMENTATION = "implementation"
    BUGFIX = "bugfix"
    CONCEPT = "concept"
    RESEARCH = "research"


class ImplementationContract(StrEnum):
    STANDARD = "standard"
    INTEGRATION_STABILIZATION = "integration_stabilization"


class StoryMode(StrEnum):
    """Execution route for one governed story run."""

    EXECUTION = "execution"
    EXPLORATION = "exploration"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class StoryTypeProfile:
    story_type: StoryType
    uses_worktree: bool
    uses_full_qa: bool
    uses_merge: bool
    allowed_modes: tuple[StoryMode, ...]
    default_mode: StoryMode
    allowed_implementation_contracts: tuple[ImplementationContract, ...]
    default_implementation_contract: ImplementationContract | None
    phases: tuple[str, ...]


PROFILES: dict[StoryType, StoryTypeProfile] = {
    StoryType.IMPLEMENTATION: StoryTypeProfile(
        story_type=StoryType.IMPLEMENTATION,
        uses_worktree=True,
        uses_full_qa=True,
        uses_merge=True,
        allowed_modes=(StoryMode.EXECUTION, StoryMode.EXPLORATION),
        default_mode=StoryMode.EXPLORATION,
        allowed_implementation_contracts=(
            ImplementationContract.STANDARD,
            ImplementationContract.INTEGRATION_STABILIZATION,
        ),
        default_implementation_contract=ImplementationContract.STANDARD,
        phases=("setup", "exploration", "implementation", "verify", "closure"),
    ),
    StoryType.BUGFIX: StoryTypeProfile(
        story_type=StoryType.BUGFIX,
        uses_worktree=True,
        uses_full_qa=True,
        uses_merge=True,
        allowed_modes=(StoryMode.EXECUTION,),
        default_mode=StoryMode.EXECUTION,
        allowed_implementation_contracts=(),
        default_implementation_contract=None,
        phases=("setup", "implementation", "verify", "closure"),
    ),
    StoryType.CONCEPT: StoryTypeProfile(
        story_type=StoryType.CONCEPT,
        uses_worktree=False,
        uses_full_qa=False,
        uses_merge=False,
        allowed_modes=(StoryMode.NOT_APPLICABLE,),
        default_mode=StoryMode.NOT_APPLICABLE,
        allowed_implementation_contracts=(),
        default_implementation_contract=None,
        phases=("setup", "implementation", "verify", "closure"),
    ),
    StoryType.RESEARCH: StoryTypeProfile(
        story_type=StoryType.RESEARCH,
        uses_worktree=False,
        uses_full_qa=False,
        uses_merge=False,
        allowed_modes=(StoryMode.NOT_APPLICABLE,),
        default_mode=StoryMode.NOT_APPLICABLE,
        allowed_implementation_contracts=(),
        default_implementation_contract=None,
        phases=("setup", "implementation", "closure"),
    ),
}


def get_profile(story_type: StoryType) -> StoryTypeProfile:
    profile = PROFILES.get(story_type)
    if profile is None:
        raise StoryError(
            f"No profile registered for story type: {story_type!r}",
            detail={"story_type": str(story_type)},
        )
    return profile

__all__ = [
    "ImplementationContract",
    "StoryMode",
    "StoryType",
    "StoryTypeProfile",
    "get_profile",
]
