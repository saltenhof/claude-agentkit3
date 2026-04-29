"""Full and delta ingestion logic against the AK3 concept collections.

Two collections are kept in sync:

- ``Ak3ConceptChunk``  — H2-section level chunks of every concept doc.
- ``Ak3GlossaryTerm``  — one entry per exported/internal glossary term.

FULL drops and re-creates both; DELTA diffs each collection independently
by ``content_hash`` (chunks) / per-term hash (glossary terms).
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

import weaviate

from tools.concept_ingester.config import IngesterConfig
from tools.concept_ingester.discovery import (
    ConceptChunk,
    DiscoveryResult,
    GlossaryTerm,
    discover,
)
from tools.concept_ingester.schema import (
    CHUNK_COLLECTION_NAME,
    GLOSSARY_COLLECTION_NAME,
    drop_all_collections,
    ensure_all_collections,
)

if TYPE_CHECKING:
    from weaviate import WeaviateClient
    from weaviate.collections.collection import Collection


class IngestStrategy(str, Enum):
    FULL = "full"
    DELTA = "delta"


@dataclass(frozen=True)
class _CollectionReport:
    discovered: int
    inserted: int
    updated: int
    deleted: int
    skipped: int
    errors: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "discovered": self.discovered,
            "inserted": self.inserted,
            "updated": self.updated,
            "deleted": self.deleted,
            "skipped": self.skipped,
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class IngestReport:
    strategy: IngestStrategy
    chunks: _CollectionReport
    glossary: _CollectionReport
    schema_projection_version: str
    domain_registry_hash: str

    # Aggregated totals (kept for backwards-compatible readers).
    @property
    def discovered(self) -> int:
        return self.chunks.discovered + self.glossary.discovered

    @property
    def inserted(self) -> int:
        return self.chunks.inserted + self.glossary.inserted

    @property
    def updated(self) -> int:
        return self.chunks.updated + self.glossary.updated

    @property
    def deleted(self) -> int:
        return self.chunks.deleted + self.glossary.deleted

    @property
    def skipped(self) -> int:
        return self.chunks.skipped + self.glossary.skipped

    @property
    def errors(self) -> tuple[str, ...]:
        return self.chunks.errors + self.glossary.errors

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy.value,
            "schema_projection_version": self.schema_projection_version,
            "domain_registry_hash": self.domain_registry_hash,
            "chunks": self.chunks.as_dict(),
            "glossary": self.glossary.as_dict(),
            "totals": {
                "discovered": self.discovered,
                "inserted": self.inserted,
                "updated": self.updated,
                "deleted": self.deleted,
                "skipped": self.skipped,
                "errors": list(self.errors),
            },
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
    result = discover(cfg.concept_root, max_chars=cfg.chunk_max_chars)
    with open_client(cfg) as client:
        if strategy is IngestStrategy.FULL:
            drop_all_collections(client)
        ensure_all_collections(client)
        chunk_coll = client.collections.get(CHUNK_COLLECTION_NAME)
        glossary_coll = client.collections.get(GLOSSARY_COLLECTION_NAME)
        if strategy is IngestStrategy.FULL:
            chunk_report = _ingest_chunks_full(chunk_coll, result.chunks)
            glossary_report = _ingest_glossary_full(glossary_coll, result.glossary_terms)
        else:
            chunk_report = _ingest_chunks_delta(chunk_coll, result.chunks)
            glossary_report = _ingest_glossary_delta(glossary_coll, result.glossary_terms)
    return IngestReport(
        strategy=strategy,
        chunks=chunk_report,
        glossary=glossary_report,
        schema_projection_version=result.schema_projection_version,
        domain_registry_hash=result.domain_registry_hash,
    )


# ---------------------------------------------------------------------------
# Chunk ingest
# ---------------------------------------------------------------------------


def _ingest_chunks_full(
    collection: Collection,
    chunks: list[ConceptChunk],
) -> _CollectionReport:
    inserted, errors = _bulk_insert(
        collection,
        objects=chunks,
        uuid_of=lambda c: c.chunk_id,
        properties_of=_to_chunk_properties,
        kind="chunk",
    )
    return _CollectionReport(
        discovered=len(chunks),
        inserted=inserted,
        updated=0,
        deleted=0,
        skipped=0,
        errors=errors,
    )


def _ingest_chunks_delta(
    collection: Collection,
    chunks: list[ConceptChunk],
) -> _CollectionReport:
    remote = _fetch_remote_state(collection)
    local_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    return _delta_apply(
        collection=collection,
        local_by_id=local_by_id,
        local_hash=lambda c: c.content_hash,
        remote=remote,
        properties_of=_to_chunk_properties,
        kind="chunk",
    )


# ---------------------------------------------------------------------------
# Glossary ingest
# ---------------------------------------------------------------------------


def _ingest_glossary_full(
    collection: Collection,
    terms: list[GlossaryTerm],
) -> _CollectionReport:
    inserted, errors = _bulk_insert(
        collection,
        objects=terms,
        uuid_of=lambda t: t.term_uuid,
        properties_of=_to_glossary_properties,
        kind="glossary",
    )
    return _CollectionReport(
        discovered=len(terms),
        inserted=inserted,
        updated=0,
        deleted=0,
        skipped=0,
        errors=errors,
    )


def _ingest_glossary_delta(
    collection: Collection,
    terms: list[GlossaryTerm],
) -> _CollectionReport:
    remote = _fetch_remote_state(collection)
    local_by_id = {term.term_uuid: term for term in terms}
    return _delta_apply(
        collection=collection,
        local_by_id=local_by_id,
        local_hash=lambda t: t.content_hash,
        remote=remote,
        properties_of=_to_glossary_properties,
        kind="glossary",
    )


# ---------------------------------------------------------------------------
# Generic delta application
# ---------------------------------------------------------------------------


def _delta_apply(
    collection: Collection,
    local_by_id: dict[str, Any],
    local_hash: Any,
    remote: dict[str, str],
    properties_of: Any,
    kind: str,
) -> _CollectionReport:
    to_insert: list[Any] = []
    to_replace: list[Any] = []
    skipped = 0
    for uid, obj in local_by_id.items():
        remote_hash = remote.get(uid)
        if remote_hash is None:
            to_insert.append(obj)
        elif remote_hash != local_hash(obj):
            to_replace.append(obj)
        else:
            skipped += 1

    to_delete = [uid for uid in remote if uid not in local_by_id]

    errors: list[str] = []
    inserted, ins_errors = _bulk_insert(
        collection,
        objects=to_insert,
        uuid_of=_uuid_of_for(kind),
        properties_of=properties_of,
        kind=kind,
    )
    errors.extend(ins_errors)
    updated, upd_errors = _bulk_replace(
        collection,
        objects=to_replace,
        uuid_of=_uuid_of_for(kind),
        properties_of=properties_of,
        kind=kind,
    )
    errors.extend(upd_errors)
    deleted, del_errors = _bulk_delete(collection, to_delete, kind=kind)
    errors.extend(del_errors)

    return _CollectionReport(
        discovered=len(local_by_id),
        inserted=inserted,
        updated=updated,
        deleted=deleted,
        skipped=skipped,
        errors=tuple(errors),
    )


def _uuid_of_for(kind: str) -> Any:
    if kind == "chunk":
        return lambda c: c.chunk_id
    return lambda t: t.term_uuid


# ---------------------------------------------------------------------------
# Weaviate primitives
# ---------------------------------------------------------------------------


def _fetch_remote_state(collection: Collection) -> dict[str, str]:
    remote: dict[str, str] = {}
    for obj in collection.iterator(return_properties=["content_hash"]):
        props = obj.properties or {}
        remote[str(obj.uuid)] = str(props.get("content_hash", ""))
    return remote


def _bulk_insert(
    collection: Collection,
    objects: list[Any],
    uuid_of: Any,
    properties_of: Any,
    kind: str,
) -> tuple[int, tuple[str, ...]]:
    if not objects:
        return 0, ()
    errors: list[str] = []
    with collection.batch.dynamic() as batch:
        for obj in objects:
            batch.add_object(properties=properties_of(obj), uuid=uuid_of(obj))
    failed = collection.batch.failed_objects
    for failure in failed:
        errors.append(_format_failure(failure, kind))
    inserted = len(objects) - len(failed)
    return inserted, tuple(errors)


def _bulk_replace(
    collection: Collection,
    objects: list[Any],
    uuid_of: Any,
    properties_of: Any,
    kind: str,
) -> tuple[int, tuple[str, ...]]:
    if not objects:
        return 0, ()
    errors: list[str] = []
    updated = 0
    for obj in objects:
        try:
            collection.data.replace(uuid=uuid_of(obj), properties=properties_of(obj))
            updated += 1
        except Exception as exc:  # noqa: BLE001 - we report and continue
            errors.append(f"replace {kind} {uuid_of(obj)}: {exc}")
    return updated, tuple(errors)


def _bulk_delete(
    collection: Collection,
    uuids: list[str],
    kind: str,
) -> tuple[int, tuple[str, ...]]:
    if not uuids:
        return 0, ()
    errors: list[str] = []
    deleted = 0
    for uid in uuids:
        try:
            collection.data.delete_by_id(uid)
            deleted += 1
        except Exception as exc:  # noqa: BLE001 - we report and continue
            errors.append(f"delete {kind} {uid}: {exc}")
    return deleted, tuple(errors)


# ---------------------------------------------------------------------------
# Property mappings
# ---------------------------------------------------------------------------


def _to_chunk_properties(chunk: ConceptChunk) -> dict[str, Any]:
    return {
        # Identity / structural
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
        # Bounded-context filters
        "domain": chunk.domain,
        "cross_cutting": chunk.cross_cutting,
        "surface": chunk.surface,
        "domain_display_name": chunk.domain_display_name,
        "contract_state": chunk.contract_state,
        "applies_policies": list(chunk.applies_policies),
        # Reference graph
        "defers_to_ids": list(chunk.defers_to_ids),
        "defers_to_edges": list(chunk.defers_to_edges),
        "formal_ref_ids": list(chunk.formal_ref_ids),
        "supersedes_ids": list(chunk.supersedes_ids),
        "superseded_by_id": chunk.superseded_by_id,
        "authority_scopes": list(chunk.authority_scopes),
        # Glossary linkage
        "has_glossary": chunk.has_glossary,
        "exported_term_ids": list(chunk.exported_term_ids),
        # Migration / drift tracking
        "schema_projection_version": chunk.schema_projection_version,
        "domain_registry_hash": chunk.domain_registry_hash,
        # Nested non-query payload
        "metadata": _metadata_object(chunk.metadata),
    }


def _to_glossary_properties(term: GlossaryTerm) -> dict[str, Any]:
    return {
        "term_id": term.term_id,
        "term": term.term,
        "normalized_term": term.normalized_term,
        "definition": term.definition,
        "term_kind": term.term_kind,
        "domain": term.domain,
        "domain_display_name": term.domain_display_name,
        "source_doc_id": term.source_doc_id,
        "source_section_anchor": term.source_section_anchor,
        "see_also_terms": list(term.see_also_terms),
        "contract_state": term.contract_state,
        "values": list(term.values),
        "reason": term.reason,
        "content_hash": term.content_hash,
        "file_mtime": term.file_mtime,
        "schema_projection_version": term.schema_projection_version,
        "domain_registry_hash": term.domain_registry_hash,
    }


_METADATA_KEYS: tuple[str, ...] = (
    "doc_kind",
    "status",
    "spec_kind",
    "context",
    "version",
    "parent_concept_id",
    "formal_scope",
    "prose_anchor_policy",
    "migration_ack",
    "defers_to_full",
    "supersedes_full",
    "authority_over_full",
)


def _metadata_object(metadata: dict[str, Any]) -> dict[str, str]:
    """Coerce the metadata dict to the nested-object shape Weaviate expects."""
    obj: dict[str, str] = {}
    for key in _METADATA_KEYS:
        value = metadata.get(key, "")
        obj[key] = value if isinstance(value, str) else str(value)
    return obj


def _format_failure(failure: Any, kind: str) -> str:
    obj = getattr(failure, "object_", None)
    uid = getattr(obj, "uuid", None) if obj is not None else None
    message = getattr(failure, "message", str(failure))
    return f"insert {kind} {uid}: {message}"
