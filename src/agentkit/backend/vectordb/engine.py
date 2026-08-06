"""Compose and serve the production FK-13 VectorDB runtime over stdio."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

from agentkit.backend.vectordb.commit_recovery import project_commit_recovery_journal
from agentkit.backend.vectordb.endpoints import split_grpc_endpoint, split_http_endpoint
from agentkit.backend.vectordb.runtime_binding import RuntimeBinding, RuntimeBindingError
from agentkit.backend.vectordb.sync import SyncService
from agentkit.integration_clients.vectordb.errors import VectorDbUnavailableError

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from agentkit.backend.vectordb.client_port import CorpusClientPort
    from agentkit.backend.vectordb.mcp_server import McpToolService


def connect_real_client(binding: RuntimeBinding) -> CorpusClientPort:
    """Build a real Weaviate client from the binding's EXACT endpoints (R02/R03).

    Both endpoints come verbatim from the registered env (D2) and are passed into
    ``weaviate.connect_to_custom`` -- the only connect API of the pinned client
    that accepts a DISTINCT gRPC host (``connect_to_local`` does not, R03).
    Raises :class:`VectorDbUnavailableError` fail-closed.
    """
    from agentkit.integration_clients.vectordb.weaviate_adapter import _build_real_client

    http_host, http_port, http_secure = split_http_endpoint(binding.weaviate_http_endpoint)
    grpc_host, grpc_port, grpc_secure = split_grpc_endpoint(binding.weaviate_grpc_endpoint)
    return cast(
        "CorpusClientPort",
        _build_real_client(
            http_host=http_host,
            http_port=http_port,
            http_secure=http_secure,
            grpc_host=grpc_host,
            grpc_port=grpc_port,
            grpc_secure=grpc_secure,
        ),
    )


def compose_runtime(
    env: Mapping[str, str],
    *,
    concepts_dir: Path,
    stories_dir: Path,
    client: CorpusClientPort | None = None,
    command: str | None = None,
    args: tuple[str, ...] = (),
    cwd: str = ".",
) -> McpToolService:
    """Build the productive :class:`McpToolService` from the env (R02).

    Ensures the StoryContext collection exists idempotently. Fails closed on any
    binding or connection fault.
    """
    from agentkit.backend.installer.interpreter import resolve_ak3_interpreter
    from agentkit.backend.vectordb.corpus_store import WeaviateCorpusStore
    from agentkit.backend.vectordb.mcp_server import McpToolService
    from agentkit.backend.vectordb.provisioning import ensure_corpus_collections
    from agentkit.backend.vectordb.retrieval import WeaviateRetrievalPort

    owner_command = str(resolve_ak3_interpreter())
    if command is not None and command != owner_command:
        raise RuntimeBindingError(
            "VectorDB runtime command diverges from the central AK3 interpreter "
            f"owner: {command!r} != {owner_command!r}."
        )
    binding = RuntimeBinding.from_env(
        env,
        command=owner_command,
        args=args,
        cwd=cwd,
    )
    resolved_client = client if client is not None else connect_real_client(binding)
    # Idempotent collection creation. The schema-OWNER (schema.py) declares the
    # property set via ``weaviate_property_specs()`` + the FK-13 §13.2
    # server-side text2vec-transformers vectorizer (N02); the thin adapter's
    # ``ensure_collection`` materialises it. Created via the port (not raw
    # ``.collections``) so it works through the CorpusClientPort boundary.
    ensure_corpus_collections(resolved_client)
    from pathlib import Path

    store = WeaviateCorpusStore(
        client=resolved_client,
        recovery_journal=project_commit_recovery_journal(Path(cwd)),
    )
    sync = SyncService(store=store)
    retrieval = WeaviateRetrievalPort(client=resolved_client, store=store, binding=binding)
    return McpToolService(
        binding=binding,
        retrieval=retrieval,
        sync=sync,
        concepts_dir=concepts_dir,
        stories_dir=stories_dir,
    )


def run_stdio_server(service: McpToolService) -> None:
    """Run the FastMCP server over stdio for the composed service (R02)."""
    from agentkit.backend.vectordb.mcp_server import build_mcp_server

    server = build_mcp_server(service)
    server.run()


def main() -> int:
    """Executable stdio entry point.

    Reads the env, composes the production engine, and serves. Fails closed
    (exit 1) on any binding/connection fault -- never starts on a localhost
    default or missing endpoint (D2).
    """
    import os

    env = dict(os.environ)
    cwd = os.getcwd()
    # N20/D2: the concept corpus root is project configuration and must come from
    # the registered env. Defaulting to the literal ``concept`` pointed the server
    # at AK3's OWN development corpus; a missing binding stops the server.
    concepts_dir_value = env.get("AGENTKIT_CONCEPTS_DIR", "").strip()
    if not concepts_dir_value:
        print(
            json.dumps(
                {
                    "error": "composition_failed",
                    "detail": (
                        "AGENTKIT_CONCEPTS_DIR is missing/empty; the concept corpus root has no default (fail-closed, D2/N20)."
                    ),
                }
            )
        )
        return 1
    concepts_dir = _resolve_dir(concepts_dir_value)
    # The story corpus root is the CANONICAL relative layout the classifier
    # recognises (FK-13 §13.3.2 ``stories/<story>/story.md``), resolved inside the
    # bound cwd -- not a foreign path.
    stories_dir = _resolve_dir(env.get("AGENTKIT_STORIES_DIR", "stories"))
    try:
        service = compose_runtime(
            env,
            concepts_dir=concepts_dir,
            stories_dir=stories_dir,
            cwd=cwd,
        )
    except (RuntimeBindingError, VectorDbUnavailableError) as exc:
        print(json.dumps({"error": "composition_failed", "detail": str(exc)}))
        return 1
    try:
        run_stdio_server(service)
    finally:
        service.close()
    return 0


def _resolve_dir(path: str) -> Path:
    from pathlib import Path

    return Path(path).resolve()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "compose_runtime",
    "connect_real_client",
    "main",
    "run_stdio_server",
]
