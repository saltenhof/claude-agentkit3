"""Ingest profiles parameterising the shared chunking kernel (AG3-174).

Profiles: ``fk13_concept``, ``fk13_story``, ``ak3_tool``.
Token unit is bound to the embedding-model tokenizer; overflow splits
deterministically below the heading level.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from agentkit.backend.vectordb.tokenizer import MAX_CHUNK_TOKENS


class IngestProfileId(StrEnum):
    """Named ingest profiles sharing the concepts/ chunking kernel."""

    FK13_CONCEPT = "fk13_concept"
    FK13_STORY = "fk13_story"
    AK3_TOOL = "ak3_tool"


@dataclass(frozen=True)
class IngestProfile:
    """Chunking / identity parameters for one source family."""

    profile_id: IngestProfileId
    source_type: str
    producer_tool: str
    max_tokens: int
    heading_levels: tuple[int, ...]
    enforce_token_limit_as_error: bool


PROFILES: Final[dict[IngestProfileId, IngestProfile]] = {
    IngestProfileId.FK13_CONCEPT: IngestProfile(
        profile_id=IngestProfileId.FK13_CONCEPT,
        source_type="concept",
        producer_tool="concept_sync",
        max_tokens=MAX_CHUNK_TOKENS,
        heading_levels=(2, 3),
        # E-CHUNK-001 remains blocking even if the generic chunker could split.
        enforce_token_limit_as_error=True,
    ),
    IngestProfileId.FK13_STORY: IngestProfile(
        profile_id=IngestProfileId.FK13_STORY,
        source_type="story",
        producer_tool="story_sync",
        max_tokens=MAX_CHUNK_TOKENS,
        heading_levels=(2, 3),
        enforce_token_limit_as_error=False,
    ),
    IngestProfileId.AK3_TOOL: IngestProfile(
        profile_id=IngestProfileId.AK3_TOOL,
        source_type="concept",
        producer_tool="concept_sync",
        max_tokens=MAX_CHUNK_TOKENS,
        heading_levels=(2,),
        enforce_token_limit_as_error=False,
    ),
}


def get_profile(profile_id: IngestProfileId | str) -> IngestProfile:
    """Resolve a profile by id (fail-closed on unknown)."""
    if isinstance(profile_id, str):
        try:
            profile_id = IngestProfileId(profile_id)
        except ValueError as exc:
            raise KeyError(f"unknown ingest profile: {profile_id!r}") from exc
    return PROFILES[profile_id]


__all__ = [
    "PROFILES",
    "IngestProfile",
    "IngestProfileId",
    "get_profile",
]
