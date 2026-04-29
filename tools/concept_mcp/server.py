"""FastMCP server exposing search and ingest tools for the concept corpus."""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP
from weaviate.classes.query import Filter, MetadataQuery

from tools.concept_ingester.config import IngesterConfig
from tools.concept_ingester.ingester import (
    IngestStrategy,
    open_client,
    run_ingest,
)
from tools.concept_ingester.schema import (
    CHUNK_COLLECTION_NAME,
    GLOSSARY_COLLECTION_NAME,
    SCHEMA_PROJECTION_VERSION,
    ensure_all_collections,
)
from tools.concept_mcp.filters import FilterSyntaxError, build_filter

SERVER_INSTRUCTIONS = """\
AgentKit 3 concept knowledge base.

WHAT THIS SERVER IS
-------------------
A semantic + lexical (hybrid) index over the entire AgentKit 3 concept
corpus under `concept/`. Two collections are indexed:

  - Ak3ConceptChunk   -> H2-section level chunks of every concept doc.
  - Ak3GlossaryTerm   -> exported and internal glossary terms of every
                          contract doc; vectorised so semantic search
                          lands on the canonical definition.

Three concept layers feed the chunk collection:

  - "domain"     -> concept/domain-design/   (DK-XX, fachliche Sicht)
  - "technical"  -> concept/technical-design/ (FK-XX, Feinkonzept)
  - "formal"     -> concept/formal-spec/      (formal.<context>.<x>)

Bounded-Context-Schnitt aus dem aktuellen Refactor:
  - `domain` (BC-id) und `surface` ("contract" | "internal") sind
    aus `_meta/domain-registry.yaml` projiziert.
  - `cross_cutting=true` markiert Foundation-/Adapter-/Reference-Docs
    ohne BC-Owner (siehe 00_index.md §9.13).
  - `applies_policies`, `defers_to_ids`, `defers_to_edges`,
    `formal_ref_ids`, `supersedes_ids`, `superseded_by_id`,
    `authority_scopes` sind ebenfalls top-level filterbar.

WHEN TO USE THIS SERVER (instead of grep / Read on concept/*.md)
----------------------------------------------------------------
Always prefer `concept_search` / `concept_glossary_search` over grep
or file walks for any of:

  * "Wo steht etwas zu <Begriff/Funktion/Komponente>?"
  * "Was sagt das Konzept zu <Pipeline-Phase / Guard / Artefakt>?"
  * "Welche Invarianten / Trust-Klassen gelten fuer X?"
  * "Welche FK-Dokumente / formal-Specs sind fuer Aufgabe Y relevant?"
  * "Wie ist Begriff X im BC <verify-system> definiert?"
    -> concept_glossary_search
  * Disambiguierung zwischen Domain-Idee (DK), Feinkonzept (FK) und
    formaler Spec (formal.*) — der Layer-Filter loest das in einem Call.
  * Eingrenzung auf einen Bounded Context — `domain="verify-system"`
    plus `surface="contract"` liefert die Vertrags-Sicht des BC.

DEFAULT STRATEGY FOR AGENTS
---------------------------
1. Start mit `concept_search(query=..., limit=8)` ohne Filter.
2. Wenn die Top-Treffer aus dem falschen Layer/BC kommen oder zu
   breit sind, eingrenzen via `layer="technical"`, `domain="..."`,
   `surface="contract"` oder via `where`-DSL.
3. Fuer einen vollstaendigen Dokumentinhalt:
   `concept_get(doc_id="FK-27")` oder `concept_get(rel_path="...")`.
4. Fuer Begriffsdefinitionen:
   `concept_glossary_search(query="Stage-Registry")`.
5. Nur in den seltenen Faellen, in denen der Index veraltet sein
   koennte, `concept_ingest(strategy="delta")` aufrufen — Ingest
   ist Tooling, nicht Default-Suche.

FILTER DSL
----------
`where` ist rekursiv (and / or / equal / not_equal / contains_any /
contains_all / like). Filterbare Top-Level-Properties siehe
`concept_filter_help()`.
"""

