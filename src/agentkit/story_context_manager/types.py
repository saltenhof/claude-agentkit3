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
        # FK-23 §23.1 / AG3-057: a bugfix can route into Exploration mode when
        # one of the four triggers fires.  ``default_mode`` stays EXECUTION
        # (a bugfix is explorative only when a trigger fires explicitly).
        # ``phases`` now includes ``"exploration"`` so that
        # ``routing_rules.get_phases_for_story`` can remove it for
        # EXECUTION-route bugfixes (same mechanism as for implementation stories,
        # no special-casing needed).  The BUGFIX_WORKFLOW definition was updated
        # in sync (definitions.py) to carry the exploration phase and its
        # transitions (setup→exploration, exploration→implementation).
        allowed_modes=(StoryMode.EXECUTION, StoryMode.EXPLORATION),
        default_mode=StoryMode.EXECUTION,
        allowed_implementation_contracts=(),
        default_implementation_contract=None,
        phases=("setup", "exploration", "implementation", "closure"),
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
