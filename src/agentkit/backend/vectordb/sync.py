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

import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable

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


class ClaimSupersededError(SyncError):
    """The source claim was taken over while the window was open (N15 fence)."""


class ReceiptState(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


@dataclass(frozen=True)
class SourceClaim:
    """A held, fenced claim on one ``(project_id, source_file)`` (N15/N27/D3).

    A claim NEVER expires by time (N27/D3: the concurrent-sync rejection admits no
    time-based exception, and Weaviate cannot fence a mutation atomically on an
    epoch). A claim left behind by a crashed writer is released by an EXPLICIT
    ADMINISTRATIVE RECLAIM only -- the operator asserts the previous writer is
    dead. Every mutation is preceded by a fence check, so a resumed previous holder
    aborts at its next step instead of writing stale chunks.

    Attributes:
        owner_id: Identity of the holding writer (one id per ``SyncService``
            instance, so two writers in ONE process still conflict).
        epoch: Monotonic claim generation. A reclaim CREATES the next epoch, never
            deletes and re-creates the same record, so the store itself picks a
            single winner.
        claimed_at: UTC instant the claim was acquired (diagnostics only -- it is
            NOT an expiry).
        reclaimed_from: The owner this claim was administratively taken from
            (``""`` for a normal acquisition).
    """

    project_id: str
    source_file: str
    owner_id: str
    epoch: int
    claimed_at: str
    reclaimed_from: str = ""


#: Every receipt field that MUST carry a non-blank value for a completion to be
#: publishable (N08). The first four are supplied by the CALLER, so they are also
#: the pre-mutation gate of every sync path (N34); ``digest``/``completed_at`` are
#: produced when the store seals the receipt.
RECEIPT_MANDATORY_FIELDS: Final[tuple[str, ...]] = (
    "project_id",
    "source_file",
    "source_type",
    "corpus_revision",
    "digest",
    "completed_at",
)

#: The subset of :data:`RECEIPT_MANDATORY_FIELDS` the caller of a sync supplies.
COMPLETION_INPUT_FIELDS: Final[tuple[str, ...]] = (
    "project_id",
    "source_file",
    "source_type",
    "corpus_revision",
)


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
        """Build an UNSTAMPED completion receipt for one source.

        The digest can only be computed once the store has assigned the atomic
        completion ``sequence`` (it is part of the binding, N16), so the receipt
        leaves this constructor with ``sequence=0`` and an empty digest and is
        sealed by :meth:`stamped`.
        """
        return cls(
            project_id=project_id,
            source_file=source_file,
            source_type=source_type,
            corpus_revision=corpus_revision,
            digest="",
            state=ReceiptState.COMPLETED,
            completed_at=completed_at or utc_now(),
        )

    def stamped(self, *, sequence: int) -> SyncReceipt:
        """Return the sealed receipt: atomic sequence + digest over ALL fields."""
        if sequence < 1:
            raise SyncError(f"receipt sequence must be >= 1, got {sequence} (N16).")
        sealed = replace(self, sequence=sequence)
        return replace(sealed, digest=sealed.expected_digest())

    def expected_digest(self) -> str:
        """Return the digest this receipt's own fields must bind to (N16)."""
        return sync_receipt_digest(
            project_id=self.project_id,
            source_file=self.source_file,
            source_type=self.source_type,
            corpus_revision=self.corpus_revision,
            state=self.state.value,
            completed_at=self.completed_at,
            sequence=self.sequence,
        )

    def verify(self) -> None:
        """Assert the receipt's mandatory fields, timestamp and digest (N08/N16).

        Raises:
            SyncError: When a mandatory field is empty, the timestamp is not a
                UTC ISO-8601 instant, the sequence is not positive, or the digest
                does not bind every identity and ordering field.
        """
        for name in RECEIPT_MANDATORY_FIELDS:
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise SyncError(
                    f"sync receipt field {name!r} is empty/non-string ({value!r}); "
                    "fail-closed (N08)."
                )
        if self.sequence < 1:
            raise SyncError(
                f"sync receipt sequence {self.sequence} is not a positive completion "
                "order (fail-closed, N16)."
            )
        parse_utc_timestamp(self.completed_at)
        expected = self.expected_digest()
        if self.digest != expected:
            raise SyncError(
                f"sync receipt digest {self.digest!r} does not bind its own fields "
                f"(expected {expected!r}); fail-closed (N08/N16: identity AND "
                "ordering fields are part of the binding)."
            )


def utc_now() -> str:
    """Return the current UTC time as an ISO-8601 string with a ``Z`` suffix."""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def parse_utc_timestamp(value: str) -> datetime:
    """Parse a strict UTC ISO-8601 instant (fail-closed, no naive timestamps).

    Raises:
        SyncError: When the value is not parseable or carries no UTC offset.
    """
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SyncError(
            f"timestamp {value!r} is not an ISO-8601 instant (fail-closed, N16)."
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise SyncError(
            f"timestamp {value!r} is not UTC (fail-closed, N16)."
        )
    return parsed


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

    def set_receipt(self, *, receipt: SyncReceipt) -> SyncReceipt:
        """Persist a receipt and return it SEALED (atomic sequence + digest, N16)."""
        ...

    def try_claim_source(
        self, *, project_id: str, source_file: str, owner_id: str
    ) -> SourceClaim | None:
        """Atomically claim a source for syncing (D3, N03, N15, N27).

        Returns the held :class:`SourceClaim` when the claim was acquired, or
        ``None`` when ANY claim on this ``(project_id, source_file)`` already
        exists -- with no time-based exception (N27/D3). The claim is STORE-LEVEL /
        shared (never process-local).
        """
        ...

    def reclaim_source(
        self, *, project_id: str, source_file: str, owner_id: str, reason: str
    ) -> SourceClaim:
        """ADMINISTRATIVELY take over a source claim (N27).

        The caller asserts that the previous holder is dead. The takeover creates
        the NEXT epoch, so the previous holder is fenced out of every further
        mutation. Never called implicitly -- only from an explicit operator path.
        """
        ...

    def assert_claim_held(self, *, claim: SourceClaim) -> None:
        """Fence: raise when ``claim`` is no longer the active claim (N15).

        Raises:
            ClaimSupersededError: When a newer epoch or another owner took over.
        """
        ...

    def release_source(self, *, claim: SourceClaim) -> None:
        """Release a previously acquired source claim (N03)."""
        ...


#: Reason recorded on an administrative reclaim triggered by the operator path.
ADMIN_RECLAIM_REASON: Final[str] = "operator asserted the previous writer is dead"


@dataclass
class SyncService:
    """Implements the bounded-window corpus sync against a :class:`CorpusStorePort`.

    D3's concurrent-reject is enforced via a STORE-LEVEL atomic source claim
    (N03/N15/N27): two service instances over one shared store cannot both write
    the same ``(project_id, source_file)`` -- the loser is REJECTED fail-closed
    (not serialized, and with NO time-based exception). ``owner_id`` is per SERVICE
    INSTANCE, so two writers inside one process still conflict.

    A claim left behind by a crashed writer is released only by an EXPLICIT
    administrative reclaim (``reclaim=True``, driven by an operator command), which
    creates the next epoch and thereby fences the previous holder out of every
    further mutation. Partial writes/deletes anywhere are rejected before the
    receipt is published (R12), EVERY object is validated before the first mutation
    of a run (N17), and every mutation is preceded by a fence check (N27).
    """

    store: CorpusStorePort
    owner_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    #: Explicit ADMINISTRATIVE takeover of a foreign claim (N27). Never defaulted
    #: on: the operator asserts that the previous writer is dead.
    reclaim: bool = False

    def sync_source(
        self,
        *,
        project_id: str,
        source_file: str,
        source_type: str,
        objects: Sequence[StoryContextObject],
        corpus_revision: str,
    ) -> SyncResult:
        """Sync one source through the bounded window (D3).

        Validation runs BEFORE the claim is written (N17/N34): the claim record is
        a mutation, so neither an invalid object set NOR an unpublishable
        completion may leave one behind.
        """
        if not objects:
            raise SyncError(
                f"source {source_file!r} carries no objects; an empty generation is "
                "not a sync target (remove a source through the vanished-source "
                "path). Fail-closed (N29)."
            )
        _validate_completion_inputs(
            project_id=project_id,
            source_file=source_file,
            source_type=source_type,
            corpus_revision=corpus_revision,
        )
        _validate_objects_against_target(
            objects, project_id=project_id, source_file=source_file, source_type=source_type
        )
        claim = self._claim(project_id=project_id, source_file=source_file)
        try:
            return self._sync_impl(
                claim=claim,
                source_type=source_type,
                objects=objects,
                corpus_revision=corpus_revision,
            )
        finally:
            self.store.release_source(claim=claim)

    def _claim(self, *, project_id: str, source_file: str) -> SourceClaim:
        """Acquire the store-level source claim or reject fail-closed (D3/N27).

        A held claim is NEVER taken over implicitly -- not after any amount of
        time. Only the explicit administrative ``reclaim`` flag takes it over.
        """
        claim = self.store.try_claim_source(
            project_id=project_id, source_file=source_file, owner_id=self.owner_id
        )
        if claim is not None:
            return claim
        if not self.reclaim:
            raise ConcurrentSyncRejectedError(
                f"concurrent sync of {(project_id, source_file)!r} rejected (D3/N03); "
                "a claim left behind by a dead writer requires an EXPLICIT "
                "administrative reclaim (N27) -- it never expires by time."
            )
        return self.store.reclaim_source(
            project_id=project_id,
            source_file=source_file,
            owner_id=self.owner_id,
            reason=ADMIN_RECLAIM_REASON,
        )

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

        The COMPLETE incoming matrix is validated before the FIRST mutation
        (N17), INCLUDING the completion inputs every source would publish (N34) --
        the vanished-source delete below is a mutation too.
        """
        _validate_matrix(project_id, producer, objects_by_source, corpus_revision)
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

        The COMPLETE incoming matrix is validated before the FIRST mutation
        (N17), INCLUDING the completion inputs every source would publish (N34) --
        the vanished-source delete below is a mutation too.
        """
        _validate_matrix(project_id, producer, objects_by_source, corpus_revision)
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
        vanished-source deletes in their counters (R12). Every vanished source is
        CLAIMED before it is mutated (N15/D3) -- a delete is a mutation of that
        source just like a write. The delete count is verified exactly; a partial
        delete raises before anything is reported as success.
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
            claim = self._claim(project_id=project_id, source_file=vanished)
            try:
                # FENCE BEFORE the delete (N27): a writer whose claim was
                # administratively taken over must not mutate the source at all --
                # checking afterwards would already have destroyed the generation.
                self.store.assert_claim_held(claim=claim)
                deleted = self.store.delete_objects(uuids=uuids) if uuids else 0
                if uuids and deleted != len(uuids):
                    raise PartialWriteError(
                        f"partial delete for vanished source {vanished!r}: {deleted} of "
                        f"{len(uuids)} deleted (R12)."
                    )
            finally:
                self.store.release_source(claim=claim)
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
        claim: SourceClaim,
        source_type: str,
        objects: Sequence[StoryContextObject],
        corpus_revision: str,
    ) -> SyncResult:
        # Objects were validated BEFORE the claim was written (N17); the claim is
        # itself a mutation, so nothing may be written before validation passes.
        project_id = claim.project_id
        source_file = claim.source_file
        # (1) FENCE BEFORE THE FIRST WRITE (N27): if this writer's claim was
        # administratively taken over while it was paused, it must not write stale
        # chunks at all -- the previous implementation fenced only AFTER the upsert.
        self.store.assert_claim_held(claim=claim)
        # Write the new should-generation fully + verify EXACT transport count.
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
        # (2) FENCE again before the delete: the new owner may still need the old
        # generation (N15/N27).
        self.store.assert_claim_held(claim=claim)
        # Delete old/foreign chunks of the SAME source AFTER + verify count.
        to_delete = [uid for uid in persisted_uuids if uid not in should_uuids]
        deleted = self.store.delete_objects(uuids=to_delete) if to_delete else 0
        if deleted != len(to_delete):
            raise PartialWriteError(
                f"partial delete for {source_file!r}: transport reported {deleted} of "
                f"{len(to_delete)} old UUIDs deleted (R12)."
            )
        # (3) FENCE a third time before publishing: if the claim was taken over
        # while the window was open, this writer's generation is no longer
        # authoritative and it must NOT publish a completion (N15/N27).
        self.store.assert_claim_held(claim=claim)
        # (4) Publish the completion ONLY after a verified full window. The store
        # establishes the completion order and the identity in ONE immutable
        # conditional create, and verifies the sealed receipt BEFORE persisting it
        # (N16/N28/N29).
        sealed = self.store.set_receipt(
            receipt=SyncReceipt.for_completion(
                project_id, source_file, source_type, corpus_revision
            )
        )
        sealed.verify()
        return SyncResult(
            project_id=project_id,
            source_file=source_file,
            source_type=source_type,
            written=written,
            deleted=deleted,
            corpus_revision=corpus_revision,
            receipt_digest=sealed.digest,
        )


def _validate_completion_inputs(
    *,
    project_id: str,
    source_file: str,
    source_type: str,
    corpus_revision: str,
) -> None:
    """Validate every caller-supplied mandatory completion field (N34).

    The pre-mutation gate used to cover only the OBJECTS. That left the receipt's
    own inputs unchecked: a run with perfectly valid objects and
    ``corpus_revision=""`` claimed the source, wrote the new generation and deleted
    the old one, and only then failed when :meth:`SyncReceipt.verify` rejected the
    blank revision -- a mutated corpus with no publishable completion. A run that
    provably cannot publish must not mutate anything at all, so every mandatory
    completion field the caller supplies is validated BEFORE the claim.

    Args:
        project_id: Bound project the completion belongs to.
        source_file: Source the completion is published for.
        source_type: Source type of that source.
        corpus_revision: Revision the completion would carry.

    Raises:
        SyncError: When any mandatory completion input is blank or not a string.
    """
    supplied = {
        "project_id": project_id,
        "source_file": source_file,
        "source_type": source_type,
        "corpus_revision": corpus_revision,
    }
    for name in COMPLETION_INPUT_FIELDS:
        value = supplied[name]
        if not isinstance(value, str) or not value.strip():
            raise SyncError(
                f"completion input {name!r} is empty/non-string ({value!r}); the "
                "receipt this sync would publish could never verify, so the run must "
                "not claim, write or delete anything (fail-closed, N34)."
            )


def _validate_matrix(
    project_id: str,
    producer: str,
    objects_by_source: Mapping[str, Sequence[StoryContextObject]],
    corpus_revision: str,
) -> None:
    """Validate the COMPLETE incoming matrix before ANY mutation (N17/N29/N34/AC10).

    ``reconcile_sources`` / ``full_reindex`` delete vanished sources and write
    claims; if a LATER source in the same run turned out to be invalid, those
    mutations would already have happened. Validating everything up front keeps the
    zero-mutation guarantee for an invalid run.

    Checks per source, before anything is claimed, deleted or written:

    - the object list is NON-EMPTY (N29). An empty entry validated over zero
      objects, derived ``source_type=""`` and then claimed, deleted the persisted
      generation and reserved a completion before the malformed receipt was finally
      rejected. Removing a source is the vanished-source path, not an empty entry;
    - all objects of a source share ONE source_type;
    - that source_type is OWNED by the calling producer (source/producer closure,
      FK-13 §13.3.2 / §13.9.5) -- ``story_sync`` may not write concept chunks and
      vice versa;
    - every object matches the target (project, source, identity);
    - every mandatory COMPLETION input of that source is publishable (N34) --
      otherwise the vanished-source delete below would already have happened.
    """
    owned = source_types_for_producer(producer)
    if not owned:
        raise SyncError(f"unknown producer {producer!r}; fail-closed (N29).")
    for source_file, objects in objects_by_source.items():
        if not objects:
            raise SyncError(
                f"source {source_file!r} carries no objects; an empty generation is "
                "not a sync target (remove a source through the vanished-source "
                "path). Fail-closed (N29)."
            )
        source_types = {str(obj.properties.get("source_type", "")) for obj in objects}
        if len(source_types) > 1:
            raise SyncError(
                f"source {source_file!r} mixes source types {sorted(source_types)}; "
                "fail-closed (N17)."
            )
        source_type = next(iter(source_types))
        if source_type not in owned:
            raise SyncError(
                f"source {source_file!r} has source_type {source_type!r} which "
                f"producer {producer!r} does not own (owns {sorted(owned)}); "
                "fail-closed (N29 producer closure)."
            )
        _validate_completion_inputs(
            project_id=project_id,
            source_file=source_file,
            source_type=source_type,
            corpus_revision=corpus_revision,
        )
        _validate_objects_against_target(
            objects, project_id=project_id, source_file=source_file, source_type=source_type
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
    "ADMIN_RECLAIM_REASON",
    "COMPLETION_INPUT_FIELDS",
    "RECEIPT_MANDATORY_FIELDS",
    "ClaimSupersededError",
    "ConcurrentSyncRejectedError",
    "SourceClaim",
    "parse_utc_timestamp",
    "utc_now",
    "CorpusStorePort",
    "PartialWriteError",
    "ReceiptState",
    "SyncError",
    "SyncReceipt",
    "SyncResult",
    "SyncService",
]
