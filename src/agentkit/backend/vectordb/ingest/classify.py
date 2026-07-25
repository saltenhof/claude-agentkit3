"""Source-type / producer classification (FK-13 §13.3.2 corrected, §13.9.5).

Maps a file path to its ``source_type`` (or ``None`` = NOT ingested) and the
owning sync tool. This is the abnahmeverbindliche closure (Review 174-P0-1):

- ``stories/<story>/story.md``            -> ``story``     -> ``story_sync``
- ``stories/<story>/research/**/*.md``     -> ``research``  -> ``story_sync``
  (POSITIVE canonical-path recognition, NOT a negativfilter)
- configured concept / architecture sources -> ``concept``  -> ``concept_sync``
- ``review*.md``, closure/audit artefacts, unknown markdown -> NEGATIVE
  (``None``); a ``review*.md`` never lands as a research case.

``full_reindex`` deletes ONLY the source-types owned by the calling tool within
the bound ``project_id`` (enforced in :mod:`agentkit.backend.vectordb.sync`).
"""

from __future__ import annotations

import re
from typing import Final

#: source_type -> owning sync tool (the closure).
PRODUCER_BY_SOURCE_TYPE: Final[dict[str, str]] = {
    "story": "story_sync",
    "research": "story_sync",
    "concept": "concept_sync",
}

#: Project-relative name of the story corpus root (FK-13 §13.3.2).
STORIES_DIR_NAME: Final[str] = "stories"

#: Canonical story-DIRECTORY name: the story id plus an optional slug suffix
#: (e.g. ``AG3-174-vectordb-retrieval-engine``). This is the ONE definition of the
#: directory <-> story-id relation; the export, the repair scan and the research
#: ingest all derive the story id through :func:`story_id_from_story_dir_name`
#: (N32: returning the directory name verbatim mis-identified slugged stories).
STORY_DIR_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<story_id>[A-Z][A-Z0-9]{1,9}-\d+)(?:[_-].*)?$"
)

_STORY_MD_RE = re.compile(r"^stories/[^/]+/story\.md$")
_RESEARCH_RE = re.compile(r"^stories/[^/]+/research/.+\.md$")
_REVIEW_RE = re.compile(r"(^|/)review[^/]*\.md$", re.IGNORECASE)
#: Closure/audit artefact markers (negative research cases).
_CLOSURE_MARKERS: Final[tuple[str, ...]] = (
    "/closure/",
    "/audit/",
    "handover",
    "cut-history",
)


def classify_source_file(rel_path: str, *, concept_roots: tuple[str, ...] = ()) -> str | None:
    """Classify a POSIX-relative file path into a source_type or None.

    Args:
        rel_path: POSIX-style path relative to the project root.
        concept_roots: Configured concept corpus roots (anything beneath them is
            ``concept``). Defaults to ``("concept/",)``.

    Returns:
        ``"story"`` / ``"research"`` / ``"concept"`` or ``None`` (not ingested).
    """
    path = rel_path.replace("\\", "/").lstrip("./")
    # Negative cases FIRST: review*.md / closure / audit artefacts never land.
    if _REVIEW_RE.search(path):
        return None
    if any(marker in path.lower() for marker in _CLOSURE_MARKERS):
        return None
    # Story artefact: stories/<id>/story.md
    if _STORY_MD_RE.match(path):
        return "story"
    # Research: positive canonical-path recognition.
    if _RESEARCH_RE.match(path):
        return "research"
    # Concept / architecture sources.
    roots = concept_roots or ("concept/",)
    for root in roots:
        if path.startswith(root):
            return "concept"
    # Unknown markdown: not ingested (negative).
    return None


def story_id_from_story_dir_name(directory_name: str) -> str | None:
    """Return the story id a story-directory name identifies (``None`` if none).

    ``AG3-174`` and ``AG3-174-vectordb-retrieval-engine`` both identify ``AG3-174``
    (the corpus convention); anything else is not a story directory.
    """
    match = STORY_DIR_RE.match(directory_name)
    return match.group("story_id") if match else None


def producer_for(source_type: str | None) -> str | None:
    """Return the owning sync tool for a source_type (None if not ingested)."""
    if source_type is None:
        return None
    return PRODUCER_BY_SOURCE_TYPE.get(source_type)


def source_types_for_producer(producer: str) -> tuple[str, ...]:
    """Return the source_types owned by a sync tool (delete-closure scope)."""
    return tuple(st for st, prod in PRODUCER_BY_SOURCE_TYPE.items() if prod == producer)


__all__ = [
    "PRODUCER_BY_SOURCE_TYPE",
    "STORIES_DIR_NAME",
    "STORY_DIR_RE",
    "classify_source_file",
    "producer_for",
    "source_types_for_producer",
    "story_id_from_story_dir_name",
]
