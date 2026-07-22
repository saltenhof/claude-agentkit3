"""Build ChunkRecords from story / research / concept sources (R08/R16)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from agentkit.backend.concept_catalog.corpus.chunking import chunk_markdown
from agentkit.backend.concept_catalog.corpus.discovery import ConceptDocument, discover_concept_files
from agentkit.backend.concept_catalog.corpus.domain_errors import ConceptParseError
from agentkit.backend.concept_catalog.corpus.frontmatter import (
    parse_frontmatter_yaml,
    split_frontmatter_bytes,
)
from agentkit.backend.concept_catalog.corpus.profiles import IngestProfileId, get_profile
from agentkit.backend.vectordb.ingest.identity import deterministic_chunk_uuid
from agentkit.backend.vectordb.ingest.models import ChunkRecord, SourceType
from agentkit.backend.vectordb.ingest.source_routing import (
    classify_markdown_path,
    producer_for,
    story_id_from_path,
)

if TYPE_CHECKING:
    from agentkit.backend.vectordb.project_binding import ProjectBinding

_NORMATIVE_SECTION_RE = re.compile(
    r"(?im)^#{2,3}\s+(normative\s+rules?|verbindliche\s+regeln?|invariants?)\s*$"
)


class IngestSourceError(Exception):
    """Raised when a source file fails strict parse (aborts entire sync)."""


def build_story_and_research_chunks(
    binding: ProjectBinding,
    *,
    generation_id: str = "",
    corpus_revision: str = "",
) -> list[ChunkRecord]:
    """Discover and chunk story.md + research sources under stories/."""
    stories_dir = binding.stories_dir
    if not stories_dir.is_dir():
        return []
    profile = get_profile(IngestProfileId.FK13_STORY)
    records: list[ChunkRecord] = []
    for path in sorted(stories_dir.rglob("*.md")):
        if not path.is_file():
            continue
        rel = binding.relative_posix(path)
        source_type = classify_markdown_path(rel)
        if source_type is None:
            continue
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise IngestSourceError(
                f"cannot read source {rel}: {exc} (fail-closed, no skip, R08)"
            ) from exc
        meta, body = _parse_story_frontmatter_strict(data, path=rel)
        title = meta["title"]
        story_id = meta["story_id"]
        chunks, _ = chunk_markdown(body, profile=profile, title=title)
        for chunk in chunks:
            uid = deterministic_chunk_uuid(
                project_id=binding.project_id,
                source_file=rel,
                section_heading=chunk.section_heading,
                content_hash=chunk.content_hash,
                ordering=chunk.ordering,
            )
            records.append(
                ChunkRecord(
                    chunk_uuid=uid,
                    content=chunk.content,
                    content_hash=chunk.content_hash,
                    project_id=binding.project_id,
                    source_type=source_type,
                    source_file=rel,
                    producer_tool=producer_for(source_type),
                    section_heading=chunk.section_heading,
                    section_number=chunk.section_number,
                    title=title,
                    story_id=story_id,
                    status=str(meta.get("status") or ""),
                    story_type=str(meta.get("story_type") or meta.get("type") or ""),
                    module=str(meta.get("module") or ""),
                    epic=str(meta.get("epic") or ""),
                    generation_id=generation_id,
                    corpus_revision=corpus_revision,
                )
            )
    return records


def build_concept_chunks(
    binding: ProjectBinding,
    *,
    generation_id: str = "",
    corpus_revision: str = "",
    documents: tuple[ConceptDocument, ...] | None = None,
) -> list[ChunkRecord]:
    """Chunk concept documents from the shared discovery SSOT."""
    profile = get_profile(IngestProfileId.FK13_CONCEPT)
    if documents is None:
        result = discover_concept_files(binding.concepts_dir, strict=True)
        documents = result.documents
    records: list[ChunkRecord] = []
    for doc in documents:
        try:
            rel = binding.relative_posix(doc.path)
        except Exception:  # noqa: BLE001
            rel = f"{binding.config.concepts_dir.rstrip('/')}/{doc.rel_path}"
        chunks, _ = chunk_markdown(
            doc.body,
            profile=profile,
            title=doc.frontmatter.title,
        )
        defers = tuple(d.target for d in doc.frontmatter.defers_to)
        authority = tuple(a.scope for a in doc.frontmatter.authority_over)
        is_appendix = doc.frontmatter.doc_kind == "appendix"
        for chunk in chunks:
            uid = deterministic_chunk_uuid(
                project_id=binding.project_id,
                source_file=rel,
                section_heading=chunk.section_heading,
                content_hash=chunk.content_hash,
                ordering=chunk.ordering,
            )
            records.append(
                ChunkRecord(
                    chunk_uuid=uid,
                    content=chunk.content,
                    content_hash=chunk.content_hash,
                    project_id=binding.project_id,
                    source_type=SourceType.CONCEPT,
                    source_file=rel,
                    producer_tool=producer_for(SourceType.CONCEPT),
                    section_heading=chunk.section_heading,
                    section_number=chunk.section_number,
                    title=doc.frontmatter.title,
                    module=doc.frontmatter.module,
                    concept_id=doc.concept_id,
                    is_appendix=is_appendix,
                    parent_concept_id=doc.frontmatter.parent_concept_id or "",
                    defers_to=defers,
                    authority_over=authority,
                    concept_status=doc.effective_status,
                    normative_rules=extract_normative_rules(chunk.content),
                    generation_id=generation_id,
                    corpus_revision=corpus_revision,
                )
            )
    return records


def build_story_export_chunks(
    *,
    project_id: str,
    story_id: str,
    title: str,
    body: str,
    source_file: str,
    meta: dict[str, Any] | None = None,
    generation_id: str = "",
    corpus_revision: str = "",
) -> list[ChunkRecord]:
    """Build chunks for a single exported story.md payload."""
    if not project_id or not isinstance(project_id, str):
        raise IngestSourceError(
            "project_id is required for story export indexing (no 'default', R15)."
        )
    profile = get_profile(IngestProfileId.FK13_STORY)
    meta = meta or {}
    chunks, _ = chunk_markdown(body, profile=profile, title=title)
    records: list[ChunkRecord] = []
    for chunk in chunks:
        uid = deterministic_chunk_uuid(
            project_id=project_id,
            source_file=source_file,
            section_heading=chunk.section_heading,
            content_hash=chunk.content_hash,
            ordering=chunk.ordering,
        )
        records.append(
            ChunkRecord(
                chunk_uuid=uid,
                content=chunk.content,
                content_hash=chunk.content_hash,
                project_id=project_id,
                source_type=SourceType.STORY,
                source_file=source_file,
                producer_tool=producer_for(SourceType.STORY),
                section_heading=chunk.section_heading,
                section_number=chunk.section_number,
                title=title,
                story_id=story_id,
                status=str(meta.get("status") or ""),
                story_type=str(meta.get("story_type") or ""),
                module=str(meta.get("module") or ""),
                epic=str(meta.get("epic") or ""),
                generation_id=generation_id,
                corpus_revision=corpus_revision,
            )
        )
    return records


def extract_normative_rules(section_content: str) -> str:
    """Extract normative-rule text from a section (FK-13 §13.9.4 / R16).

    When the section heading itself is a normative-rules heading, return the
    body; otherwise extract a nested normative-rules subsection if present.
    """
    text = section_content.strip()
    if not text:
        return ""
    lines = text.splitlines()
    first_line = lines[0] if lines else ""
    if _NORMATIVE_SECTION_RE.match(first_line):
        return "\n".join(lines[1:]).strip()
    match = _NORMATIVE_SECTION_RE.search(text)
    if match is None:
        return ""
    rest = text[match.end() :]
    next_heading = re.search(r"(?m)^#{2,3}\s+", rest)
    body = rest[: next_heading.start()] if next_heading else rest
    return body.strip()


def _parse_story_frontmatter_strict(
    data: bytes, *, path: str
) -> tuple[dict[str, Any], str]:
    """Strict story/research frontmatter (R08 / AC 10)."""
    try:
        yaml_bytes, body_bytes = split_frontmatter_bytes(data, path=path)
        raw = parse_frontmatter_yaml(yaml_bytes, path=path)
    except ConceptParseError as exc:
        raise IngestSourceError(str(exc)) from exc
    # Story required fields: story_id, title (strings, non-empty). No coercion.
    story_id = raw.get("story_id")
    title = raw.get("title")
    if not isinstance(story_id, str) or not story_id.strip():
        raise IngestSourceError(
            f"{path}: story_id must be a non-empty string (fail-closed, R08)"
        )
    if not isinstance(title, str) or not title.strip():
        raise IngestSourceError(
            f"{path}: title must be a non-empty string (fail-closed, R08)"
        )
    # Optional string fields: reject wrong types
    for key in ("status", "story_type", "type", "module", "epic"):
        if key in raw and raw[key] is not None and not isinstance(raw[key], str):
            raise IngestSourceError(
                f"{path}: {key} must be a string when set (fail-closed, R08)"
            )
    story_type_raw = raw.get("story_type")
    if story_type_raw is None:
        story_type_raw = raw.get("type")
    if story_type_raw is not None and not isinstance(story_type_raw, str):
        raise IngestSourceError(
            f"{path}: story_type must be a string when set (fail-closed, R08)"
        )
    meta = {
        "story_id": story_id.strip(),
        "title": title.strip(),
        "status": raw["status"].strip() if isinstance(raw.get("status"), str) else "",
        "story_type": story_type_raw.strip() if isinstance(story_type_raw, str) else "",
        "module": raw["module"].strip() if isinstance(raw.get("module"), str) else "",
        "epic": raw["epic"].strip() if isinstance(raw.get("epic"), str) else "",
    }
    # Research may omit story_id only if path supplies it; story.md always requires FM.
    if meta["story_id"] == "" and "/story.md" in path.replace("\\", "/"):
        raise IngestSourceError(f"{path}: story.md requires story_id")
    if meta["story_id"] == "":
        # Research: path-derived only when story_id key was absent entirely.
        if "story_id" in raw:
            raise IngestSourceError(f"{path}: story_id must be non-empty when present")
        derived = story_id_from_path(path)
        if not derived:
            raise IngestSourceError(f"{path}: cannot resolve story_id")
        meta["story_id"] = derived
    try:
        body = body_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise IngestSourceError(f"{path}: body is not valid UTF-8: {exc}") from exc
    return meta, body


__all__ = [
    "IngestSourceError",
    "build_concept_chunks",
    "build_story_and_research_chunks",
    "build_story_export_chunks",
    "extract_normative_rules",
]
