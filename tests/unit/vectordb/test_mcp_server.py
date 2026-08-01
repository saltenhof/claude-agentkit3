"""MCP surface tests: advertised schema, REAL calls for all five tools, envelopes.

R01: the advertised ``inputSchema`` of every tool is asserted against the FK-13
contract (§13.4.1 / §13.9.5) AND every one of the five tools is invoked through
the server's real ``call_tool`` path -- the same public surface FastMCP binds into
the MCP protocol handlers. The only double is the Weaviate CLIENT boundary, so
the whole tool stack (validators, sync, retrieval, ranking) runs productively.
"""

from __future__ import annotations

from textwrap import dedent
from typing import TYPE_CHECKING, Any

import pytest
from tests.unit.vectordb.corpus_doubles import (
    RecordingWeaviateClient,
    concept_hit,
    corpus_store,
    story_hit,
)

from agentkit.backend.vectordb.contracts import (
    CONCEPT_STATUSES,
    DEFAULT_LIMIT,
    MAX_LIMIT,
    TOOL_CONTRACTS,
    TOOL_NAMES,
    ToolArgumentError,
    contract_for,
    validate_bool,
    validate_limit,
    validate_search_mode,
)
from agentkit.backend.vectordb.mcp_server import (
    McpToolService,
    build_mcp_server,
    handle_tool_call,
)
from agentkit.backend.vectordb.retrieval import WeaviateRetrievalPort
from agentkit.backend.vectordb.runtime_binding import RuntimeBinding
from agentkit.backend.vectordb.sync import SyncService
from agentkit.integration_clients.vectordb.weaviate_adapter import SEARCH_MODES

if TYPE_CHECKING:
    from pathlib import Path

_ENV = {
    "PROJECT_ID": "acme",
    "WEAVIATE_HTTP_ENDPOINT": "http://weaviate.acme.local:8080",
    "WEAVIATE_GRPC_ENDPOINT": "weaviate.acme.local:50051",
}

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

_STORY = dedent(
    """\
    ---
    story_id: AG3-1
    title: Real title
    status: Done
    story_type: implementation
    ---

    # Real title

    ## Problem

    Need.
    """
)


def _service(
    tmp_path: Path, client: RecordingWeaviateClient | None = None
) -> tuple[McpToolService, RecordingWeaviateClient]:
    client = client or RecordingWeaviateClient()
    cdir = tmp_path / "concept" / "technical-design"
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "13_retrieval.md").write_text(_CONCEPT, encoding="utf-8")
    story = tmp_path / "stories" / "AG3-1" / "story.md"
    story.parent.mkdir(parents=True, exist_ok=True)
    story.write_text(_STORY, encoding="utf-8")
    binding = RuntimeBinding.from_env(_ENV, command="python", args=(), cwd=str(tmp_path))
    store = corpus_store(client)
    service = McpToolService(
        binding=binding,
        retrieval=WeaviateRetrievalPort(client=client, store=store, binding=binding),  # type: ignore[arg-type]
        sync=SyncService(store=store),
        concepts_dir=tmp_path / "concept",
        stories_dir=tmp_path / "stories",
    )
    return service, client


# --------------------------------------------------------------------------- #
# AC7/AC8/R01: the ADVERTISED tool surface is the FK-13 contract
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
async def test_r01_every_tool_advertises_its_real_input_schema(tmp_path: Path) -> None:
    service, _client = _service(tmp_path)
    server = build_mcp_server(service)
    tools = {t.name: t for t in await server.list_tools()}
    assert sorted(tools) == sorted(TOOL_NAMES)
    for contract in TOOL_CONTRACTS:
        schema = tools[contract.name].inputSchema
        assert schema["type"] == "object"
        # No generic 'kwargs' catch-all: the advertised properties ARE the FK-13
        # parameters, and unknown keys are refused by the schema itself.
        assert set(schema["properties"]) == {p.name for p in contract.params}
        assert schema["required"] == list(contract.required_params)
        assert schema["additionalProperties"] is False
        for param in contract.params:
            advertised = schema["properties"][param.name]
            assert advertised["type"] == param.json_type
            if param.enum:
                assert advertised["enum"] == list(param.enum)
    # Spot-check the FK-13 §13.4.1 / §13.9.5 parameter tables themselves.
    assert tools["story_search"].inputSchema["required"] == ["query"]
    story_props = tools["story_search"].inputSchema["properties"]
    assert set(story_props) == {
        "query", "search_mode", "project_id", "status", "story_type", "limit"
    }
    assert story_props["limit"]["type"] == "integer"
    assert story_props["search_mode"]["enum"] == list(SEARCH_MODES)
    concept_props = tools["concept_search"].inputSchema["properties"]
    assert set(concept_props) == {
        "query", "search_mode", "project_id", "concept_id", "module",
        "authority_scope", "is_appendix", "concept_status", "limit",
    }
    assert concept_props["authority_scope"]["type"] == "string"
    assert concept_props["is_appendix"]["type"] == "boolean"
    # D8: the status filter is advertised as a SET (enum on the item schema).
    assert concept_props["concept_status"]["type"] == "array"
    assert concept_props["concept_status"]["items"]["enum"] == list(CONCEPT_STATUSES)
    assert concept_props["concept_status"]["minItems"] == 1
    assert concept_props["concept_status"]["uniqueItems"] is True
    assert set(tools["concept_sync"].inputSchema["properties"]) == {
        "project_id", "full_reindex", "concept_path"
    }


