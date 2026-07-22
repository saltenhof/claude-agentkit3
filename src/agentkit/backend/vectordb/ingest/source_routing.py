"""Source-type / producer closure (FK-13 §13.3.2 / §13.9.5, Review 174-P0-1).

Positive path recognition for research via the canonical
``stories/<story-folder>/research/**/*.md`` layout. ``review*.md``,
closure/audit artefacts and other unknown markdown are negative research
cases (not ingested).
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from agentkit.backend.vectordb.ingest.models import SourceType

PRODUCER_BY_SOURCE: dict[SourceType, str] = {
    SourceType.STORY: "story_sync",
    SourceType.RESEARCH: "story_sync",
    SourceType.CONCEPT: "concept_sync",
}

SOURCE_TYPES_BY_PRODUCER: dict[str, frozenset[SourceType]] = {
    "story_sync": frozenset({SourceType.STORY, SourceType.RESEARCH}),
    "concept_sync": frozenset({SourceType.CONCEPT}),
}

_STORY_MD_RE = re.compile(r"^stories/[^/]+/story\.md$")
_RESEARCH_MD_RE = re.compile(r"^stories/[^/]+/research/.+\.md$")
_NEGATIVE_RESEARCH_NAMES = re.compile(
    r"(^|/)(review[^/]*|closure[^/]*|audit[^/]*)\.md$",
    re.IGNORECASE,
)


def classify_markdown_path(rel_posix: str) -> SourceType | None:
    """Classify a project-relative markdown path into a source type.

    Returns:
        Source type, or ``None`` when the path must not be ingested.
    """
    path = rel_posix.replace("\\", "/").lstrip("./")
    if _NEGATIVE_RESEARCH_NAMES.search(path):
        return None
    if _STORY_MD_RE.match(path):
        return SourceType.STORY
    if _RESEARCH_MD_RE.match(path):
        return SourceType.RESEARCH
    # Concept paths are decided by the concepts discovery root, not this helper.
    return None


def story_id_from_path(rel_posix: str) -> str:
    """Extract the story folder name from a stories/... path."""
    parts = PurePosixPath(rel_posix.replace("\\", "/")).parts
    if len(parts) >= 2 and parts[0] == "stories":
        return parts[1]
    return ""


def producer_for(source_type: SourceType) -> str:
    """Return the exclusive producer tool for ``source_type``."""
    return PRODUCER_BY_SOURCE[source_type]


def owned_source_types(producer_tool: str) -> frozenset[SourceType]:
    """Return source types owned by ``producer_tool`` (delete/full_reindex scope)."""
    try:
        return SOURCE_TYPES_BY_PRODUCER[producer_tool]
    except KeyError as exc:
        raise KeyError(f"unknown producer tool: {producer_tool!r}") from exc


__all__ = [
    "PRODUCER_BY_SOURCE",
    "SOURCE_TYPES_BY_PRODUCER",
    "classify_markdown_path",
    "owned_source_types",
    "producer_for",
    "story_id_from_path",
]
