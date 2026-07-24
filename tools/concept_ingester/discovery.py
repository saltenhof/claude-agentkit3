"""Concept ingester discovery -- THIN ADAPTER over ``agentkit.concepts`` (R06).

This module NO LONGER has its own parser, frontmatter loader, chunker or
hasher. The SINGLE source of truth for discovery is
:func:`agentkit.concepts.parser.discover_concept_files` (FK-13 §13.9.13). This
adapter projects the SSOT :class:`~agentkit.concepts.parser.ConceptChunk` into
the ingester's richer ``ConceptChunk`` / ``GlossaryTerm`` shapes, layering the
bounded-context (domain-registry) and glossary projections on top as EXPLICIT
profiles. There is no second ``yaml.safe_load`` parser, no character-based
chunking, no localhost default (SINGLE SOURCE OF TRUTH, AC9).
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import yaml

from agentkit.concepts.hashing import PARSER_VERSION
from agentkit.concepts.parser import discover_concept_files

from .schema import SCHEMA_PROJECTION_VERSION

if TYPE_CHECKING:
    from pathlib import Path

LAYER_DOMAIN = "domain"
LAYER_FORMAL = "formal"
LAYER_TECHNICAL = "technical"

_CHUNK_NAMESPACE = uuid.UUID("4f3a07f6-9b6c-5e9b-8c5c-2a1d2b3c4d5e")
_GLOSSARY_NAMESPACE = uuid.UUID("9d3e2c1f-7e54-4f88-8b22-2d97c6a5b3aa")
_H2_RE = re.compile(r"^##\s+(?P<heading>.+?)\s*$", re.MULTILINE)
_SLUG_RE = re.compile(r"[^a-z0-9]+")


# --------------------------------------------------------------------------- #
# Datatypes (preserved for ingester consumers; projected from the SSOT set)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ConceptChunk:
    """A single retrievable unit (projection of the SSOT chunk + BC profile)."""

    chunk_id: str
    layer: str
    doc_id: str
    title: str
    module: str
    tags: tuple[str, ...]
    rel_path: str
    section_anchor: str
    heading: str
    ordering: int
    content: str
    content_hash: str
    file_mtime: str

    domain: str
    cross_cutting: bool
    surface: str
    domain_display_name: str
    contract_state: str
    applies_policies: tuple[str, ...]

    defers_to_ids: tuple[str, ...]
    defers_to_edges: tuple[str, ...]
    formal_ref_ids: tuple[str, ...]
    supersedes_ids: tuple[str, ...]
    superseded_by_id: str
    authority_scopes: tuple[str, ...]

    has_glossary: bool
    exported_term_ids: tuple[str, ...]

    schema_projection_version: str
    domain_registry_hash: str

    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GlossaryTerm:
    """A single glossary entry projected from a contract doc's frontmatter."""

    term_uuid: str
    term_id: str
    term: str
    normalized_term: str
    definition: str
    term_kind: str
    domain: str
    domain_display_name: str
    source_doc_id: str
    source_section_anchor: str
    see_also_terms: tuple[str, ...]
    contract_state: str
    values: tuple[str, ...]
    reason: str
    content_hash: str
    file_mtime: str
    schema_projection_version: str
    domain_registry_hash: str


@dataclass(frozen=True)
class DiscoveryResult:
    """All output of one discovery pass (projected from the SSOT set)."""

    chunks: list[ConceptChunk]
    glossary_terms: list[GlossaryTerm]
    domain_registry_hash: str
    schema_projection_version: str


# --------------------------------------------------------------------------- #
# Domain-registry projection (BC profile, layered over the SSOT set)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _DomainProjection:
    by_doc: dict[str, tuple[str, str, str]]
    registry_hash: str

    @classmethod
    def empty(cls) -> _DomainProjection:
        return cls(by_doc={}, registry_hash="")


def _load_domain_projection(repo_root: Path) -> _DomainProjection:
    path = repo_root / "concept" / "technical-design" / "_meta" / "domain-registry.yaml"
    if not path.is_file():
        return _DomainProjection.empty()
    raw = path.read_bytes()
    registry_hash = hashlib.sha256(raw).hexdigest()
    try:
        data = yaml.safe_load(raw.decode("utf-8")) or {}
    except yaml.YAMLError:
        return _DomainProjection(by_doc={}, registry_hash=registry_hash)
    by_doc: dict[str, tuple[str, str, str]] = {}
    for entry in data.get("domains") or []:
        if not isinstance(entry, dict):
            continue
        domain_id = _string(entry.get("id"))
        display = _string(entry.get("display_name")) or domain_id
        if not domain_id:
            continue
        for cid in entry.get("contract_docs") or []:
            if _string(cid):
                by_doc[_string(cid)] = (domain_id, "contract", display)
        for cid in entry.get("member_docs") or []:
            if _string(cid) and _string(cid) not in by_doc:
                by_doc[_string(cid)] = (domain_id, "internal", display)
    return _DomainProjection(by_doc=by_doc, registry_hash=registry_hash)


