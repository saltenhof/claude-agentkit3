"""Walks the concept corpus and turns it into typed, hashable chunks.

In addition to the per-section chunks (`ConceptChunk`), this module also
extracts canonical glossary entries (`GlossaryTerm`) from contract docs
that carry a `glossary:` block in their frontmatter.

Bounded-context awareness is materialised at discovery time:
- `domain`, `surface`, `domain_display_name` come from
  `_meta/domain-registry.yaml`.
- `domain_registry_hash` is the SHA-256 of that file's bytes; written
  into every chunk so drift between index and registry is observable.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from tools.concept_ingester.schema import SCHEMA_PROJECTION_VERSION

LAYER_DOMAIN = "domain"
LAYER_FORMAL = "formal"
LAYER_TECHNICAL = "technical"

_LAYER_BY_DIR: dict[str, str] = {
    "domain-design": LAYER_DOMAIN,
    "formal-spec": LAYER_FORMAL,
    "technical-design": LAYER_TECHNICAL,
}

_FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
_H2_RE = re.compile(r"^##\s+(?P<heading>.+?)\s*$", re.MULTILINE)
_SLUG_RE = re.compile(r"[^a-z0-9]+")

_CHUNK_NAMESPACE = uuid.UUID("4f3a07f6-9b6c-5e9b-8c5c-2a1d2b3c4d5e")
_GLOSSARY_NAMESPACE = uuid.UUID("9d3e2c1f-7e54-4f88-8b22-2d97c6a5b3aa")


# ---------------------------------------------------------------------------
# Datatypes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConceptChunk:
    """A single retrievable unit of concept knowledge (one H2 section)."""

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

    # BC fields
    domain: str
    cross_cutting: bool
    surface: str
    domain_display_name: str
    contract_state: str
    applies_policies: tuple[str, ...]

    # Reference graph (filterable IDs)
    defers_to_ids: tuple[str, ...]
    defers_to_edges: tuple[str, ...]
    formal_ref_ids: tuple[str, ...]
    supersedes_ids: tuple[str, ...]
    superseded_by_id: str
    authority_scopes: tuple[str, ...]

    # Glossary linkage
    has_glossary: bool
    exported_term_ids: tuple[str, ...]

    # Migration tracking
    schema_projection_version: str
    domain_registry_hash: str

    # Non-query payload
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GlossaryTerm:
    """A single glossary entry (exported or internal) of a contract doc."""

    term_uuid: str
    term_id: str
    term: str
    normalized_term: str
    definition: str
    term_kind: str  # "exported" | "internal"
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
    """All output of one discovery pass."""

    chunks: list[ConceptChunk]
    glossary_terms: list[GlossaryTerm]
    domain_registry_hash: str
    schema_projection_version: str


# ---------------------------------------------------------------------------
# Domain-registry projection
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _DomainProjection:
    """Lookup table built from `_meta/domain-registry.yaml`."""

    by_doc: dict[str, tuple[str, str, str]]  # doc_id -> (domain, surface, display)
    registry_hash: str

    @classmethod
    def empty(cls) -> _DomainProjection:
        return cls(by_doc={}, registry_hash="")


def _prose_ref_to_concept_id(rel: str) -> str | None:
    """Map a prose-ref path to its FK/DK concept id."""
    rel = rel.replace("\\", "/").strip()
    if not rel:
        return None
    parts = rel.split("/")
    if len(parts) < 3:
        return None
    layer_dir = parts[-2]
    filename = parts[-1]
    if layer_dir == "technical-design":
        num = filename.split("_", 1)[0]
        return f"FK-{num}" if num.isdigit() else None
    if layer_dir == "domain-design":
        num = filename.split("-", 1)[0]
        return f"DK-{num}" if num.isdigit() else None
    return None


def _formal_folder_of(rel_path: str) -> str | None:
    """Return the formal-spec folder of a formal doc, e.g. 'deterministic-checks'."""
    parts = rel_path.replace("\\", "/").split("/")
    if len(parts) < 3 or parts[0] != "formal-spec":
        return None
    folder = parts[1]
    # Skip meta and toplevel READMEs.
    if folder.startswith("00_") or folder.endswith(".md"):
        return None
    return folder


@dataclass(frozen=True)
class _FormalFolderProjection:
    """BC ownership of each formal-spec folder."""

    by_folder: dict[str, tuple[str, bool, str, str]]  # folder -> (domain, cross_cutting, surface, display)


def _build_formal_folder_projection(
    frames: list[_DocumentFrame], projection: _DomainProjection
) -> _FormalFolderProjection:
    """Aggregate prose_refs across all formal docs of each folder.

    A folder gets a single BC ownership decision so all six per-folder
    spec files (entities/invariants/commands/events/state-machine/scenarios)
    share the same BC even when individual files are imported by other BCs.

    Decision rule:

    * majority BC across all referenced FK/DK docs in the folder wins
    * tied majority -> cross_cutting=True
    * all references foundation/cross-cutting -> cross_cutting=True
    * no references at all -> empty (formal doc remains unassigned)
    """
    contributions: dict[str, list[tuple[str, bool, str, str]]] = {}
    for frame in frames:
        if frame.layer != LAYER_FORMAL:
            continue
        folder = _formal_folder_of(frame.rel_path)
        if folder is None:
            continue
        bucket = contributions.setdefault(folder, [])
        prose_refs = frame.frontmatter.get("prose_refs")
        if not isinstance(prose_refs, list):
            continue
        for raw in prose_refs:
            cid = _prose_ref_to_concept_id(str(raw))
            if cid is None:
                continue
            entry = projection.by_doc.get(cid)
            if entry is None:
                bucket.append(("", True, "", ""))
            else:
                domain, surface, display = entry
                bucket.append((domain, False, surface, display))

    by_folder: dict[str, tuple[str, bool, str, str]] = {}
    for folder, contribs in contributions.items():
        if not contribs:
            continue
        bc_contribs = [(d, surf, disp) for (d, cc, surf, disp) in contribs if not cc and d]
        if not bc_contribs:
            by_folder[folder] = ("", True, "", "")
            continue
        from collections import Counter

        counts = Counter(d for (d, _, _) in bc_contribs)
        top_count = max(counts.values())
        top_bcs = [d for d, c in counts.items() if c == top_count]
        if len(top_bcs) > 1:
            # Tie between BCs -> cross-cutting.
            by_folder[folder] = ("", True, "", "")
            continue
        primary = top_bcs[0]
        primary_contribs = [(d, s, disp) for (d, s, disp) in bc_contribs if d == primary]
        surfaces = {s for (_, s, _) in primary_contribs}
        display = primary_contribs[0][2]
        surface = "contract" if "contract" in surfaces else next(iter(surfaces))
        by_folder[folder] = (primary, False, surface, display)
    return _FormalFolderProjection(by_folder=by_folder)


def _formal_owner_from_prose_refs(
    prose_refs: Any,
    projection: _DomainProjection,
    folder_projection: _FormalFolderProjection | None = None,
    rel_path: str | None = None,
) -> tuple[str, bool, str, str]:
    """Look up a formal spec's BC ownership.

    When ``folder_projection`` is provided we use the per-folder decision so
    every spec in a folder shares the same BC. Otherwise we fall back to the
    per-doc rule (single BC across all prose_refs, else cross_cutting).

    Returns ``(domain, cross_cutting, surface, domain_display_name)``.
    """
    if folder_projection is not None and rel_path is not None:
        folder = _formal_folder_of(rel_path)
        if folder is not None:
            entry = folder_projection.by_folder.get(folder)
            if entry is not None:
                return entry

    if not isinstance(prose_refs, list):
        return ("", False, "", "")

    contributions: list[tuple[str, bool, str, str]] = []
    for raw in prose_refs:
        cid = _prose_ref_to_concept_id(str(raw))
        if cid is None:
            continue
        entry = projection.by_doc.get(cid)
        if entry is None:
            contributions.append(("", True, "", ""))
        else:
            domain, surface, display = entry
            contributions.append((domain, False, surface, display))

    if not contributions:
        return ("", False, "", "")
    bc_owners = {(d, surf, disp) for (d, cc, surf, disp) in contributions if not cc and d}
    if not bc_owners:
        return ("", True, "", "")
    distinct_bcs = {(d, disp) for (d, _, disp) in bc_owners}
    if len(distinct_bcs) == 1:
        domain, display = next(iter(distinct_bcs))
        surfaces = {s for (_, s, _) in bc_owners}
        surface = "contract" if "contract" in surfaces else next(iter(surfaces))
        return (domain, False, surface, display)
    return ("", True, "", "")


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
    domains = data.get("domains") or []
    by_doc: dict[str, tuple[str, str, str]] = {}
    for entry in domains:
        if not isinstance(entry, dict):
            continue
        domain_id = _string(entry.get("id"))
        display = _string(entry.get("display_name")) or domain_id
        if not domain_id:
            continue
        for cid in entry.get("contract_docs") or []:
            doc_id = _string(cid)
            if doc_id:
                by_doc[doc_id] = (domain_id, "contract", display)
        for cid in entry.get("member_docs") or []:
            doc_id = _string(cid)
            if doc_id and doc_id not in by_doc:
                by_doc[doc_id] = (domain_id, "internal", display)
    return _DomainProjection(by_doc=by_doc, registry_hash=registry_hash)


# ---------------------------------------------------------------------------
# Document iteration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _DocumentFrame:
    path: Path
    rel_path: str
    layer: str
    frontmatter: dict[str, Any]
    body: str
    mtime: str


def discover_chunks(concept_root: Path, max_chars: int) -> list[ConceptChunk]:
    """Backwards-compatible wrapper that returns only the chunk list."""
    return discover(concept_root, max_chars=max_chars).chunks


def discover(concept_root: Path, max_chars: int) -> DiscoveryResult:
    """Discover all chunks and glossary terms beneath ``concept_root``."""
    if not concept_root.is_dir():
        raise FileNotFoundError(f"concept root does not exist: {concept_root}")
    repo_root = concept_root.parent
    projection = _load_domain_projection(repo_root)

    frames = list(_iter_documents(concept_root))
    folder_projection = _build_formal_folder_projection(frames, projection)

    chunks: list[ConceptChunk] = []
    glossary_terms: list[GlossaryTerm] = []
    for frame in frames:
        doc_view = _build_doc_view(frame, projection, folder_projection)
        chunks.extend(_chunk_document(frame, doc_view, max_chars=max_chars))
        glossary_terms.extend(_extract_glossary_terms(frame, doc_view))
    return DiscoveryResult(
        chunks=chunks,
        glossary_terms=glossary_terms,
        domain_registry_hash=projection.registry_hash,
        schema_projection_version=SCHEMA_PROJECTION_VERSION,
    )


def _iter_documents(concept_root: Path) -> Iterator[_DocumentFrame]:
    for path in sorted(concept_root.rglob("*.md")):
        rel = path.relative_to(concept_root).as_posix()
        layer = _layer_for(rel)
        if layer is None:
            continue
        text = path.read_text(encoding="utf-8")
        frontmatter, body = _split_frontmatter(text)
        mtime = (
            datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
        yield _DocumentFrame(
            path=path,
            rel_path=rel,
            layer=layer,
            frontmatter=frontmatter,
            body=body,
            mtime=mtime,
        )


def _layer_for(rel_path: str) -> str | None:
    head = rel_path.split("/", 1)[0]
    return _LAYER_BY_DIR.get(head)


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        return {}, text
    try:
        loaded = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return {}, text[match.end() :]
    if not isinstance(loaded, dict):
        return {}, text[match.end() :]
    return loaded, text[match.end() :]


# ---------------------------------------------------------------------------
# Per-document derived view
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _DocView:
    """Fields derived once per document and shared across all its chunks."""

    doc_id: str
    title: str
    module: str
    tags: tuple[str, ...]

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

    domain_registry_hash: str
    schema_projection_version: str

    metadata: dict[str, Any]


def _build_doc_view(
    frame: _DocumentFrame,
    projection: _DomainProjection,
    folder_projection: _FormalFolderProjection | None = None,
) -> _DocView:
    fm = frame.frontmatter
    doc_id = _doc_id(fm, frame.rel_path)
    title = _string(fm.get("title")) or _fallback_title(frame.rel_path)
    module = _string(fm.get("module")) or _string(fm.get("context")) or ""
    tags = _string_list(fm.get("tags"))

    fm_domain = _string(fm.get("domain"))
    cross_cutting = bool(fm.get("cross_cutting") is True)
    registry_entry = projection.by_doc.get(doc_id)

    if frame.layer == LAYER_FORMAL:
        # Formal specs inherit BC from their folder: all six per-folder spec
        # files share one decision (entities/invariants/commands/events/
        # state-machine/scenarios), based on the majority BC across all
        # prose_refs of the whole folder. Falls back to per-doc if the
        # folder is unknown (e.g. meta READMEs).
        domain, cross_cutting, surface, domain_display_name = (
            _formal_owner_from_prose_refs(
                fm.get("prose_refs"),
                projection,
                folder_projection=folder_projection,
                rel_path=frame.rel_path,
            )
        )
    elif cross_cutting:
        domain = ""
        surface = ""
        domain_display_name = ""
    elif registry_entry is not None:
        domain, surface, domain_display_name = registry_entry
    else:
        # Frontmatter declares a domain but the registry has no entry.
        # Lints would catch this, but discovery stays deterministic:
        # fall back to the frontmatter value with empty surface.
        domain = fm_domain
        surface = ""
        domain_display_name = ""

    contract_state = _string(fm.get("contract_state"))
    applies_policies = _string_list(fm.get("applies_policies"))

    defers_to_ids, defers_to_edges, defers_to_full = _normalise_defers_to(fm.get("defers_to"))
    formal_ref_ids = _string_list(fm.get("formal_refs"))
    supersedes_ids, supersedes_full = _normalise_supersedes(fm.get("supersedes"))
    superseded_by_id = _string(fm.get("superseded_by"))
    authority_scopes, authority_full = _normalise_authority_over(fm.get("authority_over"))

    glossary_block = fm.get("glossary") if isinstance(fm.get("glossary"), dict) else None
    has_glossary = glossary_block is not None
    exported_term_ids = (
        tuple(
            _slugify_term(_string(item.get("id")))
            for item in (glossary_block.get("exported_terms") or [])
            if isinstance(item, dict) and _string(item.get("id"))
        )
        if has_glossary
        else ()
    )

    metadata = {
        "doc_kind": _string(fm.get("doc_kind")),
        "status": _string(fm.get("status")),
        "spec_kind": _string(fm.get("spec_kind")),
        "context": _string(fm.get("context")),
        "version": _string(fm.get("version")),
        "parent_concept_id": _string(fm.get("parent_concept_id")),
        "formal_scope": _string(fm.get("formal_scope")),
        "prose_anchor_policy": _string(fm.get("prose_anchor_policy")),
        "migration_ack": _string(fm.get("migration_ack")),
        "defers_to_full": _json_dump(defers_to_full),
        "supersedes_full": _json_dump(supersedes_full),
        "authority_over_full": _json_dump(authority_full),
    }

    return _DocView(
        doc_id=doc_id,
        title=title,
        module=module,
        tags=tags,
        domain=domain,
        cross_cutting=cross_cutting,
        surface=surface,
        domain_display_name=domain_display_name,
        contract_state=contract_state,
        applies_policies=applies_policies,
        defers_to_ids=defers_to_ids,
        defers_to_edges=defers_to_edges,
        formal_ref_ids=formal_ref_ids,
        supersedes_ids=supersedes_ids,
        superseded_by_id=superseded_by_id,
        authority_scopes=authority_scopes,
        has_glossary=has_glossary,
        exported_term_ids=exported_term_ids,
        domain_registry_hash=projection.registry_hash,
        schema_projection_version=SCHEMA_PROJECTION_VERSION,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def _chunk_document(
    frame: _DocumentFrame,
    view: _DocView,
    max_chars: int,
) -> list[ConceptChunk]:
    sections = _split_into_sections(frame.body)
    chunks: list[ConceptChunk] = []
    for ordering, (heading, content) in enumerate(sections):
        for sub_ordering, sub_text in enumerate(_subsplit(content, max_chars)):
            anchor = _section_anchor(heading, ordering, sub_ordering)
            chunk_uuid = str(uuid.uuid5(_CHUNK_NAMESPACE, f"{frame.rel_path}#{anchor}"))
            content_hash = _chunk_content_hash(sub_text, view)
            chunks.append(
                ConceptChunk(
                    chunk_id=chunk_uuid,
                    layer=frame.layer,
                    doc_id=view.doc_id,
                    title=view.title,
                    module=view.module,
                    tags=view.tags,
                    rel_path=frame.rel_path,
                    section_anchor=anchor,
                    heading=heading,
                    ordering=ordering * 1000 + sub_ordering,
                    content=sub_text,
                    content_hash=content_hash,
                    file_mtime=frame.mtime,
                    domain=view.domain,
                    cross_cutting=view.cross_cutting,
                    surface=view.surface,
                    domain_display_name=view.domain_display_name,
                    contract_state=view.contract_state,
                    applies_policies=view.applies_policies,
                    defers_to_ids=view.defers_to_ids,
                    defers_to_edges=view.defers_to_edges,
                    formal_ref_ids=view.formal_ref_ids,
                    supersedes_ids=view.supersedes_ids,
                    superseded_by_id=view.superseded_by_id,
                    authority_scopes=view.authority_scopes,
                    has_glossary=view.has_glossary,
                    exported_term_ids=view.exported_term_ids,
                    schema_projection_version=view.schema_projection_version,
                    domain_registry_hash=view.domain_registry_hash,
                    metadata=view.metadata,
                )
            )
    return chunks


def _split_into_sections(body: str) -> list[tuple[str, str]]:
    body = body.strip("\n")
    if not body:
        return []
    matches = list(_H2_RE.finditer(body))
    if not matches:
        return [("(document)", body.strip())]
    sections: list[tuple[str, str]] = []
    intro = body[: matches[0].start()].strip()
    if intro:
        sections.append(("(intro)", intro))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        heading = m.group("heading").strip()
        content = body[m.end() : end].strip()
        if not content:
            continue
        sections.append((heading, f"## {heading}\n\n{content}"))
    return sections


def _subsplit(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    parts: list[str] = []
    paragraphs = text.split("\n\n")
    buf: list[str] = []
    size = 0
    for para in paragraphs:
        para_size = len(para) + 2
        if buf and size + para_size > max_chars:
            parts.append("\n\n".join(buf))
            buf = [para]
            size = para_size
        else:
            buf.append(para)
            size += para_size
    if buf:
        parts.append("\n\n".join(buf))
    return parts


def _section_anchor(heading: str, ordering: int, sub_ordering: int) -> str:
    base = _SLUG_RE.sub("-", heading.lower()).strip("-") or "section"
    suffix = f"-{ordering:03d}"
    if sub_ordering > 0:
        suffix += f"-{sub_ordering:02d}"
    return base + suffix


def _chunk_content_hash(text: str, view: _DocView) -> str:
    """Hash over the body plus structural frontmatter.

    Including the projected fields means the delta-ingest detects changes
    in `domain`, `surface`, the reference graph etc., not just body edits.
    """
    payload = json.dumps(
        {
            "content": text,
            "doc_id": view.doc_id,
            "domain": view.domain,
            "cross_cutting": view.cross_cutting,
            "surface": view.surface,
            "contract_state": view.contract_state,
            "applies_policies": list(view.applies_policies),
            "defers_to_ids": list(view.defers_to_ids),
            "defers_to_edges": list(view.defers_to_edges),
            "formal_ref_ids": list(view.formal_ref_ids),
            "supersedes_ids": list(view.supersedes_ids),
            "superseded_by_id": view.superseded_by_id,
            "authority_scopes": list(view.authority_scopes),
            "has_glossary": view.has_glossary,
            "exported_term_ids": list(view.exported_term_ids),
            "tags": list(view.tags),
            "schema_projection_version": view.schema_projection_version,
            "metadata": view.metadata,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Glossary extraction
# ---------------------------------------------------------------------------


def _extract_glossary_terms(frame: _DocumentFrame, view: _DocView) -> list[GlossaryTerm]:
    glossary = frame.frontmatter.get("glossary")
    if not isinstance(glossary, dict):
        return []
    terms: list[GlossaryTerm] = []

    glossary_anchor = _detect_glossary_section_anchor(frame.body)

    for entry in glossary.get("exported_terms") or []:
        term = _build_glossary_term(
            entry=entry,
            kind="exported",
            view=view,
            frame=frame,
            section_anchor=glossary_anchor,
        )
        if term is not None:
            terms.append(term)

    for entry in glossary.get("internal_terms") or []:
        term = _build_glossary_term(
            entry=entry,
            kind="internal",
            view=view,
            frame=frame,
            section_anchor=glossary_anchor,
        )
        if term is not None:
            terms.append(term)

    return terms


def _detect_glossary_section_anchor(body: str) -> str:
    """Return the section anchor of a `## Glossar` heading if present, else ''."""
    for ordering, match in enumerate(_H2_RE.finditer(body)):
        heading = match.group("heading").strip()
        if heading.lower().startswith("glossar"):
            return _section_anchor(heading, ordering, 0)
    return ""


def _build_glossary_term(
    entry: Any,
    kind: str,
    view: _DocView,
    frame: _DocumentFrame,
    section_anchor: str,
) -> GlossaryTerm | None:
    if not isinstance(entry, dict):
        return None
    raw_id = _string(entry.get("id"))
    if not raw_id:
        return None
    term_id = _slugify_term(raw_id)

    definition = _string(entry.get("definition"))
    values = _string_list(entry.get("values"))
    reason = _string(entry.get("reason"))
    see_also = _normalise_see_also(entry.get("see_also"))

    payload = json.dumps(
        {
            "term": raw_id,
            "definition": definition,
            "kind": kind,
            "domain": view.domain,
            "source_doc_id": view.doc_id,
            "values": list(values),
            "see_also": list(see_also),
            "reason": reason,
            "schema_projection_version": view.schema_projection_version,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    content_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()

    term_uuid = str(
        uuid.uuid5(
            _GLOSSARY_NAMESPACE,
            f"{view.doc_id}#{view.domain}#{kind}#{term_id}",
        )
    )

    return GlossaryTerm(
        term_uuid=term_uuid,
        term_id=term_id,
        term=raw_id,
        normalized_term=raw_id.lower(),
        definition=definition,
        term_kind=kind,
        domain=view.domain,
        domain_display_name=view.domain_display_name,
        source_doc_id=view.doc_id,
        source_section_anchor=section_anchor,
        see_also_terms=see_also,
        contract_state=view.contract_state,
        values=values,
        reason=reason,
        content_hash=content_hash,
        file_mtime=frame.mtime,
        schema_projection_version=view.schema_projection_version,
        domain_registry_hash=view.domain_registry_hash,
    )


# ---------------------------------------------------------------------------
# Frontmatter normalisation helpers
# ---------------------------------------------------------------------------


def _normalise_defers_to(
    raw: Any,
) -> tuple[tuple[str, ...], tuple[str, ...], list[dict[str, Any]]]:
    """Return (target_ids, edges, full_entries).

    ``defers_to`` may carry strings or {target, scope, reason} dicts.
    The string form yields an empty scope; the dict form yields one
    edge per scope occurrence.
    """
    if not isinstance(raw, list):
        return (), (), []
    ids: list[str] = []
    edges: list[str] = []
    full: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in raw:
        if isinstance(item, str):
            target = item.strip()
            if not target:
                continue
            if target not in seen_ids:
                ids.append(target)
                seen_ids.add(target)
            edges.append(f"{target}|")
            full.append({"target": target, "scope": "", "reason": ""})
        elif isinstance(item, dict):
            target = _string(item.get("target"))
            if not target:
                continue
            scope = _string(item.get("scope"))
            reason = _string(item.get("reason"))
            if target not in seen_ids:
                ids.append(target)
                seen_ids.add(target)
            edges.append(f"{target}|{scope}")
            full.append({"target": target, "scope": scope, "reason": reason})
    return tuple(ids), tuple(edges), full


def _normalise_supersedes(raw: Any) -> tuple[tuple[str, ...], list[dict[str, Any]]]:
    if not isinstance(raw, list):
        return (), []
    ids: list[str] = []
    full: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, str):
            target = item.strip()
            if not target:
                continue
            ids.append(target)
            full.append({"target": target, "scope": "", "reason": ""})
        elif isinstance(item, dict):
            target = _string(item.get("target"))
            if not target:
                continue
            ids.append(target)
            full.append(
                {
                    "target": target,
                    "scope": _string(item.get("scope")),
                    "reason": _string(item.get("reason")),
                }
            )
    return tuple(ids), full


def _normalise_authority_over(raw: Any) -> tuple[tuple[str, ...], list[dict[str, Any]]]:
    if not isinstance(raw, list):
        return (), []
    scopes: list[str] = []
    full: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, str):
            scope = item.strip()
            if not scope:
                continue
            scopes.append(scope)
            full.append({"scope": scope})
        elif isinstance(item, dict):
            scope = _string(item.get("scope"))
            if not scope:
                continue
            scopes.append(scope)
            full.append(dict(item))
    return tuple(scopes), full


def _normalise_see_also(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    edges: list[str] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        term = _slugify_term(_string(item.get("term")))
        domain = _string(item.get("domain"))
        if not term or not domain:
            continue
        edges.append(f"{domain}|{term}")
    return tuple(edges)


def _slugify_term(value: str) -> str:
    slug = _SLUG_RE.sub("-", value.lower()).strip("-")
    return slug or value.strip()


def _doc_id(frontmatter: dict[str, Any], rel_path: str) -> str:
    for key in ("concept_id", "id"):
        value = _string(frontmatter.get(key))
        if value:
            return value
    return rel_path


def _fallback_title(rel_path: str) -> str:
    name = rel_path.rsplit("/", 1)[-1]
    return name.removesuffix(".md").replace("_", " ").replace("-", " ").strip()


def _string(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    return ""


def _string_list(value: Any) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split(",") if part.strip())
    return ()


def _json_dump(value: Any) -> str:
    """Serialise to compact JSON; metadata payload is plain text in Weaviate."""
    if value in (None, "", [], {}):
        return ""
    return json.dumps(value, ensure_ascii=False, sort_keys=True)