mcp = FastMCP("agentkit3-concepts", instructions=SERVER_INSTRUCTIONS)


def _config() -> IngesterConfig:
    return IngesterConfig.from_env()


def _combine(*parts: Filter | None) -> Filter | None:
    active = [p for p in parts if p is not None]
    if not active:
        return None
    if len(active) == 1:
        return active[0]
    return Filter.all_of(active)


def _equal_filter(prop: str, value: str | list[str] | None) -> Filter | None:
    if value is None:
        return None
    if isinstance(value, str):
        if not value:
            return None
        return Filter.by_property(prop).equal(value)
    if isinstance(value, list) and value:
        return Filter.by_property(prop).contains_any(value)
    return None


def _bool_filter(prop: str, value: bool | None) -> Filter | None:
    if value is None:
        return None
    return Filter.by_property(prop).equal(value)


_CHUNK_RETURN_PROPERTIES: tuple[str, ...] = (
    "layer",
    "doc_id",
    "title",
    "module",
    "tags",
    "rel_path",
    "section_anchor",
    "heading",
    "ordering",
    "content",
    "domain",
    "cross_cutting",
    "surface",
    "domain_display_name",
    "contract_state",
    "applies_policies",
    "defers_to_ids",
    "defers_to_edges",
    "formal_ref_ids",
    "supersedes_ids",
    "superseded_by_id",
    "authority_scopes",
    "has_glossary",
    "exported_term_ids",
    "schema_projection_version",
    "domain_registry_hash",
    "metadata",
)


def _serialize_chunk(obj: Any) -> dict[str, Any]:
    props = dict(obj.properties or {})
    metadata = getattr(obj, "metadata", None)
    score = getattr(metadata, "score", None) if metadata is not None else None
    distance = getattr(metadata, "distance", None) if metadata is not None else None
    return {
        "chunk_id": str(obj.uuid),
        "score": score,
        "distance": distance,
        "layer": props.get("layer"),
        "doc_id": props.get("doc_id"),
        "title": props.get("title"),
        "module": props.get("module"),
        "tags": props.get("tags") or [],
        "rel_path": props.get("rel_path"),
        "section_anchor": props.get("section_anchor"),
        "heading": props.get("heading"),
        "ordering": props.get("ordering"),
        "content": props.get("content"),
        "domain": props.get("domain") or "",
        "cross_cutting": bool(props.get("cross_cutting")),
        "surface": props.get("surface") or "",
        "domain_display_name": props.get("domain_display_name") or "",
        "contract_state": props.get("contract_state") or "",
        "applies_policies": props.get("applies_policies") or [],
        "defers_to_ids": props.get("defers_to_ids") or [],
        "defers_to_edges": props.get("defers_to_edges") or [],
        "formal_ref_ids": props.get("formal_ref_ids") or [],
        "supersedes_ids": props.get("supersedes_ids") or [],
        "superseded_by_id": props.get("superseded_by_id") or "",
        "authority_scopes": props.get("authority_scopes") or [],
        "has_glossary": bool(props.get("has_glossary")),
        "exported_term_ids": props.get("exported_term_ids") or [],
        "frontmatter_metadata": props.get("metadata") or {},
    }


def _serialize_glossary_term(obj: Any) -> dict[str, Any]:
    props = dict(obj.properties or {})
    metadata = getattr(obj, "metadata", None)
    score = getattr(metadata, "score", None) if metadata is not None else None
    distance = getattr(metadata, "distance", None) if metadata is not None else None
    return {
        "term_uuid": str(obj.uuid),
        "score": score,
        "distance": distance,
        "term_id": props.get("term_id"),
        "term": props.get("term"),
        "normalized_term": props.get("normalized_term"),
        "definition": props.get("definition"),
        "term_kind": props.get("term_kind"),
        "domain": props.get("domain") or "",
        "domain_display_name": props.get("domain_display_name") or "",
        "source_doc_id": props.get("source_doc_id"),
        "source_section_anchor": props.get("source_section_anchor") or "",
        "see_also_terms": props.get("see_also_terms") or [],
        "contract_state": props.get("contract_state") or "",
        "values": props.get("values") or [],
        "reason": props.get("reason") or "",
    }