# --------------------------------------------------------------------------- #
# Discovery -- delegates to the SSOT core (R06)
# --------------------------------------------------------------------------- #


def discover_chunks(concept_root: Path, max_chars: int = 0) -> list[ConceptChunk]:
    """Backwards-compatible wrapper that returns only the chunk list."""
    return discover(concept_root).chunks


def discover(concept_root: Path, max_chars: int = 0) -> DiscoveryResult:
    """Discover chunks + glossary by delegating to the SSOT core (R06).

    The file walk, strict frontmatter parse, bound-tokenizer chunking and
    content hashing ALL happen once in
    :func:`agentkit.concepts.parser.discover_concept_files`. This adapter only
    PROJECTS the SSOT result into the ingester shape + layers the BC/glossary
    profiles. ``max_chars`` is accepted for backwards compatibility but ignored
    (the SSOT core sizes by tokens of the bound model).
    """
    del max_chars  # SSOT core sizes by tokens; char sizing removed (R06).
    if not concept_root.is_dir():
        raise FileNotFoundError(f"concept root does not exist: {concept_root}")
    repo_root = concept_root.parent
    projection = _load_domain_projection(repo_root)
    ssot = discover_concept_files(concept_root)
    doc_by_id = {doc.concept_id: doc for doc in ssot.documents}

    chunks: list[ConceptChunk] = []
    glossary_terms: list[GlossaryTerm] = []
    # R06: iterate the SSOT chunks directly -- NO local re-chunking/re-hashing.
    # The content_hash is the SSOT chunk hash (not a local document_hash).
    for ssot_chunk in ssot.chunks:
        doc = doc_by_id.get(ssot_chunk.concept_id)
        if doc is None:
            continue
        domain, surface, display = _bc_for(doc, projection)
        mtime = _mtime_of(repo_root, doc.rel_path)
        chunks.append(_project_chunk(ssot_chunk, doc, domain, surface, display, mtime))
    # Glossary is a projection over the SSOT raw frontmatter (strict parse).
    for doc in ssot.documents:
        domain, surface, display = _bc_for(doc, projection)
        mtime = _mtime_of(repo_root, doc.rel_path)
        glossary_terms.extend(_extract_glossary(doc, domain, display, mtime))
    return DiscoveryResult(
        chunks=chunks,
        glossary_terms=glossary_terms,
        domain_registry_hash=projection.registry_hash,
        schema_projection_version=SCHEMA_PROJECTION_VERSION,
    )


def _bc_for(doc: Any, projection: _DomainProjection) -> tuple[str, str, str]:
    """Resolve the bounded-context projection for a document (BC profile)."""
    if getattr(doc, "is_archived", False):
        return ("", "", "")
    entry = projection.by_doc.get(doc.concept_id)
    if entry is not None:
        return entry
    return ("", False, "")


def _project_chunk(
    ssot_chunk: Any, doc: Any, domain: str, surface: str, display: str, mtime: str
) -> ConceptChunk:
    """Project ONE SSOT chunk (+ BC profile) into the ingester ConceptChunk shape.

    Uses the SSOT chunk's ``content_hash`` and ``chunk_id`` verbatim (R06: no
    local re-hash, no second parser).
    """
    return ConceptChunk(
        chunk_id=ssot_chunk.chunk_id,
        layer=ssot_chunk.layer,
        doc_id=doc.concept_id,
        title=doc.title,
        module=doc.module,
        tags=doc.tags,
        rel_path=doc.rel_path,
        section_anchor=_section_anchor(ssot_chunk.section_heading, ssot_chunk.ordering),
        heading=ssot_chunk.section_heading,
        ordering=ssot_chunk.ordering,
        content=ssot_chunk.content,
        content_hash=ssot_chunk.content_hash,
        file_mtime=mtime,
        domain=domain,
        cross_cutting=not bool(domain),
        surface=surface,
        domain_display_name=display,
        contract_state="",
        applies_policies=(),
        defers_to_ids=ssot_chunk.defers_to,
        defers_to_edges=tuple(f"{t}|" for t in ssot_chunk.defers_to),
        formal_ref_ids=(),
        supersedes_ids=doc.supersedes,
        superseded_by_id=doc.superseded_by,
        authority_scopes=ssot_chunk.authority_over,
        has_glossary=False,
        exported_term_ids=(),
        schema_projection_version=SCHEMA_PROJECTION_VERSION,
        domain_registry_hash=PARSER_VERSION,
        metadata={
            "doc_kind": doc.doc_kind,
            "status": doc.effective_status,
            "section_number": ssot_chunk.section_number,
            "concept_status": doc.effective_status,
        },
    )


