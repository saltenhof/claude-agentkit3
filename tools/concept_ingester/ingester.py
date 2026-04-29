"""Full and delta ingestion logic against a Weaviate collection."""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

import weaviate

from tools.concept_ingester.config import IngesterConfig
from tools.concept_ingester.discovery import ConceptChunk, discover_chunks
from tools.concept_ingester.schema import drop_collection, ensure_collection

if TYPE_CHECKING:
    from weaviate import WeaviateClient
    from weaviate.collections.collection import Collection


class IngestStrategy(str, Enum):
    FULL = "full"
    DELTA = "delta"


@dataclass(frozen=True)
class IngestReport:
    strategy: IngestStrategy
    discovered: int
    inserted: int
    updated: int
    deleted: int
    skipped: int
    errors: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy.value,
            "discovered": self.discovered,
            "inserted": self.inserted,
            "updated": self.updated,
            "deleted": self.deleted,
            "skipped": self.skipped,
            "errors": list(self.errors),
        }


@contextlib.contextmanager
def open_client(config: IngesterConfig) -> Iterator[WeaviateClient]:
    client = weaviate.connect_to_local(
        host=config.weaviate_host,
        port=config.weaviate_http_port,
        grpc_port=config.weaviate_grpc_port,
    )
    try:
        yield client
    finally:
        client.close()


def run_ingest(strategy: IngestStrategy, config: IngesterConfig | None = None) -> IngestReport:
    cfg = config or IngesterConfig.from_env()
    chunks = discover_chunks(cfg.concept_root, max_chars=cfg.chunk_max_chars)
    with open_client(cfg) as client:
        if strategy is IngestStrategy.FULL:
            drop_collection(client, cfg.collection_name)
        ensure_collection(client, cfg.collection_name)
        collection = client.collections.get(cfg.collection_name)
        if strategy is IngestStrategy.FULL:
            return _ingest_full(collection, chunks)
        return _ingest_delta(collection, chunks)


def _ingest_full(collection: Collection, chunks: list[ConceptChunk]) -> IngestReport:
    inserted, errors = _bulk_insert(collection, chunks)
    return IngestReport(
        strategy=IngestStrategy.FULL,
        discovered=len(chunks),
        inserted=inserted,
        updated=0,
        deleted=0,
        skipped=0,
        errors=errors,
    )


def _ingest_delta(collection: Collection, chunks: list[ConceptChunk]) -> IngestReport:
    remote = _fetch_remote_state(collection)
    local_by_id = {chunk.chunk_id: chunk for chunk in chunks}

    to_insert: list[ConceptChunk] = []
    to_replace: list[ConceptChunk] = []
    skipped = 0
    for chunk_id, chunk in local_by_id.items():
        remote_hash = remote.get(chunk_id)
        if remote_hash is None:
            to_insert.append(chunk)
        elif remote_hash != chunk.content_hash:
            to_replace.append(chunk)
        else:
            skipped += 1

    to_delete = [uid for uid in remote if uid not in local_by_id]

    errors: list[str] = []
    inserted, ins_errors = _bulk_insert(collection, to_insert)
    errors.extend(ins_errors)
    updated, upd_errors = _bulk_replace(collection, to_replace)
    errors.extend(upd_errors)
    deleted, del_errors = _bulk_delete(collection, to_delete)
    errors.extend(del_errors)

    return IngestReport(
        strategy=IngestStrategy.DELTA,
        discovered=len(chunks),
        inserted=inserted,
        updated=updated,
        deleted=deleted,
        skipped=skipped,
        errors=tuple(errors),
    )


def _fetch_remote_state(collection: Collection) -> dict[str, str]:
    remote: dict[str, str] = {}
    for obj in collection.iterator(return_properties=["content_hash"]):
        props = obj.properties or {}
        remote[str(obj.uuid)] = str(props.get("content_hash", ""))
    return remote


def _bulk_insert(collection: Collection, chunks: list[ConceptChunk]) -> tuple[int, tuple[str, ...]]:
    if not chunks:
        return 0, ()
    errors: list[str] = []
    with collection.batch.dynamic() as batch:
        for chunk in chunks:
            batch.add_object(properties=_to_properties(chunk), uuid=chunk.chunk_id)
    failed = collection.batch.failed_objects
    for failure in failed:
        errors.append(_format_failure(failure))
    inserted = len(chunks) - len(failed)
    return inserted, tuple(errors)


def _bulk_replace(collection: Collection, chunks: list[ConceptChunk]) -> tuple[int, tuple[str, ...]]:
    if not chunks:
        return 0, ()
    errors: list[str] = []
    updated = 0
    for chunk in chunks:
        try:
            collection.data.replace(uuid=chunk.chunk_id, properties=_to_properties(chunk))
            updated += 1
        except Exception as exc:  # noqa: BLE001 - we report and continue
            errors.append(f"replace {chunk.chunk_id}: {exc}")
    return updated, tuple(errors)


def _bulk_delete(collection: Collection, uuids: list[str]) -> tuple[int, tuple[str, ...]]:
    if not uuids:
        return 0, ()
    errors: list[str] = []
    deleted = 0
    for uid in uuids:
        try:
            collection.data.delete_by_id(uid)
            deleted += 1
        except Exception as exc:  # noqa: BLE001 - we report and continue
            errors.append(f"delete {uid}: {exc}")
    return deleted, tuple(errors)


def _to_properties(chunk: ConceptChunk) -> dict[str, Any]:
    props: dict[str, Any] = {
        "layer": chunk.layer,
        "doc_id": chunk.doc_id,
        "title": chunk.title,
        "module": chunk.module,
        "tags": list(chunk.tags),
        "rel_path": chunk.rel_path,
        "section_anchor": chunk.section_anchor,
        "heading": chunk.heading,
        "ordering": chunk.ordering,
        "content": chunk.content,
        "content_hash": chunk.content_hash,
        "file_mtime": chunk.file_mtime,
    }
    if chunk.extra:
        props["extra"] = {k: _stringify(v) for k, v in chunk.extra.items()}
    return props


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    return str(value)


def _format_failure(failure: Any) -> str:
    obj = getattr(failure, "object_", None)
    uid = getattr(obj, "uuid", None) if obj is not None else None
    message = getattr(failure, "message", str(failure))
    return f"insert {uid}: {message}"