@mcp.tool()
def concept_search(
    query: str,
    layer: str | list[str] | None = None,
    domain: str | list[str] | None = None,
    surface: str | None = None,
    cross_cutting: bool | None = None,
    where: dict[str, Any] | None = None,
    limit: int = 10,
    hybrid_alpha: float = 0.5,
    include_content: bool = True,
) -> str:
    """Primary entry point for ANY question about the AgentKit 3 concept corpus.

    Prefer this over grep / Read on concept/*.md. The chunk index covers
    all H2 sections across the three concept layers (domain, technical,
    formal) and ranks them via a hybrid of BM25 and multilingual vector
    similarity. Without filters, results are mixed across layers and
    bounded contexts and sorted by relevance.

    When to use:
        * Looking up where a term, rule, invariant, component or KPI is
          described, regardless of which document or layer it lives in.
        * Comparing how the same topic is treated on the domain
          (DK-XX), technical (FK-XX) and formal (formal.*) level.
        * Scoping to a single Bounded Context with `domain="..."` (and
          optionally `surface="contract"` for the contract-only view).

    Args:
        query: Natural language query in German or English.
        layer: Optional layer constraint. One of "domain", "technical",
            "formal", or a list. Omit to mix all three layers.
        domain: Optional Bounded-Context id (e.g. "verify-system",
            "story-lifecycle", "governance-and-guards") or list of ids.
            Use `concept_filter_help()` for the BC catalogue.
        surface: Optional surface filter inside the chosen BC.
            "contract" -> only the BC's contract docs (export surface).
            "internal" -> only the BC's internal/member docs.
            Omit to include both.
        cross_cutting: Optional flag. True -> only foundation/adapter/
            reference docs (no BC owner). False -> exclude them.
        where: Optional recursive filter DSL on top of the structured
            filters. See `concept_filter_help()` for shape and the full
            list of filterable top-level properties.
        limit: Max number of chunks (default 10).
        hybrid_alpha: 0.0 = pure BM25, 1.0 = pure vector, 0.5 = balanced.
        include_content: If False, omit the chunk body and return only
            metadata + heading.

    Returns:
        JSON object: {"hits": [...], "count": N}.
    """
    cfg = _config()
    try:
        custom_filter = build_filter(where)
    except FilterSyntaxError as exc:
        return json.dumps({"error": f"invalid where filter: {exc}"})

    combined = _combine(
        _equal_filter("layer", layer),
        _equal_filter("domain", domain),
        _equal_filter("surface", surface),
        _bool_filter("cross_cutting", cross_cutting),
        custom_filter,
    )
    with open_client(cfg) as client:
        ensure_all_collections(client)
        collection = client.collections.get(CHUNK_COLLECTION_NAME)
        result = collection.query.hybrid(
            query=query,
            alpha=hybrid_alpha,
            filters=combined,
            limit=limit,
            return_metadata=MetadataQuery(score=True, distance=True),
        )
    payload = [_serialize_chunk(o) for o in result.objects]
    if not include_content:
        for entry in payload:
            entry.pop("content", None)
    return json.dumps({"hits": payload, "count": len(payload)}, ensure_ascii=False, indent=2)


