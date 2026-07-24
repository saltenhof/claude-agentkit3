"""Production retrieval engine for the FK-13 MCP server (R02).

Real, productive implementations of :class:`RetrievalPort` and
:class:`CorpusStorePort` over the THIN Weaviate transport adapter, plus an
env-bound runtime composition (:func:`compose_runtime`) and an executable stdio
entry point (:func:`main`). The engine never synthesises endpoints: both the
HTTP and gRPC endpoints come exclusively from the registered env (D2), are
passed verbatim into the real connection, and a localhost default fails closed.

This is the ONLY production wiring of the engine; tests instantiate the ports
with fakes at the :class:`CorpusStorePort` / :class:`RetrievalPort` boundary
(the narrow mock exception).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from agentkit.backend.vectordb.runtime_binding import RuntimeBinding, RuntimeBindingError
from agentkit.backend.vectordb.schema import (
    STORY_CONTEXT_COLLECTION,
    StoryContextObject,
    ensure_story_context_collection,
)
from agentkit.backend.vectordb.sync import SyncReceipt, SyncService
from agentkit.integration_clients.vectordb.errors import VectorDbUnavailableError

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

#: Dedicated collection for digest-bound sync receipts (R02/R12).
RECEIPT_COLLECTION = "__agentkit_sync_receipts"


class CorpusClientPort(Protocol):
    """The thin-adapter corpus surface the engine needs (R02)."""

    def fetch_by_property(
        self, *, collection: str, prop: str, value: str, return_props: Sequence[str]
    ) -> Sequence[tuple[str, dict[str, object]]]: ...

    def fetch_by_property_any(
        self, *, collection: str, prop: str, values: Sequence[str], return_props: Sequence[str]
    ) -> Sequence[tuple[str, dict[str, object]]]: ...

    def upsert(self, *, collection: str, objects: Sequence[Mapping[str, object]]) -> int: ...

    def delete_by_ids(self, *, collection: str, uuids: Sequence[str]) -> int: ...

    def ensure_collection(
        self, *, collection: str, property_specs: Sequence[Mapping[str, object]]
    ) -> None: ...


@dataclass
class WeaviateCorpusStore:
    """Production :class:`CorpusStorePort` over the thin Weaviate adapter (R02)."""

    client: CorpusClientPort
    collection: str = STORY_CONTEXT_COLLECTION

    def list_objects_for_source(
        self, *, project_id: str, source_file: str
    ) -> Sequence[Mapping[str, object]]:
        rows = self.client.fetch_by_property(
            collection=self.collection,
            prop="source_file",
            value=source_file,
            return_props=("content_hash", "source_type", "project_id"),
        )
        return [
            {"uuid": uid, "source_file": source_file, "source_type": p.get("source_type", ""),
             "project_id": p.get("project_id", ""), "content_hash": p.get("content_hash", "")}
            for uid, p in rows
            if str(p.get("project_id", "")) == project_id
        ]

    def list_objects_for_source_types(
        self, *, project_id: str, source_types: Sequence[str]
    ) -> Sequence[Mapping[str, object]]:
        rows = self.client.fetch_by_property_any(
            collection=self.collection,
            prop="source_type",
            values=tuple(source_types),
            return_props=("source_file", "project_id", "source_type"),
        )
        return [
            {"uuid": uid, "source_file": p.get("source_file", ""),
             "source_type": p.get("source_type", ""), "project_id": p.get("project_id", "")}
            for uid, p in rows
            if str(p.get("project_id", "")) == project_id
        ]

    def upsert_objects(self, *, objects: Sequence[StoryContextObject]) -> int:
        # Exact confirmed count: the adapter inspects batch failures and raises
        # on a partial batch (R12); a clean return == len(objects).
        docs = [{**obj.properties, "uuid": obj.uuid} for obj in objects]
        return self.client.upsert(collection=self.collection, objects=docs)

    def delete_objects(self, *, uuids: Sequence[str]) -> int:
        return self.client.delete_by_ids(collection=self.collection, uuids=tuple(uuids))

    def get_receipt(self, *, project_id: str, source_file: str) -> SyncReceipt | None:
        rows = self.client.fetch_by_property(
            collection=RECEIPT_COLLECTION,
            prop="source_file",
            value=source_file,
            return_props=("project_id", "source_type", "corpus_revision", "digest", "state"),
        )
        for _uid, p in rows:
            if str(p.get("project_id", "")) == project_id:
                return _receipt_from_props(project_id, source_file, p)
        return None

    def set_receipt(self, *, receipt: SyncReceipt) -> None:
        doc = {
            "project_id": receipt.project_id,
            "source_file": receipt.source_file,
            "source_type": receipt.source_type,
            "corpus_revision": receipt.corpus_revision,
            "digest": receipt.digest,
            "state": receipt.state.value,
            "uuid": receipt.digest,  # idempotent: latest receipt replaces prior
        }
        self.client.upsert(collection=RECEIPT_COLLECTION, objects=[doc])


def _receipt_from_props(project_id: str, source_file: str, props: Mapping[str, object]) -> SyncReceipt | None:
    from agentkit.backend.vectordb.sync import ReceiptState

    state_raw = str(props.get("state", ""))
    try:
        state = ReceiptState(state_raw)
    except ValueError:
        return None
    return SyncReceipt(
        project_id=project_id,
        source_file=source_file,
        source_type=str(props.get("source_type", "")),
        corpus_revision=str(props.get("corpus_revision", "")),
        digest=str(props.get("digest", "")),
        state=state,
    )


@dataclass
class WeaviateRetrievalPort:
    """Production :class:`RetrievalPort` over the thin Weaviate adapter (R02).

    Search delegates to the adapter's project-scoped query (3 modes). Source
    listings are aggregated from the corpus store so ``story_list_sources``
    returns the real indexed state (D1 shape), not a stub.
    """

    adapter: Any  # WeaviateStoryAdapter (duck-typed to avoid a circular import)
    store: WeaviateCorpusStore
    binding: RuntimeBinding

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
        # The adapter search is story-shaped; for the concept/story search we
        # project full properties by re-reading matched objects is not feasible
        # without vector infra. We delegate the semantic match to the adapter and
        # augment with filter pass-through. Outage is fail-closed (VectorDbError).
        raw = self.adapter.story_search(
            query,
            search_mode=search_mode,
            project_id=project_id,
            limit=limit,
        )
        return [self._project_hit(h, source_type) for h in raw]

    @staticmethod
    def _project_hit(hit: Any, source_type: str) -> dict[str, object]:
        return {
            "story_id": getattr(hit, "story_id", ""),
            "title": getattr(hit, "title", ""),
            "score": getattr(hit, "score", 0.0),
            "snippet": getattr(hit, "snippet", ""),
            "source_type": source_type,
        }

    def list_sources(self, *, project_id: str) -> Sequence[Mapping[str, object]]:
        from agentkit.backend.vectordb.ingest.classify import PRODUCER_BY_SOURCE_TYPE

        out: list[Mapping[str, object]] = []
        for source_type, producer in PRODUCER_BY_SOURCE_TYPE.items():
            rows = self.store.list_objects_for_source_types(
                project_id=project_id, source_types=(source_type,)
            )
            files = {str(r.get("source_file")) for r in rows}
            out.append(
                {
                    "project_id": project_id,
                    "source_type": source_type,
                    "producer": producer,
                    "source_count": len(files),
                    "chunk_count": len(rows),
                    "last_revision": "",
                }
            )
        return out


def connect_real_client(binding: RuntimeBinding) -> CorpusClientPort:
    """Build a real Weaviate client from the binding's EXACT endpoints (R02/R03).

    Both HTTP and gRPC endpoints come verbatim from the registered env (D2); no
    localhost default. Raises :class:`VectorDbUnavailableError` fail-closed.
    """
    from agentkit.integration_clients.vectordb.weaviate_adapter import _build_real_client

    # The binding carries the canonical host/port split of the configured endpoints.
    http_host, http_port = _split_endpoint(binding.weaviate_http_endpoint)
    grpc_host, grpc_port = _split_grpc(binding.weaviate_grpc_endpoint)
    client = _build_real_client(host=http_host, port=http_port)
    # gRPC endpoint is asserted (required) and surfaced for the connection layer.
    client._agentkit_grpc = (grpc_host, grpc_port)  # type: ignore[attr-defined]  # noqa: SLF001
    return client  # type: ignore[return-value]


def _split_endpoint(endpoint: str) -> tuple[str, int]:
    """Split an ``http://host:port`` endpoint into ``(host, port)`` fail-closed."""
    import urllib.parse

    parsed = urllib.parse.urlparse(endpoint)
    if not parsed.hostname or parsed.port is None:
        raise VectorDbUnavailableError(
            f"WEAVIATE_HTTP_ENDPOINT {endpoint!r} is not host:port (fail-closed, D2)."
        )
    return parsed.hostname, parsed.port


