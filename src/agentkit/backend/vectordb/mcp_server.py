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
    TOOL_NAMES,
    ToolArgumentError,
    reject_unknown_args,
    validate_bool,
    validate_concept_filters,
    validate_search_args,
    validate_story_filters,
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
        filters = validate_story_filters(args)
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
        objects_by_source = self._discover_story_corpus_objects(project_id)
        revision = self._story_revision()
        results = (
            self.sync.full_reindex(
                project_id=project_id,
                producer="story_sync",
                objects_by_source=objects_by_source,
                corpus_revision=revision,
            )
            if full
            else self.sync.reconcile_sources(
                project_id=project_id,
                producer="story_sync",
                objects_by_source=objects_by_source,
                corpus_revision=revision,
            )
        )
        written = sum(r.written for r in results)
        deleted = sum(r.deleted for r in results)
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
        filters = validate_concept_filters(args)
        hits = self.retrieval.search(
            project_id=validated["project_id"],
            source_type="concept",
            query=validated["query"],
            search_mode=validated["search_mode"],
            limit=validated["limit"],
            filters=filters,
        )
        # Authority ranking in the app layer (FK-13 §13.9.11) against the query
        # scope/module/detail (R10).
        discovery = discover_concept_files(self.concepts_dir)
        graph = build_graph(discovery)
        ranked = rank_hits(
            graph,
            hits,
            query_scope=str(filters.get("module", "")),
            query_module=str(filters.get("module", "")),
            query_detail="",
        )
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

    def _discover_story_corpus_objects(self, project_id: str) -> dict[str, list[StoryContextObject]]:
        """Discover story AND research sources via the canonical classifier (R05).

        Walks the project root, classifies each ``.md`` via
        :func:`classify_source_file` (POSITIVE canonical-path recognition), and
        ingests every ``story``/``research`` source with PROJECT-RELATIVE paths.
        ``review*.md`` / closure artefacts are negative cases (never ingested).
        """
        from pathlib import Path

        from agentkit.backend.vectordb.ingest.adapter import story_file_to_objects
        from agentkit.backend.vectordb.ingest.classify import classify_source_file

        root = self.binding.spec.cwd
        root_path = Path(root)
        if not root_path.is_dir():
            return {}
        by_source: dict[str, list[StoryContextObject]] = {}
        for path in sorted(root_path.rglob("*.md")):
            try:
                rel = path.relative_to(root_path).as_posix()
            except ValueError:
                continue
            source_type = classify_source_file(rel)
            if source_type not in ("story", "research"):
                continue
            objs = story_file_to_objects(project_id, path)
            # Force the classified source_type (research vs story) + relative path.
            for obj in objs:
                obj.properties["source_type"] = source_type
                obj.properties["source_file"] = rel
            if objs:
                by_source[rel] = objs
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


def build_mcp_server(service: McpToolService) -> object:
    """Build a FastMCP server registering the five FK-13 tools (stdio transport).

    Each tool is registered with EXPLICITLY TYPED parameters (R01) so FastMCP
    advertises the real FK-13 input schema per tool (not a generic ``kwargs``
    property). The handler validates the collected args strictly via
    :mod:`contracts` before dispatching.
    """
    from mcp.server.fastmcp import FastMCP  # noqa: PLC0415 (runtime dependency)

    server = FastMCP("story-knowledge-base")
    _register_story_search(server, service)
    _register_story_list_sources(server, service)
    _register_story_sync(server, service)
    _register_concept_search(server, service)
    _register_concept_sync(server, service)
    return server


def _collect(**kwargs: object) -> dict[str, object]:
    """Drop ``None`` optionals so validators see omitted-as-absent (R01)."""
    return {k: v for k, v in kwargs.items() if v is not None}


def _register_story_search(server: Any, service: McpToolService) -> None:
    @server.tool(name="story_search", description="Semantic search over stories and research.")  # type: ignore[untyped-decorator]  # FastMCP (mcp SDK)
    async def story_search(  # noqa: ANN202
        query: str,
        search_mode: str | None = None,
        project_id: str | None = None,
        status: str | None = None,
        story_type: str | None = None,
        limit: int | None = None,
    ) -> dict[str, object]:
        return handle_tool_call(service, "story_search", _collect(**locals()))

    story_search.__name__ = "story_search"


def _register_story_list_sources(server: Any, service: McpToolService) -> None:
    @server.tool(name="story_list_sources", description="List indexed source types and producers.")  # type: ignore[untyped-decorator]
    async def story_list_sources(project_id: str | None = None) -> dict[str, object]:  # noqa: ANN202
        return handle_tool_call(service, "story_list_sources", _collect(**locals()))

    story_list_sources.__name__ = "story_list_sources"


def _register_story_sync(server: Any, service: McpToolService) -> None:
    @server.tool(name="story_sync", description="Incremental/full index of story and research sources.")  # type: ignore[untyped-decorator]
    async def story_sync(project_id: str | None = None, full_reindex: bool | None = None) -> dict[str, object]:  # noqa: ANN202
        return handle_tool_call(service, "story_sync", _collect(**locals()))

    story_sync.__name__ = "story_sync"


def _register_concept_search(server: Any, service: McpToolService) -> None:
    @server.tool(name="concept_search", description="Semantic search over concepts (default active, authority-ranked).")  # type: ignore[untyped-decorator]
    async def concept_search(  # noqa: ANN202
        query: str,
        search_mode: str | None = None,
        project_id: str | None = None,
        concept_id: str | None = None,
        module: str | None = None,
        is_appendix: bool | None = None,
        concept_status: str | None = None,
        limit: int | None = None,
    ) -> dict[str, object]:
        return handle_tool_call(service, "concept_search", _collect(**locals()))

    concept_search.__name__ = "concept_search"


def _register_concept_sync(server: Any, service: McpToolService) -> None:
    @server.tool(name="concept_sync", description="Incremental/full index of concepts (validate is a precondition).")  # type: ignore[untyped-decorator]
    async def concept_sync(  # noqa: ANN202
        project_id: str | None = None,
        full_reindex: bool | None = None,
        concept_path: str | None = None,
    ) -> dict[str, object]:
        return handle_tool_call(service, "concept_sync", _collect(**locals()))

    concept_sync.__name__ = "concept_sync"


__all__ = [
    "McpToolService",
    "RetrievalPort",
    "build_mcp_server",
    "handle_tool_call",
]
