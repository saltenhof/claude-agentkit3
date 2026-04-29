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
from tools.concept_ingester.schema import COLLECTION_NAME, ensure_collection
from tools.concept_mcp.filters import FilterSyntaxError, build_filter

SERVER_INSTRUCTIONS = """\
AgentKit 3 concept knowledge base.

WHAT THIS SERVER IS
-------------------
A semantic + lexical (hybrid) index over the entire AgentKit 3 concept
corpus under `concept/`. The corpus is ~1000 chunked sections across
three coordinated layers:

  - "domain"     -> concept/domain-design/   (DK-XX, fachliche Sicht,
                    Rollen, Pipeline-Domaene, Governance-Idee, KPIs)
  - "technical"  -> concept/technical-design/ (FK-XX, Feinkonzept:
                    Architektur, Pipeline-Engine, Verify, State-Backend,
                    Komponentenschnitt, Schemas, Defaults)
  - "formal"     -> concept/formal-spec/     (formal.<context>.<x>,
                    maschinell pruefbare YAML-Specs zu Architektur,
                    Truth-Boundary, Stage-Registry, Konformitaet)

A single chunk corresponds to one H2-section of a concept document.
It carries the original frontmatter (concept_id, module, tags, status,
spec_kind, ...) so that filtering by layer, module, tag or doc_id is
cheap and exact.

WHEN TO USE THIS SERVER (instead of grep / Read on concept/*.md)
----------------------------------------------------------------
Always prefer `concept_search` over grep / file walks for any of:

  * "Wo steht etwas zu <Begriff/Funktion/Komponente>?"
  * "Was sagt das Konzept zu <Pipeline-Phase / Guard / Artefakt>?"
  * "Welche Invarianten / Trust-Klassen gelten fuer X?"
  * "Welche FK-Dokumente / formal-Specs sind fuer Aufgabe Y relevant?"
  * Disambiguierung zwischen Domain-Idee (DK), Feinkonzept (FK) und
    formaler Spec (formal.*) — der Layer-Filter loest das in einem Call.

Reasons to prefer search over grep:
  * Hybrid-Score (BM25 + multilinguale Embeddings) findet semantische
    Treffer ueber Synonyme und deutsche/englische Varianten.
  * Treffer kommen mit Layer-, Modul- und Tag-Metadaten — der Agent
    weiss sofort, welcher Konzept-Layer geantwortet hat.
  * Eine ungefilterte Anfrage liefert eine *gemischte* Top-N-Liste
    aus allen drei Ebenen, sortiert nach Relevanz. Damit wird die
    natuerliche Schichtung Domain -> Technical -> Formal in der
    Antwort sichtbar, ohne dass der Agent dreimal sucht.
  * `concept_get` liefert *alle Sections eines Dokuments in
    Originalreihenfolge* — schneller und billiger als das Markdown
    selbst zu lesen.

DEFAULT STRATEGY FOR AGENTS
---------------------------
1. Start mit `concept_search(query=..., limit=8)` ohne Layer-Filter.
2. Wenn die Top-Treffer aus dem falschen Layer kommen oder zu breit
   sind, eingrenzen via `layer="technical"` oder via `where`-DSL.
3. Fuer einen vollstaendigen Dokumentinhalt:
   `concept_get(doc_id="FK-27")` oder `concept_get(rel_path="...")`.
4. Nur in den seltenen Faellen, in denen der Index veraltet sein
   koennte, `concept_ingest(strategy="delta")` aufrufen — Ingest
   ist Tooling, nicht Default-Suche.

FILTER DSL
----------
`where` ist rekursiv (and / or / equal / not_equal / contains_any /
contains_all / like). Filterbare Properties: layer, doc_id, module,
tags, rel_path, section_anchor. Siehe `concept_filter_help()`.
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


def _layer_filter(layer: str | list[str] | None) -> Filter | None:
    if layer is None:
        return None
    if isinstance(layer, str):
        return Filter.by_property("layer").equal(layer)
    if isinstance(layer, list) and layer:
        return Filter.by_property("layer").contains_any(layer)
    return None


def _serialize_object(obj: Any) -> dict[str, Any]:
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
        "extra": props.get("extra") or {},
    }


@mcp.tool()
def concept_search(
    query: str,
    layer: str | list[str] | None = None,
    where: dict[str, Any] | None = None,
    limit: int = 10,
    hybrid_alpha: float = 0.5,
    include_content: bool = True,
) -> str:
    """Primary entry point for ANY question about the AgentKit 3 concept corpus.

    Prefer this over grep / Read on concept/*.md. The index covers all
    ~1000 sections across the three concept layers (domain, technical,
    formal) and ranks them via a hybrid of BM25 and multilingual vector
    similarity. Without a filter, results are mixed across layers and
    sorted by relevance.

    When to use:
        * Looking up where a term, rule, invariant, component or KPI is
          described, regardless of which document or layer it lives in.
        * Comparing how the same topic is treated on the domain
          (DK-XX), technical (FK-XX) and formal (formal.*) level.
        * Pre-flight before editing code: find the concept that owns a
          contract before changing the implementation.

    Args:
        query: Natural language query in German or English. Examples:
            "Verify-Phase 4 Schichten", "integrity gate dimensions",
            "wer darf QA-Artefakte schreiben".
        layer: Optional layer constraint. One of "domain", "technical",
            "formal", or a list of those values. Omit to mix all three
            layers in the result, which is usually preferred for
            exploratory queries.
        where: Optional recursive filter DSL on top of layer. Useful
            for: tag-based scoping ("governance"), module scoping
            ("verify"), wildcard doc_id matching ("FK-2*"). See
            `concept_filter_help()` for shape and examples.
        limit: Max number of chunks (default 10). Increase to ~25 for
            broad surveys, lower to 3-5 for "find the canonical
            section" lookups.
        hybrid_alpha: 0.0 = pure BM25 (lexical), 1.0 = pure vector
            (semantic), 0.5 = balanced default. Lower alpha when the
            query contains specific identifiers (FK-numbers, function
            names). Higher alpha for fuzzy / paraphrased questions.
        include_content: If False, omit the chunk body and return only
            metadata + heading. Useful when surveying many docs.

    Returns:
        JSON object: {"hits": [...], "count": N}.
        Each hit carries chunk_id, score, layer, doc_id, title, module,
        tags, rel_path, section_anchor, heading, ordering, content
        (when include_content), extra (frontmatter spillover).
    """
    cfg = _config()
    try:
        custom_filter = build_filter(where)
    except FilterSyntaxError as exc:
        return json.dumps({"error": f"invalid where filter: {exc}"})

    combined = _combine(_layer_filter(layer), custom_filter)
    with open_client(cfg) as client:
        ensure_collection(client, cfg.collection_name)
        collection = client.collections.get(cfg.collection_name)
        result = collection.query.hybrid(
            query=query,
            alpha=hybrid_alpha,
            filters=combined,
            limit=limit,
            return_metadata=MetadataQuery(score=True, distance=True),
        )
    payload = [_serialize_object(o) for o in result.objects]
    if not include_content:
        for entry in payload:
            entry.pop("content", None)
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

    When to use:
        * "Lies mir FK-27 komplett" -> concept_get(doc_id="FK-27").
        * "Zeig mir die formale Spec zu architecture-conformance" ->
          concept_get(rel_path="formal-spec/architecture-conformance/entities.md").
        * Picking up where a search left off: pass the rel_path of the
          top hit to retrieve neighbouring sections.

    Provide exactly one anchor:
        doc_id: Concept identifier from frontmatter (DK-XX, FK-XX,
            formal.<context>.<x>). Most ergonomic.
        rel_path: Path under concept/ (use forward slashes).
        chunk_id: UUID of a single chunk, e.g. from a prior search hit.

    Args:
        doc_id: Concept ID such as "FK-27" or "formal.architecture-conformance.entities".
        rel_path: e.g. "technical-design/27_verify_pipeline_closure_orchestration.md".
        chunk_id: UUID of one chunk (returns just that chunk).
        limit: Cap on chunks returned (default 50, enough for any single doc).

    Returns:
        JSON: {"hits": [...sorted by ordering...], "count": N}.
    """
    cfg = _config()
    if not any([doc_id, rel_path, chunk_id]):
        return json.dumps({"error": "provide doc_id, rel_path or chunk_id"})

    with open_client(cfg) as client:
        ensure_collection(client, cfg.collection_name)
        collection = client.collections.get(cfg.collection_name)
        if chunk_id is not None:
            obj = collection.query.fetch_object_by_id(chunk_id)
            if obj is None:
                return json.dumps({"hits": [], "count": 0})
            return json.dumps({"hits": [_serialize_object(obj)], "count": 1}, ensure_ascii=False, indent=2)
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
        payload = [_serialize_object(o) for o in ordered]
    return json.dumps({"hits": payload, "count": len(payload)}, ensure_ascii=False, indent=2)


@mcp.tool()
def concept_ingest(strategy: str = "delta") -> str:
    """Re-index the concept corpus into Weaviate. Tooling, not search.

    This is *not* the way to query concepts — use `concept_search` /
    `concept_get` for that. Run an ingest only when:

        * concept/*.md files have been edited and you need fresh
          search results in the same session.
        * The collection is empty (`concept_status()` shows zero
          remote chunks) — usually after a Weaviate reset.

    Args:
        strategy:
            "delta" (default): Diff local chunks vs. remote by content
                hash; insert/update/delete only the changed ones.
                Idempotent and cheap (seconds for ~1000 chunks).
            "full": Drop and recreate the collection, then ingest
                everything from scratch. Use after schema changes.

    Returns:
        JSON ingest report: discovered, inserted, updated, deleted,
        skipped, errors.
    """
    try:
        chosen = IngestStrategy(strategy)
    except ValueError:
        return json.dumps({"error": f"unknown strategy: {strategy}"})
    report = run_ingest(chosen)
    return json.dumps(report.as_dict(), ensure_ascii=False, indent=2)


@mcp.tool()
def concept_status() -> str:
    """Diagnostics: local vs. remote chunk counts, broken down by layer.

    Use this to verify that the index is populated and roughly in sync
    with the on-disk corpus before running heavy searches. A large
    delta between local and remote means the index is stale and a
    `concept_ingest(strategy="delta")` is in order.

    Returns:
        JSON with:
            collection: Weaviate collection name.
            concept_root: Absolute path of the concept/ directory.
            discovered: {total, by_layer} from disk.
            remote: {total, by_layer} from Weaviate (or {error: "..."}
                when the server is unreachable).
    """
    cfg = _config()
    from tools.concept_ingester.discovery import discover_chunks

    chunks = discover_chunks(cfg.concept_root, max_chars=cfg.chunk_max_chars)
    by_layer_local: dict[str, int] = {}
    for chunk in chunks:
        by_layer_local[chunk.layer] = by_layer_local.get(chunk.layer, 0) + 1

    payload: dict[str, Any] = {
        "collection": cfg.collection_name,
        "concept_root": str(cfg.concept_root),
        "discovered": {"total": len(chunks), "by_layer": by_layer_local},
    }
    try:
        with open_client(cfg) as client:
            ensure_collection(client, cfg.collection_name)
            collection = client.collections.get(cfg.collection_name)
            total = collection.aggregate.over_all(total_count=True).total_count
            by_layer_remote: dict[str, int] = {}
            for layer in ("domain", "formal", "technical"):
                agg = collection.aggregate.over_all(
                    filters=Filter.by_property("layer").equal(layer),
                    total_count=True,
                )
                by_layer_remote[layer] = agg.total_count
            payload["remote"] = {"total": total, "by_layer": by_layer_remote}
    except Exception as exc:  # noqa: BLE001 - status is read-only
        payload["remote"] = {"error": str(exc)}
    return json.dumps(payload, ensure_ascii=False, indent=2)


@mcp.tool()
def concept_filter_help() -> str:
    """Reference for the recursive `where` filter DSL used by concept_search.

    Returns the supported operators, the filterable properties, the
    layer taxonomy, and worked examples. Call this once before issuing
    your first non-trivial filtered search if you are unsure about
    the syntax.
    """
    return json.dumps(
        {
            "leaf_ops": ["equal", "not_equal", "contains_any", "contains_all", "like"],
            "group_ops": ["and", "or"],
            "leaf_shape": {"op": "<leaf_op>", "property": "<name>", "value": "<value>"},
            "group_shape": {"op": "and|or", "operands": ["<filter>", "<filter>"]},
            "filterable_properties": {
                "layer": "domain | technical | formal",
                "doc_id": "DK-XX, FK-XX, formal.<context>.<name>",
                "module": "frontmatter module / context label",
                "tags": "string array; use contains_any / contains_all",
                "rel_path": "path under concept/ (forward slashes)",
                "section_anchor": "stable per-section slug",
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
                    "Maschinenpruefbare YAML-Specs (Architecture-"
                    "Conformance, Truth-Boundary, Stage-Registry, ...)."
                ),
            },
            "examples": [
                {
                    "intent": "technical only, governance-tagged",
                    "filter": {
                        "op": "and",
                        "operands": [
                            {"op": "equal", "property": "layer", "value": "technical"},
                            {"op": "contains_any", "property": "tags", "value": ["governance"]},
                        ],
                    },
                },
                {
                    "intent": "any FK-2x doc",
                    "filter": {"op": "like", "property": "doc_id", "value": "FK-2*"},
                },
                {
                    "intent": "domain or formal, but not technical",
                    "filter": {
                        "op": "or",
                        "operands": [
                            {"op": "equal", "property": "layer", "value": "domain"},
                            {"op": "equal", "property": "layer", "value": "formal"},
                        ],
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
