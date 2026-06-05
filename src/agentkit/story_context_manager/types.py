"""Story type definitions and pipeline routing profiles.

``StoryMode`` und ``StorySize`` werden seit AG3-021 aus
``agentkit.core_types`` re-exportiert. Lokale Definitionen existieren
nicht mehr; alle Importer arbeiten gegen den Core-Typ.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from agentkit.core_types import StoryMode
from agentkit.exceptions import StoryError


class StoryType(StrEnum):
    IMPLEMENTATION = "implementation"
    BUGFIX = "bugfix"
    CONCEPT = "concept"
    RESEARCH = "research"


class ImplementationContract(StrEnum):
    STANDARD = "standard"
    INTEGRATION_STABILIZATION = "integration_stabilization"


@dataclass(frozen=True)
class StoryTypeProfile:
    story_type: StoryType
    uses_worktree: bool
    uses_full_qa: bool
    uses_merge: bool
    allowed_modes: tuple[StoryMode | None, ...]
    default_mode: StoryMode | None
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
        phases=("setup", "exploration", "implementation", "closure"),
    ),
    StoryType.BUGFIX: StoryTypeProfile(
        story_type=StoryType.BUGFIX,
        uses_worktree=True,
        uses_full_qa=True,
        uses_merge=True,
        # FK-23 §23.1: the scope of mode determination is the implementing story
        # types Implementation AND Bugfix. A bugfix with e.g. ``Concept
        # Quality=Low`` may route into exploration mode (FK-21 §21.3.3 /
        # exploration-and-design.C3). ``default_mode`` stays EXECUTION (a bugfix
        # is explorative only when a trigger fires); ``phases`` stays unchanged --
        # the exploration phase is inserted solely via the mode switch
        # (routing_rules), not via the profile phase tuple.
        allowed_modes=(StoryMode.EXECUTION, StoryMode.EXPLORATION),
        default_mode=StoryMode.EXECUTION,
        allowed_implementation_contracts=(),
        default_implementation_contract=None,
        phases=("setup", "implementation", "closure"),
    ),
    StoryType.CONCEPT: StoryTypeProfile(
        story_type=StoryType.CONCEPT,
        uses_worktree=False,
        uses_full_qa=False,
        uses_merge=False,
        allowed_modes=(None,),
        default_mode=None,
        allowed_implementation_contracts=(),
        default_implementation_contract=None,
        phases=("setup", "implementation", "closure"),
    ),
    StoryType.RESEARCH: StoryTypeProfile(
        story_type=StoryType.RESEARCH,
        uses_worktree=False,
        uses_full_qa=False,
        uses_merge=False,
        allowed_modes=(None,),
        default_mode=None,
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
