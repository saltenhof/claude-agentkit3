"""Concept discovery consumer over ``agentkit.backend.concept_catalog`` (R02).

No second YAML/parser/chunking path: files are discovered and chunked via the
SSOT kernel. Glossary extraction is a pure consumer of the discovered document
set and its already-parsed frontmatter raw maps.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agentkit.backend.concept_catalog.corpus.chunking import chunk_markdown
from agentkit.backend.concept_catalog.corpus.discovery import (
    ConceptDocument,
    discover_concept_files,
)
from agentkit.backend.concept_catalog.corpus.hashing import sha256_text
from agentkit.backend.concept_catalog.corpus.identity import deterministic_chunk_uuid
from agentkit.backend.concept_catalog.corpus.profiles import IngestProfileId, get_profile

from .schema import SCHEMA_PROJECTION_VERSION

_GLOSSARY_NAMESPACE = uuid.UUID("9d3e2c1f-7e54-4f88-8b22-2d97c6a5b3aa")
_SLUG_RE = re.compile(r"[^a-z0-9]+")

LAYER_DOMAIN = "domain"
LAYER_FORMAL = "formal"
LAYER_TECHNICAL = "technical"
_LAYER_BY_DIR = {
    "domain-design": LAYER_DOMAIN,
    "formal-spec": LAYER_FORMAL,
    "technical-design": LAYER_TECHNICAL,
}


@dataclass(frozen=True)
class ConceptChunk:
    """A single retrievable unit of concept knowledge (one section)."""

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
    """Glossary entry extracted as a consumer of discovered frontmatter."""

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
    chunks: list[ConceptChunk]
    glossary_terms: list[GlossaryTerm]
    domain_registry_hash: str
    schema_projection_version: str


def discover(concept_root: Path, max_chars: int) -> DiscoveryResult:
    """Discover chunks via the SSOT kernel (R02).

    ``max_chars`` is accepted for back-compat; token limits come from the
    bound model tokenizer profile.
    """
    del max_chars
    if not concept_root.is_dir():
        raise FileNotFoundError(f"concept root does not exist: {concept_root}")
    # Same discovery owner; inventory mode allows extra doc_kind AFTER hard parse.
    ssot = discover_concept_files(
        concept_root, strict=True, frontmatter_mode="inventory"
    )
    profile = get_profile(IngestProfileId.AK3_TOOL)
    chunks: list[ConceptChunk] = []
    glossary: list[GlossaryTerm] = []
    registry_hash = _domain_registry_hash(concept_root.parent)
    for doc in ssot.documents:
        layer = _layer_for(doc.rel_path)
        if layer is None:
            # Preserve original concept_ingester layer filter: only domain/
            # formal/technical trees are inventory sources (not _meta/, etc.).
            continue
        text_chunks, _ = chunk_markdown(
            doc.body, profile=profile, title=doc.frontmatter.title
        )
        fm = doc.frontmatter
        tags = fm.tags
        defers_ids = tuple(d.target for d in fm.defers_to)
        defers_edges = tuple(f"{d.target}|{d.scope}" for d in fm.defers_to)
        authority = tuple(a.scope for a in fm.authority_over)
        mtime = (
            datetime.fromtimestamp(doc.path.stat().st_mtime, tz=UTC)
            .isoformat()
            .replace("+00:00", "Z")
            if doc.path.exists()
            else ""
        )
        glossary_block = fm.raw.get("glossary") if isinstance(fm.raw.get("glossary"), dict) else None
        exported_ids: tuple[str, ...] = ()
        if glossary_block is not None:
            exported_ids = tuple(
                _slugify(str(item.get("id")))
                for item in (glossary_block.get("exported_terms") or [])
                if isinstance(item, dict) and item.get("id")
            )
            glossary.extend(
                _extract_glossary(doc, glossary_block, registry_hash, mtime)
            )
        for tc in text_chunks:
            anchor = _section_anchor(tc.section_heading, tc.ordering)
            # SSOT identity (R02) — inventory uses empty project_id discriminator.
            chunk_uuid = deterministic_chunk_uuid(
                project_id="",
                source_file=doc.rel_path,
                section_heading=tc.section_heading,
                content_hash=tc.content_hash,
                ordering=tc.ordering,
            )
            chunks.append(
                ConceptChunk(
                    chunk_id=chunk_uuid,
                    layer=layer,
                    doc_id=doc.concept_id,
                    title=fm.title,
                    module=fm.module,
                    tags=tags,
                    rel_path=doc.rel_path,
                    section_anchor=anchor,
                    heading=tc.section_heading,
                    ordering=tc.ordering,
                    content=tc.content,
                    content_hash=tc.content_hash or sha256_text(tc.content),
                    file_mtime=mtime,
                    domain=str(fm.raw.get("domain") or ""),
                    cross_cutting=bool(fm.raw.get("cross_cutting") is True),
                    surface="",
                    domain_display_name="",
                    contract_state=str(fm.raw.get("contract_state") or ""),
                    applies_policies=(),
                    defers_to_ids=defers_ids,
                    defers_to_edges=defers_edges,
                    formal_ref_ids=(),
                    supersedes_ids=fm.supersedes,
                    superseded_by_id=fm.superseded_by[0] if fm.superseded_by else "",
                    authority_scopes=authority,
                    has_glossary=glossary_block is not None,
                    exported_term_ids=exported_ids,
                    schema_projection_version=SCHEMA_PROJECTION_VERSION,
                    domain_registry_hash=registry_hash,
                    metadata={
                        "doc_kind": fm.doc_kind,
                        "status": fm.status,
                        "parent_concept_id": fm.parent_concept_id or "",
                        "defers_to_full": json.dumps(
                            [
                                {
                                    "target": d.target,
                                    "scope": d.scope,
                                    "reason": d.reason,
                                }
                                for d in fm.defers_to
                            ],
                            ensure_ascii=False,
                        ),
                        "authority_over_full": json.dumps(
                            [{"scope": a.scope} for a in fm.authority_over],
                            ensure_ascii=False,
                        ),
                        "supersedes_full": json.dumps(
                            list(fm.supersedes), ensure_ascii=False
                        ),
                    },
                )
            )
    return DiscoveryResult(
        chunks=chunks,
        glossary_terms=glossary,
        domain_registry_hash=registry_hash,
        schema_projection_version=SCHEMA_PROJECTION_VERSION,
    )


def discover_chunks(concept_root: Path, max_chars: int) -> list[ConceptChunk]:
    return discover(concept_root, max_chars=max_chars).chunks


def _layer_for(rel_path: str) -> str | None:
    head = rel_path.split("/", 1)[0]
    return _LAYER_BY_DIR.get(head)


def _domain_registry_hash(repo_root: Path) -> str:
    path = repo_root / "concept" / "technical-design" / "_meta" / "domain-registry.yaml"
    if not path.is_file():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _slugify(value: str) -> str:
    return _SLUG_RE.sub("-", value.lower()).strip("-") or value.strip()


def _section_anchor(heading: str, ordering: int) -> str:
    base = _slugify(heading) or "section"
    return f"{base}-{ordering:03d}"


def _extract_glossary(
    doc: ConceptDocument,
    glossary_block: dict[str, Any],
    registry_hash: str,
    mtime: str,
) -> list[GlossaryTerm]:
    terms: list[GlossaryTerm] = []
    for kind, key in (("exported", "exported_terms"), ("internal", "internal_terms")):
        for entry in glossary_block.get(key) or []:
            if not isinstance(entry, dict):
                continue
            raw_id = str(entry.get("id") or "").strip()
            if not raw_id:
                continue
            term_id = _slugify(raw_id)
            definition = str(entry.get("definition") or "")
            payload = json.dumps(
                {
                    "term": raw_id,
                    "definition": definition,
                    "kind": kind,
                    "source_doc_id": doc.concept_id,
                },
                sort_keys=True,
            )
            content_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            term_uuid = str(
                uuid.uuid5(_GLOSSARY_NAMESPACE, f"{doc.concept_id}#{kind}#{term_id}")
            )
            terms.append(
                GlossaryTerm(
                    term_uuid=term_uuid,
                    term_id=term_id,
                    term=raw_id,
                    normalized_term=raw_id.lower(),
                    definition=definition,
                    term_kind=kind,
                    domain=str(doc.frontmatter.raw.get("domain") or ""),
                    domain_display_name="",
                    source_doc_id=doc.concept_id,
                    source_section_anchor="",
                    see_also_terms=(),
                    contract_state=str(doc.frontmatter.raw.get("contract_state") or ""),
                    values=tuple(str(v) for v in (entry.get("values") or []) if v),
                    reason=str(entry.get("reason") or ""),
                    content_hash=content_hash,
                    file_mtime=mtime,
                    schema_projection_version=SCHEMA_PROJECTION_VERSION,
                    domain_registry_hash=registry_hash,
                )
            )
    return terms


__all__ = [
    "ConceptChunk",
    "DiscoveryResult",
    "GlossaryTerm",
    "discover",
    "discover_chunks",
]
