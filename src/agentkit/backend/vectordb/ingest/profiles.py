"""Ingest profiles (FK-13 §13.3.3 / §13.9.4, Review 174-P1-4).

Three profiles parametrise the same SSOT discovery core:

- ``fk13_concept``: concept/architecture sources, token-sized by the bound
  MiniLM tokenizer; ``source_type="concept"``.
- ``fk13_story``: story + research sources, same bound tokenizer; chunks carry
  ``source_type`` ``story`` / ``research``.
- ``ak3_tool``: the AK3 tooling corpus (``tools/`` ingester), same tokenizer.

All profiles bind the SAME embedding-model tokenizer (FK-13 §13.2) and use the
DETERMINISTIC overflow split below the heading level. Behavioural equality
across profiles is secured by the drift test (AC9).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from agentkit.concepts.chunking import DEFAULT_MAX_TOKENS

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True)
class IngestProfile:
    """One parameterisation of the SSOT ingest core.

    Attributes:
        name: Profile identifier (``fk13_concept`` / ``fk13_story`` / ``ak3_tool``).
        max_tokens: Max tokens per chunk under the bound tokenizer.
        source_types: The source_type values this profile is allowed to emit.
        producer: The owning sync tool (``story_sync`` / ``concept_sync``).
    """

    name: str
    max_tokens: int
    source_types: tuple[str, ...]
    producer: str


#: FK-13 concept/architecture profile (concept_sync).
FK13_CONCEPT_PROFILE: Final[IngestProfile] = IngestProfile(
    name="fk13_concept",
    max_tokens=DEFAULT_MAX_TOKENS,
    source_types=("concept",),
    producer="concept_sync",
)

#: FK-13 story + research profile (story_sync).
FK13_STORY_PROFILE: Final[IngestProfile] = IngestProfile(
    name="fk13_story",
    max_tokens=DEFAULT_MAX_TOKENS,
    source_types=("story", "research"),
    producer="story_sync",
)

#: AK3 tooling corpus profile (concept_sync; tooling is concept-class).
AK3_TOOL_PROFILE: Final[IngestProfile] = IngestProfile(
    name="ak3_tool",
    max_tokens=DEFAULT_MAX_TOKENS,
    source_types=("concept",),
    producer="concept_sync",
)

ALL_PROFILES: Final[tuple[IngestProfile, ...]] = (
    FK13_CONCEPT_PROFILE,
    FK13_STORY_PROFILE,
    AK3_TOOL_PROFILE,
)


def profile_by_name(name: str) -> IngestProfile:
    """Return the profile by name (fail-closed on unknown)."""
    for profile in ALL_PROFILES:
        if profile.name == name:
            return profile
    raise KeyError(f"unknown ingest profile {name!r}")


def profiles_for_source_type(source_type: str) -> Sequence[IngestProfile]:
    """Return the profiles allowed to emit ``source_type``."""
    return tuple(p for p in ALL_PROFILES if source_type in p.source_types)


__all__ = [
    "AK3_TOOL_PROFILE",
    "ALL_PROFILES",
    "FK13_CONCEPT_PROFILE",
    "FK13_STORY_PROFILE",
    "IngestProfile",
    "profile_by_name",
    "profiles_for_source_type",
]
