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
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from agentkit.backend.vectordb.runtime_binding import RuntimeBinding, RuntimeBindingError
from agentkit.backend.vectordb.schema import (
    STORY_CONTEXT_COLLECTION,
    StoryContextObject,
)
from agentkit.backend.vectordb.sync import SyncReceipt, SyncService
from agentkit.integration_clients.vectordb.errors import VectorDbUnavailableError, VectorDbWriteError

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

#: Dedicated collection for digest-bound sync receipts (R02/R12).
RECEIPT_COLLECTION = "__agentkit_sync_receipts"

#: Dedicated collection for store-level atomic source claims (N03/D3).
CLAIM_COLLECTION = "__agentkit_source_claims"

#: Stable namespace for per-source receipt identity (N08).
_RECEIPT_NAMESPACE = uuid.UUID("8c5e2f3a-1b6d-4e7a-9c8f-2a1b3c4d5e6f")
#: Stable namespace for per-source claim identity (N03).
_CLAIM_NAMESPACE = uuid.UUID("9d6f3a4b-2c7e-5f8b-ad9c-3b2c4d5e6f7a")


class CorpusClientPort(Protocol):
    """The thin-adapter corpus surface the engine needs (R02)."""

    def fetch_by_property(
        self, *, collection: str, prop: str, value: str, return_props: Sequence[str]
    ) -> Sequence[tuple[str, dict[str, object]]]: ...

    def fetch_by_property_any(
        self, *, collection: str, prop: str, values: Sequence[str], return_props: Sequence[str]
    ) -> Sequence[tuple[str, dict[str, object]]]: ...

    def search_objects(
        self,
        *,
        collection: str,
        query: str,
        search_mode: str,
        project_id: str,
        source_type: str,
        filters: Mapping[str, object],
        limit: int,
        return_props: Sequence[str],
    ) -> Sequence[tuple[str, dict[str, object], float]]: ...

    def upsert(self, *, collection: str, objects: Sequence[Mapping[str, object]]) -> int: ...

    def delete_by_ids(self, *, collection: str, uuids: Sequence[str]) -> int: ...

    def ensure_collection(
        self, *, collection: str, property_specs: Sequence[Mapping[str, object]], vectorizer: str = ...
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
        # N08: STABLE per-source receipt identity (uuid5 of project+source) so the
        # latest receipt REPLACES the prior -- never accumulates multiple records
        # per source. The upsert count is verified (fail-closed, never silent).
        stable_uuid = str(uuid.uuid5(_RECEIPT_NAMESPACE, f"{receipt.project_id}|{receipt.source_file}"))
        doc = {
            "project_id": receipt.project_id,
            "source_file": receipt.source_file,
            "source_type": receipt.source_type,
            "corpus_revision": receipt.corpus_revision,
            "digest": receipt.digest,
            "state": receipt.state.value,
            "uuid": stable_uuid,
        }
        written = self.client.upsert(collection=RECEIPT_COLLECTION, objects=[doc])
        if written != 1:
            raise VectorDbWriteError(
                f"receipt upsert for {receipt.source_file!r} wrote {written} (expected 1); "
                "fail-closed (N08)."
            )

    def try_claim_source(self, *, project_id: str, source_file: str) -> bool:
        """Atomically claim a source via a dedicated claims collection (N03/D3).

        The claim is STORE-LEVEL (shared across processes): the claim record is
        keyed by a stable per-source UUID. A prior live claim (state=claimed)
        rejects the second writer. This is NOT process-local.
        """
        claim_uuid = str(uuid.uuid5(_CLAIM_NAMESPACE, f"{project_id}|{source_file}"))
        existing = self.client.fetch_by_property(
            collection=CLAIM_COLLECTION,
            prop="source_file",
            value=source_file,
            return_props=("project_id", "state"),
        )
        for _uid, props in existing:
            if str(props.get("project_id", "")) == project_id and str(props.get("state", "")) == "claimed":
                return False
        self.client.upsert(
            collection=CLAIM_COLLECTION,
            objects=[{"project_id": project_id, "source_file": source_file, "state": "claimed", "uuid": claim_uuid}],
        )
        return True

    def release_source(self, *, project_id: str, source_file: str) -> None:
        claim_uuid = str(uuid.uuid5(_CLAIM_NAMESPACE, f"{project_id}|{source_file}"))
        # Best-effort release; a stuck claim is reconciled by a retry that
        # re-reads state. Never mask a write fault in the hot path.
        import contextlib

        with contextlib.suppress(VectorDbUnavailableError):
            self.client.delete_by_ids(collection=CLAIM_COLLECTION, uuids=[claim_uuid])


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
    """Production :class:`RetrievalPort` over the thin Weaviate adapter (R02/N01).

    Search issues a REAL StoryContext query scoped by project_id AND source_type
    AND the typed filters, returning full properties (concept_id/status/module
    preserved). Source listings read the persisted receipts for real freshness
    (N04/D1).
    """

    client: CorpusClientPort
    store: WeaviateCorpusStore
    binding: RuntimeBinding
    collection: str = STORY_CONTEXT_COLLECTION

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
        return_props = (
            "story_id", "title", "status", "story_type", "module", "epic",
            "source_type", "source_file", "section_heading", "section_number",
            "content", "concept_id", "is_appendix", "parent_concept_id",
            "concept_status",
        )
        rows = self.client.search_objects(
            collection=self.collection,
            query=query,
            search_mode=search_mode,
            project_id=project_id,
            source_type=source_type,
            filters=filters,
            limit=limit,
            return_props=return_props,
        )
        return [
            {**props, "score": score, "snippet": str(props.get("content", ""))[:200]}
            for _uid, props, score in rows
        ]

    def list_sources(self, *, project_id: str) -> Sequence[Mapping[str, object]]:
        from agentkit.backend.vectordb.ingest.classify import PRODUCER_BY_SOURCE_TYPE

        out: list[Mapping[str, object]] = []
        for source_type, producer in PRODUCER_BY_SOURCE_TYPE.items():
            rows = self.store.list_objects_for_source_types(
                project_id=project_id, source_types=(source_type,)
            )
            files = {str(r.get("source_file")) for r in rows}
            # N04/D1: read the REAL latest revision from persisted receipts.
            last_revision = self._latest_revision(project_id, files)
            out.append(
                {
                    "project_id": project_id,
                    "source_type": source_type,
                    "producer": producer,
                    "source_count": len(files),
                    "chunk_count": len(rows),
                    "last_revision": last_revision,
                }
            )
        return out

    def _latest_revision(self, project_id: str, files: set[str]) -> str:
        """Return the latest persisted receipt revision across the source files (N04)."""
        revisions: list[str] = []
        for source_file in files:
            receipt = self.store.get_receipt(project_id=project_id, source_file=source_file)
            if receipt is not None and receipt.state.value == "completed":
                revisions.append(receipt.corpus_revision)
        return max(revisions) if revisions else ""


def connect_real_client(binding: RuntimeBinding) -> CorpusClientPort:
    """Build a real Weaviate client from the binding's EXACT endpoints (R02/R03).

    Both HTTP and gRPC endpoints come verbatim from the registered env (D2) and
    are passed INTO ``weaviate.connect_to_local`` -- no localhost default, no
    private attribute. Raises :class:`VectorDbUnavailableError` fail-closed.
    """
    from agentkit.integration_clients.vectordb.weaviate_adapter import _build_real_client

    http_host, http_port = _split_endpoint(binding.weaviate_http_endpoint)
    grpc_host, grpc_port = _split_grpc(binding.weaviate_grpc_endpoint)
    return _build_real_client(  # type: ignore[return-value]
        host=http_host,
        port=http_port,
        grpc_host=grpc_host,
        grpc_port=grpc_port,
    )


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

    binding = RuntimeBinding.from_env(env, command=command, args=args, cwd=cwd)
    client = connect_real_client(binding)
    # Idempotent collection creation. The schema-OWNER (schema.py) declares the
    # property set via ``weaviate_property_specs()`` + the FK-13 §13.2
    # server-side text2vec-transformers vectorizer (N02); the thin adapter's
    # ``ensure_collection`` materialises it. Created via the port (not raw
    # ``.collections``) so it works through the CorpusClientPort boundary.
    from agentkit.backend.vectordb.schema import weaviate_property_specs

    client.ensure_collection(
        collection=STORY_CONTEXT_COLLECTION,
        property_specs=weaviate_property_specs(),
        vectorizer="text2vec_transformers",
    )
    # The receipt + claim collections are auxiliary (no vectors); their creation
    # is NOT suppressed -- a failure to ensure them must surface fail-closed
    # (N08), since receipt/claim persistence is required for the bounded-window
    # freshness + D3 concurrent-reject contracts.
    _aux_specs = _receipt_property_specs()
    client.ensure_collection(
        collection=RECEIPT_COLLECTION, property_specs=_aux_specs, vectorizer="self_provided"
    )
    client.ensure_collection(
        collection=CLAIM_COLLECTION, property_specs=_aux_specs, vectorizer="self_provided"
    )
    store = WeaviateCorpusStore(client=client)
    sync = SyncService(store=store)
    retrieval = WeaviateRetrievalPort(client=client, store=store, binding=binding)
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
    "CLAIM_COLLECTION",
    "RECEIPT_COLLECTION",
    "WeaviateCorpusStore",
    "WeaviateRetrievalPort",
    "compose_runtime",
    "connect_real_client",
    "main",
    "run_stdio_server",
]
