"""MCP server tests: tools/list=5, search modes, envelopes, arg validation, D2 (AC7/8/10/11).

Fakes live ONLY at the RetrievalPort + CorpusStorePort (external boundaries).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.vectordb.contracts import (
    TOOL_NAMES,
    ToolArgumentError,
    validate_limit,
    validate_search_mode,
)
from agentkit.backend.vectordb.mcp_server import (
    McpToolService,
    build_mcp_server,
    handle_tool_call,
)
from agentkit.backend.vectordb.runtime_binding import RuntimeBinding
from agentkit.backend.vectordb.sync import SyncReceipt, SyncService

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path


@dataclass
class FakeRetrieval:
    """Fake at the RetrievalPort boundary."""

    hits: list[Mapping[str, object]] = field(default_factory=list)
    sources: list[Mapping[str, object]] = field(default_factory=list)
    raise_search: bool = False

    def search(self, **kwargs: object) -> Sequence[Mapping[str, object]]:
        if self.raise_search:
            from agentkit.integration_clients.vectordb.errors import VectorDbUnavailableError

            raise VectorDbUnavailableError("down")
        return self.hits

    def list_sources(self, *, project_id: str) -> Sequence[Mapping[str, object]]:
        return self.sources


@dataclass
class FakeStore:
    objects: dict[str, dict[str, object]] = field(default_factory=dict)
    receipts: dict[str, SyncReceipt] = field(default_factory=dict)

    def list_objects_for_source(self, *, project_id: str, source_file: str) -> Sequence[Mapping[str, object]]:
        return [
            {"uuid": uid, "source_file": o["source_file"], "source_type": o["source_type"],
             "project_id": o["project_id"]}
            for uid, o in self.objects.items()
            if o["project_id"] == project_id and o["source_file"] == source_file
        ]

    def list_objects_for_source_types(self, *, project_id: str, source_types: Sequence[str]) -> Sequence[Mapping[str, object]]:
        types = set(source_types)
        return [
            {"uuid": uid, "source_file": o["source_file"], "source_type": o["source_type"],
             "project_id": o["project_id"]}
            for uid, o in self.objects.items()
            if o["project_id"] == project_id and o["source_type"] in types
        ]

    def upsert_objects(self, *, objects: Sequence[object]) -> int:
        for obj in objects:
            d = dict(obj.properties)  # type: ignore[attr-defined]
            d["uuid"] = obj.uuid  # type: ignore[attr-defined]
            self.objects[obj.uuid] = d  # type: ignore[attr-defined]
        return len(objects)

    def delete_objects(self, *, uuids: Sequence[str]) -> int:
        n = 0
        for uid in uuids:
            if uid in self.objects:
                del self.objects[uid]
                n += 1
        return n

    def get_receipt(self, *, project_id: str, source_file: str) -> SyncReceipt | None:
        return self.receipts.get(f"{project_id}|{source_file}")

    def set_receipt(self, *, receipt: SyncReceipt) -> None:
        self.receipts[f"{receipt.project_id}|{receipt.source_file}"] = receipt


_ENV = {
    "PROJECT_ID": "acme",
    "WEAVIATE_HTTP_ENDPOINT": "http://weaviate.acme.local:8080",
}


def _binding() -> RuntimeBinding:
    return RuntimeBinding.from_env(_ENV, command="python", args=(), cwd="/srv")


_CONCEPT = dedent(
    """\
    ---
    concept_id: FK-13
    title: Retrieval
    module: vectordb
    status: active
    doc_kind: core
    authority_over:
      - scope: vectordb
    ---

    # 13 Retrieval

    ## Purpose

    Semantic search.
    """
)


def _service(tmp_path: Path, *, retrieval: FakeRetrieval | None = None) -> McpToolService:
    cdir = tmp_path / "concept" / "technical-design"
    cdir.mkdir(parents=True)
    (cdir / "13_retrieval.md").write_text(_CONCEPT, encoding="utf-8")
    (tmp_path / "stories").mkdir()
    return McpToolService(
        binding=_binding(),
        retrieval=retrieval or FakeRetrieval(),
        sync=SyncService(store=FakeStore()),
        concepts_dir=tmp_path / "concept",
        stories_dir=tmp_path / "stories",
    )


# --------------------------------------------------------------------------- #
# AC7: tools/list returns exactly the five tools
# --------------------------------------------------------------------------- #


def test_tool_names_are_exactly_five() -> None:
    assert set(TOOL_NAMES) == {
        "story_search",
        "story_list_sources",
        "story_sync",
        "concept_search",
        "concept_sync",
    }


@pytest.mark.asyncio
async def test_mcp_server_registers_exactly_five_tools(tmp_path: Path) -> None:
    service = _service(tmp_path)
    server = build_mcp_server(service)
    tools = await server.list_tools()  # type: ignore[attr-defined]
    names = sorted(t.name for t in tools)
    assert names == sorted(TOOL_NAMES)


# --------------------------------------------------------------------------- #
# AC10: strict argument validation
# --------------------------------------------------------------------------- #


def test_search_mode_strict() -> None:
    assert validate_search_mode(None) == "hybrid"
    assert validate_search_mode("vector") == "vector"
    with pytest.raises(ToolArgumentError):
        validate_search_mode("fuzzy")


def test_limit_rejects_bool_as_int() -> None:
    with pytest.raises(ToolArgumentError):
        validate_limit(True)
    with pytest.raises(ToolArgumentError):
        validate_limit(0)
    with pytest.raises(ToolArgumentError):
        validate_limit(101)
    assert validate_limit(None) == 10
    assert validate_limit(25) == 25


# --------------------------------------------------------------------------- #
# D2 / AC11: project_id resolution
# --------------------------------------------------------------------------- #


def test_story_search_omitted_project_uses_bound(tmp_path: Path) -> None:
    retrieval = FakeRetrieval(hits=[{"story_id": "S1", "title": "t", "score": 0.5}])
    service = _service(tmp_path, retrieval=retrieval)
    result = handle_tool_call(service, "story_search", {"query": "x"})
    assert result["project_id"] == "acme"


def test_story_search_divergent_project_rejected(tmp_path: Path) -> None:
    service = _service(tmp_path)
    with pytest.raises(ToolArgumentError, match="diverges"):
        handle_tool_call(service, "story_search", {"query": "x", "project_id": "other"})


def test_story_list_sources_divergent_project_rejected(tmp_path: Path) -> None:
    service = _service(tmp_path)
    with pytest.raises(ToolArgumentError, match="diverges"):
        handle_tool_call(service, "story_list_sources", {"project_id": "other"})


# --------------------------------------------------------------------------- #
# AC7: search modes differ / envelopes / fail-closed
# --------------------------------------------------------------------------- #


def test_concept_search_applies_authority_ranking_and_envelope(tmp_path: Path) -> None:
    retrieval = FakeRetrieval(
        hits=[{"concept_id": "FK-13", "title": "Retrieval", "module": "vectordb", "score": 0.5}]
    )
    service = _service(tmp_path, retrieval=retrieval)
    result = handle_tool_call(service, "concept_search", {"query": "retrieval"})
    assert result["project_id"] == "acme"
    assert result["results"]
    assert "authority_score" in result["results"][0]
    assert result["results"][0]["concept_id"] == "FK-13"


def test_weaviate_outage_is_fail_closed(tmp_path: Path) -> None:
    retrieval = FakeRetrieval(raise_search=True)
    service = _service(tmp_path, retrieval=retrieval)
    result = handle_tool_call(service, "story_search", {"query": "x"})
    assert result["error"] == "vectordb_unavailable"


# --------------------------------------------------------------------------- #
# concept_sync validate precondition + envelope
# --------------------------------------------------------------------------- #


def test_concept_sync_envelope_has_revision(tmp_path: Path) -> None:
    service = _service(tmp_path)
    result = handle_tool_call(service, "concept_sync", {"full_reindex": True})
    assert result["project_id"] == "acme"
    assert "corpus_revision" in result
    assert result["written"] >= 1


def test_concept_sync_blocks_on_invalid_corpus(tmp_path: Path) -> None:
    cdir = tmp_path / "concept" / "technical-design"
    cdir.mkdir(parents=True)
    (cdir / "broken.md").write_text("no frontmatter", encoding="utf-8")
    (tmp_path / "stories").mkdir()
    service = McpToolService(
        binding=_binding(),
        retrieval=FakeRetrieval(),
        sync=SyncService(store=FakeStore()),
        concepts_dir=tmp_path / "concept",
        stories_dir=tmp_path / "stories",
    )
    result = handle_tool_call(service, "concept_sync", {"full_reindex": True})
    assert result.get("error") == "concept_validate_failed"


def test_story_list_sources_envelope_shape(tmp_path: Path) -> None:
    retrieval = FakeRetrieval(
        sources=[{"project_id": "acme", "source_type": "story", "producer": "story_sync"}]
    )
    service = _service(tmp_path, retrieval=retrieval)
    result = handle_tool_call(service, "story_list_sources", {})
    assert result["project_id"] == "acme"
    assert result["sources"][0]["project_id"] == "acme"


def test_story_sync_incremental_envelope(tmp_path: Path) -> None:
    # story_dir is empty -> incremental sync of zero sources still returns envelope.
    service = _service(tmp_path)
    result = handle_tool_call(service, "story_sync", {"full_reindex": False})
    assert result["project_id"] == "acme"
    assert "corpus_revision" in result


def test_unknown_tool_rejected(tmp_path: Path) -> None:
    service = _service(tmp_path)
    with pytest.raises(ToolArgumentError, match="unknown tool"):
        handle_tool_call(service, "bogus_tool", {})


def test_search_missing_query_rejected(tmp_path: Path) -> None:
    service = _service(tmp_path)
    with pytest.raises(ToolArgumentError, match="query"):
        handle_tool_call(service, "story_search", {})
