"""FK-13 story-knowledge-base MCP server (§13.4 / §13.9.5, Review 174-P0-2).

Exposes the five FK-13 tools over MCP (stdio). Tool NAMES, required params and
return fields are bound by :mod:`agentkit.backend.vectordb.contracts`. Every
argument is validated strictly (AC10); ``project_id`` is resolved against the
runtime binding (D2: omitted -> bound, divergent -> REJECTED). ``concept_search``
defaults to ``active`` and applies authority ranking. Weaviate outage is
fail-closed (§13.8).

The transport boundary (:class:`RetrievalPort`) is the ONLY place a fake is
permitted; all tool logic runs for real.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from agentkit.backend.vectordb.concept_corpus.graph import build_graph
from agentkit.backend.vectordb.concept_corpus.resolver import rank_hits
from agentkit.backend.vectordb.concept_corpus.validator import validate_corpus
from agentkit.backend.vectordb.contracts import (
    TOOL_CONTRACTS,
    TOOL_NAMES,
    ToolArgumentError,
    validate_bool,
    validate_concept_status,
    validate_search_args,
)
from agentkit.backend.vectordb.ingest.adapter import concept_chunks_to_objects
from agentkit.concepts.parser import discover_concept_files
from agentkit.integration_clients.vectordb.errors import VectorDbError

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from agentkit.backend.vectordb.runtime_binding import RuntimeBinding
    from agentkit.backend.vectordb.schema import StoryContextObject
    from agentkit.backend.vectordb.sync import SyncResult, SyncService


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


@dataclass
class McpToolService:
    """The five FK-13 tool handlers (real logic; transport at :class:`RetrievalPort`)."""

    binding: RuntimeBinding
    retrieval: RetrievalPort
    sync: SyncService
    concepts_dir: Path
    stories_dir: Path

    # ------------------------------------------------------------------ #
    # story_search
    # ------------------------------------------------------------------ #
    def story_search(self, args: Mapping[str, Any]) -> dict[str, Any]:
        validated = validate_search_args(self.binding, args)
        status = args.get("status")
        story_type = args.get("story_type")
        filters: dict[str, object] = {}
        if isinstance(status, str) and status:
            filters["status"] = status
        if isinstance(story_type, str) and story_type:
            filters["story_type"] = story_type
        hits = self.retrieval.search(
            project_id=validated["project_id"],
            source_type="story",
            query=validated["query"],
            search_mode=validated["search_mode"],
            limit=validated["limit"],
            filters=filters,
        )
        return {"project_id": validated["project_id"], "results": [dict(h) for h in hits]}

    # ------------------------------------------------------------------ #
    # story_list_sources (D1 shape)
    # ------------------------------------------------------------------ #
    def story_list_sources(self, args: Mapping[str, Any]) -> dict[str, Any]:
        from agentkit.backend.vectordb.contracts import resolve_project_id

        project_id = resolve_project_id(self.binding, args)
        sources = self.retrieval.list_sources(project_id=project_id)
        return {"project_id": project_id, "sources": [dict(s) for s in sources]}

    # ------------------------------------------------------------------ #
    # story_sync
    # ------------------------------------------------------------------ #
    def story_sync(self, args: Mapping[str, Any]) -> dict[str, Any]:
        from agentkit.backend.vectordb.contracts import resolve_project_id

        project_id = resolve_project_id(self.binding, args)
        full = validate_bool(args.get("full_reindex"), name="full_reindex")
        objects_by_source = self._discover_story_objects(project_id)
        results = self.sync.full_reindex(
            project_id=project_id,
            producer="story_sync",
            objects_by_source=objects_by_source,
            corpus_revision=self._story_revision(),
        ) if full else self._incremental_sync(project_id, objects_by_source, "story_sync")
        written = sum(r.written for r in results)
        deleted = sum(r.deleted for r in results)
        revision = results[0].corpus_revision if results else self._story_revision()
        return {
            "project_id": project_id,
            "synced_sources": len(objects_by_source),
            "written": written,
            "deleted": deleted,
            "corpus_revision": revision,
        }

    # ------------------------------------------------------------------ #
    # concept_search (default active, authority-ranked)
    # ------------------------------------------------------------------ #
    def concept_search(self, args: Mapping[str, Any]) -> dict[str, Any]:
        validated = validate_search_args(self.binding, args)
        concept_status = validate_concept_status(args.get("concept_status"))
        is_appendix = args.get("is_appendix")
        filters: dict[str, object] = {"concept_status": concept_status}
        if is_appendix is not None:
            filters["is_appendix"] = validate_bool(is_appendix, name="is_appendix")
        for key in ("concept_id", "module"):
            val = args.get(key)
            if isinstance(val, str) and val:
                filters[key] = val
        hits = self.retrieval.search(
            project_id=validated["project_id"],
            source_type="concept",
            query=validated["query"],
            search_mode=validated["search_mode"],
            limit=validated["limit"],
            filters=filters,
        )
        # Authority ranking in the app layer (FK-13 §13.9.11).
        discovery = discover_concept_files(self.concepts_dir)
        graph = build_graph(discovery)
        ranked = rank_hits(graph, hits, query_module=str(filters.get("module", "")))
        return {
            "project_id": validated["project_id"],
            "results": self._ranked_envelope(hits, ranked),
        }

    def _ranked_envelope(self, hits: Sequence[Mapping[str, object]], ranked: list[Any]) -> list[dict[str, Any]]:
        by_id = {str(h.get("concept_id")): dict(h) for h in hits}
        out: list[dict[str, Any]] = []
        for r in ranked:
            base = by_id.get(r.concept_id, {})
            base = {**base, "authority_score": r.authority_score, "rank_reasons": list(r.reasons)}
            out.append(base)
        return out

    # ------------------------------------------------------------------ #
    # concept_sync (validate is a hard precondition)
    # ------------------------------------------------------------------ #
    def concept_sync(self, args: Mapping[str, Any]) -> dict[str, Any]:
        from agentkit.backend.vectordb.contracts import resolve_project_id

        project_id = resolve_project_id(self.binding, args)
        full = validate_bool(args.get("full_reindex"), name="full_reindex")
        discovery = discover_concept_files(self.concepts_dir)
        # concept_validate is the hard sync precondition (FK-13 §13.9.5).
        report = validate_corpus(discovery)
        if report.has_errors:
            return {
                "project_id": project_id,
                "synced_sources": 0,
                "written": 0,
                "deleted": 0,
                "corpus_revision": discovery.corpus_revision,
                "error": "concept_validate_failed",
                "validation_errors": len(report.errors),
            }
        objects = concept_chunks_to_objects(project_id, discovery)
        by_source: dict[str, list[StoryContextObject]] = {}
        for obj in objects:
            by_source.setdefault(obj.properties["source_file"], []).append(obj)
        results = (
            self.sync.full_reindex(
                project_id=project_id,
                producer="concept_sync",
                objects_by_source=by_source,
                corpus_revision=discovery.corpus_revision,
            )
            if full
            else self._incremental_sync(project_id, by_source, "concept_sync")
        )
        written = sum(r.written for r in results)
        deleted = sum(r.deleted for r in results)
        revision = results[0].corpus_revision if results else discovery.corpus_revision
        return {
            "project_id": project_id,
            "synced_sources": len(by_source),
            "written": written,
            "deleted": deleted,
            "corpus_revision": revision,
        }

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def _incremental_sync(
        self,
        project_id: str,
        objects_by_source: Mapping[str, Sequence[StoryContextObject]],
        producer: str,
    ) -> list[SyncResult]:
        results: list[SyncResult] = []
        revision = self._story_revision() if producer == "story_sync" else self._concept_revision()
        for source_file, objs in objects_by_source.items():
            source_type = str(objs[0].properties["source_type"]) if objs else ""
            results.append(
                self.sync.sync_source(
                    project_id=project_id,
                    source_file=source_file,
                    source_type=source_type,
                    objects=objs,
                    corpus_revision=revision,
                )
            )
        return results

    def _discover_story_objects(self, project_id: str) -> dict[str, list[StoryContextObject]]:
        from agentkit.backend.vectordb.ingest.adapter import story_file_to_objects

        by_source: dict[str, list[StoryContextObject]] = {}
        if not self.stories_dir.is_dir():
            return by_source
        for path in sorted(self.stories_dir.rglob("story.md")):
            objs = story_file_to_objects(project_id, path)
            if objs:
                by_source[path.as_posix()] = objs
        return by_source

    def _story_revision(self) -> str:
        return discover_concept_files(self.concepts_dir).corpus_revision

    def _concept_revision(self) -> str:
        return discover_concept_files(self.concepts_dir).corpus_revision


def handle_tool_call(
    service: McpToolService, name: str, args: Mapping[str, Any]
) -> dict[str, Any]:
    """Dispatch a validated tool call; map transport outage to fail-closed error."""
    if name not in TOOL_NAMES:
        raise ToolArgumentError(f"unknown tool {name!r}")
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


def build_mcp_server(service: McpToolService) -> object:
    """Build a FastMCP server registering the five FK-13 tools (stdio transport).

    Returns the FastMCP server instance. Tool input schemas are bound to the
    contracts in :mod:`agentkit.backend.vectordb.contracts`.
    """
    from mcp.server.fastmcp import FastMCP  # noqa: PLC0415 (runtime dependency)

    server = FastMCP("story-knowledge-base")

    for contract in TOOL_CONTRACTS:
        _register_tool(server, service, contract)
    return server


def _register_tool(server: Any, service: McpToolService, contract: Any) -> None:
    """Register one tool on the FastMCP server (closure over the service)."""
    name = contract.name

    @server.tool(name=name, description=contract.description)  # type: ignore[untyped-decorator]  # FastMCP decorator (mcp SDK, untyped seam)
    async def _handler(**kwargs: object) -> dict[str, object]:
        return handle_tool_call(service, name, dict(kwargs))

    _handler.__name__ = name


__all__ = [
    "McpToolService",
    "RetrievalPort",
    "build_mcp_server",
    "handle_tool_call",
]