@mcp.tool()
def concept_glossary_search(
    query: str,
    domain: str | list[str] | None = None,
    term_kind: str | None = None,
    limit: int = 10,
    hybrid_alpha: float = 0.5,
) -> str:
    """Search the glossary collection (term + definition pairs).

    Glossary terms live in their own collection because the canonical
    answer to "what does <term> mean inside BC X?" is a single
    sentence, not a body chunk. Vector + BM25 land directly on the
    definition.

    Args:
        query: Term or paraphrase. Examples: "Stage-Registry",
            "integrity gate", "trust class".
        domain: Optional BC id (or list) to scope to one bounded
            context. A term may be exported by multiple BCs; without
            this filter, all BC-specific definitions are returned.
        term_kind: "exported" | "internal". Default: both. Exported
            terms are part of the BC's published vocabulary; internal
            terms describe BC-private concepts.
        limit: Max number of terms (default 10).
        hybrid_alpha: Same semantics as `concept_search.hybrid_alpha`.

    Returns:
        JSON: {"hits": [...], "count": N}. Each hit carries term,
        definition, domain, source_doc_id, source_section_anchor, and
        see_also_terms.
    """
    cfg = _config()
    combined = _combine(
        _equal_filter("domain", domain),
        _equal_filter("term_kind", term_kind),
    )
    with open_client(cfg) as client:
        ensure_all_collections(client)
        collection = client.collections.get(GLOSSARY_COLLECTION_NAME)
        result = collection.query.hybrid(
            query=query,
            alpha=hybrid_alpha,
            filters=combined,
            limit=limit,
            return_metadata=MetadataQuery(score=True, distance=True),
        )
    payload = [_serialize_glossary_term(o) for o in result.objects]
    return json.dumps({"hits": payload, "count": len(payload)}, ensure_ascii=False, indent=2)


@mcp.tool()
def concept_get(
    doc_id: str | None = None,
    rel_path: str | None = None,
    chunk_id: str | None = None,
    limit: int = 50,
) -> str:
    """Fetch the full content of a known concept document or chunk.

    Use this *after* a `concept_search` has identified the right doc, or
    when you already know the canonical identifier (e.g. "FK-27"). It
    returns every chunk of the document in original section order — no
    embedding, no ranking, just the document.

    Args:
        doc_id: Concept ID such as "FK-27" or "formal.architecture-conformance.entities".
        rel_path: e.g. "technical-design/27_verify_pipeline_closure_orchestration.md".
        chunk_id: UUID of one chunk (returns just that chunk).
        limit: Cap on chunks returned (default 50).

    Returns:
        JSON: {"hits": [...sorted by ordering...], "count": N}.
    """
    cfg = _config()
    if not any([doc_id, rel_path, chunk_id]):
        return json.dumps({"error": "provide doc_id, rel_path or chunk_id"})

    with open_client(cfg) as client:
        ensure_all_collections(client)
        collection = client.collections.get(CHUNK_COLLECTION_NAME)
        if chunk_id is not None:
            obj = collection.query.fetch_object_by_id(chunk_id)
            if obj is None:
                return json.dumps({"hits": [], "count": 0})
            return json.dumps(
                {"hits": [_serialize_chunk(obj)], "count": 1},
                ensure_ascii=False,
                indent=2,
            )
        criteria: Filter | None
        if doc_id is not None and rel_path is not None:
            criteria = Filter.all_of(
                [
                    Filter.by_property("doc_id").equal(doc_id),
                    Filter.by_property("rel_path").equal(rel_path),
                ]
            )
        elif doc_id is not None:
            criteria = Filter.by_property("doc_id").equal(doc_id)
        else:
            criteria = Filter.by_property("rel_path").equal(rel_path)
        result = collection.query.fetch_objects(filters=criteria, limit=limit)
        ordered = sorted(
            result.objects, key=lambda o: int((o.properties or {}).get("ordering", 0) or 0)
        )
        payload = [_serialize_chunk(o) for o in ordered]
    return json.dumps({"hits": payload, "count": len(payload)}, ensure_ascii=False, indent=2)


