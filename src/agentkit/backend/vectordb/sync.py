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

**Ownership during an open window (D9).** A claim is taken over only by an explicit
administrative reclaim, which can land between a check and the following mutation --
a preceding check cannot close that. The DESTRUCTIVE steps are therefore guarded
STRUCTURALLY: every write stamps the object version with its claim's persistent
generation, and every delete is bound storage-side to "strictly older than MY
generation", scoped to the bound project and source. A superseded holder can never
remove what a newer generation wrote, in either race order.

**What is NOT closed (P2-7).** The chunk WRITE has no storage-side precondition at
this seam, so a superseded holder that resumes can still APPEND objects of its own,
lower generation. The earlier justification -- "harmless, because the write is
idempotent: same uuid, same content" -- is **refuted**: with CHANGED content the uuids
differ, so those rows are additional rows the newer generation never overwrites. The
required final delete runs from a FRESH read immediately before the completion, which
removes everything that landed up to that point; a write arriving after it is removed
by the next sync of that source, which is NOT time-bounded. That residual is open and
unratified and is owned by a follow-up story -- it is not an accepted contract. The
completion side is safe: completions are insert-only, position-bound (N28) and ordered
by GENERATION (N39), so a stale append can neither win nor prune a newer one. No
transactional atomicity is claimed anywhere.
"""

from __future__ import annotations

import functools
import hashlib
import json
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable

from agentkit.backend.vectordb.ingest.classify import (
    producer_for,
    source_types_for_producer,
)
from agentkit.backend.vectordb.schema import (
    OWNING_GENERATION_PROPERTY,
    GenerationClass,
    StoryContextObject,
    classify_owning_generation,
    deterministic_uuid,
    is_ordered_generation,
    validate_object,
)
from agentkit.concepts.hashing import sync_receipt_digest

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

class SyncError(RuntimeError):
    """Base error for corpus sync (fail-closed)."""


class PartialWriteError(SyncError):
    """A transport write/delete was incomplete (R12: never advance freshness)."""


class CommitOutcomeUnknownError(SyncError):
    """A completion write may have committed and must be recovered before mutation."""


class ConcurrentSyncRejectedError(SyncError):
    """Two concurrent syncs of the same ``(project_id, source_file)`` (D3)."""


class ClaimSupersededError(SyncError):
    """The source claim was taken over while the window was open (N15 fence)."""


class ClaimReleaseFailedError(SyncError):
    """The source stayed HELD because its release could not be persisted (N45).

    Never silent: an unreleased source blocks every later sync of it until an
    administrative reclaim, so the operator must learn about it at the moment it
    happens rather than from an unexplained rejection later. When the sync itself also
    failed, the primary fault is preserved and this one is attached to it.
    """


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
        generation: The source's PERSISTENT, strictly monotonic generation ordinal
            (N37). EVERY acquisition -- normal or administrative reclaim -- allocates
            the next number by conditional create, and a normal release keeps the
            ladder position (it only adds a release marker). A superseding owner
            therefore always holds a strictly HIGHER generation than the holder it
            supersedes, which is what makes "written by an older generation" a
            decidable, storage-side condition for the destructive delete.
        claimed_at: UTC instant the claim was acquired (diagnostics only -- it is
            NOT an expiry).
        reclaimed_from: The owner this claim was administratively taken from
            (``""`` for a normal acquisition).
    """

    project_id: str
    source_file: str
    owner_id: str
    generation: int
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

#: Receipt fields the STORE produces when it seals a completion (digest over the
#: identity + ordering fields, and the completion instant).
RECEIPT_SEALED_FIELDS: Final[frozenset[str]] = frozenset({"digest", "completed_at"})

#: The caller-supplied subset of :data:`RECEIPT_MANDATORY_FIELDS`, derived
#: STRUCTURALLY (P2-5): a new mandatory receipt field is automatically part of the
#: pre-mutation gate unless it is explicitly a store-sealed field, so it can never
#: silently miss the gate.
COMPLETION_INPUT_FIELDS: Final[tuple[str, ...]] = tuple(
    name for name in RECEIPT_MANDATORY_FIELDS if name not in RECEIPT_SEALED_FIELDS
)

#: Run-wide completion inputs -- the same for every source of one sync run. They are
#: validated at the ENTRY of a multi-source run, before ANY mutation (N40).
RUN_WIDE_COMPLETION_INPUTS: Final[tuple[str, ...]] = ("project_id", "corpus_revision")


