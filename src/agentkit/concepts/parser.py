"""SSOT concept discovery / parser core (FK-13 §13.9.13).

:func:`discover_concept_files` is the SINGLE owner of validation, build, graph
and sync discovery. The corpus validator, INDEX/graph builder, the vectordb
ingest adapter and ``tools/concept_ingester`` ALL consume the typed
:class:`DiscoveryResult` from this module -- there is no second parser path.

The core is transport-free: it never imports Weaviate and is usable for lint /
validate without an index. Every concept document is parsed with the strict
frontmatter loader (:mod:`agentkit.concepts.frontmatter`) and chunked with the
bound tokenizer (:mod:`agentkit.concepts.chunking`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from agentkit.concepts.chunking import DEFAULT_MAX_TOKENS, Section, chunk_document
from agentkit.concepts.frontmatter import (
    FrontmatterError,
    parse_document_frontmatter,
    read_text_strict,
    split_frontmatter,
)
from agentkit.concepts.hashing import chunk_hash, document_hash
from agentkit.concepts.ignore import load_ignore_file

if TYPE_CHECKING:
    from pathlib import Path

#: Subdirectory under the concept root that marks archived concepts (§13.9.10).
ARCHIVE_SUBDIR = "archiv"

#: Markdown file extension handled by discovery.
MARKDOWN_SUFFIX = ".md"


@dataclass(frozen=True)
class ConceptDocument:
    """One parsed concept document (transport-free projection).

    Carries the full FK-13 §13.9.6 frontmatter projection plus corpus identity.
    """

    concept_id: str
    title: str
    module: str
    status: str
    doc_kind: str
    parent_concept_id: str
    rel_path: str
    layer: str
    is_archived: bool
    supersedes: tuple[str, ...]
    superseded_by: str
    tags: tuple[str, ...]
    authority_scopes: tuple[str, ...]
    defers_to_targets: tuple[str, ...]
    defers_to_full: tuple[tuple[str, str, str], ...]
    supersedes_full: tuple[tuple[str, str, str], ...]
    raw_text: str
    body: str
    document_hash: str

    @property
    def effective_status(self) -> str:
        """Concept status with archive-path override (§13.9.10)."""
        return "archived" if self.is_archived else self.status

    @property
    def is_appendix(self) -> bool:
        return self.doc_kind == "appendix"


@dataclass(frozen=True)
class ConceptChunk:
    """One retrievable chunk of a concept document (FK-13 §13.3.1 / §13.9.3).

    Identity model (R11 / FK-13 §13.9.9 bounded window):

    - ``chunk_id`` is the STABLE LOGICAL identity (concept + path + section +
      ordering). It never changes on a content-only edit and is used for
      reconciliation (mapping the old generation onto the new).
    - ``shadow_id`` is the GENERATION identity -- it folds in ``content_hash``
      (and the corpus revision). A content-only edit changes ``shadow_id`` so
      the new generation is written under a NEW object UUID, then the old
      generation is deleted: the ratified write-new -> validate -> delete-old
      bounded window. ``chunk_id`` stays stable for reconcile.
    """

    chunk_id: str
    shadow_id: str
    source_file: str
    section_heading: str
    section_number: str
    content: str
    content_hash: str

    concept_id: str
    title: str
    module: str
    concept_status: str
    doc_kind: str
    is_appendix: bool
    parent_concept_id: str
    defers_to: tuple[str, ...]
    authority_over: tuple[str, ...]
    normative_rules: str
    layer: str
    ordering: int


@dataclass(frozen=True)
class ParseError:
    """A discovery-time parse failure for one file."""

    path: str
    code: str
    message: str


@dataclass(frozen=True)
class DiscoveryResult:
    """All output of one discovery pass (the SSOT discovery set)."""

    documents: list[ConceptDocument]
    chunks: list[ConceptChunk]
    errors: list[ParseError]
    corpus_revision: str
    ignored_files: tuple[str, ...] = field(default_factory=tuple)

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)


def discover_concept_files(
    concepts_dir: Path,
    *,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    included_docs: frozenset[str] | None = None,
) -> DiscoveryResult:
    """Discover and chunk all concept files under ``concepts_dir`` (SSOT owner).

    Args:
        concepts_dir: Configured concept corpus root (FK-13 §13.9 "massgebliches
            concepts_dir").
        max_tokens: Max tokens per chunk (bound tokenizer).

    Returns:
        A :class:`DiscoveryResult` with parsed documents, chunks, parse errors
        and the shared ``corpus_revision``.
    """
    if not concepts_dir.is_dir():
        raise FileNotFoundError(f"concept root does not exist: {concepts_dir}")
    concepts_dir = concepts_dir.resolve()

    ignore_patterns = load_ignore_file(concepts_dir / ".conceptignore")

    documents: list[ConceptDocument] = []
    chunks: list[ConceptChunk] = []
    errors: list[ParseError] = []
    ignored: list[str] = []

    file_hashes: list[str] = []
    for path in sorted(concepts_dir.rglob("*")):
        if not path.is_file() or path.suffix != MARKDOWN_SUFFIX:
            continue
        rel = path.relative_to(concepts_dir).as_posix()
        if included_docs is not None and rel not in included_docs:
            continue
        from agentkit.concepts.ignore import is_ignored

        if is_ignored(rel, ignore_patterns):
            ignored.append(rel)
            continue
        raw_text = read_text_strict(path)
        file_hashes.append(document_hash(raw_text))
        try:
            doc = _parse_document(rel, raw_text)
        except FrontmatterError as exc:
            errors.append(ParseError(path=rel, code=exc.code, message=str(exc)))
            continue
        documents.append(doc)
        chunks.extend(_chunk_document(doc, max_tokens=max_tokens))

    from agentkit.concepts.hashing import corpus_revision as _cr

    revision = _cr(file_hashes)
    return DiscoveryResult(
        documents=documents,
        chunks=chunks,
        errors=errors,
        corpus_revision=revision,
        ignored_files=tuple(ignored),
    )


def _parse_document(rel: str, raw_text: str) -> ConceptDocument:
    """Parse one concept document into a :class:`ConceptDocument`."""
    frontmatter_text, body = split_frontmatter(raw_text)
    if not frontmatter_text:
        raise FrontmatterError(f"concept document {rel} has no frontmatter block", code="E-SCHEMA-001")
    fm = parse_document_frontmatter(raw_text)
    assert fm is not None  # frontmatter_text present implies parsed
    rel_norm = rel.replace("\\", "/")
    layer = _layer_for(rel_norm)
    is_archived = rel_norm.split("/")[0] == ARCHIVE_SUBDIR or any(seg == ARCHIVE_SUBDIR for seg in rel_norm.split("/"))
    defers_full = fm.defers_to_full
    return ConceptDocument(
        concept_id=fm.concept_id,
        title=fm.title,
        module=fm.module,
        status=fm.status,
        doc_kind=fm.doc_kind,
        parent_concept_id=fm.parent_concept_id,
        rel_path=rel_norm,
        layer=layer,
        is_archived=is_archived,
        supersedes=fm.supersedes_targets,
        superseded_by=fm.superseded_by,
        tags=tuple(fm.tags),
        authority_scopes=fm.authority_scopes,
        defers_to_targets=fm.defers_to_targets,
        defers_to_full=defers_full,
        supersedes_full=fm.supersedes_full,
        raw_text=raw_text,
        body=body,
        document_hash=document_hash(raw_text),
    )


def _layer_for(rel_posix: str) -> str:
    head = rel_posix.split("/", 1)[0]
    mapping = {
        "domain-design": "domain",
        "formal-spec": "formal",
        "technical-design": "technical",
    }
    return mapping.get(head, "technical")


def _chunk_document(doc: ConceptDocument, *, max_tokens: int) -> list[ConceptChunk]:
    """Chunk one document into :class:`ConceptChunk` objects."""
    out: list[ConceptChunk] = []
    for ordering, (section, piece) in enumerate(chunk_document(doc.body, max_tokens=max_tokens)):
        normative_rules = _extract_normative_rules(piece)
        chunk_id = _chunk_uuid(doc.concept_id, doc.rel_path, section, ordering)
        payload = {
            "content": piece,
            "concept_id": doc.concept_id,
            "section_heading": section.heading,
            "section_number": section.section_number,
            "module": doc.module,
            "doc_kind": doc.doc_kind,
            "defers_to": list(doc.defers_to_targets),
            "authority_over": list(doc.authority_scopes),
            "tags": list(doc.tags),
        }
        content_hash = chunk_hash(payload)
        out.append(
            ConceptChunk(
                chunk_id=chunk_id,
                shadow_id=_shadow_uuid(chunk_id, content_hash),
                source_file=doc.rel_path,
                section_heading=section.heading,
                section_number=section.section_number,
                content=piece,
                content_hash=content_hash,
                concept_id=doc.concept_id,
                title=doc.title,
                module=doc.module,
                concept_status=doc.effective_status,
                doc_kind=doc.doc_kind,
                is_appendix=doc.is_appendix,
                parent_concept_id=doc.parent_concept_id,
                defers_to=doc.defers_to_targets,
                authority_over=doc.authority_scopes,
                normative_rules=normative_rules,
                layer=doc.layer,
                ordering=ordering,
            )
        )
    return out


def _chunk_uuid(concept_id: str, rel_path: str, section: Section, ordering: int) -> str:
    import uuid  # noqa: PLC0415

    namespace = uuid.UUID("4f3a07f6-9b6c-5e9b-8c5c-2a1d2b3c4d5e")
    key = f"{concept_id}#{rel_path}#{section.section_number}#{section.heading}#{ordering}"
    return str(uuid.uuid5(namespace, key))


def _shadow_uuid(chunk_id: str, content_hash: str) -> str:
    """Generation identity: folds content_hash into the logical id (R11).

    A content-only edit changes this UUID, so the sync writes a NEW generation
    object and deletes the old one (true bounded window), while ``chunk_id``
    stays stable for reconciliation.
    """
    import uuid  # noqa: PLC0415

    namespace = uuid.UUID("5b4d1e7f-4c6a-6fac-9d6e-1f2a3b4c5d6e")
    return str(uuid.uuid5(namespace, f"{chunk_id}#{content_hash}"))


def _extract_normative_rules(text: str) -> str:
    """Extract a ``normative_rules`` marker block from a chunk (FK-13 §13.9.4).

    Concepts may carry a fenced ``normative-rules`` block; the rule content is
    kept verbatim for deterministic conflict checking (not vectorised). Returns
    an empty string when absent.
    """
    marker = "```normative-rules"
    marker_start = text.find(marker)
    if marker_start < 0:
        return ""
    header_end = text.find("\n", marker_start + len(marker))
    if header_end < 0 or text[marker_start + len(marker) : header_end].strip():
        return ""
    closing = text.find("```", header_end + 1)
    if closing < 0:
        return ""
    return text[header_end + 1 : closing].strip()


__all__ = [
    "ARCHIVE_SUBDIR",
    "ConceptChunk",
    "ConceptDocument",
    "DiscoveryResult",
    "ParseError",
    "discover_concept_files",
]
