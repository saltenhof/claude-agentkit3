"""stdio MCP runner for AG3-174 R06 boundary tests.

Spawns the productive low-level MCP server surface with a MemoryWeaviateClient
behind WeaviateStoryAdapter (fake only at the external port). Invoked as a
subprocess by the stdio contract test — never a production entrypoint.
"""

from __future__ import annotations

import asyncio
import os


def main() -> int:
    """Run story-knowledge-base MCP over stdio with bound project env."""
    from tests.support.vectordb.memory_store import MemoryWeaviateClient

    from agentkit.backend.vectordb.ingest.engine import IngestEngine
    from agentkit.backend.vectordb.mcp.tools import KnowledgeTools
    from agentkit.backend.vectordb.mcp_server import create_mcp_server
    from agentkit.backend.vectordb.runtime_binding import load_runtime_binding_from_env
    from agentkit.integration_clients.vectordb.weaviate_adapter import WeaviateStoryAdapter

    # Pre-seed is done by parent via env AK3_TEST_SEED_DIR + files on disk;
    # runner does story+concept sync so tools/list+call work.
    binding = load_runtime_binding_from_env(dict(os.environ))
    mem = MemoryWeaviateClient()
    adapter = WeaviateStoryAdapter(mem)  # type: ignore[arg-type]
    engine = IngestEngine(
        adapter,
        lock_dir=binding.project.project_root / ".agentkit" / "vectordb" / "locks",
    )
    engine.story_sync(binding.project, full_reindex=True)
    from agentkit.backend.vectordb.concept_corpus.sync import concept_sync_bounded_window

    concept_sync_bounded_window(binding.project, engine, full_reindex=True)
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