@mcp.tool()
def concept_ingest(strategy: str = "delta") -> str:
    """Re-index the concept corpus into Weaviate. Tooling, not search.

    This is *not* the way to query concepts — use `concept_search` /
    `concept_glossary_search` / `concept_get` for that. Run an ingest
    only when:

        * concept/*.md files have been edited and you need fresh
          search results in the same session.
        * The collections are empty (`concept_status()` shows zero
          remote objects).

    Args:
        strategy:
            "delta" (default): Diff local objects vs. remote by content
                hash; insert/update/delete only the changed ones.
                Idempotent. Runs over both collections.
            "full": Drop and recreate both collections, then ingest
                everything from scratch. Use after schema changes.

    Returns:
        JSON ingest report: per-collection counts plus aggregated totals.
    """
    try:
        chosen = IngestStrategy(strategy)
    except ValueError:
        return json.dumps({"error": f"unknown strategy: {strategy}"})
    report = run_ingest(chosen)
    return json.dumps(report.as_dict(), ensure_ascii=False, indent=2)


@mcp.tool()
def concept_status() -> str:
    """Diagnostics: local vs. remote counts for both collections.

    Use this to verify that the index is populated and roughly in sync
    with the on-disk corpus before running heavy searches.

    Returns:
        JSON with per-collection local discovery (chunks broken down by
        layer / domain / cross_cutting; glossary terms broken down by
        kind / domain) and remote total counts.
    """
    cfg = _config()
    from tools.concept_ingester.discovery import discover

    result = discover(cfg.concept_root, max_chars=cfg.chunk_max_chars)

    by_layer_local: dict[str, int] = {}
    by_domain_local: dict[str, int] = {}
    cross_cutting_chunks = 0
    for chunk in result.chunks:
        by_layer_local[chunk.layer] = by_layer_local.get(chunk.layer, 0) + 1
        if chunk.cross_cutting:
            cross_cutting_chunks += 1
        elif chunk.domain:
            by_domain_local[chunk.domain] = by_domain_local.get(chunk.domain, 0) + 1

    glossary_by_kind: dict[str, int] = {}
    glossary_by_domain: dict[str, int] = {}
    for term in result.glossary_terms:
        glossary_by_kind[term.term_kind] = glossary_by_kind.get(term.term_kind, 0) + 1
        if term.domain:
            glossary_by_domain[term.domain] = glossary_by_domain.get(term.domain, 0) + 1

    payload: dict[str, Any] = {
        "concept_root": str(cfg.concept_root),
        "schema_projection_version": SCHEMA_PROJECTION_VERSION,
        "domain_registry_hash": result.domain_registry_hash,
        "discovered": {
            "chunks": {
                "total": len(result.chunks),
                "by_layer": by_layer_local,
                "by_domain": by_domain_local,
                "cross_cutting": cross_cutting_chunks,
            },
            "glossary_terms": {
                "total": len(result.glossary_terms),
                "by_kind": glossary_by_kind,
                "by_domain": glossary_by_domain,
            },
        },
    }
    try:
        with open_client(cfg) as client:
            ensure_all_collections(client)
            chunk_total = (
                client.collections.get(CHUNK_COLLECTION_NAME)
                .aggregate.over_all(total_count=True)
                .total_count
            )
            glossary_total = (
                client.collections.get(GLOSSARY_COLLECTION_NAME)
                .aggregate.over_all(total_count=True)
                .total_count
            )
            payload["remote"] = {
                CHUNK_COLLECTION_NAME: {"total": chunk_total},
                GLOSSARY_COLLECTION_NAME: {"total": glossary_total},
            }
    except Exception as exc:  # noqa: BLE001 - status is read-only
        payload["remote"] = {"error": str(exc)}
    return json.dumps(payload, ensure_ascii=False, indent=2)


