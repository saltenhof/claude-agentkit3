"""Story-knowledge-base MCP server — low-level wire boundary (R06).

Uses the MCP Server low-level API so tool calls deliver the raw argument map
before FastMCP/Pydantic coercion. Flat inputSchemas match FK-13 tool params.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, cast

from agentkit.backend.vectordb.ingest.engine import IngestEngine
from agentkit.backend.vectordb.mcp.contracts import TOOL_NAMES
from agentkit.backend.vectordb.mcp.tools import KnowledgeTools, ToolExecutionError
from agentkit.backend.vectordb.runtime_binding import (
    RuntimeBindingError,
    load_runtime_binding_from_env,
)
from agentkit.backend.vectordb.schema import STORY_COLLECTION, ensure_story_context_schema

#: Flat JSON-Schema fragments for tools/list (FK-13).
_FLAT_SCHEMAS: dict[str, dict[str, object]] = {
    "story_search": {
        "type": "object",
        "additionalProperties": False,
        "required": ["query"],
        "properties": {
            "query": {"type": "string"},
            "search_mode": {"type": "string", "enum": ["hybrid", "vector", "keyword"]},
            "project_id": {"type": "string"},
            "status": {"type": "string"},
            "story_type": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
        },
    },
    "story_list_sources": {
        "type": "object",
        "additionalProperties": False,
        "properties": {"project_id": {"type": "string"}},
    },
    "story_sync": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "project_id": {"type": "string"},
            "full_reindex": {"type": "boolean"},
        },
    },
    "concept_search": {
        "type": "object",
        "additionalProperties": False,
        "required": ["query"],
        "properties": {
            "query": {"type": "string"},
            "search_mode": {"type": "string", "enum": ["hybrid", "vector", "keyword"]},
            "project_id": {"type": "string"},
            "concept_id": {"type": "string"},
            "module": {"type": "string"},
            "is_appendix": {"type": "boolean"},
            "concept_status": {"type": "string", "enum": ["active", "draft", "archived"]},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            "query_scopes": {"type": "array", "items": {"type": "string"}},
        },
    },
    "concept_sync": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "project_id": {"type": "string"},
            "full_reindex": {"type": "boolean"},
            "concept_path": {"type": "string"},
        },
    },
}


def build_tools_from_env(
    env: dict[str, str] | None = None,
    *,
    store: object | None = None,
) -> KnowledgeTools:
    """Construct bound tools from the authoritative runtime env."""
    binding = load_runtime_binding_from_env(env)
    if store is None:
        from agentkit.integration_clients.vectordb.weaviate_adapter import (
            WeaviateStoryAdapter,
        )

        adapter = WeaviateStoryAdapter.connect(
            host=binding.weaviate_host,
            port=binding.weaviate_http_port,
            grpc_port=binding.weaviate_grpc_port,
        )
        store = adapter
        ensure_story_context_schema(adapter.raw_client)
    engine = IngestEngine(
        store,  # type: ignore[arg-type]
        lock_dir=binding.project.project_root / ".agentkit" / "vectordb" / "locks",
    )
    return KnowledgeTools(binding, engine, search_port=store)


def list_tools() -> list[dict[str, object]]:
    """Return flat tool descriptors for tools/list (R06)."""
    out: list[dict[str, object]] = []
    for name in TOOL_NAMES:
        schema = _FLAT_SCHEMAS[name]
        required_raw = schema.get("required") or []
        required_list = (
            list(cast("list[object]", required_raw))
            if isinstance(required_raw, list)
            else []
        )
        out.append(
            {
                "name": name,
                "description": name,
                "inputSchema": schema,
                "required": required_list,
                "properties": schema.get("properties") or {},
            }
        )
    return out


def dispatch_tool(
    tools: KnowledgeTools, name: str, arguments: dict[str, Any] | None
) -> dict[str, object]:
    """Dispatch raw tool arguments through strict wire models (R06)."""
    if name not in TOOL_NAMES:
        return {"ok": False, "error_code": "unknown_tool", "error": name}
    raw = dict(arguments or {})
    try:
        return tools.handle_raw(name, raw)
    except ToolExecutionError as exc:
        return exc.as_envelope()


def create_mcp_server(tools: KnowledgeTools) -> object:
    """Build a low-level MCP Server with flat schemas and raw call handling."""
    from mcp.server import Server
    from mcp.types import TextContent, Tool

    server = Server("story-knowledge-base")

    async def _list_tools() -> list[Tool]:
        return [
            Tool(
                name=name,
                description=name,
                inputSchema=_FLAT_SCHEMAS[name],
            )
            for name in TOOL_NAMES
        ]

    async def _call_tool(
        name: str, arguments: dict[str, Any] | None
    ) -> list[TextContent]:
        # ``arguments`` is the raw tool-call map from the MCP client (R06).
        result = dispatch_tool(tools, name, arguments)
        return [TextContent(type="text", text=json.dumps(result))]

    # Low-level Server decorators may be untyped depending on mcp package stubs.
    def _register(handler: object, name: str) -> None:
        decorator_factory = getattr(server, name)
        decorator_factory()(handler)

    _register(_list_tools, "list_tools")
    _register(_call_tool, "call_tool")

    server._ak3_tool_names = list(TOOL_NAMES)  # type: ignore[attr-defined]
    server._ak3_collection = STORY_COLLECTION  # type: ignore[attr-defined]
    return server


def main(argv: list[str] | None = None) -> int:
    """stdio MCP server entrypoint (low-level Server API)."""
    del argv
    try:
        binding = load_runtime_binding_from_env()
    except RuntimeBindingError as exc:
        print(f"Runtime binding failed: {exc}", file=sys.stderr)
        return 2

    from agentkit.integration_clients.vectordb.weaviate_adapter import WeaviateStoryAdapter

    try:
        adapter = WeaviateStoryAdapter.connect(
            host=binding.weaviate_host,
            port=binding.weaviate_http_port,
            grpc_port=binding.weaviate_grpc_port,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Weaviate connect failed (fail-closed): {exc}", file=sys.stderr)
        return 2

    try:
        ensure_story_context_schema(adapter.raw_client)
    except Exception as exc:  # noqa: BLE001
        print(f"Schema ensure failed (fail-closed, R14): {exc}", file=sys.stderr)
        adapter.close()
        return 2

    engine = IngestEngine(
        adapter,
        lock_dir=binding.project.project_root / ".agentkit" / "vectordb" / "locks",
    )
    tools = KnowledgeTools(binding, engine, search_port=adapter)
    server = create_mcp_server(tools)

    async def _run() -> None:
        from mcp.server.stdio import stdio_server

        async with stdio_server() as (read_stream, write_stream):
            await server.run(  # type: ignore[attr-defined]
                read_stream,
                write_stream,
                server.create_initialization_options(),  # type: ignore[attr-defined]
            )

    asyncio.run(_run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