@pytest.mark.asyncio
async def test_r01_all_five_tools_run_through_a_real_call_tool(tmp_path: Path) -> None:
    """Every tool is dispatched for real; each observable effect is asserted."""
    service, client = _service(tmp_path)
    client.search_results = [
        concept_hit("c1", "FK-13", 0.9),
        story_hit("s1", "AG3-1", 0.8),
    ]
    server = build_mcp_server(service)

    concept_search = await server.call_tool("concept_search", {"query": "retrieval"})
    assert concept_search["results"][0]["concept_id"] == "FK-13"
    assert client.search_calls[-1]["source_type"] == "concept"

    story_search = await server.call_tool("story_search", {"query": "need", "limit": 5})
    assert story_search["results"][0]["story_id"] == "AG3-1"
    assert sorted(str(c["source_type"]) for c in client.search_calls[-2:]) == [
        "research", "story"
    ]

    concept_sync = await server.call_tool("concept_sync", {"full_reindex": True})
    assert concept_sync["written"] >= 1
    assert concept_sync["corpus_revision"]

    story_sync = await server.call_tool("story_sync", {"full_reindex": True})
    assert story_sync["written"] >= 1
    assert story_sync["corpus_revision"] != concept_sync["corpus_revision"]

    listed = await server.call_tool("story_list_sources", {})
    by_type = {s["source_type"]: s for s in listed["sources"]}
    assert by_type["concept"]["chunk_count"] >= 1
    assert by_type["story"]["chunk_count"] >= 1
    assert by_type["story"]["producer"] == "story_sync"
    assert by_type["concept"]["last_revision"] == concept_sync["corpus_revision"]
    assert by_type["story"]["last_revision"] == story_sync["corpus_revision"]


@pytest.mark.asyncio
async def test_r01_call_tool_rejects_an_unknown_argument(tmp_path: Path) -> None:
    service, _client = _service(tmp_path)
    server = build_mcp_server(service)
    with pytest.raises(ToolArgumentError, match="unknown argument"):
        await server.call_tool("story_search", {"query": "x", "bogus": 1})


@pytest.mark.asyncio
async def test_r01_call_tool_preserves_an_explicit_null(tmp_path: Path) -> None:
    """The transport must NOT collapse an explicit null into the default (R13)."""
    service, _client = _service(tmp_path)
    server = build_mcp_server(service)
    with pytest.raises(ToolArgumentError, match="limit"):
        await server.call_tool("story_search", {"query": "x", "limit": None})


def test_return_fields_are_bound_to_the_fk13_tables() -> None:
    assert set(contract_for("story_search").return_fields) >= {
        "story_id", "title", "status", "story_type", "source_type", "module",
        "epic", "section_heading", "score", "snippet",
    }
    assert set(contract_for("concept_search").return_fields) >= {
        "concept_id", "title", "module", "section_heading", "section_number",
        "is_appendix", "parent_concept_id", "defers_to", "authority_over",
        "normative_rules", "concept_status", "score", "snippet",
    }
    # D1 fixed a MINIMAL shape, so the set may grow but never shrink: the minimum is
    # asserted as a subset, and the CURRENT shape exactly -- extension stays deliberate.
    d1_minimum = {
        "project_id", "source_type", "producer", "source_count",
        "chunk_count", "last_revision",
    }
    assert d1_minimum <= set(contract_for("story_list_sources").return_fields)
    assert set(contract_for("story_list_sources").return_fields) == {
        *d1_minimum,
        # AG3-177: the ratified residual must be detectable where callers look.
        "stale_chunk_count",
    }


# --------------------------------------------------------------------------- #
# AC10: strict argument validation with ABSENCE semantics (R13)
# --------------------------------------------------------------------------- #


def test_search_mode_absent_defaults_present_is_strict() -> None:
    assert validate_search_mode({}) == "hybrid"
    assert validate_search_mode({"search_mode": "vector"}) == "vector"
    with pytest.raises(ToolArgumentError):
        validate_search_mode({"search_mode": "fuzzy"})
    with pytest.raises(ToolArgumentError, match="explicitly null"):
        validate_search_mode({"search_mode": None})