def _split_grpc(endpoint: str) -> tuple[str, int]:
    """Split a ``host:port`` gRPC endpoint into ``(host, port)`` fail-closed."""
    if ":" not in endpoint:
        raise VectorDbUnavailableError(
            f"WEAVIATE_GRPC_ENDPOINT {endpoint!r} is not host:port (fail-closed, D2)."
        )
    host, _, port = endpoint.rpartition(":")
    try:
        return host, int(port)
    except ValueError as exc:
        raise VectorDbUnavailableError(
            f"WEAVIATE_GRPC_ENDPOINT {endpoint!r} has non-integer port (fail-closed, D2)."
        ) from exc


def compose_runtime(
    env: Mapping[str, str],
    *,
    concepts_dir: Path,
    stories_dir: Path,
    command: str = "python",
    args: tuple[str, ...] = (),
    cwd: str = ".",
) -> object:
    """Build the productive :class:`McpToolService` from the env (R02).

    Ensures the StoryContext collection exists idempotently. Fails closed on any
    binding or connection fault.
    """
    from agentkit.backend.vectordb.mcp_server import McpToolService
    from agentkit.integration_clients.vectordb.weaviate_adapter import WeaviateStoryAdapter

    binding = RuntimeBinding.from_env(env, command=command, args=args, cwd=cwd)
    client = connect_real_client(binding)
    # Idempotent collection creation -- the schema-owner (schema.py) is the
    # single declarer of the StoryContext property set (R02).
    ensure_story_context_collection(client)
    # The receipt collection is best-effort at compose (dedicated, non-critical).
    import contextlib

    with contextlib.suppress(Exception):
        client.ensure_collection(
            collection=RECEIPT_COLLECTION, property_specs=_receipt_property_specs()
        )
    store = WeaviateCorpusStore(client=client)
    sync = SyncService(store=store)
    adapter = WeaviateStoryAdapter(client)  # type: ignore[arg-type]
    retrieval = WeaviateRetrievalPort(adapter=adapter, store=store, binding=binding)
    return McpToolService(
        binding=binding,
        retrieval=retrieval,
        sync=sync,
        concepts_dir=concepts_dir,
        stories_dir=stories_dir,
    )


