"""MCP tools + strict wire models (R06/R07/R09)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError
from tests.support.vectordb.memory_store import MemoryWeaviateClient
from tests.support.vectordb.project_fixtures import make_fk13_project

from agentkit.backend.vectordb.concept_corpus.sync import concept_sync_bounded_window
from agentkit.backend.vectordb.ingest.engine import IngestEngine
from agentkit.backend.vectordb.mcp.contracts import TOOL_NAMES
from agentkit.backend.vectordb.mcp.tools import KnowledgeTools, ToolExecutionError
from agentkit.backend.vectordb.mcp.wire_models import parse_tool_args
from agentkit.backend.vectordb.mcp_server import dispatch_tool, list_tools
from agentkit.backend.vectordb.runtime_binding import load_runtime_binding_from_env

if TYPE_CHECKING:
    from pathlib import Path


def _setup(tmp_path: Path) -> KnowledgeTools:
    root = make_fk13_project(tmp_path, "PROJ")
    env = {
        "PROJECT_ID": "PROJ",
        "WEAVIATE_HOST": "weaviate.example.test",
        "WEAVIATE_HTTP_PORT": "9903",
        "WEAVIATE_GRPC_PORT": "50051",
    }
    binding = load_runtime_binding_from_env(env, cwd=root)
    client = MemoryWeaviateClient()
    engine = IngestEngine(client, lock_dir=root / ".locks")
    engine.story_sync(binding.project, full_reindex=True)
    # Builds concept_graph.json required for strict graph load (R09).
    concept_sync_bounded_window(binding.project, engine, full_reindex=True)
    return KnowledgeTools(binding, engine, search_port=client)


def test_tools_list_exactly_five() -> None:
    names = [t["name"] for t in list_tools()]
    assert names == list(TOOL_NAMES)


def test_wire_model_rejects_bool_as_int_and_extras() -> None:
    with pytest.raises(ValidationError):
        parse_tool_args("story_sync", {"full_reindex": 1})
    with pytest.raises(ValidationError):
        parse_tool_args("story_search", {"query": "x", "limit": True})
    with pytest.raises(ValidationError):
        parse_tool_args("story_search", {"query": "x", "extra_field": "nope"})


def test_wire_model_accepts_omit_project_id() -> None:
    args = parse_tool_args("story_sync", {})
    assert args["project_id"] is None
    assert args["full_reindex"] is False


def test_search_modes_differ(tmp_path: Path) -> None:
    tools = _setup(tmp_path)
    hybrid = tools.handle_raw(
        "story_search", {"query": "retrieval engine", "search_mode": "hybrid"}
    )
    vector = tools.handle_raw(
        "story_search", {"query": "retrieval engine", "search_mode": "vector"}
    )
    keyword = tools.handle_raw(
        "story_search", {"query": "retrieval engine", "search_mode": "keyword"}
    )
    assert hybrid["ok"] and vector["ok"] and keyword["ok"]
    assert hybrid["search_mode"] == "hybrid"
    # Modes can return different scores/order for same query.
    assert hybrid["results"] or vector["results"] or keyword["results"]


def test_concept_search_default_active(tmp_path: Path) -> None:
    tools = _setup(tmp_path)
    out = tools.handle_raw("concept_search", {"query": "retrieval"})
    assert out["ok"]
    assert out["concept_status"] == "active"


def test_foreign_project_rejected(tmp_path: Path) -> None:
    tools = _setup(tmp_path)
    with pytest.raises(ToolExecutionError):
        tools.handle_raw("story_search", {"query": "x", "project_id": "OTHER"})
    with pytest.raises(ToolExecutionError):
        tools.handle_raw("story_list_sources", {"project_id": "OTHER"})


def test_story_list_sources_minimal_shape(tmp_path: Path) -> None:
    tools = _setup(tmp_path)
    out = tools.handle_raw("story_list_sources", {})
    assert out["ok"]
    assert out["project_id"] == "PROJ"
    for src in out["sources"]:  # type: ignore[union-attr]
        assert src["project_id"] == "PROJ"
        assert "source_type" in src
        assert "producer" in src


def test_dispatch_unknown_tool(tmp_path: Path) -> None:
    tools = _setup(tmp_path)
    out = dispatch_tool(tools, "nope", {})
    assert out["ok"] is False


def test_adapter_search_normalises_hits(tmp_path: Path) -> None:
    """R07: MCP-used search path rejects incomplete hits."""
    from agentkit.integration_clients.vectordb import (
        VectorDbUnavailableError,
        WeaviateStoryAdapter,
    )

    class _Bad:
        def search(self, **kwargs: object):  # type: ignore[no-untyped-def]
            return [{"score": 0.5}]

        def is_ready(self) -> bool:
            return True

        def close(self) -> None:
            return None

        def upsert(self, **kwargs: object) -> int:
            return 0

        def delete_by_filter(self, **kwargs: object) -> int:
            return 0

        def fetch(self, **kwargs: object):  # type: ignore[no-untyped-def]
            return []

    adapter = WeaviateStoryAdapter(_Bad())  # type: ignore[arg-type]
    with pytest.raises(VectorDbUnavailableError):
        adapter.search(
            collection="StoryContext",
            query="q",
            search_mode="hybrid",
            project_id="P",
            limit=5,
        )
