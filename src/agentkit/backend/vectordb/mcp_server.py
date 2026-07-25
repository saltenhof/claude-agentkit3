"""FK-13 story-knowledge-base MCP server (§13.4 / §13.9.5, Review 174-P0-2).

Exposes the five FK-13 tools over MCP (stdio, FastMCP per FK-13 §13.2). Tool
NAMES, parameters, the ADVERTISED input schema and the return fields are bound by
:mod:`agentkit.backend.vectordb.contracts`.

The transport layer hands the RAW argument mapping to :func:`handle_tool_call`
(R13): FastMCP's typed-parameter reconstruction would collapse "key absent" and
"key explicitly null" into the same value, so the tool surface is declared from
the contract SSOT and dispatched with the arguments as they arrived. Every
argument is then validated strictly (AC10); ``project_id`` is resolved against
the runtime binding (D2: omitted -> bound, divergent -> REJECTED).
``concept_search`` defaults to ``active`` and applies authority ranking.
Weaviate outage is fail-closed (§13.8).

The transport boundary (:class:`RetrievalPort`) is the ONLY place a fake is
permitted; all tool logic runs for real.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from agentkit.backend.vectordb.concept_corpus.graph import build_graph
from agentkit.backend.vectordb.concept_corpus.resolver import derive_query_detail, rank_hits
from agentkit.backend.vectordb.concept_corpus.validator import validate_corpus
from agentkit.backend.vectordb.contracts import (
    TOOL_CONTRACTS,
    TOOL_NAMES,
    ToolArgumentError,
    optional_str,
    reject_unknown_args,
    resolve_project_id,
    validate_bool,
    validate_concept_filters,
    validate_search_args,
    validate_story_filters,
)
from agentkit.backend.vectordb.ingest.adapter import (
    concept_chunks_to_objects,
    story_file_to_objects,
)
from agentkit.backend.vectordb.ingest.classify import classify_source_file
from agentkit.concepts.frontmatter import FrontmatterError, read_text_strict
from agentkit.concepts.hashing import corpus_revision, document_hash
from agentkit.concepts.parser import discover_concept_files
from agentkit.integration_clients.vectordb.errors import VectorDbError

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from agentkit.backend.vectordb.concept_corpus.resolver import RankedHit
    from agentkit.backend.vectordb.runtime_binding import RuntimeBinding
    from agentkit.backend.vectordb.schema import StoryContextObject
    from agentkit.backend.vectordb.sync import SyncService


@runtime_checkable
class RetrievalPort(Protocol):
    """External retrieval boundary (Weaviate adapter; fakes permitted here)."""

    def search(
        self,
        *,
        project_id: str,
        source_type: str,
        query: str,
        search_mode: str,
        limit: int,
        filters: Mapping[str, object],
    ) -> Sequence[Mapping[str, object]]:
        """Return raw hit mappings (already project-scoped)."""
        ...

    def list_sources(self, *, project_id: str) -> Sequence[Mapping[str, object]]:
        """Return indexed source-type summaries (D1 shape)."""
        ...


@dataclass(frozen=True)
class StoryCorpus:
    """The discovered story/research corpus of one project.

    Attributes:
        objects_by_source: Project-relative source path -> its chunk objects.
        corpus_revision: Revision of the STORY corpus (FK-13 §13.9.9 freshness
            indicator). Derived from the story/research documents only -- it is
            deliberately NOT the concept-corpus digest (N04/D1).
    """

    objects_by_source: dict[str, list[StoryContextObject]]
    corpus_revision: str


@dataclass
class McpToolService:
    """The five FK-13 tool handlers (real logic; transport at :class:`RetrievalPort`)."""

    binding: RuntimeBinding
    retrieval: RetrievalPort
    sync: SyncService
    concepts_dir: Path
    stories_dir: Path
    #: Authority scope the ranking rules 1/2 evaluate against (N23). FK-13 §13.9.5
    #: defines NO scope parameter for ``concept_search``, so this stays empty in
    #: production until such an input is ratified; it is a field (not a derived
    #: value) so the split from ``module`` is explicit and testable.
    query_authority_scope: str = ""

    # ------------------------------------------------------------------ #
    # story_search
    # ------------------------------------------------------------------ #
    def story_search(self, args: Mapping[str, Any]) -> dict[str, Any]:
        """Search stories AND research, globally ranked and limited (R05/N09)."""
        validated = validate_search_args(self.binding, args)
        filters = validate_story_filters(args)
        limit = int(validated["limit"])
        # R05: both owned source types are queried, each with a BOUNDED candidate
        # set. N09: the candidates are then merged in GLOBAL score order and
        # truncated to the requested limit -- never concatenated per source type
        # (which returned up to 2x limit hits, all story before research).
        candidates: list[Mapping[str, object]] = []
        for source_type in ("story", "research"):
            candidates.extend(
                self.retrieval.search(
                    project_id=validated["project_id"],
                    source_type=source_type,
                    query=validated["query"],
                    search_mode=validated["search_mode"],
                    limit=limit,
                    filters=filters,
                )
            )
        ranked = sorted(candidates, key=_score_order)[:limit]
        return {
            "project_id": validated["project_id"],
            "results": [dict(hit) for hit in ranked],
        }

    # ------------------------------------------------------------------ #
    # story_list_sources (D1 shape)
    # ------------------------------------------------------------------ #
    def story_list_sources(self, args: Mapping[str, Any]) -> dict[str, Any]:
        """List the indexed source types of the bound project (D1 shape)."""
        project_id = resolve_project_id(self.binding, args)
        sources = self.retrieval.list_sources(project_id=project_id)
        return {"project_id": project_id, "sources": [dict(s) for s in sources]}

    # ------------------------------------------------------------------ #
    # story_sync
    # ------------------------------------------------------------------ #
    def story_sync(self, args: Mapping[str, Any]) -> dict[str, Any]:
        """Index story + research sources (incremental or full reindex)."""
        project_id = resolve_project_id(self.binding, args)
        full = validate_bool(args, name="full_reindex")
        try:
            corpus = self._discover_story_corpus(project_id)
        except (FrontmatterError, ValueError) as exc:
            # AC10: an invalid source is a named, zero-write failure -- never a
            # silent partial index of the parsable subset.
            return _sync_error_envelope(project_id, "story_source_invalid", str(exc))
        results = (
            self.sync.full_reindex(
                project_id=project_id,
                producer="story_sync",
                objects_by_source=corpus.objects_by_source,
                corpus_revision=corpus.corpus_revision,
            )
            if full
            else self.sync.reconcile_sources(
                project_id=project_id,
                producer="story_sync",
                objects_by_source=corpus.objects_by_source,
                corpus_revision=corpus.corpus_revision,
            )
        )
        return {
            "project_id": project_id,
            "synced_sources": len(corpus.objects_by_source),
            "written": sum(r.written for r in results),
            "deleted": sum(r.deleted for r in results),
            "corpus_revision": corpus.corpus_revision,
        }

    # ------------------------------------------------------------------ #
    # concept_search (default active, authority-ranked)
    # ------------------------------------------------------------------ #
    def concept_search(self, args: Mapping[str, Any]) -> dict[str, Any]:
        """Search concept chunks, authority-ranked (FK-13 §13.9.11)."""
        validated = validate_search_args(self.binding, args)
        filters = validate_concept_filters(args)
        hits = self.retrieval.search(
            project_id=validated["project_id"],
            source_type="concept",
            query=validated["query"],
            search_mode=validated["search_mode"],
            limit=int(validated["limit"]),
            filters=filters,
        )
        # Authority ranking in the app layer (FK-13 §13.9.11).
        #
        # ``module`` is the FK-13 §13.9.5 module filter and is passed ONLY as the
        # query module (rule 5). It is NOT reused as the authority scope: FK-13
        # models ``module`` and ``authority_over`` scopes separately, and §13.9.5
        # defines no scope parameter for ``concept_search`` (N23). The scope input
        # therefore stays EXPLICIT and unpopulated until a scope parameter is
        # ratified -- rules 1/2 are inert rather than wrong.
        discovery = discover_concept_files(self.concepts_dir)
        graph = build_graph(discovery)
        ranked = rank_hits(
            graph,
            hits,
            query_authority_scope=self.query_authority_scope,
            query_module=str(filters.get("module", "")),
            query_detail=derive_query_detail(str(validated["query"])),
        )
        return {
            "project_id": validated["project_id"],
            "results": _ranked_envelope(hits, ranked),
        }

    # ------------------------------------------------------------------ #
    # concept_sync (validate is a hard precondition)
    # ------------------------------------------------------------------ #
    def concept_sync(self, args: Mapping[str, Any]) -> dict[str, Any]:
        """Index concept sources; ``concept_validate`` is a hard precondition.

        ``concept_path`` (FK-13 §13.9.5) restricts the sync to ONE discovered
        concept document; it is never ignored. Combining it with ``full_reindex``
        is rejected -- a full reindex deletes every concept chunk of the project,
        so re-writing only one document would drop the rest.
        """
        project_id = resolve_project_id(self.binding, args)
        full = validate_bool(args, name="full_reindex")
        concept_path = optional_str(args, "concept_path")
        if concept_path is not None and full:
            return _sync_error_envelope(
                project_id,
                "concept_path_with_full_reindex",
                "concept_path selects a single document while full_reindex rebuilds "
                "the whole project corpus; the combination is rejected (fail-closed).",
            )
        discovery = discover_concept_files(self.concepts_dir)
        # concept_validate is the hard sync precondition (FK-13 §13.9.5).
        report = validate_corpus(discovery)
        if report.has_errors:
            envelope = _sync_error_envelope(
                project_id,
                "concept_validate_failed",
                f"{len(report.errors)} blocking finding(s); the corpus is not indexed.",
                corpus_revision=discovery.corpus_revision,
            )
            envelope["validation_errors"] = len(report.errors)
            return envelope
        objects = concept_chunks_to_objects(project_id, discovery)
        by_source: dict[str, list[StoryContextObject]] = {}
        for obj in objects:
            by_source.setdefault(str(obj.properties["source_file"]), []).append(obj)
        if concept_path is not None:
            return self._sync_single_concept(
                project_id, concept_path, by_source, discovery.corpus_revision
            )
        results = (
            self.sync.full_reindex(
                project_id=project_id,
                producer="concept_sync",
                objects_by_source=by_source,
                corpus_revision=discovery.corpus_revision,
            )
            if full
            else self.sync.reconcile_sources(
                project_id=project_id,
                producer="concept_sync",
                objects_by_source=by_source,
                corpus_revision=discovery.corpus_revision,
            )
        )
        return {
            "project_id": project_id,
            "synced_sources": len(by_source),
            "written": sum(r.written for r in results),
            "deleted": sum(r.deleted for r in results),
            "corpus_revision": discovery.corpus_revision,
        }

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def _sync_single_concept(
        self,
        project_id: str,
        concept_path: str,
        by_source: Mapping[str, list[StoryContextObject]],
        revision: str,
    ) -> dict[str, Any]:
        """Sync exactly ONE discovered concept document (FK-13 §13.9.5).

        Only the selected source goes through the bounded window; no vanished-
        source reconcile runs, because a single-document sync says nothing about
        the rest of the corpus. An unknown path is a named, zero-write error.
        """
        normalised = concept_path.replace("\\", "/").removeprefix("./")
        if normalised not in by_source:
            return _sync_error_envelope(
                project_id,
                "concept_path_unknown",
                f"{concept_path!r} is not a discovered concept source "
                f"(known: {len(by_source)} source(s)); fail-closed.",
                corpus_revision=revision,
            )
        objects = by_source[normalised]
        result = self.sync.sync_source(
            project_id=project_id,
            source_file=normalised,
            source_type=str(objects[0].properties["source_type"]),
            objects=objects,
            corpus_revision=revision,
        )
        return {
            "project_id": project_id,
            "synced_sources": 1,
            "written": result.written,
            "deleted": result.deleted,
            "corpus_revision": revision,
        }

    def _discover_story_corpus(self, project_id: str) -> StoryCorpus:
        """Discover story AND research sources via the canonical classifier (R05).

        Walks the project root, classifies each ``.md`` via
        :func:`classify_source_file` (POSITIVE canonical-path recognition), and
        ingests every ``story``/``research`` source with its PROJECT-RELATIVE path
        (R04: the relative path is what the content hash and the deterministic
        identity are derived from). ``review*.md`` / closure artefacts are
        negative cases (never ingested).

        The story ``corpus_revision`` is computed from the discovered story
        documents themselves (N04) -- it is NOT the concept-corpus digest.
        """
        root = Path(self.binding.spec.cwd)
        if not root.is_dir():
            return StoryCorpus(objects_by_source={}, corpus_revision=corpus_revision([]))
        by_source: dict[str, list[StoryContextObject]] = {}
        file_hashes: list[str] = []
        for path in sorted(root.rglob("*.md")):
            try:
                rel = path.relative_to(root).as_posix()
            except ValueError:  # pragma: no cover -- rglob yields contained paths
                continue
            source_type = classify_source_file(rel)
            if source_type not in ("story", "research"):
                continue
            file_hashes.append(document_hash(read_text_strict(path)))
            objects = story_file_to_objects(
                project_id, path, source_file=rel, source_type=source_type
            )
            if objects:
                by_source[rel] = objects
        return StoryCorpus(
            objects_by_source=by_source, corpus_revision=corpus_revision(file_hashes)
        )


def _sync_error_envelope(
    project_id: str, code: str, detail: str, *, corpus_revision: str = ""
) -> dict[str, Any]:
    """Return a COMPLETE zero-write sync error envelope (no silent partial)."""
    return {
        "project_id": project_id,
        "synced_sources": 0,
        "written": 0,
        "deleted": 0,
        "corpus_revision": corpus_revision,
        "error": code,
        "detail": detail,
    }


def _score_order(hit: Mapping[str, object]) -> tuple[float, str, str, str]:
    """Global ranking key: score DESC, then a deterministic identity tie-break."""
    raw = hit.get("score")
    score = float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else 0.0
    return (
        -score,
        str(hit.get("source_file", "")),
        str(hit.get("section_number", "")),
        str(hit.get("section_heading", "")),
    )


def _ranked_envelope(
    hits: Sequence[Mapping[str, object]], ranked: Sequence[RankedHit]
) -> list[dict[str, Any]]:
    """Project ranked hits back onto their ORIGINAL hit records (N10).

    The ranking carries a per-hit index, so multiple section hits of the SAME
    concept stay distinct; mapping by ``concept_id`` collapsed them and silently
    dropped results.
    """
    out: list[dict[str, Any]] = []
    for entry in ranked:
        base = dict(hits[entry.hit_index])
        base["authority_score"] = entry.authority_score
        base["rank_reasons"] = list(entry.reasons)
        out.append(base)
    return out


def handle_tool_call(
    service: McpToolService, name: str, args: Mapping[str, Any]
) -> dict[str, Any]:
    """Dispatch a validated tool call; map transport outage to fail-closed error.

    ``args`` is the RAW MCP argument mapping (R13): the strict validators need to
    see whether a key was absent or explicitly ``null``.
    """
    if name not in TOOL_NAMES:
        raise ToolArgumentError(f"unknown tool {name!r}")
    reject_unknown_args(name, args)  # R13: reject unknown keys before dispatch
    handler = {
        "story_search": service.story_search,
        "story_list_sources": service.story_list_sources,
        "story_sync": service.story_sync,
        "concept_search": service.concept_search,
        "concept_sync": service.concept_sync,
    }[name]
    try:
        return handler(args)
    except VectorDbError as exc:
        # Weaviate outage -> fail-closed error envelope (§13.8), never silent.
        return {"error": "vectordb_unavailable", "detail": str(exc)}


def build_mcp_server(service: McpToolService) -> Any:
    """Build the FastMCP server exposing the five FK-13 tools over stdio.

    The tool surface is declared from :data:`TOOL_CONTRACTS` and dispatched with
    the RAW arguments (see module docstring, R01/R13).
    """
    from mcp.server.fastmcp import FastMCP  # noqa: PLC0415 (runtime dependency)
    from mcp.types import Tool  # noqa: PLC0415 (runtime dependency)

    class StoryKnowledgeBaseServer(FastMCP):
        """FastMCP server whose tool surface comes from the contract SSOT.

        ``list_tools`` / ``call_tool`` are the public surface FastMCP itself binds
        into the MCP protocol handlers, so overriding them keeps the real stdio
        transport on exactly the path the tests exercise.
        """

        async def list_tools(self) -> list[Tool]:
            """Advertise the five FK-13 tools with their real input schema."""
            return [
                Tool(
                    name=contract.name,
                    description=contract.description,
                    inputSchema=contract.input_schema(),
                )
                for contract in TOOL_CONTRACTS
            ]

        async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            """Dispatch a tool call with the arguments EXACTLY as received."""
            return handle_tool_call(service, name, arguments)

    return StoryKnowledgeBaseServer("story-knowledge-base")


__all__ = [
    "McpToolService",
    "RetrievalPort",
    "StoryCorpus",
    "build_mcp_server",
    "handle_tool_call",
]