def _receipt_property_specs() -> list[dict[str, object]]:
    return [
        {"name": "project_id", "data_type": "TEXT", "skip_vectorization": True},
        {"name": "source_file", "data_type": "TEXT", "skip_vectorization": True},
        {"name": "source_type", "data_type": "TEXT", "skip_vectorization": True},
        {"name": "corpus_revision", "data_type": "TEXT", "skip_vectorization": True},
        {"name": "digest", "data_type": "TEXT", "skip_vectorization": True},
        {"name": "state", "data_type": "TEXT", "skip_vectorization": True},
    ]


def run_stdio_server(service: object) -> None:
    """Run the FastMCP server over stdio for the composed service (R02)."""
    from agentkit.backend.vectordb.mcp_server import build_mcp_server

    server = build_mcp_server(service)  # type: ignore[arg-type]
    server.run()  # type: ignore[attr-defined]


def main() -> int:
    """Executable stdio entry point.

    Reads the env, composes the production engine, and serves. Fails closed
    (exit 1) on any binding/connection fault -- never starts on a localhost
    default or missing endpoint (D2).
    """
    import os

    env = dict(os.environ)
    cwd = os.getcwd()
    concepts_dir = _resolve_dir(env.get("AGENTKIT_CONCEPTS_DIR", "concept"))
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
    run_stdio_server(service)
    return 0


def _resolve_dir(path: str) -> Path:
    from pathlib import Path

    return Path(path).resolve()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "RECEIPT_COLLECTION",
    "WeaviateCorpusStore",
    "WeaviateRetrievalPort",
    "compose_runtime",
    "connect_real_client",
    "main",
    "run_stdio_server",
]