@dataclass(frozen=True)
class SyncReceipt:
    """Digest-bound sync completion marker (DR 2026-07-21 Rand 5).

    Attributes:
        completed_at: UTC completion timestamp (ISO-8601).
        sequence: Store-assigned completion position. ``0`` marks a not-yet-persisted
            receipt. The position makes the record immutable (its uuid folds it in);
            it is NOT the freshness order (N39).
        generation: The SOURCE GENERATION that published this completion. Freshness
            is selected by the highest generation, so a superseded writer that
            appends a later POSITION can never become authoritative (N39).
    """

    project_id: str
    source_file: str
    source_type: str
    corpus_revision: str
    digest: str
    state: ReceiptState
    completed_at: str
    sequence: int = 0
    generation: int = 0

    @classmethod
    def for_completion(
        cls,
        project_id: str,
        source_file: str,
        source_type: str,
        corpus_revision: str,
        *,
        generation: int = 0,
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
            generation=generation,
        )

    def stamped(self, *, sequence: int) -> SyncReceipt:
        """Return the sealed receipt: atomic sequence + digest over ALL fields."""
        if sequence < 1:
            raise SyncError(f"receipt sequence must be >= 1, got {sequence} (N16).")
        sealed = SyncReceipt(
            project_id=self.project_id,
            source_file=self.source_file,
            source_type=self.source_type,
            corpus_revision=self.corpus_revision,
            digest="",
            state=self.state,
            completed_at=self.completed_at,
            sequence=sequence,
            generation=self.generation,
        )
        return SyncReceipt(
            project_id=sealed.project_id,
            source_file=sealed.source_file,
            source_type=sealed.source_type,
            corpus_revision=sealed.corpus_revision,
            digest=sealed.expected_digest(),
            state=sealed.state,
            completed_at=sealed.completed_at,
            sequence=sealed.sequence,
            generation=sealed.generation,
        )

    def expected_digest(self) -> str:
        """Return the digest this receipt's own fields must bind to (N16/N39)."""
        return sync_receipt_digest(
            project_id=self.project_id,
            source_file=self.source_file,
            source_type=self.source_type,
            corpus_revision=self.corpus_revision,
            state=self.state.value,
            completed_at=self.completed_at,
            sequence=self.sequence,
            generation=self.generation,
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
        if self.generation < 1:
            raise SyncError(
                f"sync receipt generation {self.generation} is not a positive source "
                "generation; a completion that cannot be ordered against a takeover "
                "must never be trusted (fail-closed, N39)."
            )
        parse_utc_timestamp(self.completed_at)
        expected = self.expected_digest()
        if self.digest != expected:
            raise SyncError(
                f"sync receipt digest {self.digest!r} does not bind its own fields "
                f"(expected {expected!r}); fail-closed (N08/N16: identity AND "
                "ordering fields are part of the binding)."
            )


@dataclass(frozen=True)
class ProducerCompletion:
    """Producer-wide successful completion, including a zero-source corpus."""

    project_id: str
    producer: str
    source_types: tuple[str, ...]
    corpus_revision: str
    sequence: int = 0

    def verify(self) -> None:
        """Validate the producer identity, owned source types, revision and order."""
        if not self.project_id or not self.producer or not self.corpus_revision:
            raise SyncError("producer completion has a blank mandatory field")
        owned = source_types_for_producer(self.producer)
        if not owned or self.source_types != owned:
            raise SyncError(
                f"producer completion {self.producer!r} does not bind its exact "
                f"source types: {self.source_types!r} != {owned!r}"
            )
        if self.sequence < 1:
            raise SyncError("producer completion sequence must be positive")

    def stamped(self, *, sequence: int) -> ProducerCompletion:
        """Bind this producer completion to the run's atomic position."""
        stamped = ProducerCompletion(
            project_id=self.project_id,
            producer=self.producer,
            source_types=self.source_types,
            corpus_revision=self.corpus_revision,
            sequence=sequence,
        )
        stamped.verify()
        return stamped


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
    """Outcome of one sync call (complete result/error envelope).

    Attributes:
        backfilled: Legacy rows of this source that carried NO writing generation and
            were removed so the corpus could converge (N43). Recorded rather than
            silent -- a run that had to repair pre-existing rows should be visible in
            its own result. It is deliberately NOT part of the MCP tool envelope: the
            FK-13 §13.4.1 return fields are a fixed contract.
    """

    project_id: str
    source_file: str
    source_type: str
    written: int
    deleted: int
    corpus_revision: str
    receipt_digest: str
    error: str = ""
    backfilled: int = 0


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

    def upsert_objects(
        self, *, objects: Sequence[StoryContextObject], owning_generation: int
    ) -> int:
        """Insert/replace objects (deterministic uuids) STAMPED with the writing
        SOURCE GENERATION (N37); return the EXACT count of objects confirmed written
        (R12). A return value below ``len(objects)`` indicates a partial batch and
        MUST NOT be reported as success; batch failures are surfaced as a lower
        count, not an exception, so the SyncService can reject the partial window
        fail-closed."""
        ...

    def delete_objects_older_than(
        self, *, project_id: str, source_file: str, uuids: Sequence[str], owning_generation: int
    ) -> int:
        """Delete objects ONLY where the writing generation is STRICTLY OLDER (N37).

        Scoped to the authoritative ``project_id``/``source_file`` as well: every
        delete carries project isolation (AC4/N48).

        The ordering condition MUST be evaluated by the store together with the
        delete -- a preceding application check can always be overtaken. Returns the
        EXACT count confirmed deleted (R12); a lower count means at least one object
        belongs to a generation that is NOT older than the caller's."""
        ...

    def delete_objects_without_generation(
        self, *, project_id: str, source_file: str, uuids: Sequence[str]
    ) -> int:
        """Delete objects that carry NO writing generation at all (N43).

        The IS-NULL condition MUST be evaluated by the store, so it can only ever
        match rows predating the ownership-ordering property, and it MUST be scoped to
        the authoritative ``project_id``/``source_file`` -- every delete carries project
        isolation (AC4/N48). Returns the EXACT count confirmed deleted (R12)."""
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

    def set_receipts(
        self,
        *,
        run_id: str,
        receipts: Sequence[SyncReceipt],
        producer_completions: Sequence[ProducerCompletion],
    ) -> Sequence[SyncReceipt]:
        """Atomically publish every completion of one run.

        Until this call succeeds, none of ``receipts`` is authoritative. The
        implementation must establish the complete set through one atomic
        visibility boundary; a partial write must leave the previously visible
        completion set unchanged.
        """
        ...

    def list_producer_completions(
        self, *, project_id: str
    ) -> Sequence[ProducerCompletion]:
        """Return every verified producer-wide completion."""
        ...

    def resolve_pending_commits(self, *, project_id: str) -> None:
        """Resolve durable unknown completion outcomes before another mutation."""
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
class PreparedSyncRun:
    """Mutated chunks plus completions that are not authoritative yet.

    A prepared run is the run-wide publish boundary required by CP10a and the
    post-commit incremental-sync ring. Source windows may already have written their
    generation, but retrieval freshness continues to be derived from the old
    completions until :meth:`commit` atomically publishes the complete receipt
    set.
    """

    store: CorpusStorePort
    project_id: str
    results: list[SyncResult]
    receipts: list[SyncReceipt]
    producer_completions: list[ProducerCompletion] = field(default_factory=list)
    run_id: str = ""
    _finished: bool = False

    def merge(self, other: PreparedSyncRun) -> None:
        """Join another producer into this still-unpublished run."""
        if self._finished or other._finished:
            raise SyncError("cannot merge a committed or aborted sync run")
        if other.store is not self.store or other.project_id != self.project_id:
            raise SyncError("cannot merge sync runs from different stores/projects")
        self.results.extend(other.results)
        self.receipts.extend(other.receipts)
        self.producer_completions.extend(other.producer_completions)
        other._finished = True

    def commit(self) -> list[SyncResult]:
        """Publish every source completion through one atomic store boundary."""
        if self._finished:
            raise SyncError("sync run is already committed or aborted")
        self.run_id = completion_run_id(
            self.project_id,
            self.receipts,
            self.producer_completions,
        )
        sealed = tuple(
            self.store.set_receipts(
                run_id=self.run_id,
                receipts=tuple(self.receipts),
                producer_completions=tuple(self.producer_completions),
            )
        )
        if len(sealed) != len(self.receipts):
            raise PartialWriteError(
                f"completion batch returned {len(sealed)} of {len(self.receipts)} "
                "receipts; freshness remains unchanged"
            )
        by_identity = {
            (receipt.source_file, receipt.generation): receipt for receipt in sealed
        }
        committed: list[SyncResult] = []
        for result in self.results:
            candidate = next(
                (
                    receipt
                    for receipt in self.receipts
                    if receipt.source_file == result.source_file
                ),
                None,
            )
            if candidate is None:
                committed.append(result)
                continue
            published = by_identity.get((candidate.source_file, candidate.generation))
            if published is None:
                raise PartialWriteError(
                    f"completion batch omitted {candidate.source_file!r}; "
                    "freshness remains unchanged"
                )
            published.verify()
            committed.append(replace(result, receipt_digest=published.digest))
        self._finished = True
        return committed

    def abort(self) -> None:
        """Fence a prepared run without publishing any completion."""
        if self._finished:
            return
        self._finished = True


def _producer_for_source_type(source_type: str) -> str:
    producer = producer_for(source_type)
    if producer is None:
        raise SyncError(f"source type {source_type!r} has no registered producer")
    return producer


def completion_run_id(
    project_id: str,
    receipts: Sequence[SyncReceipt],
    producer_completions: Sequence[ProducerCompletion],
) -> str:
    """Derive the stable run key from the exact unsealed semantic payload."""
    material = {
        "producer_completions": [
            {
                "corpus_revision": completion.corpus_revision,
                "producer": completion.producer,
                "project_id": completion.project_id,
                "source_types": list(completion.source_types),
            }
            for completion in producer_completions
        ],
        "project_id": project_id,
        "receipts": [
            {
                "completed_at": receipt.completed_at,
                "corpus_revision": receipt.corpus_revision,
                "generation": receipt.generation,
                "project_id": receipt.project_id,
                "source_file": receipt.source_file,
                "source_type": receipt.source_type,
                "state": receipt.state.value,
            }
            for receipt in receipts
        ],
    }
    encoded = json.dumps(
        material,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
        self.store.resolve_pending_commits(project_id=project_id)
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
        result, receipt = self._with_release(
            claim,
            functools.partial(
                self._sync_impl,
                claim=claim,
                source_type=source_type,
                objects=objects,
                corpus_revision=corpus_revision,
            ),
        )
        prepared = PreparedSyncRun(
            store=self.store,
            project_id=project_id,
            results=[result],
            receipts=[receipt],
            producer_completions=[
                ProducerCompletion(
                    project_id=project_id,
                    producer=_producer_for_source_type(source_type),
                    source_types=source_types_for_producer(
                        _producer_for_source_type(source_type)
                    ),
                    corpus_revision=corpus_revision,
                )
            ],
        )
        return prepared.commit()[0]

    def _with_release[ResultT](
        self, claim: SourceClaim, operation: Callable[[], ResultT]
    ) -> ResultT:
        """Run ``operation`` under ``claim`` and CONFIRM its release afterwards (N45).

        The release is not best-effort: a source that stays held blocks every later
        sync of it until an administrative reclaim, so a failed release is a typed
        fault (:class:`ClaimReleaseFailedError`).

        When the operation ALSO failed, its exception is the primary one and is
        re-raised unchanged -- the release failure is attached as a note instead of
        replacing it. A plain ``finally`` would have substituted the release fault for
        the real cause of the run's failure.

        Args:
            claim: The held claim to release.
            operation: The work to run while holding it.

        Returns:
            Whatever ``operation`` returned.
        """
        try:
            result = operation()
        except BaseException as primary:
            try:
                self.store.release_source(claim=claim)
            except ClaimReleaseFailedError as release_failure:
                primary.add_note(f"additionally: {release_failure}")
            raise
        self.store.release_source(claim=claim)
        return result

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
        return self.prepare_reconcile_sources(
            project_id=project_id,
            producer=producer,
            objects_by_source=objects_by_source,
            corpus_revision=corpus_revision,
        ).commit()

    def prepare_reconcile_sources(
        self,
        *,
        project_id: str,
        producer: str,
        objects_by_source: Mapping[str, Sequence[StoryContextObject]],
        corpus_revision: str,
    ) -> PreparedSyncRun:
        """Prepare an incremental multi-source run without publishing freshness."""
        self.store.resolve_pending_commits(project_id=project_id)
        _validate_matrix(project_id, producer, objects_by_source, corpus_revision)
        results = self._delete_vanished_sources(
            project_id=project_id,
            producer=producer,
            objects_by_source=objects_by_source,
            corpus_revision=corpus_revision,
        )
        receipts: list[SyncReceipt] = []
        for source_file, objs in objects_by_source.items():
            source_type = str(objs[0].properties["source_type"]) if objs else ""
            result, receipt = self._prepare_source(
                    project_id=project_id,
                    source_file=source_file,
                    source_type=source_type,
                    objects=objs,
                    corpus_revision=corpus_revision,
            )
            results.append(result)
            receipts.append(receipt)
        return PreparedSyncRun(
            store=self.store,
            project_id=project_id,
            results=results,
            receipts=receipts,
            producer_completions=[
                ProducerCompletion(
                    project_id=project_id,
                    producer=producer,
                    source_types=source_types_for_producer(producer),
                    corpus_revision=corpus_revision,
                )
            ],
        )

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
        return self.prepare_full_reindex(
            project_id=project_id,
            producer=producer,
            objects_by_source=objects_by_source,
            corpus_revision=corpus_revision,
        ).commit()

    def prepare_full_reindex(
        self,
        *,
        project_id: str,
        producer: str,
        objects_by_source: Mapping[str, Sequence[StoryContextObject]],
        corpus_revision: str,
    ) -> PreparedSyncRun:
        """Prepare a full multi-source run without publishing freshness."""
        self.store.resolve_pending_commits(project_id=project_id)
        _validate_matrix(project_id, producer, objects_by_source, corpus_revision)
        results = self._delete_vanished_sources(
            project_id=project_id,
            producer=producer,
            objects_by_source=objects_by_source,
            corpus_revision=corpus_revision,
        )
        receipts: list[SyncReceipt] = []
        for source_file, objs in objects_by_source.items():
            source_type = objs[0].properties["source_type"] if objs else ""
            result, receipt = self._prepare_source(
                    project_id=project_id,
                    source_file=source_file,
                    source_type=str(source_type),
                    objects=objs,
                    corpus_revision=corpus_revision,
            )
            results.append(result)
            receipts.append(receipt)
        return PreparedSyncRun(
            store=self.store,
            project_id=project_id,
            results=results,
            receipts=receipts,
            producer_completions=[
                ProducerCompletion(
                    project_id=project_id,
                    producer=producer,
                    source_types=source_types_for_producer(producer),
                    corpus_revision=corpus_revision,
                )
            ],
        )

    def _prepare_source(
        self,
        *,
        project_id: str,
        source_file: str,
        source_type: str,
        objects: Sequence[StoryContextObject],
        corpus_revision: str,
    ) -> tuple[SyncResult, SyncReceipt]:
        """Run one bounded source window but retain its completion."""
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
            objects,
            project_id=project_id,
            source_file=source_file,
            source_type=source_type,
        )
        claim = self._claim(project_id=project_id, source_file=source_file)
        return self._with_release(
            claim,
            functools.partial(
                self._sync_impl,
                claim=claim,
                source_type=source_type,
                objects=objects,
                corpus_revision=corpus_revision,
            ),
        )

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
            claim = self._claim(project_id=project_id, source_file=vanished)
            # The destructive delete is bound to the GENERATION ORDER and evaluated BY
            # THE STORE (N37). There is deliberately NO preceding ownership check here:
            # a check followed by a separate delete is exactly the window this decision
            # removes, and keeping one would only restore the illusion of safety. The
            # claim release is CONFIRMED afterwards (N45).
            deleted, backfilled = self._with_release(
                claim,
                functools.partial(self._delete_vanished_generation, rows, claim=claim),
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
                    backfilled=backfilled,
                )
            )
        return results

    def _delete_vanished_generation(
        self, rows: Sequence[Mapping[str, object]], *, claim: SourceClaim
    ) -> tuple[int, int]:
        """Remove EVERY row of a vanished source, stamped or not (N37 + N43).

        A vanished source has no should-set, so all of its rows must go. Stamped rows
        are removed under the generation ordering; rows predating the ordering property
        under the IS-NULL condition, so a legacy source converges instead of blocking
        every retry.

        Args:
            rows: The vanished source's rows, as read.
            claim: The HELD claim of that source.

        Returns:
            ``(deleted_total, legacy_removed)`` -- the legacy count is reported
            separately so a run that had to repair pre-existing rows is visible in its
            own result (N49).
        """
        # Classify and VALIDATE the complete row set before the first delete (N49):
        # otherwise a legacy row would already be gone when an unusable generation on
        # another row aborts the run.
        legacy, older = self._classify_source_rows(
            rows, claim=claim, should_uuids=frozenset()
        )
        backfilled = self._delete_legacy_rows(legacy, claim=claim)
        deleted = backfilled + self._delete_older_generations(older, claim=claim)
        return deleted, backfilled

    def _classify_source_rows(
        self,
        rows: Sequence[Mapping[str, object]],
        *,
        claim: SourceClaim,
        should_uuids: frozenset[str] | set[str],
    ) -> tuple[list[str], list[Mapping[str, object]]]:
        """Classify a source's rows BEFORE anything is deleted (N47/N49).

        The COMPLETE set is validated first, so a row nobody may touch stops the run
        while the corpus is still intact -- rather than after some other row has already
        been removed.

        Returns two disjoint groups of rows that are NOT part of this generation:

        - ``legacy``: uuids of rows carrying NO generation at all. They predate the
          ordering property, so they cannot be ordered against a claim; they are
          removed under an IS-NULL condition (never adopted, see
          :meth:`_delete_legacy_rows`). Legacy rows that ARE part of this generation
          need nothing: the upsert overwrites and thereby stamps them.
        - ``older``: rows written by a generation strictly BELOW this claim's. Rows at
          a generation >= this claim's are in NEITHER group: a higher generation is a
          newer owner, whose data is not this writer's to remove.

        Args:
            rows: The source's rows, as read.
            claim: The HELD claim of that source.
            should_uuids: The uuids this generation writes (empty for a vanished source).

        Returns:
            ``(legacy_uuids, older_rows)``.

        Raises:
            SyncError: For a row whose generation is PRESENT but unusable (non-integer,
                boolean, zero, negative -- :attr:`GenerationClass.UNUSABLE`). It is
                neither orderable nor an unstamped legacy row, so adopting or deleting
                it would be a guess -- it is a named error. An ABSENT or ``null`` value
                is NOT this class: it is legacy and converges (the storage-side IS-NULL
                condition matches exactly those rows).
        """
        legacy: list[str] = []
        older: list[Mapping[str, object]] = []
        for row in rows:
            raw = row.get(OWNING_GENERATION_PROPERTY)
            # ONE ladder for both consumers (AG3-177/R2-N2): this path and the source
            # listing must agree about what a row IS, or the reported remedy is wrong.
            if not is_ordered_generation(raw):
                if classify_owning_generation(raw) is GenerationClass.MISSING:
                    # Absent OR null: not orderable, but converges under IS-NULL.
                    if str(row["uuid"]) not in should_uuids:
                        legacy.append(str(row["uuid"]))
                    continue
                raise SyncError(
                    f"object {row.get('uuid')!r} of {claim.source_file!r} carries an "
                    f"unusable writing generation ({raw!r}): it is neither orderable "
                    "nor an unstamped legacy row, so it is never adopted or deleted "
                    "on a guess (fail-closed, N43)."
                )
            if str(row["uuid"]) in should_uuids:
                continue
            if raw < claim.generation:
                older.append(row)
        return legacy, older

    def _delete_legacy_rows(
        self, uuids: Sequence[str], *, claim: SourceClaim
    ) -> int:
        """Remove rows that carry NO writing generation, under an IS-NULL condition.

        This is the convergence path for rows predating the ordering property (N43):
        without it the ordering delete refuses them and every retry fails identically,
        so the corpus can never converge. Nothing is adopted -- the content is either
        re-written by this generation or genuinely gone from the source -- and the
        condition is evaluated by the store, scoped to this project and source, so it
        can never widen to another project (AC4) nor touch a stamped row.

        Args:
            uuids: Legacy row ids of the CLAIMED source (from
                :meth:`_classify_source_rows`).
            claim: The HELD claim of that source.

        Returns:
            The number of legacy rows removed.

        Raises:
            SyncError: When the store confirms fewer deletes than were requested --
                the corpus did not converge, so the run must not report success.
        """
        if not uuids:
            return 0
        removed = self.store.delete_objects_without_generation(
            project_id=claim.project_id, source_file=claim.source_file, uuids=uuids
        )
        if removed != len(uuids):
            raise SyncError(
                f"legacy cleanup for {claim.source_file!r} removed {removed} of "
                f"{len(uuids)} unstamped row(s); the corpus did not converge, so the "
                "run must not report success (fail-closed, N43)."
            )
        return removed

    def _delete_older_generations(
        self,
        rows: Sequence[Mapping[str, object]],
        *,
        claim: SourceClaim,
    ) -> int:
        """Delete the given objects, bound STORAGE-SIDE to the generation order (N37).

        The condition is "written by a generation strictly OLDER than mine", and
        ``mine`` is the deleting claim's own generation -- a number this writer owns
        and cannot be misled about. That is the whole difference to the superseded
        model: deleting "whatever still carries the value I read" closes only the
        interval between the read and the delete, and never establishes WHOSE
        generation that value was, so a resumed writer could authorise itself to
        delete a newer generation's data simply by reading it.

        Because the ladder is persistent and strictly monotonic, this holds in BOTH
        race orders: whether the newer generation writes before or after this writer
        reads, its objects carry a HIGHER generation and can never match. And no
        legitimate delete is lost: objects of any earlier generation -- several
        different ones at once -- are all strictly below.

        Args:
            rows: Objects to delete, as read (uuid + writing generation).
            claim: The claim under which this delete runs.

        Returns:
            The number of objects confirmed deleted.

        Raises:
            SyncError: When a candidate carries no readable generation. That is a
                data-integrity refusal, never an authorisation: it only ever
                REFUSES, and every object AK3 writes is stamped (N38).
            ClaimSupersededError: When fewer objects were deleted than requested --
                at least one belongs to a generation that is not older than this
                claim's, so this writer's window is no longer authoritative.
        """
        uuids: list[str] = []
        for row in rows:
            raw = row.get(OWNING_GENERATION_PROPERTY)
            if not is_ordered_generation(raw):
                raise SyncError(
                    f"object {row.get('uuid')!r} of {claim.source_file!r} carries no "
                    f"readable writing generation ({raw!r}); it cannot be ordered "
                    "against this claim, so it is never deleted (fail-closed, N37)."
                )
            uuids.append(str(row["uuid"]))
        if not uuids:
            return 0
        deleted = self.store.delete_objects_older_than(
            project_id=claim.project_id,
            source_file=claim.source_file,
            uuids=uuids,
            owning_generation=claim.generation,
        )
        if deleted != len(uuids):
            raise ClaimSupersededError(
                f"conditional delete for {claim.source_file!r} removed {deleted} of "
                f"{len(uuids)} objects: at least one belongs to a generation that is "
                f"not older than this claim's generation {claim.generation}, so a "
                "superseded holder was prevented from deleting a newer generation's "
                "data (fail-closed, N37)."
            )
        return deleted

    def _sync_impl(
        self,
        *,
        claim: SourceClaim,
        source_type: str,
        objects: Sequence[StoryContextObject],
        corpus_revision: str,
    ) -> tuple[SyncResult, SyncReceipt]:
        # Objects were validated BEFORE the claim was written (N17); the claim is
        # itself a mutation, so nothing may be written before validation passes.
        project_id = claim.project_id
        source_file = claim.source_file
        # (1) FENCE BEFORE THE FIRST WRITE (N27): if this writer's claim was
        # administratively taken over while it was paused, it must not write stale
        # chunks at all. This check CAN still be overtaken, and the consequence is NOT
        # harmless: a superseded holder that resumes here appends objects of its own,
        # LOWER generation, and with CHANGED content those carry DIFFERENT uuids that
        # the newer generation never overwrites (P2-7 -- the earlier "same content"
        # justification was refuted, see FK-13 §13.9.9 and the D9 record). The
        # generation ordering keeps such a writer from DELETING anything of the newer
        # owner's; the residual VISIBILITY of what it wrote is the contract AG3-177
        # ratified (FK-13 §13.9.9): no atomicity and no time bound are claimed, the
        # rows are REPORTED via ``story_list_sources.stale_chunk_count``, and the
        # operational duty is to sync the affected source after a takeover
        # (FK-04 §4.5.14). The sweep below stays -- it covers the common case.
        self.store.assert_claim_held(claim=claim)
        should_uuids = {obj.uuid for obj in objects}
        # (1a) PREVALIDATE the whole source BEFORE mutating anything (N47/N49): a row
        # whose generation is present but unusable must stop the run while the corpus
        # is still untouched. Nothing is deleted here -- the legacy cleanup happens
        # only AFTER the replacement generation is written and verified, so a failed
        # write can never leave the source with neither its old nor its new rows.
        self._classify_source_rows(
            self.store.list_objects_for_source(
                project_id=project_id, source_file=source_file
            ),
            claim=claim,
            should_uuids=should_uuids,
        )
        # Write the new should-generation fully + verify EXACT transport count. Every
        # object version carries the generation of THIS claim (N37), which is what
        # makes the deletes below storage-conditional.
        written = self.store.upsert_objects(
            objects=objects, owning_generation=claim.generation
        )
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
        # (2) THE REQUIRED FINAL DELETE, from a FRESH read and BEFORE the receipt
        # (N46/N47). It is read fresh so it also removes what a superseded writer
        # appended after the write, and it runs before the completion so freshness can
        # never advance past a destructive step that has not happened yet. Both deletes
        # are evaluated BY THE STORE -- the legacy rows under an IS-NULL condition that
        # cannot touch a stamped row, the superseded generations under the ordering
        # predicate -- and neither is preceded by an ownership check, which could always
        # be overtaken before the delete landed.
        final_rows = self.store.list_objects_for_source(
            project_id=project_id, source_file=source_file
        )
        legacy_uuids, older_rows = self._classify_source_rows(
            final_rows, claim=claim, should_uuids=should_uuids
        )
        backfilled = self._delete_legacy_rows(legacy_uuids, claim=claim)
        deleted = backfilled + self._delete_older_generations(older_rows, claim=claim)
        # (3) FENCE again before publishing: if the claim was taken over while the
        # window was open, this writer's generation is no longer authoritative and it
        # must NOT publish a completion (N15/N27). This check CAN still be overtaken;
        # the completion is insert-only and position-bound (N28) and freshness is
        # ordered by GENERATION (N39), so a superseded holder can at most append a
        # non-authoritative record -- it can never overwrite one or pull freshness back.
        self.store.assert_claim_held(claim=claim)
        candidate = SyncReceipt.for_completion(
            project_id,
            source_file,
            source_type,
            corpus_revision,
            generation=claim.generation,
        )
        return (
            SyncResult(
                project_id=project_id,
                source_file=source_file,
                source_type=source_type,
                written=written,
                deleted=deleted,
                corpus_revision=corpus_revision,
                receipt_digest="",
                backfilled=backfilled,
            ),
            candidate,
        )


