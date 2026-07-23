"""Bounded-window corpus sync (FK-13 §13.9.9, Review 174-P1-1, PO decision D3).

Generationskonsistenter Replace with a SHORT switch window -- NO CAS, NO
generation pointer (DR 2026-07-21 Rand 5). The order is binding:

1. write the new should-generation fully + validate the should-set;
2. delete old/foreign chunks of the SAME source only AFTER;
3. publish a digest-bound sync receipt with ``corpus_revision`` ONLY after a
   successful delete;
4. a crash before the receipt leaves the last completion marker unchanged; a
   retry recognises and cleans full/partial residue deterministically;
5. concurrent syncs of the same ``(project_id, source_file)`` are REJECTED
   fail-closed (D3 -- not serialized).

``full_reindex`` deletes ONLY the source-types owned by the calling tool within
the bound ``project_id`` (``story_sync`` never touches concept chunks & vice-
versa). The external Weaviate boundary is the :class:`CorpusStorePort`; fakes are
permitted ONLY there (the narrow mock exception).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from agentkit.backend.vectordb.ingest.classify import source_types_for_producer
from agentkit.backend.vectordb.schema import StoryContextObject, validate_object
from agentkit.concepts.hashing import sync_receipt_digest

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


class SyncError(RuntimeError):
    """Base error for corpus sync (fail-closed)."""


class ConcurrentSyncRejectedError(SyncError):
    """Two concurrent syncs of the same ``(project_id, source_file)`` (D3)."""


class ReceiptState(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


@dataclass(frozen=True)
class SyncReceipt:
    """Digest-bound sync completion marker (DR 2026-07-21 Rand 5)."""

    project_id: str
    source_file: str
    source_type: str
    corpus_revision: str
    digest: str
    state: ReceiptState

    @classmethod
    def for_completion(
        cls, project_id: str, source_file: str, source_type: str, corpus_revision: str
    ) -> SyncReceipt:
        digest = sync_receipt_digest(project_id, source_file, corpus_revision)
        return cls(
            project_id=project_id,
            source_file=source_file,
            source_type=source_type,
            corpus_revision=corpus_revision,
            digest=digest,
            state=ReceiptState.COMPLETED,
        )


@dataclass(frozen=True)
class SyncResult:
    """Outcome of one sync call (complete result/error envelope)."""

    project_id: str
    source_file: str
    source_type: str
    written: int
    deleted: int
    corpus_revision: str
    receipt_digest: str
    error: str = ""


@runtime_checkable
class CorpusStorePort(Protocol):
    """External boundary for corpus persistence (Weaviate adapter; fakes OK).

    Every method is project-scoped; no operation may touch another project.
    """

    def list_objects_for_source(
        self, *, project_id: str, source_file: str
    ) -> Sequence[Mapping[str, object]]:
        """Return existing objects (uuid + content_hash) for one source."""
        ...

    def list_objects_for_source_types(
        self, *, project_id: str, source_types: Sequence[str]
    ) -> Sequence[Mapping[str, object]]:
        """Return existing objects for a set of source_types (full_reindex scope)."""
        ...

    def upsert_objects(self, *, objects: Sequence[StoryContextObject]) -> int:
        """Insert/replace objects (deterministic uuids); return count written."""
        ...

    def delete_objects(self, *, uuids: Sequence[str]) -> int:
        """Delete objects by uuid; return count deleted."""
        ...

    def get_receipt(self, *, project_id: str, source_file: str) -> SyncReceipt | None:
        """Return the persisted receipt for a source (None if absent)."""
        ...

    def set_receipt(self, *, receipt: SyncReceipt) -> None:
        """Persist a receipt (in_progress or completed)."""
        ...


@dataclass
class SyncService:
    """Implements the bounded-window corpus sync against a :class:`CorpusStorePort`.

    The in-flight guard is per-process (thread-safe); D3's concurrent-reject is
    enforced for truly overlapping calls. Crash recovery is receipt-driven: a
    retry cleans residue deterministically (the should-set recomputation is the
    reconciliation).
    """

    store: CorpusStorePort
    _inflight: set[tuple[str, str]] = field(default_factory=set)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def sync_source(
        self,
        *,
        project_id: str,
        source_file: str,
        source_type: str,
        objects: Sequence[StoryContextObject],
        corpus_revision: str,
    ) -> SyncResult:
        """Sync one source through the bounded window (D3)."""
        key = (project_id, source_file)
        with self._lock:
            if key in self._inflight:
                raise ConcurrentSyncRejectedError(
                    f"concurrent sync of {(project_id, source_file)!r} rejected (D3)"
                )
            self._inflight.add(key)
        try:
            return self._sync_impl(
                project_id=project_id,
                source_file=source_file,
                source_type=source_type,
                objects=objects,
                corpus_revision=corpus_revision,
            )
        finally:
            with self._lock:
                self._inflight.discard(key)

    def full_reindex(
        self,
        *,
        project_id: str,
        producer: str,
        objects_by_source: Mapping[str, Sequence[StoryContextObject]],
        corpus_revision: str,
    ) -> list[SyncResult]:
        """Full reindex: delete ONLY the producer's source-types, then sync each source.

        ``story_sync(full_reindex=true)`` deletes only story+research chunks;
        ``concept_sync(full_reindex=true)`` deletes only concept chunks. The two
        are isolated within the bound ``project_id``.
        """
        owned = source_types_for_producer(producer)
        # Pre-delete the producer's source-types (scoped to project_id).
        existing = self.store.list_objects_for_source_types(
            project_id=project_id, source_types=owned
        )
        # Group existing by source_file to delete sources no longer present.
        present_sources = set(objects_by_source.keys())
        results: list[SyncResult] = []
        # Delete entire sources that vanished.
        vanished_sources = {
            str(o.get("source_file"))
            for o in existing
            if str(o.get("source_file")) not in present_sources
        }
        for vanished in vanished_sources:
            uuids = [str(o["uuid"]) for o in existing if str(o.get("source_file")) == vanished]
            self.store.delete_objects(uuids=uuids)
        # Sync each source through the window.
        for source_file, objs in objects_by_source.items():
            source_type = objs[0].properties["source_type"] if objs else ""
            results.append(
                self.sync_source(
                    project_id=project_id,
                    source_file=source_file,
                    source_type=str(source_type),
                    objects=objs,
                    corpus_revision=corpus_revision,
                )
            )
        return results

    def _sync_impl(
        self,
        *,
        project_id: str,
        source_file: str,
        source_type: str,
        objects: Sequence[StoryContextObject],
        corpus_revision: str,
    ) -> SyncResult:
        # Validate every object before any write (fail-closed, AC10).
        for obj in objects:
            validate_object(obj.properties)
            if obj.properties.get("source_type") != source_type:
                raise SyncError(
                    f"object source_type {obj.properties.get('source_type')!r} != {source_type!r}"
                )
        # (1) Write the new should-generation fully.
        should_uuids = {obj.uuid for obj in objects}
        self.store.upsert_objects(objects=objects)
        # (2) Delete old/foreign chunks of the SAME source AFTER.
        existing = self.store.list_objects_for_source(
            project_id=project_id, source_file=source_file
        )
        to_delete = [str(o["uuid"]) for o in existing if str(o["uuid"]) not in should_uuids]
        deleted = self.store.delete_objects(uuids=to_delete) if to_delete else 0
        # (3) Publish the digest-bound receipt ONLY after a successful delete.
        receipt = SyncReceipt.for_completion(
            project_id=project_id,
            source_file=source_file,
            source_type=source_type,
            corpus_revision=corpus_revision,
        )
        self.store.set_receipt(receipt=receipt)
        return SyncResult(
            project_id=project_id,
            source_file=source_file,
            source_type=source_type,
            written=len(objects),
            deleted=deleted,
            corpus_revision=corpus_revision,
            receipt_digest=receipt.digest,
        )


__all__ = [
    "ConcurrentSyncRejectedError",
    "CorpusStorePort",
    "ReceiptState",
    "SyncError",
    "SyncReceipt",
    "SyncResult",
    "SyncService",
]
