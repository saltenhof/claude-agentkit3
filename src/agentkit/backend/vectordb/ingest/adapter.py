"""Ingest adapter: SSOT discovery core -> StoryContext objects (Review 174-P1-4).

Thin adapter on :mod:`agentkit.concepts`. Adds NO second discovery path: it
projects the typed :class:`~agentkit.concepts.parser.ConceptChunk` (and story
documents) into the Weaviate ``StoryContext`` property shape owned by
:mod:`agentkit.backend.vectordb.schema`. Every object gets a deterministic UUID
and is fail-closed validated before it is handed to the transport.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.vectordb.schema import (
    SOURCE_TYPES,
    StoryContextObject,
    deterministic_uuid,
    validate_object,
)
from agentkit.concepts.chunking import DEFAULT_MAX_TOKENS, chunk_document
from agentkit.concepts.frontmatter import parse_frontmatter_block, split_frontmatter
from agentkit.concepts.hashing import chunk_hash

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from agentkit.backend.vectordb.project_binding import ProjectBinding
    from agentkit.concepts.parser import ConceptChunk, DiscoveryResult


def concept_chunks_to_objects(
    project_id: str,
    discovery: DiscoveryResult,
) -> list[StoryContextObject]:
    """Project concept discovery chunks into StoryContext objects.

    Args:
        project_id: Bound multi-tenant discriminator.
        discovery: The SSOT discovery result (concept corpus).

    Returns:
        Validated :class:`StoryContextObject` list with ``source_type="concept"``.
    """
    objects: list[StoryContextObject] = []
    for chunk in discovery.chunks:
        objects.append(_concept_chunk_to_object(project_id, chunk))
    return objects


def _concept_chunk_to_object(project_id: str, chunk: ConceptChunk) -> StoryContextObject:
    properties = {
        "content": chunk.content,
        "title": chunk.title,
        "module": chunk.module,
        "source_type": "concept",
        "source_file": chunk.source_file,
        "section_heading": chunk.section_heading,
        "section_number": chunk.section_number,
        "content_hash": chunk.content_hash,
        "project_id": project_id,
        "concept_id": chunk.concept_id,
        "is_appendix": chunk.is_appendix,
        "parent_concept_id": chunk.parent_concept_id,
        "defers_to": list(chunk.defers_to),
        "authority_over": list(chunk.authority_over),
        "normative_rules": chunk.normative_rules,
        "concept_status": chunk.concept_status,
        "story_id": "",
        "status": chunk.concept_status,
        "story_type": "concept",
        "epic": "",
    }
    return _build_object(project_id, chunk.source_file, chunk.shadow_id, properties)


def story_file_to_objects(
    project_id: str,
    story_md_path: Path,
    *,
    source_file: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> list[StoryContextObject]:
    """Project a single ``story.md`` (or research ``.md``) into StoryContext objects.

    Reuses the SSOT chunker + hasher. ``source_file`` is the PROJECT-RELATIVE
    path (R04); when omitted it defaults to the path's POSIX form. ``title`` and
    ``status`` come from the frontmatter (real values, not the story_id). Invalid
    frontmatter PROPAGATES as :class:`FrontmatterError` (N05) -- it is never
    silently swallowed and replaced with ``{}``; nothing is indexed for a doc
    whose frontmatter fails the strict parse (AC10).
    """
    raw = story_md_path.read_text(encoding="utf-8")
    fm_text, body = split_frontmatter(raw)
    story_id = ""
    title = ""
    status = ""
    story_type = "implementation"
    if fm_text:
        data = parse_frontmatter_block(fm_text)  # raises FrontmatterError on invalid (N05)
        story_id = str(data.get("story_id", ""))
        title = str(data.get("title", "")) or story_id
        status = str(data.get("status", ""))
        if data.get("story_type"):
            story_type = str(data["story_type"])
    rel = source_file if source_file is not None else story_md_path.as_posix()
    objects: list[StoryContextObject] = []
    for ordering, (section, piece) in enumerate(chunk_document(body, max_tokens=max_tokens)):
        payload: dict[str, object] = {
            "content": piece,
            "story_id": story_id,
            "title": title or rel,
            "status": status,
            "story_type": story_type,
            "source_type": "story",
            "source_file": rel,
            "section_heading": section.heading,
            "section_number": section.section_number,
            "content_hash": chunk_hash(
                {"content": piece, "story_id": story_id, "source_file": rel}
            ),
            "project_id": project_id,
        }
        chunk_id = f"story-{ordering}-{chunk_hash({'content': piece})[:16]}"
        objects.append(_build_object(project_id, rel, chunk_id, payload))
    return objects


def _build_object(
    project_id: str,
    source_file: str,
    chunk_id: str,
    properties: dict[str, object],
) -> StoryContextObject:
    """Build + validate a StoryContext object with a deterministic UUID."""
    validate_object(properties)
    uid = deterministic_uuid(project_id, source_file, chunk_id)
    return StoryContextObject(uuid=uid, properties=properties)


def classify_story_corpus_files(
    binding: ProjectBinding,
    *,
    extra_concept_roots: Sequence[str] = (),
) -> dict[str, str]:
    """Classify all markdown files under the project root (source closure).

    Returns a mapping of POSIX-relative path -> source_type for INGESTED files
    only (negative cases are absent).
    """
    from agentkit.backend.vectordb.ingest.classify import classify_source_file

    root = binding.project_root
    classified: dict[str, str] = {}
    for path in sorted(root.rglob("*.md")):
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            continue
        source_type = classify_source_file(rel, concept_roots=tuple(extra_concept_roots))
        if source_type in SOURCE_TYPES:
            classified[rel] = source_type
    return classified


__all__ = [
    "classify_story_corpus_files",
    "concept_chunks_to_objects",
    "story_file_to_objects",
]