@mcp.tool()
def concept_filter_help() -> str:
    """Reference for the recursive `where` filter DSL and the BC catalogue.

    Returns the supported operators, the filterable top-level properties
    of the chunk and glossary collections, the layer taxonomy, and
    worked examples. Call this once before issuing your first non-
    trivial filtered search if you are unsure about the syntax or BC
    ids.
    """
    return json.dumps(
        {
            "leaf_ops": ["equal", "not_equal", "contains_any", "contains_all", "like"],
            "group_ops": ["and", "or"],
            "leaf_shape": {"op": "<leaf_op>", "property": "<name>", "value": "<value>"},
            "group_shape": {"op": "and|or", "operands": ["<filter>", "<filter>"]},
            "chunk_filterable_properties": {
                "layer": "domain | technical | formal",
                "doc_id": "DK-XX, FK-XX, formal.<context>.<name>",
                "module": "frontmatter module / context label",
                "tags": "string array; use contains_any / contains_all",
                "rel_path": "path under concept/ (forward slashes)",
                "section_anchor": "stable per-section slug",
                "domain": (
                    "Bounded-Context id from the registry "
                    "(e.g. verify-system, story-lifecycle). "
                    "Empty string for cross-cutting docs."
                ),
                "cross_cutting": "bool; true for foundation/adapter docs.",
                "surface": "contract | internal | '' (cross-cutting).",
                "contract_state": "active | compatible | deprecating | breaking | ''",
                "applies_policies": "string array; contains_any / contains_all.",
                "defers_to_ids": "string array (target ids only).",
                "defers_to_edges": (
                    "string array of '<target>|<scope>' composite edges "
                    "for scope-precise filtering."
                ),
                "formal_ref_ids": "string array.",
                "supersedes_ids": "string array.",
                "superseded_by_id": "single id or ''.",
                "authority_scopes": "string array of authority_over scopes.",
                "has_glossary": "bool; doc carries a glossary block.",
                "exported_term_ids": "string array of exported term slugs.",
            },
            "glossary_filterable_properties": {
                "term_id": "stable slug of the term within its source doc",
                "normalized_term": "lower-cased term for exact lookup",
                "term_kind": "exported | internal",
                "domain": "BC id of the source doc",
                "source_doc_id": "concept id of the source doc",
                "see_also_terms": "string array of '<domain>|<term_id>' edges",
                "contract_state": "inherited from source doc",
                "values": "string array; optional enum values",
            },
            "layers": {
                "domain": (
                    "DK-XX in concept/domain-design/. Fachliche Sicht: "
                    "Rollen, Pipeline-Idee, Governance-Konzept, KPIs."
                ),
                "technical": (
                    "FK-XX in concept/technical-design/. Feinkonzept: "
                    "Architektur, State-Modell, Pipeline-Engine, "
                    "Verify-Schichten, Komponentenschnitt, Schemas."
                ),
                "formal": (
                    "formal.<context>.<x> in concept/formal-spec/. "
                    "Maschinenpruefbare YAML-Specs."
                ),
            },
            "bounded_contexts": [
                "pipeline-framework",
                "exploration-and-design",
                "implementation-phase",
                "verify-system",
                "story-closure",
                "story-lifecycle",
                "execution-planning",
                "governance-and-guards",
                "artifacts",
                "telemetry-and-events",
                "requirements-and-scope-coverage",
                "prompt-runtime",
                "agent-skills",
                "kpi-and-dashboard",
                "failure-corpus",
                "installation-and-bootstrap",
            ],
            "examples": [
                {
                    "intent": "verify-system contract docs only",
                    "filter": {
                        "op": "and",
                        "operands": [
                            {"op": "equal", "property": "domain", "value": "verify-system"},
                            {"op": "equal", "property": "surface", "value": "contract"},
                        ],
                    },
                },
                {
                    "intent": "any FK-2x doc",
                    "filter": {"op": "like", "property": "doc_id", "value": "FK-2*"},
                },
                {
                    "intent": "docs that apply policy P-INTEGRITY-V1",
                    "filter": {
                        "op": "contains_any",
                        "property": "applies_policies",
                        "value": ["P-INTEGRITY-V1"],
                    },
                },
                {
                    "intent": "docs that defer to FK-20 with scope runtime-profile",
                    "filter": {
                        "op": "contains_any",
                        "property": "defers_to_edges",
                        "value": ["FK-20|runtime-profile"],
                    },
                },
                {
                    "intent": "exclude cross-cutting foundation docs",
                    "filter": {
                        "op": "equal",
                        "property": "cross_cutting",
                        "value": False,
                    },
                },
            ],
        },
        indent=2,
        ensure_ascii=False,
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