def _validate_run_wide_completion_inputs(
    *, project_id: str, corpus_revision: str
) -> None:
    """Validate the completion inputs shared by EVERY source of a run (N40).

    ``_validate_matrix`` used to check the completion inputs only inside its loop over
    the incoming sources, so an EMPTY matrix skipped the gate entirely -- and the
    vanished-source delete that follows is a mutation. These fields do not depend on
    any source, so they are checked at the entry of the run.

    Raises:
        SyncError: When a run-wide completion input is blank or not a string.
    """
    supplied = {"project_id": project_id, "corpus_revision": corpus_revision}
    for name in RUN_WIDE_COMPLETION_INPUTS:
        value = supplied[name]
        if not isinstance(value, str) or not value.strip():
            raise SyncError(
                f"completion input {name!r} is empty/non-string ({value!r}); the "
                "receipts this run would publish could never verify, so the run must "
                "not claim, write or delete anything -- not even with an empty "
                "matrix (fail-closed, N34/N40)."
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
    # RUN-WIDE fields first, OUTSIDE the loop (N40): an EMPTY matrix never entered
    # the loop, so a blank corpus_revision went unchecked while
    # ``_delete_vanished_sources`` already mutated. A run that provably cannot
    # publish must not delete anything, whether it carries sources or not.
    _validate_run_wide_completion_inputs(
        project_id=project_id, corpus_revision=corpus_revision
    )
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
    "ClaimReleaseFailedError",
    "COMPLETION_INPUT_FIELDS",
    "RECEIPT_MANDATORY_FIELDS",
    "ClaimSupersededError",
    "ConcurrentSyncRejectedError",
    "SourceClaim",
    "parse_utc_timestamp",
    "utc_now",
    "CorpusStorePort",
    "PartialWriteError",
    "CommitOutcomeUnknownError",
    "completion_run_id",
    "ProducerCompletion",
    "ReceiptState",
    "SyncError",
    "SyncReceipt",
    "SyncResult",
    "SyncService",
]
