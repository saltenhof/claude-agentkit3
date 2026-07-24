"""Ingest adapter: SSOT discovery core -> StoryContext objects (Review 174-P1-4).

Thin adapter on :mod:`agentkit.concepts`. Adds NO second discovery path: it
projects the typed :class:`~agentkit.concepts.parser.ConceptChunk` (and story
documents) into the Weaviate ``StoryContext`` property shape owned by
:mod:`agentkit.backend.vectordb.schema`. Every object gets a deterministic UUID
and is fail-closed validated before it is handed to the transport.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.backend.vectordb.schema import (
    SOURCE_TYPES,
    StoryContextObject,
    deterministic_uuid,
    validate_object,
)
from agentkit.concepts.chunking import DEFAULT_MAX_TOKENS, chunk_document
from agentkit.concepts.frontmatter import (
    FrontmatterError,
    parse_frontmatter_block,
    read_text_strict,
    split_frontmatter,
)
from agentkit.concepts.hashing import chunk_hash

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

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
    source_file: str,
    source_type: str = "story",
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> list[StoryContextObject]:
    """Project a single ``story.md`` (or research ``.md``) into StoryContext objects.

    Reuses the SSOT chunker + hasher.

    Args:
        project_id: Bound multi-tenant discriminator.
        story_md_path: Absolute path of the document to read.
        source_file: The PROJECT-RELATIVE corpus path (FK-13 §13.3.1, R04). It is
            MANDATORY: the content hash and the deterministic object identity are
            derived from it, so an absolute filesystem path would leak the local
            layout into the index identity.
        source_type: ``story`` or ``research`` (the classifier's verdict).
        max_tokens: Max tokens per chunk (bound tokenizer).

    Returns:
        The validated :class:`StoryContextObject` list.

    Raises:
        FrontmatterError: When the frontmatter block is ABSENT, unparsable or
            carries wrongly-typed metadata (N05/AC10). A story document without
            frontmatter is not ingestible -- ``story.md`` is a deterministic
            export that always carries ``story_id``/``title``/``status``
            (FK-21 §21.11.3). Nothing is indexed for such a document.
        ValueError: For an unsupported ``source_type``.
    """
    if source_type not in ("story", "research"):
        raise ValueError(
            f"story ingest source_type must be story|research, got {source_type!r} (AC10)"
        )
    if not source_file or Path(source_file).is_absolute():
        raise ValueError(
            f"source_file {source_file!r} must be a non-empty PROJECT-RELATIVE path (R04)"
        )
    raw = read_text_strict(story_md_path)
    fm_text, body = split_frontmatter(raw)
    if not fm_text:
        raise FrontmatterError(
            f"story document {source_file} has no frontmatter block; a story "
            "artefact without frontmatter is not ingestible (N05/AC10)",
            code="E-SCHEMA-001",
        )
    data = parse_frontmatter_block(fm_text)  # raises FrontmatterError on invalid (N05)
    story_id = _strict_str(data, "story_id", source_file, required=True)
    title = _strict_str(data, "title", source_file) or story_id
    status = _strict_str(data, "status", source_file)
    story_type = _strict_str(data, "story_type", source_file) or "implementation"
    objects: list[StoryContextObject] = []
    for ordering, (section, piece) in enumerate(chunk_document(body, max_tokens=max_tokens)):
        payload: dict[str, object] = {
            "content": piece,
            "story_id": story_id,
            "title": title,
            "status": status,
            "story_type": story_type,
            "source_type": source_type,
            "source_file": source_file,
            "section_heading": section.heading,
            "section_number": section.section_number,
            "content_hash": chunk_hash(
                {"content": piece, "story_id": story_id, "source_file": source_file}
            ),
            "project_id": project_id,
        }
        chunk_id = f"{source_type}-{ordering}-{chunk_hash({'content': piece})[:16]}"
        objects.append(_build_object(project_id, source_file, chunk_id, payload))
    return objects


def _strict_str(
    data: Mapping[str, object], key: str, source_file: str, *, required: bool = False
) -> str:
    """Read a story-metadata field STRICTLY: no ``str()`` coercion (N05/AC10).

    A numeric, boolean, list or mapping value is a named error instead of being
    coerced into a string; an absent optional field yields ``""``.
    """
    if key not in data:
        if required:
            raise FrontmatterError(
                f"story document {source_file} is missing the mandatory "
                f"frontmatter field {key!r} (N05/AC10)",
                code="E-SCHEMA-002",
            )
        return ""
    value = data[key]
    if not isinstance(value, str):
        raise FrontmatterError(
            f"story document {source_file} frontmatter field {key!r} must be a "
            f"string, got {type(value).__name__} (no coercion, N05/AC10)",
            code="E-SCHEMA-003",
        )
    if required and not value.strip():
        raise FrontmatterError(
            f"story document {source_file} frontmatter field {key!r} is empty "
            "(N05/AC10)",
            code="E-SCHEMA-002",
        )
    return value.strip()


def _build_object(
    project_id: str,
    source_file: str,
    chunk_id: str,
    properties: dict[str, object],
) -> StoryContextObject:
    """Build + validate a StoryContext object with a deterministic UUID."""
    validate_object(properties)
    uid = deterministic_uuid(project_id, source_file, chunk_id)
    return StoryContextObject(uuid=uid, chunk_id=chunk_id, properties=properties)


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