def test_limit_absent_defaults_present_is_strict() -> None:
    assert validate_limit({}) == DEFAULT_LIMIT
    assert validate_limit({"limit": 25}) == 25
    with pytest.raises(ToolArgumentError, match="explicitly null"):
        validate_limit({"limit": None})
    with pytest.raises(ToolArgumentError):
        validate_limit({"limit": True})  # bool-as-int
    with pytest.raises(ToolArgumentError):
        validate_limit({"limit": 0})
    with pytest.raises(ToolArgumentError):
        validate_limit({"limit": MAX_LIMIT + 1})


def test_bool_absent_defaults_present_is_strict() -> None:
    assert validate_bool({}, name="full_reindex") is False
    assert validate_bool({"full_reindex": True}, name="full_reindex") is True
    with pytest.raises(ToolArgumentError, match="explicitly null"):
        validate_bool({"full_reindex": None}, name="full_reindex")
    with pytest.raises(ToolArgumentError):
        validate_bool({"full_reindex": "yes"}, name="full_reindex")


# --------------------------------------------------------------------------- #
# D2 / AC11: project_id resolution
# --------------------------------------------------------------------------- #


def test_story_search_omitted_project_uses_bound(tmp_path: Path) -> None:
    service, client = _service(tmp_path)
    client.search_results = [story_hit("s1", "AG3-1", 0.5)]
    result = handle_tool_call(service, "story_search", {"query": "x"})
    assert result["project_id"] == "acme"
    assert result["results"][0]["story_id"] == "AG3-1"


@pytest.mark.parametrize(
    "tool,args",
    [
        ("story_search", {"query": "x", "project_id": "other"}),
        ("story_list_sources", {"project_id": "other"}),
        ("story_sync", {"project_id": "other"}),
        ("concept_search", {"query": "x", "project_id": "other"}),
        ("concept_sync", {"project_id": "other"}),
    ],
)
def test_foreign_project_id_is_rejected_for_every_tool(
    tmp_path: Path, tool: str, args: dict[str, Any]
) -> None:
    service, client = _service(tmp_path)
    with pytest.raises(ToolArgumentError, match="diverges"):
        handle_tool_call(service, tool, args)
    assert client.objects == {}
    assert client.search_calls == []


# --------------------------------------------------------------------------- #
# AC7: envelopes / fail-closed
# --------------------------------------------------------------------------- #


def test_concept_search_applies_authority_ranking_and_envelope(tmp_path: Path) -> None:
    service, client = _service(tmp_path)
    client.search_results = [concept_hit("c1", "FK-13", 0.5)]
    result = handle_tool_call(service, "concept_search", {"query": "retrieval"})
    assert result["project_id"] == "acme"
    assert "authority_score" in result["results"][0]
    assert result["results"][0]["concept_id"] == "FK-13"


def test_weaviate_outage_is_fail_closed(tmp_path: Path) -> None:
    from agentkit.integration_clients.vectordb.errors import VectorDbUnavailableError

    service, client = _service(tmp_path)

    def _down(**_kwargs: object) -> None:
        raise VectorDbUnavailableError("node down")

    client.search_objects = _down  # type: ignore[method-assign]
    result = handle_tool_call(service, "story_search", {"query": "x"})
    assert result["error"] == "vectordb_unavailable"
    assert "node down" in result["detail"]


def test_three_search_modes_reach_the_transport_distinctly(tmp_path: Path) -> None:
    service, client = _service(tmp_path)
    client.search_results = [concept_hit("c1", "FK-13", 0.5)]
    for mode in SEARCH_MODES:
        handle_tool_call(service, "concept_search", {"query": "x", "search_mode": mode})
    assert [c["search_mode"] for c in client.search_calls] == list(SEARCH_MODES)


def test_concept_sync_blocks_on_invalid_corpus(tmp_path: Path) -> None:
    service, client = _service(tmp_path)
    (service.concepts_dir / "technical-design" / "broken.md").write_text(
        "no frontmatter", encoding="utf-8"
    )
    result = handle_tool_call(service, "concept_sync", {"full_reindex": True})
    assert result["error"] == "concept_validate_failed"
    assert result["written"] == 0
    assert client.objects == {}


def test_unknown_tool_rejected(tmp_path: Path) -> None:
    service, _client = _service(tmp_path)
    with pytest.raises(ToolArgumentError, match="unknown tool"):
        handle_tool_call(service, "bogus_tool", {})


def test_search_missing_query_rejected(tmp_path: Path) -> None:
    service, _client = _service(tmp_path)
    with pytest.raises(ToolArgumentError, match="query"):
        handle_tool_call(service, "story_search", {})
