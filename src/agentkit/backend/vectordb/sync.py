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

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from agentkit.backend.vectordb.ingest.classify import source_types_for_producer
from agentkit.backend.vectordb.schema import (
    StoryContextObject,
    deterministic_uuid,
    validate_object,
)
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
    """Digest-bound sync completion marker (DR 2026-07-21 Rand 5).

    Attributes:
        completed_at: UTC completion timestamp (ISO-8601).
        sequence: Store-monotonic completion order. Assigned by the store on
            persist; ``0`` marks a not-yet-persisted receipt. The "latest"
            receipt is the highest sequence -- NOT a lexicographic maximum over
            content digests (N04).
    """

    project_id: str
    source_file: str
    source_type: str
    corpus_revision: str
    digest: str
    state: ReceiptState
    completed_at: str
    sequence: int = 0

    @classmethod
    def for_completion(
        cls,
        project_id: str,
        source_file: str,
        source_type: str,
        corpus_revision: str,
        *,
        completed_at: str | None = None,
    ) -> SyncReceipt:
        """Build the digest-bound completion receipt for one source."""
        digest = sync_receipt_digest(project_id, source_file, corpus_revision)
        return cls(
            project_id=project_id,
            source_file=source_file,
            source_type=source_type,
            corpus_revision=corpus_revision,
            digest=digest,
            state=ReceiptState.COMPLETED,
            completed_at=completed_at or _utc_now(),
        )

    def stamped(self, *, sequence: int) -> SyncReceipt:
        """Return a copy carrying the store-assigned completion sequence (N04)."""
        return replace(self, sequence=sequence)

    def verify(self) -> None:
        """Assert the receipt's mandatory fields and digest binding (N08).

        Raises:
            SyncError: When a mandatory field is empty or the digest does not
                match the ``(project_id, source_file, corpus_revision)`` anchor.
        """
        for name in ("project_id", "source_file", "source_type", "corpus_revision", "digest", "completed_at"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise SyncError(
                    f"sync receipt field {name!r} is empty/non-string ({value!r}); "
                    "fail-closed (N08)."
                )
        expected = sync_receipt_digest(self.project_id, self.source_file, self.corpus_revision)
        if self.digest != expected:
            raise SyncError(
                f"sync receipt digest {self.digest!r} does not bind "
                f"({self.project_id!r}, {self.source_file!r}, {self.corpus_revision!r}); "
                "fail-closed (N08)."
            )


def _utc_now() -> str:
    """Return the current UTC time as an ISO-8601 string with a ``Z`` suffix."""
    from datetime import UTC, datetime  # noqa: PLC0415

    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


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

    def list_receipts(self, *, project_id: str) -> Sequence[SyncReceipt]:
        """Return every VERIFIED persisted receipt of a project (N04/N08)."""
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
        results = self._delete_vanished_sources(
            project_id=project_id,
            producer=producer,
            objects_by_source=objects_by_source,
            corpus_revision=corpus_revision,
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
        count-verified AND reported in the returned counters (R12) -- an
        unreported delete would understate what the tool actually changed.
        """
        results = self._delete_vanished_sources(
            project_id=project_id,
            producer=producer,
            objects_by_source=objects_by_source,
            corpus_revision=corpus_revision,
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

    def _delete_vanished_sources(
        self,
        *,
        project_id: str,
        producer: str,
        objects_by_source: Mapping[str, Sequence[StoryContextObject]],
        corpus_revision: str,
    ) -> list[SyncResult]:
        """Delete every stored source of the producer that is no longer discovered.

        Shared by the incremental and the full-reindex path so BOTH report the
        vanished-source deletes in their counters (R12). The delete count is
        verified exactly; a partial delete raises before anything is reported as
        success.
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
            rows = [o for o in existing if str(o.get("source_file")) == vanished]
            uuids = [str(o["uuid"]) for o in rows]
            deleted = self.store.delete_objects(uuids=uuids) if uuids else 0
            if uuids and deleted != len(uuids):
                raise PartialWriteError(
                    f"partial delete for vanished source {vanished!r}: {deleted} of "
                    f"{len(uuids)} deleted (R12)."
                )
            results.append(
                SyncResult(
                    project_id=project_id,
                    source_file=vanished,
                    source_type=str(rows[0].get("source_type", "")) if rows else "",
                    written=0,
                    deleted=deleted,
                    corpus_revision=corpus_revision,
                    receipt_digest="",
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
        # Validate EVERY object BEFORE the first write (fail-closed, AC10/N13/D2):
        # project_id, source_file, source_type AND the deterministic identity must
        # match the sync target -- otherwise an object carrying a foreign
        # project_id would be written into another tenant's index before the
        # should-set comparison ever ran.
        _validate_objects_against_target(
            objects, project_id=project_id, source_file=source_file, source_type=source_type
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
            project_id, source_file, source_type, corpus_revision
        )
        receipt.verify()
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


def _validate_objects_against_target(
    objects: Sequence[StoryContextObject],
    *,
    project_id: str,
    source_file: str,
    source_type: str,
) -> None:
    """Fail closed on ANY object that does not belong to the sync target (N13).

    Checks, for every object and BEFORE any write:

    - the schema-required fields (:func:`validate_object`);
    - ``project_id`` equals the bound project (D2 -- no cross-project write);
    - ``source_file`` equals the source being synced;
    - ``source_type`` equals the declared source type;
    - the uuid is the deterministic ``(project_id, source_file, chunk_id)``
      identity, and no uuid repeats inside the batch.
    """
    seen: dict[str, str] = {}
    for obj in objects:
        validate_object(obj.properties)
        for field_name, expected in (
            ("project_id", project_id),
            ("source_file", source_file),
            ("source_type", source_type),
        ):
            actual = obj.properties.get(field_name)
            if actual != expected:
                raise SyncError(
                    f"object {obj.uuid!r} has {field_name}={actual!r} but the sync "
                    f"target is {expected!r}; fail-closed (N13/D2 -- no write)."
                )
        if not obj.chunk_id:
            raise SyncError(
                f"object {obj.uuid!r} carries no chunk_id; the deterministic "
                "identity cannot be verified (fail-closed, N13)."
            )
        expected_uuid = deterministic_uuid(project_id, source_file, obj.chunk_id)
        if obj.uuid != expected_uuid:
            raise SyncError(
                f"object identity mismatch: uuid {obj.uuid!r} is not the "
                f"deterministic identity of ({project_id!r}, {source_file!r}, "
                f"{obj.chunk_id!r}) = {expected_uuid!r}; fail-closed (N13)."
            )
        if obj.uuid in seen:
            raise SyncError(
                f"duplicate object uuid {obj.uuid!r} in the should-generation "
                f"(chunk_ids {seen[obj.uuid]!r} and {obj.chunk_id!r}); fail-closed (N13)."
            )
        seen[obj.uuid] = obj.chunk_id


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
