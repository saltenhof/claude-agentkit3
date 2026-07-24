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

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from agentkit.backend.vectordb.ingest.classify import source_types_for_producer
from agentkit.backend.vectordb.schema import StoryContextObject, validate_object
from agentkit.concepts.hashing import sync_receipt_digest

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


class SyncError(RuntimeError):
    """Base error for corpus sync (fail-closed)."""


class PartialWriteError(SyncError):
    """A transport write/delete was incomplete (R12: never advance freshness)."""


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
        """Insert/replace objects (deterministic uuids); return the EXACT count
        of objects confirmed written (R12). A return value below
        ``len(objects)`` indicates a partial batch and MUST NOT be reported as
        success; batch failures are surfaced as a lower count, not an exception,
        so the SyncService can reject the partial window fail-closed."""
        ...

    def delete_objects(self, *, uuids: Sequence[str]) -> int:
        """Delete objects by uuid; return the EXACT count confirmed deleted (R12)."""
        ...

    def get_receipt(self, *, project_id: str, source_file: str) -> SyncReceipt | None:
        """Return the persisted receipt for a source (None if absent)."""
        ...

    def set_receipt(self, *, receipt: SyncReceipt) -> None:
        """Persist a receipt (in_progress or completed)."""
        ...

    def try_claim_source(self, *, project_id: str, source_file: str) -> bool:
        """Atomically claim a source for syncing (D3, N03).

        Returns ``True`` if the claim was acquired (no other writer holds it),
        ``False`` if another writer (any process) already claims this
        ``(project_id, source_file)``. The claim is STORE-LEVEL / shared -- it
        must NOT be process-local, so two service instances over one shared store
        cannot both write the same source.
        """
        ...

    def release_source(self, *, project_id: str, source_file: str) -> None:
        """Release a previously acquired source claim (N03)."""
        ...


@dataclass
class SyncService:
    """Implements the bounded-window corpus sync against a :class:`CorpusStorePort`.

    D3's concurrent-reject is enforced via a STORE-LEVEL atomic source claim
    (N03): two service instances over one shared store cannot both write the same
    ``(project_id, source_file)`` -- the loser is REJECTED fail-closed (not
    serialized). Partial writes/deletes anywhere are rejected before the receipt
    is published (R12).
    """

    store: CorpusStorePort

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
        if not self.store.try_claim_source(project_id=project_id, source_file=source_file):
            raise ConcurrentSyncRejectedError(
                f"concurrent sync of {(project_id, source_file)!r} rejected (D3/N03)"
            )
        try:
            return self._sync_impl(
                project_id=project_id,
                source_file=source_file,
                source_type=source_type,
                objects=objects,
                corpus_revision=corpus_revision,
            )
        finally:
            self.store.release_source(project_id=project_id, source_file=source_file)

    def reconcile_sources(
        self,
        *,
        project_id: str,
        producer: str,
        objects_by_source: Mapping[str, Sequence[StoryContextObject]],
        corpus_revision: str,
    ) -> list[SyncResult]:
        """Incremental reconcile: sync present sources AND delete vanished ones.

        For each present source the bounded window writes the new generation and
        deletes the old. Sources that existed in the store for the producer's
        source-types but are no longer discovered are deleted (delete closure,
        R05). Does NOT touch other producers' source-types.
        """
        owned = source_types_for_producer(producer)
        existing = self.store.list_objects_for_source_types(
            project_id=project_id, source_types=owned
        )
        present_sources = set(objects_by_source.keys())
        vanished_sources = {
            str(o.get("source_file"))
            for o in existing
            if str(o.get("source_file")) not in present_sources
        }
        results: list[SyncResult] = []
        for vanished in sorted(vanished_sources):
            uuids = [str(o["uuid"]) for o in existing if str(o.get("source_file")) == vanished]
            deleted = self.store.delete_objects(uuids=uuids) if uuids else 0
            if uuids and deleted != len(uuids):
                raise PartialWriteError(
                    f"partial delete for vanished source {vanished!r}: {deleted} of "
                    f"{len(uuids)} deleted (R12)."
                )
            source_type = str(next((o.get("source_type") for o in existing if str(o.get("source_file")) == vanished), ""))
            results.append(
                SyncResult(
                    project_id=project_id,
                    source_file=vanished,
                    source_type=source_type,
                    written=0,
                    deleted=deleted,
                    corpus_revision=corpus_revision,
                    receipt_digest="",
                )
            )
        for source_file, objs in objects_by_source.items():
            source_type = str(objs[0].properties["source_type"]) if objs else ""
            results.append(
                self.sync_source(
                    project_id=project_id,
                    source_file=source_file,
                    source_type=source_type,
                    objects=objs,
                    corpus_revision=corpus_revision,
                )
            )
        return results

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
        are isolated within the bound ``project_id``. Vanished-source deletes are
        count-verified (R12).
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
            deleted = self.store.delete_objects(uuids=uuids) if uuids else 0
            if uuids and deleted != len(uuids):
                raise PartialWriteError(
                    f"partial delete for vanished source {vanished!r}: {deleted} of "
                    f"{len(uuids)} deleted (R12)."
                )
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
        # (1) Write the new should-generation fully + verify EXACT transport count.
        should_uuids = {obj.uuid for obj in objects}
        written = self.store.upsert_objects(objects=objects)
        if written != len(objects):
            raise PartialWriteError(
                f"partial write for {source_file!r}: transport reported {written} of "
                f"{len(objects)} objects; generation incomplete (R12)."
            )
        # Re-read the persisted should-set and prove full equality BEFORE deleting
        # old: every new-generation UUID must be present (R12).
        persisted = self.store.list_objects_for_source(
            project_id=project_id, source_file=source_file
        )
        persisted_uuids = {str(o["uuid"]) for o in persisted}
        missing = should_uuids - persisted_uuids
        if missing:
            raise PartialWriteError(
                f"should-set not persisted for {source_file!r}: {len(missing)} of "
                f"{len(should_uuids)} new UUIDs absent after write (R12)."
            )
        # (2) Delete old/foreign chunks of the SAME source AFTER + verify count.
        to_delete = [uid for uid in persisted_uuids if uid not in should_uuids]
        deleted = self.store.delete_objects(uuids=to_delete) if to_delete else 0
        if deleted != len(to_delete):
            raise PartialWriteError(
                f"partial delete for {source_file!r}: transport reported {deleted} of "
                f"{len(to_delete)} old UUIDs deleted (R12)."
            )
        # (3) Publish the digest-bound receipt ONLY after a verified full window.
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
            written=written,
            deleted=deleted,
            corpus_revision=corpus_revision,
            receipt_digest=receipt.digest,
        )


__all__ = [
    "ConcurrentSyncRejectedError",
    "CorpusStorePort",
    "PartialWriteError",
    "ReceiptState",
    "SyncError",
    "SyncReceipt",
    "SyncResult",
    "SyncService",
]