def _section_anchor(heading: str, ordering: int) -> str:
    base = _SLUG_RE.sub("-", heading.lower()).strip("-") or "section"
    return f"{base}-{ordering:03d}"


def _mtime_of(repo_root: Path, rel: str) -> str:
    import os

    path = repo_root / rel
    try:
        return datetime.fromtimestamp(os.path.getmtime(path), tz=UTC).isoformat().replace("+00:00", "Z")
    except OSError:
        return ""


# --------------------------------------------------------------------------- #
# Glossary projection (layered over the SSOT raw text)
# --------------------------------------------------------------------------- #


def _extract_glossary(doc: Any, domain: str, display: str, mtime: str) -> list[GlossaryTerm]:
    fm = _raw_frontmatter(doc.raw_text)
    glossary = fm.get("glossary") if isinstance(fm, dict) else None
    if not isinstance(glossary, dict):
        return []
    terms: list[GlossaryTerm] = []
    anchor = _detect_glossary_section_anchor(doc.body)
    for kind in ("exported_terms", "internal_terms"):
        for entry in glossary.get(kind) or []:
            term = _build_glossary_term(entry, kind.removesuffix("_terms"), doc, domain, display, anchor, mtime)
            if term is not None:
                terms.append(term)
    return terms


def _raw_frontmatter(raw_text: str) -> dict[str, Any]:
    """Re-use the SSOT STRICT frontmatter parser (R06: no lenient ``yaml.safe_load``).

    The glossary projection reads the raw ``glossary:`` block via the same strict
    loader the SSOT core uses (duplicate-key/no-coercion semantics). A parse
    failure returns ``{}`` (the doc would already be a discovery parse error).
    """
    from agentkit.concepts.frontmatter import FrontmatterError, parse_frontmatter_block, split_frontmatter

    fm_text, _body = split_frontmatter(raw_text)
    if not fm_text:
        return {}
    try:
        return parse_frontmatter_block(fm_text)
    except FrontmatterError:
        return {}


def _detect_glossary_section_anchor(body: str) -> str:
    for ordering, match in enumerate(_H2_RE.finditer(body)):
        if match.group("heading").strip().lower().startswith("glossar"):
            return _section_anchor(match.group("heading"), ordering)
    return ""


def _build_glossary_term(
    entry: Any, kind: str, doc: Any, domain: str, display: str, anchor: str, mtime: str
) -> GlossaryTerm | None:
    if not isinstance(entry, dict):
        return None
    raw_id = _string(entry.get("id"))
    if not raw_id:
        return None
    term_id = _slugify_term(raw_id)
    definition = _string(entry.get("definition"))
    values = tuple(_string(v) for v in (entry.get("values") or []) if _string(v))
    reason = _string(entry.get("reason"))
    payload = json.dumps(
        {"term": raw_id, "definition": definition, "kind": kind, "source": doc.concept_id},
        sort_keys=True, ensure_ascii=False,
    )
    return GlossaryTerm(
        term_uuid=str(uuid.uuid5(_GLOSSARY_NAMESPACE, f"{doc.concept_id}#{domain}#{kind}#{term_id}")),
        term_id=term_id,
        term=raw_id,
        normalized_term=raw_id.lower(),
        definition=definition,
        term_kind=kind,
        domain=domain,
        domain_display_name=display,
        source_doc_id=doc.concept_id,
        source_section_anchor=anchor,
        see_also_terms=(),
        contract_state="",
        values=values,
        reason=reason,
        content_hash=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        file_mtime=mtime,
        schema_projection_version=SCHEMA_PROJECTION_VERSION,
        domain_registry_hash=PARSER_VERSION,
    )


def _slugify_term(value: str) -> str:
    slug = _SLUG_RE.sub("-", value.lower()).strip("-")
    return slug or value.strip()


def _string(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    return ""


__all__ = ["ConceptChunk", "DiscoveryResult", "GlossaryTerm", "discover", "discover_chunks"]
