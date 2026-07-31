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

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable

from agentkit.backend.vectordb.commit_recovery import (
    CommitRecoveryState,
    CompletionCommitJournalEntry,
    FileCommitRecoveryJournal,
    project_commit_recovery_journal,
)
from agentkit.backend.vectordb.endpoints import split_grpc_endpoint, split_http_endpoint
from agentkit.backend.vectordb.runtime_binding import RuntimeBinding, RuntimeBindingError
from agentkit.backend.vectordb.schema import (
    OWNING_GENERATION_PROPERTY,
    STORY_CONTEXT_COLLECTION,
    StoryContextObject,
    is_ordered_generation,
    search_property_spec,
)
from agentkit.backend.vectordb.sync import (
    ClaimSupersededError,
    CommitOutcomeUnknownError,
    ConcurrentSyncRejectedError,
    ProducerCompletion,
    SourceClaim,
    SyncError,
    SyncReceipt,
    SyncService,
    completion_run_id,
    parse_utc_timestamp,
)
from agentkit.integration_clients.vectordb.errors import VectorDbUnavailableError, VectorDbWriteError

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

#: Dedicated collection for digest-bound sync receipts (R02/R12).
RECEIPT_COLLECTION = "__agentkit_sync_receipts"

#: The receipt record's full property set (verified on read, N08).
RECEIPT_PROPERTIES: tuple[str, ...] = (
    "project_id",
    "source_file",
    "source_type",
    "corpus_revision",
    "digest",
    "state",
    "completed_at",
    "sequence",
    "generation",
)

#: One immutable record publishes every completion of a multi-source run.
RUN_RECEIPT_COLLECTION = "__agentkit_sync_runs"
RUN_RECEIPT_PROPERTIES: tuple[str, ...] = (
    "project_id",
    "run_id",
    "receipts_json",
    "producer_completions_json",
    "batch_digest",
    "completed_at",
    "sequence_start",
    "sequence_end",
)

#: Dedicated collection for store-level atomic source claims (N03/D3/N15).
CLAIM_COLLECTION = "__agentkit_source_claims"

#: The claim/generation record's property set (no expiry -- N15/N27; persistent
#: monotonic ``generation`` -- N37). ``state`` is ``claimed`` for an acquisition and
#: ``released`` for the insert-only release marker of that same generation.
CLAIM_PROPERTIES: tuple[str, ...] = (
    "project_id",
    "source_file",
    "state",
    "owner_id",
    "generation",
    "claimed_at",
    "reclaimed_from",
    "reclaim_reason",
)

#: Record states in the claim collection (insert-only; nothing is ever updated).
CLAIM_STATE_HELD: Final[str] = "claimed"
CLAIM_STATE_RELEASED: Final[str] = "released"

#: Bounded number of completion positions tried before failing closed (N28).
_COMPLETION_ATTEMPT_LIMIT: Final[int] = 256

#: Stable namespace for the position-bound completion records (N28).
_RECEIPT_NAMESPACE = uuid.UUID("8c5e2f3a-1b6d-4e7a-9c8f-2a1b3c4d5e6f")
_RUN_RECEIPT_NAMESPACE = uuid.UUID("c3b74614-293d-4a72-9155-672f86d41b89")
#: Stable namespace for per-source, per-generation claim identity (N03/N15/N37).
_CLAIM_NAMESPACE = uuid.UUID("9d6f3a4b-2c7e-5f8b-ad9c-3b2c4d5e6f7a")


@dataclass(frozen=True)
class _CompletionRunRecord:
    uuid: str
    properties: dict[str, str]
    receipts: tuple[SyncReceipt, ...]
    producer_completions: tuple[ProducerCompletion, ...]
    sequence_start: int
    sequence_end: int


def _utc_clock() -> datetime:
    """Return the current UTC instant (the store's default clock)."""
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    """Render a UTC instant as an ISO-8601 string with a ``Z`` suffix."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


@runtime_checkable
class CorpusClientPort(Protocol):
    """The thin-adapter corpus surface the engine needs (R02)."""

    def fetch_by_property(
        self,
        *,
        collection: str,
        project_id: str,
        prop: str,
        value: str,
        return_props: Sequence[str],
    ) -> Sequence[tuple[str, dict[str, object]]]: ...

    def fetch_by_property_any(
        self,
        *,
        collection: str,
        project_id: str,
        prop: str,
        values: Sequence[str],
        return_props: Sequence[str],
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
        property_spec: Sequence[tuple[str, str, bool]],
    ) -> Sequence[tuple[str, dict[str, object], float]]: ...

    def upsert(self, *, collection: str, objects: Sequence[Mapping[str, object]]) -> int: ...

    def insert_object(self, *, collection: str, uuid: str, properties: Mapping[str, object]) -> bool: ...

    def delete_by_ids(self, *, collection: str, uuids: Sequence[str]) -> int: ...

    def delete_by_ids_if_property_below(
        self,
        *,
        collection: str,
        uuids: Sequence[str],
        prop: str,
        limit: int,
        project_id: str,
        source_file: str,
    ) -> int: ...

    def delete_by_ids_if_property_absent(
        self,
        *,
        collection: str,
        uuids: Sequence[str],
        prop: str,
        project_id: str,
        source_file: str,
    ) -> int: ...

    def ensure_collection(
        self,
        *,
        collection: str,
        property_specs: Sequence[Mapping[str, object]],
        vectorizer: str = ...,
        vectorizer_model: Mapping[str, object] | None = ...,
        vector_source_properties: Sequence[str] | None = ...,
    ) -> None: ...


@dataclass
class WeaviateCorpusStore:
    """Production :class:`CorpusStorePort` over the thin Weaviate adapter (R02).

    ``clock`` is the UTC time source for the claim/completion timestamps; it is a
    field so a test can drive them deterministically.
    """

    client: CorpusClientPort
    recovery_journal: FileCommitRecoveryJournal
    collection: str = STORY_CONTEXT_COLLECTION
    clock: Callable[[], datetime] = _utc_clock

    def list_objects_for_source(self, *, project_id: str, source_file: str) -> Sequence[Mapping[str, object]]:
        rows = self.client.fetch_by_property(
            collection=self.collection,
            project_id=project_id,
            prop="source_file",
            value=source_file,
            return_props=(
                "content_hash",
                "source_type",
                "project_id",
                OWNING_GENERATION_PROPERTY,
            ),
        )
        return [
            {
                "uuid": uid,
                "source_file": source_file,
                "source_type": p.get("source_type", ""),
                "project_id": p.get("project_id", ""),
                "content_hash": p.get("content_hash", ""),
                OWNING_GENERATION_PROPERTY: p.get(OWNING_GENERATION_PROPERTY),
            }
            for uid, p in rows
            # Redundant after N51 (the project filter is server-side); kept as defence
            # in depth, never as the isolation mechanism.
            if str(p.get("project_id", "")) == project_id
        ]

    def list_objects_for_source_types(self, *, project_id: str, source_types: Sequence[str]) -> Sequence[Mapping[str, object]]:
        rows = self.client.fetch_by_property_any(
            collection=self.collection,
            project_id=project_id,
            prop="source_type",
            values=tuple(source_types),
            return_props=(
                "source_file",
                "project_id",
                "source_type",
                OWNING_GENERATION_PROPERTY,
            ),
        )
        return [
            {
                "uuid": uid,
                "source_file": p.get("source_file", ""),
                "source_type": p.get("source_type", ""),
                "project_id": p.get("project_id", ""),
                OWNING_GENERATION_PROPERTY: p.get(OWNING_GENERATION_PROPERTY),
            }
            for uid, p in rows
            if str(p.get("project_id", "")) == project_id
        ]

    def upsert_objects(self, *, objects: Sequence[StoryContextObject], owning_generation: int) -> int:
        """Write objects STAMPED with the writing SOURCE GENERATION (D9/N37).

        The stamp is applied here and nowhere else, so it is structurally impossible
        to persist an object version without the ordering marker the destructive
        delete conditions on. It does not touch the object identity: the uuid stays
        ``uuid5(project|source|chunk)`` and ``content_hash`` stays content-derived, so
        a re-sync still replaces the same object.
        """
        if owning_generation < 1:
            raise VectorDbUnavailableError(
                f"refusing to write objects with a non-positive owning generation "
                f"({owning_generation}); the destructive delete orders against it "
                "(fail-closed, N37)."
            )
        # Exact confirmed count: the adapter inspects batch failures and raises
        # on a partial batch (R12); a clean return == len(objects).
        docs = [
            {
                **obj.properties,
                "uuid": obj.uuid,
                OWNING_GENERATION_PROPERTY: owning_generation,
            }
            for obj in objects
        ]
        return self.client.upsert(collection=self.collection, objects=docs)

    def delete_objects_older_than(
        self,
        *,
        project_id: str,
        source_file: str,
        uuids: Sequence[str],
        owning_generation: int,
    ) -> int:
        """Delete objects ONLY where the writing generation is STRICTLY OLDER (N37).

        The condition is evaluated by the store together with the delete, and it
        orders against a number the CALLER owns -- its own generation -- not against
        a value it happened to read. That is what authorises the delete: an equality
        against an observed value closes only the interval between the read and the
        delete; it never establishes whose generation the value belonged to, so a
        resumed writer could delete a NEWER generation's data by simply observing it.

        Because the source generation ladder is persistent and strictly monotonic, a
        superseding owner always holds a HIGHER generation, so:

        - a superseded holder can never match the new owner's objects, in either race
          order (it reads them before or after -- the condition is the same);
        - every legitimately deletable object of a PREVIOUS generation still matches,
          including objects from several different earlier generations at once.

        Args:
            project_id: Authoritative bound project -- part of the condition (AC4).
            source_file: The claimed source -- part of the condition (AC4).
            uuids: Candidate object ids.
            owning_generation: The deleting claim's own generation (exclusive bound).

        Returns:
            The exact number of objects the store confirms deleted.

        Raises:
            VectorDbUnavailableError: For a non-positive generation (fail-closed).
        """
        if owning_generation < 1:
            raise VectorDbUnavailableError(
                f"refusing to delete with a non-positive owning generation ({owning_generation}); fail-closed (N37)."
            )
        return self.client.delete_by_ids_if_property_below(
            collection=self.collection,
            uuids=tuple(uuids),
            prop=OWNING_GENERATION_PROPERTY,
            limit=owning_generation,
            project_id=project_id,
            source_file=source_file,
        )

    def delete_objects_without_generation(self, *, project_id: str, source_file: str, uuids: Sequence[str]) -> int:
        """Delete objects that carry NO writing generation at all (N43).

        The condition is an IS-NULL evaluated by the store, so it can only ever match
        rows written before the ownership-ordering property existed. A row written by
        ANY generation is stamped, so this can never touch the caller's own data and
        never a newer owner's -- which is what makes the legacy backfill safe without
        adopting foreign content into a generation.

        Args:
            project_id: Authoritative bound project -- part of the condition (AC4).
            source_file: The claimed source -- part of the condition (AC4).
            uuids: Candidate object ids of that source.

        Returns:
            The exact number of objects the store confirms deleted.
        """
        if not uuids:
            return 0
        return self.client.delete_by_ids_if_property_absent(
            collection=self.collection,
            uuids=tuple(uuids),
            prop=OWNING_GENERATION_PROPERTY,
            project_id=project_id,
            source_file=source_file,
        )

    def get_receipt(self, *, project_id: str, source_file: str) -> SyncReceipt | None:
        """Return the AUTHORITATIVE completion of one source (N28/N39).

        The winner is the highest SOURCE GENERATION, not the highest completion
        position. Insert-only records prevent an overwrite, but they do not make a
        stale APPEND harmless: a superseded writer that publishes after the newer
        owner would take the next position and, ordered by position, would become
        freshness-authoritative and prune the newer owner's valid completion. The
        generation is monotonic per source, so a superseded generation can never win.
        """
        completions = [receipt for receipt in self.list_receipts(project_id=project_id) if receipt.source_file == source_file]
        if not completions:
            return None
        return max(completions, key=lambda r: (r.generation, r.sequence))

    def set_receipt(self, *, receipt: SyncReceipt) -> SyncReceipt:
        """Establish one completion through the shared atomic run-order contract."""
        from agentkit.backend.vectordb.ingest.classify import (
            producer_for,
            source_types_for_producer,
        )

        receipt.stamped(sequence=1).verify()
        producer = producer_for(receipt.source_type)
        if producer is None:
            raise VectorDbWriteError(
                f"source type {receipt.source_type!r} has no completion producer"
            )
        producer_completion = ProducerCompletion(
            project_id=receipt.project_id,
            producer=producer,
            source_types=source_types_for_producer(producer),
            corpus_revision=receipt.corpus_revision,
        )
        run_id = completion_run_id(
            receipt.project_id,
            (receipt,),
            (producer_completion,),
        )
        sealed = self.set_receipts(
            run_id=run_id,
            receipts=(receipt,),
            producer_completions=(producer_completion,),
        )
        return sealed[0]

    def set_receipts(
        self,
        *,
        run_id: str,
        receipts: Sequence[SyncReceipt],
        producer_completions: Sequence[ProducerCompletion],
    ) -> Sequence[SyncReceipt]:
        """Publish a run idempotently through one position-bound atomic insert."""
        candidates = tuple(receipts)
        producer_candidates = tuple(producer_completions)
        if not producer_candidates:
            raise VectorDbWriteError(
                "completion run has no producer-wide completion summary"
            )
        project_ids = {receipt.project_id for receipt in candidates}
        project_ids.update(item.project_id for item in producer_candidates)
        identities = {(receipt.source_file, receipt.generation) for receipt in candidates}
        producers = {item.producer for item in producer_candidates}
        if (
            len(project_ids) != 1
            or len(identities) != len(candidates)
            or len(producers) != len(producer_candidates)
        ):
            raise VectorDbWriteError(
                "completion run must contain one project and unique sources/producers"
            )
        project_id = next(iter(project_ids))
        expected_run_id = completion_run_id(
            project_id,
            candidates,
            producer_candidates,
        )
        if run_id != expected_run_id:
            raise VectorDbWriteError(
                "completion run_id does not bind the exact semantic payload"
            )
        self.resolve_pending_commits(project_id=project_id)
        existing = self._find_run_by_id(project_id, run_id)
        if existing is not None:
            self._assert_semantic_run_match(
                existing,
                candidates,
                producer_candidates,
            )
            return existing.receipts
        return self._publish_completion_run(
            project_id=project_id,
            run_id=run_id,
            receipts=candidates,
            producer_completions=producer_candidates,
        )

    def resolve_pending_commits(self, *, project_id: str) -> None:
        """Resolve every durable unknown outcome before another corpus mutation."""
        for pending in self.recovery_journal.list_pending(project_id):
            self._resolve_pending_commit(project_id=project_id, pending=pending)

    def _resolve_pending_commit(
        self,
        *,
        project_id: str,
        pending: CompletionCommitJournalEntry,
    ) -> None:
        attempted = self._read_pending_position(pending)
        if attempted is not None:
            if attempted.properties == pending.properties:
                self._clear_recovery(pending.run_id)
            else:
                self._republish_pending(project_id=project_id, pending=pending)
            return
        try:
            inserted = self.client.insert_object(
                collection=RUN_RECEIPT_COLLECTION,
                uuid=pending.record_uuid,
                properties=pending.properties,
            )
        except VectorDbWriteError as exc:
            self._resolve_pending_insert_error(
                project_id=project_id,
                pending=pending,
                error=exc,
            )
            return
        self._resolve_pending_insert_result(
            project_id=project_id,
            pending=pending,
            inserted=inserted,
        )

    def _resolve_pending_insert_error(
        self,
        *,
        project_id: str,
        pending: CompletionCommitJournalEntry,
        error: VectorDbWriteError,
    ) -> None:
        verified = self._read_run_after_error(pending, error)
        if verified.properties == pending.properties:
            self._clear_recovery(pending.run_id)
            return
        self._republish_pending(project_id=project_id, pending=pending)

    def _resolve_pending_insert_result(
        self,
        *,
        project_id: str,
        pending: CompletionCommitJournalEntry,
        inserted: bool,
    ) -> None:
        if inserted:
            self._clear_recovery(pending.run_id)
            return
        try:
            position_owner = self._read_run_at_uuid(
                pending.project_id,
                pending.record_uuid,
            )
        except VectorDbUnavailableError as exc:
            _finish_not_committed(self.recovery_journal, pending)
            raise VectorDbUnavailableError(
                f"pending completion run {pending.run_id!r} lost its conditional "
                "create and its collision owner is unreadable; the run is "
                "definitively not committed"
            ) from exc
        if position_owner is None:
            _finish_not_committed(self.recovery_journal, pending)
            raise VectorDbWriteError(
                f"pending completion run {pending.run_id!r} was rejected without "
                "a readable collision owner; it is definitively not committed"
            )
        if position_owner.properties == pending.properties:
            self._clear_recovery(pending.run_id)
            return
        self._republish_pending(project_id=project_id, pending=pending)

    def _republish_pending(
        self,
        *,
        project_id: str,
        pending: CompletionCommitJournalEntry,
    ) -> None:
        parsed = _parse_run_record(
            pending.record_uuid,
            pending.properties,
            project_id=project_id,
        )
        self._publish_completion_run(
            project_id=project_id,
            run_id=pending.run_id,
            receipts=tuple(_unstamp_receipt(item) for item in parsed.receipts),
            producer_completions=tuple(
                _unstamp_producer_completion(item)
                for item in parsed.producer_completions
            ),
        )

    def _publish_completion_run(
        self,
        *,
        project_id: str,
        run_id: str,
        receipts: tuple[SyncReceipt, ...],
        producer_completions: tuple[ProducerCompletion, ...],
    ) -> tuple[SyncReceipt, ...]:
        candidate = self._highest_completion_sequence(project_id) + 1
        for _attempt in range(_COMPLETION_ATTEMPT_LIMIT):
            record = self._build_run_record(
                project_id=project_id,
                run_id=run_id,
                receipts=receipts,
                producer_completions=producer_completions,
                sequence_start=candidate,
            )
            pending = CompletionCommitJournalEntry(
                state=CommitRecoveryState.OUTCOME_UNKNOWN,
                project_id=project_id,
                run_id=run_id,
                record_uuid=record.uuid,
                properties=record.properties,
            )
            self.recovery_journal.stage_unknown(pending)
            try:
                inserted = self.client.insert_object(
                    collection=RUN_RECEIPT_COLLECTION,
                    uuid=record.uuid,
                    properties=record.properties,
                )
            except VectorDbWriteError as exc:
                verified = self._read_run_after_error(pending, exc)
                if verified.properties == pending.properties:
                    self._clear_recovery(run_id)
                    return verified.receipts
                _finish_not_committed(self.recovery_journal, pending)
                candidate = verified.sequence_end + 1
                continue
            if inserted:
                self._clear_recovery(run_id)
                return record.receipts
            try:
                collision = self._read_run_at_uuid(project_id, record.uuid)
            except VectorDbUnavailableError as exc:
                _finish_not_committed(self.recovery_journal, pending)
                raise VectorDbUnavailableError(
                    f"completion position {candidate} rejected this run and its "
                    "collision owner is unreadable; the run is definitively not "
                    "committed"
                ) from exc
            if collision is None:
                _finish_not_committed(self.recovery_journal, pending)
                raise VectorDbWriteError(
                    f"completion position {candidate} rejected this run without "
                    "a readable owner; it is definitively not committed"
                )
            if collision.properties == record.properties:
                self._clear_recovery(run_id)
                return collision.receipts
            _finish_not_committed(self.recovery_journal, pending)
            candidate = collision.sequence_end + 1
        raise VectorDbWriteError(
            f"could not atomically reserve a completion range after "
            f"{_COMPLETION_ATTEMPT_LIMIT} attempts"
        )

    def _build_run_record(
        self,
        *,
        project_id: str,
        run_id: str,
        receipts: tuple[SyncReceipt, ...],
        producer_completions: tuple[ProducerCompletion, ...],
        sequence_start: int,
    ) -> _CompletionRunRecord:
        sealed = tuple(
            receipt.stamped(sequence=sequence_start + offset)
            for offset, receipt in enumerate(receipts)
        )
        sequence_end = sequence_start + max(1, len(sealed)) - 1
        sealed_producers = tuple(
            completion.stamped(sequence=sequence_end)
            for completion in producer_completions
        )
        completed_at = _iso(self.clock())
        receipts_json = _render_receipt_batch(sealed)
        producer_json = _render_producer_completions(sealed_producers)
        digest = _run_receipt_digest(
            project_id=project_id,
            run_id=run_id,
            receipts_json=receipts_json,
            producer_completions_json=producer_json,
            completed_at=completed_at,
            sequence_start=sequence_start,
            sequence_end=sequence_end,
        )
        properties = {
            "project_id": project_id,
            "run_id": run_id,
            "receipts_json": receipts_json,
            "producer_completions_json": producer_json,
            "batch_digest": digest,
            "completed_at": completed_at,
            "sequence_start": str(sequence_start),
            "sequence_end": str(sequence_end),
        }
        return _CompletionRunRecord(
            uuid=self._run_position_uuid(project_id, sequence_start),
            properties=properties,
            receipts=sealed,
            producer_completions=sealed_producers,
            sequence_start=sequence_start,
            sequence_end=sequence_end,
        )

    def _read_run_after_error(
        self,
        pending: CompletionCommitJournalEntry,
        write_error: VectorDbWriteError,
    ) -> _CompletionRunRecord:
        try:
            record = self._read_run_at_uuid(
                pending.project_id,
                pending.record_uuid,
            )
        except VectorDbUnavailableError as read_error:
            raise CommitOutcomeUnknownError(
                f"completion run {pending.run_id!r} write acknowledgement was lost "
                "and strict read-back failed; recovery journal retained"
            ) from read_error
        if record is not None and record.properties == pending.properties:
            return record
        if record is not None:
            return record
        _finish_not_committed(self.recovery_journal, pending)
        raise write_error

    def _read_pending_position(
        self,
        pending: CompletionCommitJournalEntry,
    ) -> _CompletionRunRecord | None:
        """Read a journaled position without losing its unknown-outcome identity."""
        try:
            return self._read_run_at_uuid(
                pending.project_id,
                pending.record_uuid,
            )
        except VectorDbUnavailableError as exc:
            raise CommitOutcomeUnknownError(
                f"pending completion run {pending.run_id!r} cannot be resolved "
                "because its atomic position is unreadable; recovery journal retained"
            ) from exc

    def _read_run_at_uuid(
        self,
        project_id: str,
        record_uuid: str,
    ) -> _CompletionRunRecord | None:
        matches = [
            _parse_run_record(uid, props, project_id=project_id)
            for uid, props in self.client.fetch_by_property(
                collection=RUN_RECEIPT_COLLECTION,
                project_id=project_id,
                prop="project_id",
                value=project_id,
                return_props=RUN_RECEIPT_PROPERTIES,
            )
            if uid == record_uuid
        ]
        if len(matches) > 1:
            raise VectorDbUnavailableError(
                f"completion position {record_uuid!r} is duplicated"
            )
        return matches[0] if matches else None

    def _find_run_by_id(
        self,
        project_id: str,
        run_id: str,
    ) -> _CompletionRunRecord | None:
        rows = self.client.fetch_by_property(
            collection=RUN_RECEIPT_COLLECTION,
            project_id=project_id,
            prop="run_id",
            value=run_id,
            return_props=RUN_RECEIPT_PROPERTIES,
        )
        if len(rows) > 1:
            raise VectorDbUnavailableError(
                f"completion run_id {run_id!r} is duplicated"
            )
        return (
            _parse_run_record(rows[0][0], rows[0][1], project_id=project_id)
            if rows
            else None
        )

    def _assert_semantic_run_match(
        self,
        record: _CompletionRunRecord,
        receipts: tuple[SyncReceipt, ...],
        producer_completions: tuple[ProducerCompletion, ...],
    ) -> None:
        actual_receipts = tuple(_unstamp_receipt(item) for item in record.receipts)
        actual_producers = tuple(
            _unstamp_producer_completion(item)
            for item in record.producer_completions
        )
        if actual_receipts != receipts or actual_producers != producer_completions:
            raise VectorDbUnavailableError(
                f"completion run {record.properties['run_id']!r} does not match "
                "its deterministic semantic payload"
            )

    def _clear_recovery(self, run_id: str) -> None:
        try:
            self.recovery_journal.finish_committed(run_id)
        except (OSError, VectorDbWriteError) as exc:
            raise CommitOutcomeUnknownError(
                f"completion run {run_id!r} committed, but its durable recovery "
                "entry could not be cleared"
            ) from exc

    @staticmethod
    def _completion_uuid(project_id: str, sequence: int) -> str:
        return str(uuid.uuid5(_RECEIPT_NAMESPACE, f"{project_id}|{sequence}"))

    @staticmethod
    def _run_position_uuid(project_id: str, sequence_start: int) -> str:
        return str(
            uuid.uuid5(
                _RUN_RECEIPT_NAMESPACE,
                f"{project_id}|{sequence_start}",
            )
        )

    def _highest_completion_sequence(self, project_id: str) -> int:
        """Return the highest completion position already established (N28)."""
        rows = self.client.fetch_by_property(
            collection=RECEIPT_COLLECTION,
            project_id=project_id,
            prop="project_id",
            value=project_id,
            return_props=RECEIPT_PROPERTIES,
        )
        highest = 0
        for _uid, props in rows:
            highest = max(highest, _positive_int(props.get("sequence"), field_name="sequence"))
        for _uid, props in self.client.fetch_by_property(
            collection=RUN_RECEIPT_COLLECTION,
            project_id=project_id,
            prop="project_id",
            value=project_id,
            return_props=RUN_RECEIPT_PROPERTIES,
        ):
            highest = max(
                highest,
                _positive_int(props.get("sequence_end"), field_name="sequence_end"),
            )
        return highest

    def _prune_superseded_completions(self, current: SyncReceipt) -> None:
        """Delete completions of the SAME source from OLDER generations (N39).

        Pruning follows the same order as the authority rule: only a strictly lower
        SOURCE GENERATION is superseded. Pruning by completion position would let a
        stale append delete the newer owner's valid completion (best-effort
        housekeeping either way -- correctness comes from the winning record).
        """
        import contextlib

        stale = [
            self._completion_uuid(current.project_id, receipt.sequence)
            for receipt in self.list_receipts(project_id=current.project_id)
            if receipt.source_file == current.source_file and receipt.generation < current.generation
        ]
        if not stale:
            return
        with contextlib.suppress(VectorDbUnavailableError, VectorDbWriteError):
            self.client.delete_by_ids(collection=RECEIPT_COLLECTION, uuids=stale)

    def list_receipts(self, *, project_id: str) -> Sequence[SyncReceipt]:
        """Return every persisted completion of a project (each verified, N08/N28)."""
        rows = self.client.fetch_by_property(
            collection=RECEIPT_COLLECTION,
            project_id=project_id,
            prop="project_id",
            value=project_id,
            return_props=RECEIPT_PROPERTIES,
        )
        out: list[SyncReceipt] = []
        for uid, props in rows:
            source_file = props.get("source_file")
            if not isinstance(source_file, str) or not source_file:
                raise VectorDbUnavailableError("persisted sync completion carries no usable 'source_file'; fail-closed (N08).")
            completion = receipt_from_props(project_id, source_file, props)
            # The record's POSITION is part of its identity: a completion stored
            # under a different position than it binds to has been moved/replayed.
            expected_uuid = self._completion_uuid(project_id, completion.sequence)
            if uid != expected_uuid:
                raise VectorDbUnavailableError(
                    f"persisted completion for {source_file!r} is stored at {uid!r} "
                    f"but binds position {completion.sequence} ({expected_uuid!r}); "
                    "fail-closed (N28: completions are immutable and position-bound)."
                )
            out.append(completion)
        run_records = self._list_run_records(project_id)
        _verify_global_completion_ranges(
            [(receipt.sequence, receipt.sequence) for receipt in out]
            + [
                (record.sequence_start, record.sequence_end)
                for record in run_records
            ]
        )
        out.extend(
            receipt
            for record in run_records
            for receipt in record.receipts
        )
        return out

    def _list_run_receipts(self, project_id: str) -> list[SyncReceipt]:
        """Read and verify atomically published multi-source run records."""
        return [
            receipt
            for record in self._list_run_records(project_id)
            for receipt in record.receipts
        ]

    def list_producer_completions(
        self,
        *,
        project_id: str,
    ) -> Sequence[ProducerCompletion]:
        """Return producer-wide completions, including zero-source successes."""
        records = self._list_run_records(project_id)
        _verify_global_completion_ranges(
            [
                (record.sequence_start, record.sequence_end)
                for record in records
            ]
        )
        return [
            completion
            for record in records
            for completion in record.producer_completions
        ]

    def _list_run_records(self, project_id: str) -> list[_CompletionRunRecord]:
        """Read every immutable run record strictly."""
        rows = self.client.fetch_by_property(
            collection=RUN_RECEIPT_COLLECTION,
            project_id=project_id,
            prop="project_id",
            value=project_id,
            return_props=RUN_RECEIPT_PROPERTIES,
        )
        records = [
            _parse_run_record(uid, props, project_id=project_id)
            for uid, props in rows
        ]
        run_ids = [record.properties["run_id"] for record in records]
        if len(run_ids) != len(set(run_ids)):
            raise VectorDbUnavailableError("completion run_id is not globally unique")
        return records

    def try_claim_source(self, *, project_id: str, source_file: str, owner_id: str) -> SourceClaim | None:
        """Atomically claim a source by CREATING the next source generation (N37).

        The claim is STORE-LEVEL and ATOMIC (N03/D3): each generation is a distinct
        record whose uuid folds in the generation number, so acquiring it is a
        compare-and-create the store arbitrates -- there is no read-then-write window
        in which two writers both observe "no claim" and both proceed.

        The generation ladder is PERSISTENT and STRICTLY MONOTONIC per
        ``(project_id, source_file)`` (N37): a normal release does not remove the
        ladder position, it adds an insert-only ``released`` marker, so the next
        acquisition allocates a strictly HIGHER number. Without that, a released
        claim used to reset the ladder to 1 and no ordering statement about "who
        wrote this object" was decidable at all.

        There is NO time-based takeover (N27/D3): a HELD generation rejects the
        writer, no matter how old it is. It is released only by its holder finishing
        or by the EXPLICIT :meth:`reclaim_source` path.
        """
        rows = self._generation_rows(project_id, source_file)
        highest = self._highest_generation(rows)
        if self._held_claim(project_id, source_file, rows) is not None:
            return None
        return self._create_generation(
            project_id=project_id,
            source_file=source_file,
            owner_id=owner_id,
            generation=highest + 1,
        )

    def reclaim_source(self, *, project_id: str, source_file: str, owner_id: str, reason: str) -> SourceClaim:
        """ADMINISTRATIVELY take a claim over by creating the NEXT generation (N27).

        Only reached from an explicit operator path, which asserts the previous
        holder is dead. The takeover is a conditional CREATE of the next generation,
        so two concurrent reclaimers still produce exactly one winner, and the
        previous holder can never again delete data this generation writes (N37: its
        generation is strictly lower).
        """
        rows = self._generation_rows(project_id, source_file)
        held = self._held_claim(project_id, source_file, rows)
        generation = self._highest_generation(rows) + 1
        claim = self._create_generation(
            project_id=project_id,
            source_file=source_file,
            owner_id=owner_id,
            generation=generation,
            reclaimed_from=held.owner_id if held is not None else "",
            reason=reason,
        )
        if claim is None:
            raise ConcurrentSyncRejectedError(
                f"administrative reclaim of {(project_id, source_file)!r} lost the "
                f"race for generation {generation}; fail-closed (N27)."
            )
        return claim

    def _create_generation(
        self,
        *,
        project_id: str,
        source_file: str,
        owner_id: str,
        generation: int,
        reclaimed_from: str = "",
        reason: str = "",
    ) -> SourceClaim | None:
        """Conditionally CREATE one generation; ``None`` when it is already taken."""
        claimed_at = _iso(self._now())
        acquired = self.client.insert_object(
            collection=CLAIM_COLLECTION,
            uuid=self._claim_uuid(project_id, source_file, generation),
            properties={
                "project_id": project_id,
                "source_file": source_file,
                "state": CLAIM_STATE_HELD,
                "owner_id": owner_id,
                "generation": str(generation),
                "claimed_at": claimed_at,
                "reclaimed_from": reclaimed_from,
                "reclaim_reason": reason,
            },
        )
        if not acquired:
            return None
        self._prune_generations_below(project_id, source_file, generation)
        return SourceClaim(
            project_id=project_id,
            source_file=source_file,
            owner_id=owner_id,
            generation=generation,
            claimed_at=claimed_at,
            reclaimed_from=reclaimed_from,
        )

    def assert_claim_held(self, *, claim: SourceClaim) -> None:
        """Fence: the claim must still be the HELD generation (N15/N27).

        This check can be overtaken between here and the following mutation, which
        is why it is NOT what protects the destructive step -- that is bound
        storage-side to the generation ordering (N37).
        """
        held = self._held_claim(claim.project_id, claim.source_file)
        if held is None or held.generation != claim.generation or held.owner_id != claim.owner_id:
            raise ClaimSupersededError(
                f"source claim on {(claim.project_id, claim.source_file)!r} was "
                f"superseded (held generation {claim.generation} owner "
                f"{claim.owner_id!r}, active {held!r}); fail-closed (N15/N27)."
            )

    def release_source(self, *, claim: SourceClaim) -> None:
        """Release the held generation by ADDING its release marker (N37/N45).

        Insert-only: the ladder position survives, so the next acquisition of this
        source is strictly higher.

        The release is CONFIRMED, not best-effort (N45). A suppressed failure left the
        source held forever: the sync could publish its completion, fail to persist the
        marker, report success, and every later sync of that source would then be
        rejected until someone issued an administrative reclaim with no idea why. A
        release that did not land is therefore a typed, named fault.

        Raises:
            ClaimReleaseFailedError: When the marker could not be persisted, or the
                store denied it. An ALREADY EXISTING marker is success -- releasing
                twice is idempotent, not a fault.
        """
        from agentkit.backend.vectordb.sync import ClaimReleaseFailedError

        try:
            created = self.client.insert_object(
                collection=CLAIM_COLLECTION,
                uuid=self._release_uuid(claim.project_id, claim.source_file, claim.generation),
                properties={
                    "project_id": claim.project_id,
                    "source_file": claim.source_file,
                    "state": CLAIM_STATE_RELEASED,
                    "owner_id": claim.owner_id,
                    "generation": str(claim.generation),
                    "claimed_at": _iso(self._now()),
                    "reclaimed_from": "",
                    "reclaim_reason": "",
                },
            )
        except (VectorDbUnavailableError, VectorDbWriteError) as exc:
            raise ClaimReleaseFailedError(
                f"source {(claim.project_id, claim.source_file)!r} generation "
                f"{claim.generation} could NOT be released ({exc}); it stays HELD and "
                "every later sync of it will be rejected until an administrative "
                "reclaim. Reported instead of suppressed (fail-closed, N45)."
            ) from exc
        if not created and not self._release_marker_exists(claim):
            raise ClaimReleaseFailedError(
                f"source {(claim.project_id, claim.source_file)!r} generation "
                f"{claim.generation} could NOT be released: the store neither created "
                "nor holds the release marker; it stays HELD (fail-closed, N45)."
            )

    def _release_marker_exists(self, claim: SourceClaim) -> bool:
        """Whether THIS generation's valid release marker is persisted (N45/N50).

        The deterministic uuid alone is not proof. Accepting any row stored at that id
        meant a malformed duplicate -- e.g. one carrying ``state=claimed`` -- made the
        sync report a successful release while the source stayed HELD, which is exactly
        the silent-success path N45 closed. The persisted record is therefore validated
        in FULL: it must be a ``released`` marker for this project, source, owner and
        generation. Anything else is not this claim's release.

        Args:
            claim: The claim whose release is being confirmed.

        Returns:
            ``True`` only for a complete, matching release marker.
        """
        wanted = self._release_uuid(claim.project_id, claim.source_file, claim.generation)
        expected = {
            "project_id": claim.project_id,
            "source_file": claim.source_file,
            "state": CLAIM_STATE_RELEASED,
            "owner_id": claim.owner_id,
            "generation": str(claim.generation),
        }
        for uid, props in self._generation_rows(claim.project_id, claim.source_file):
            if uid != wanted:
                continue
            return all(props.get(name) == value for name, value in expected.items())
        return False

    def _prune_generations_below(self, project_id: str, source_file: str, generation: int) -> None:
        """Drop ladder records BELOW the given generation (housekeeping only).

        The record of the highest generation is never removed, so the ladder cannot
        reset -- that is the property the destructive delete depends on. Everything
        below it carries no decision any more.
        """
        import contextlib

        stale: list[str] = []
        for _uid, props in self._generation_rows(project_id, source_file):
            row_generation = _positive_int(props.get("generation"), field_name="generation")
            if row_generation >= generation:
                continue
            stale.append(self._claim_uuid(project_id, source_file, row_generation))
            stale.append(self._release_uuid(project_id, source_file, row_generation))
        if not stale:
            return
        with contextlib.suppress(VectorDbUnavailableError, VectorDbWriteError):
            self.client.delete_by_ids(collection=CLAIM_COLLECTION, uuids=stale)

    @staticmethod
    def _claim_uuid(project_id: str, source_file: str, generation: int) -> str:
        return str(uuid.uuid5(_CLAIM_NAMESPACE, f"{project_id}|{source_file}|{generation}"))

    @staticmethod
    def _release_uuid(project_id: str, source_file: str, generation: int) -> str:
        return str(uuid.uuid5(_CLAIM_NAMESPACE, f"{project_id}|{source_file}|{generation}|released"))

    def _generation_rows(self, project_id: str, source_file: str) -> list[tuple[str, Mapping[str, object]]]:
        """Return this source's ladder records (claims AND release markers).

        Read with the SAME server-side project scope as the corpus (AC4/N51): the
        app-side filter that used to follow was not enough, because another project
        holding the same ``source_file`` still had to be transported and could push this
        read into the pagination ceiling.
        """
        return list(
            self.client.fetch_by_property(
                collection=CLAIM_COLLECTION,
                project_id=project_id,
                prop="source_file",
                value=source_file,
                return_props=CLAIM_PROPERTIES,
            )
        )

    @staticmethod
    def _highest_generation(rows: Sequence[tuple[str, Mapping[str, object]]]) -> int:
        """Return the highest generation EVER allocated for the source (N37).

        Release markers count: the ladder must not reset when a claim is released,
        or "written by an older generation" stops being decidable.
        """
        highest = 0
        for _uid, props in rows:
            highest = max(highest, _positive_int(props.get("generation"), field_name="generation"))
        return highest

    def _held_claim(
        self,
        project_id: str,
        source_file: str,
        rows: Sequence[tuple[str, Mapping[str, object]]] | None = None,
    ) -> SourceClaim | None:
        """Return the currently HELD claim of a source, or ``None``.

        The highest generation decides: it is held when it has a ``claimed`` record
        and no ``released`` marker. Older generations carry no ownership any more.
        """
        ladder = list(rows) if rows is not None else self._generation_rows(project_id, source_file)
        highest = self._highest_generation(ladder)
        if highest == 0:
            return None
        claimed: SourceClaim | None = None
        for _uid, props in ladder:
            generation = _positive_int(props.get("generation"), field_name="generation")
            if generation != highest:
                continue
            if props.get("state") == CLAIM_STATE_RELEASED:
                return None
            claimed = _claim_from_props(project_id, source_file, props)
        return claimed

    def _now(self) -> datetime:
        return self.clock()


def _finish_not_committed(
    journal: FileCommitRecoveryJournal,
    pending: CompletionCommitJournalEntry,
) -> None:
    """Persist terminal failure or preserve honest outcome-unknown semantics."""
    try:
        journal.finish_not_committed(pending)
    except (OSError, VectorDbWriteError) as exc:
        raise CommitOutcomeUnknownError(
            f"completion run {pending.run_id!r} is not committed, but its terminal "
            "journal state could not be persisted; recovery remains outcome-unknown"
        ) from exc


def _positive_int(raw: object, *, field_name: str) -> int:
    """Read a positive integer strictly (no coercion, no bool-as-int, N08/N16)."""
    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        raise VectorDbUnavailableError(f"persisted record has a non-numeric {field_name!r} ({raw!r}); fail-closed (N08/N16).")
    try:
        value = int(raw)
    except ValueError as exc:
        raise VectorDbUnavailableError(
            f"persisted record has a non-numeric {field_name!r} ({raw!r}); fail-closed (N08/N16)."
        ) from exc
    if value < 1:
        raise VectorDbUnavailableError(f"persisted record has a non-positive {field_name!r} ({value}); fail-closed (N08/N16).")
    return value


def _render_receipt_batch(receipts: Sequence[SyncReceipt]) -> str:
    """Render a canonical immutable completion batch."""
    payload = [
        {
            "project_id": receipt.project_id,
            "source_file": receipt.source_file,
            "source_type": receipt.source_type,
            "corpus_revision": receipt.corpus_revision,
            "digest": receipt.digest,
            "state": receipt.state.value,
            "completed_at": receipt.completed_at,
            "sequence": receipt.sequence,
            "generation": receipt.generation,
        }
        for receipt in receipts
    ]
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _render_producer_completions(
    completions: Sequence[ProducerCompletion],
) -> str:
    payload = [
        {
            "corpus_revision": completion.corpus_revision,
            "producer": completion.producer,
            "project_id": completion.project_id,
            "sequence": completion.sequence,
            "source_types": list(completion.source_types),
        }
        for completion in completions
    ]
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _run_receipt_digest(
    *,
    project_id: str,
    run_id: str,
    receipts_json: str,
    producer_completions_json: str,
    completed_at: str,
    sequence_start: int,
    sequence_end: int,
) -> str:
    """Bind the run record to its identity, receipt content and order."""
    material = json.dumps(
        {
            "completed_at": completed_at,
            "project_id": project_id,
            "producer_completions_json": producer_completions_json,
            "receipts_json": receipts_json,
            "run_id": run_id,
            "sequence_end": sequence_end,
            "sequence_start": sequence_start,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _reject_duplicate_json_pairs(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    """Reject duplicate keys in persisted receipt JSON (no last-wins)."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise VectorDbUnavailableError(
                f"completion batch contains duplicate JSON key {key!r}"
            )
        result[key] = value
    return result


def _parse_receipt_batch(
    *,
    project_id: str,
    raw: str,
) -> list[SyncReceipt]:
    """Strictly parse every receipt in one immutable run record."""
    try:
        payload = json.loads(raw, object_pairs_hook=_reject_duplicate_json_pairs)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise VectorDbUnavailableError(
            f"completion batch is not strict JSON: {exc}"
        ) from exc
    if not isinstance(payload, list):
        raise VectorDbUnavailableError(
            "completion batch must be a JSON list"
        )
    out: list[SyncReceipt] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise VectorDbUnavailableError(
                f"completion batch item {index} is not an object"
            )
        if set(item) != set(RECEIPT_PROPERTIES):
            raise VectorDbUnavailableError(
                f"completion batch item {index} has an invalid field set"
            )
        source_file = item.get("source_file")
        if not isinstance(source_file, str) or not source_file:
            raise VectorDbUnavailableError(
                f"completion batch item {index} has no source_file"
            )
        out.append(receipt_from_props(project_id, source_file, item))
    return out


def _parse_producer_completions(
    *,
    project_id: str,
    raw: str,
) -> list[ProducerCompletion]:
    try:
        payload = json.loads(raw, object_pairs_hook=_reject_duplicate_json_pairs)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise VectorDbUnavailableError(
            f"producer completion batch is not strict JSON: {exc}"
        ) from exc
    if not isinstance(payload, list) or not payload:
        raise VectorDbUnavailableError(
            "producer completion batch must be a non-empty JSON list"
        )
    completions: list[ProducerCompletion] = []
    for index, item in enumerate(payload):
        completions.append(
            _parse_producer_completion_item(
                project_id=project_id,
                item=item,
                index=index,
            )
        )
    producers = [item.producer for item in completions]
    if len(producers) != len(set(producers)):
        raise VectorDbUnavailableError(
            "producer completion batch contains duplicate producers"
        )
    return completions


def _parse_producer_completion_item(
    *,
    project_id: str,
    item: object,
    index: int,
) -> ProducerCompletion:
    if not isinstance(item, dict):
        raise VectorDbUnavailableError(
            f"producer completion item {index} is not an object"
        )
    expected_keys = {
        "corpus_revision",
        "producer",
        "project_id",
        "sequence",
        "source_types",
    }
    if set(item) != expected_keys:
        raise VectorDbUnavailableError(
            f"producer completion item {index} has an invalid field set"
        )
    source_types = item["source_types"]
    if (
        not isinstance(source_types, list)
        or not source_types
        or any(not isinstance(value, str) or not value for value in source_types)
    ):
        raise VectorDbUnavailableError(
            f"producer completion item {index} has invalid source_types"
        )
    completion = ProducerCompletion(
        project_id=_strict_json_string(item["project_id"], field_name="project_id"),
        producer=_strict_json_string(item["producer"], field_name="producer"),
        source_types=tuple(source_types),
        corpus_revision=_strict_json_string(
            item["corpus_revision"],
            field_name="corpus_revision",
        ),
        sequence=_positive_int(item["sequence"], field_name="sequence"),
    )
    if completion.project_id != project_id:
        raise VectorDbUnavailableError(
            "producer completion carries a foreign project identity"
        )
    try:
        completion.verify()
    except SyncError as exc:
        raise VectorDbUnavailableError(
            f"producer completion item {index} is invalid: {exc}"
        ) from exc
    return completion


def _parse_run_record(
    uid: str,
    props: Mapping[str, object],
    *,
    project_id: str,
) -> _CompletionRunRecord:
    values = _required_strings(
        props,
        RUN_RECEIPT_PROPERTIES,
        context=f"completion run {uid!r}",
    )
    if values["project_id"] != project_id:
        raise VectorDbUnavailableError(
            f"completion run {uid!r} carries a foreign project identity"
        )
    sequence_start = _positive_int(
        values["sequence_start"],
        field_name="sequence_start",
    )
    sequence_end = _positive_int(
        values["sequence_end"],
        field_name="sequence_end",
    )
    expected_uuid = WeaviateCorpusStore._run_position_uuid(
        project_id,
        sequence_start,
    )
    if uid != expected_uuid:
        raise VectorDbUnavailableError(
            f"completion run {values['run_id']!r} is stored under the wrong "
            "atomic position identity"
        )
    expected_digest = _run_receipt_digest(
        project_id=project_id,
        run_id=values["run_id"],
        receipts_json=values["receipts_json"],
        producer_completions_json=values["producer_completions_json"],
        completed_at=values["completed_at"],
        sequence_start=sequence_start,
        sequence_end=sequence_end,
    )
    if values["batch_digest"] != expected_digest:
        raise VectorDbUnavailableError(
            f"completion run {values['run_id']!r} has an invalid digest"
        )
    try:
        parse_utc_timestamp(values["completed_at"])
    except SyncError as exc:
        raise VectorDbUnavailableError(
            f"completion run {values['run_id']!r} has an invalid timestamp"
        ) from exc
    receipts = tuple(
        _parse_receipt_batch(
            project_id=project_id,
            raw=values["receipts_json"],
        )
    )
    producers = tuple(
        _parse_producer_completions(
            project_id=project_id,
            raw=values["producer_completions_json"],
        )
    )
    sequences = [receipt.sequence for receipt in receipts]
    expected_end = sequence_start + max(1, len(receipts)) - 1
    if (
        sequence_end != expected_end
        or sequences != list(range(sequence_start, sequence_start + len(receipts)))
        or any(item.sequence != sequence_end for item in producers)
    ):
        raise VectorDbUnavailableError(
            f"completion run {values['run_id']!r} has an invalid atomic range"
        )
    expected_run_id = completion_run_id(
        project_id,
        tuple(_unstamp_receipt(item) for item in receipts),
        tuple(_unstamp_producer_completion(item) for item in producers),
    )
    if values["run_id"] != expected_run_id:
        raise VectorDbUnavailableError(
            f"completion run {values['run_id']!r} does not bind its semantic payload"
        )
    return _CompletionRunRecord(
        uuid=uid,
        properties=values,
        receipts=receipts,
        producer_completions=producers,
        sequence_start=sequence_start,
        sequence_end=sequence_end,
    )


def _strict_json_string(raw: object, *, field_name: str) -> str:
    if not isinstance(raw, str) or not raw:
        raise VectorDbUnavailableError(
            f"producer completion has invalid {field_name!r}"
        )
    return raw


def _unstamp_receipt(receipt: SyncReceipt) -> SyncReceipt:
    return SyncReceipt.for_completion(
        project_id=receipt.project_id,
        source_file=receipt.source_file,
        source_type=receipt.source_type,
        corpus_revision=receipt.corpus_revision,
        generation=receipt.generation,
        completed_at=receipt.completed_at,
    )


def _unstamp_producer_completion(
    completion: ProducerCompletion,
) -> ProducerCompletion:
    return ProducerCompletion(
        project_id=completion.project_id,
        producer=completion.producer,
        source_types=completion.source_types,
        corpus_revision=completion.corpus_revision,
    )


def _verify_global_completion_ranges(
    ranges: Sequence[tuple[int, int]],
) -> None:
    previous_end = 0
    for start, end in sorted(ranges):
        if start <= previous_end:
            raise VectorDbUnavailableError(
                f"completion ranges overlap at position {start}"
            )
        if end < start:
            raise VectorDbUnavailableError("completion range ends before it starts")
        previous_end = end


def _required_strings(props: Mapping[str, object], names: Sequence[str], *, context: str) -> dict[str, str]:
    """Read mandatory string fields strictly (no ``str()`` coercion, N08)."""
    values: dict[str, str] = {}
    for field_name in names:
        raw = props.get(field_name)
        if not isinstance(raw, str) or not raw:
            raise VectorDbUnavailableError(
                f"persisted {context} has a missing/non-string {field_name!r} ({raw!r}); fail-closed (N08)."
            )
        values[field_name] = raw
    return values


def _claim_from_props(project_id: str, source_file: str, props: Mapping[str, object]) -> SourceClaim:
    """Rebuild a persisted claim strictly (owner/generation/timestamp, N15/N27/N37).

    There is NO expiry field: a claim never expires by time (N27). ``claimed_at``
    is diagnostics and must still be a valid UTC instant.
    """
    values = _required_strings(props, ("owner_id", "state", "claimed_at"), context="source claim")
    if values["state"] not in (CLAIM_STATE_HELD, CLAIM_STATE_RELEASED):
        raise VectorDbUnavailableError(
            f"persisted source claim for {source_file!r} has unknown state {values['state']!r}; fail-closed (N15)."
        )
    parse_utc_timestamp(values["claimed_at"])
    reclaimed_from = props.get("reclaimed_from")
    return SourceClaim(
        project_id=project_id,
        source_file=source_file,
        owner_id=values["owner_id"],
        generation=_positive_int(props.get("generation"), field_name="generation"),
        claimed_at=values["claimed_at"],
        reclaimed_from=reclaimed_from if isinstance(reclaimed_from, str) else "",
    )


def receipt_from_props(project_id: str, source_file: str, props: Mapping[str, object]) -> SyncReceipt:
    """Rebuild a persisted receipt with FULL verification (N08/N16).

    Every mandatory field must be present and string-typed (no ``str()``
    coercion), the state must be a KNOWN receipt state, the timestamp a UTC
    instant, the sequence positive, and the digest must bind every identity AND
    ordering field. Anything else raises -- a malformed, replayed or unknown-state
    receipt can never advance the reported freshness, and an unknown state is
    REJECTED rather than skipped (which would hide it).
    """
    from agentkit.backend.vectordb.sync import ReceiptState, SyncError

    values = _required_strings(
        props,
        ("project_id", "source_file", "source_type", "corpus_revision", "digest", "state", "completed_at"),
        context=f"sync receipt for {source_file!r}",
    )
    sequence = _positive_int(props.get("sequence"), field_name="sequence")
    generation = _positive_int(props.get("generation"), field_name="generation")
    if values["project_id"] != project_id or values["source_file"] != source_file:
        raise VectorDbUnavailableError(
            f"persisted sync receipt identity mismatch: record "
            f"({values['project_id']!r}, {values['source_file']!r}) != requested "
            f"({project_id!r}, {source_file!r}); fail-closed (N08)."
        )
    try:
        state = ReceiptState(values["state"])
    except ValueError as exc:
        raise VectorDbUnavailableError(
            f"persisted sync receipt for {source_file!r} has unknown state "
            f"{values['state']!r}; fail-closed (N16: an unknown state is rejected, "
            "never skipped)."
        ) from exc
    receipt = SyncReceipt(
        project_id=project_id,
        source_file=source_file,
        source_type=values["source_type"],
        corpus_revision=values["corpus_revision"],
        digest=values["digest"],
        state=state,
        completed_at=values["completed_at"],
        sequence=sequence,
        generation=generation,
    )
    try:
        receipt.verify()
    except SyncError as exc:
        raise VectorDbUnavailableError(f"persisted sync receipt for {source_file!r} is not trustworthy: {exc}") from exc
    return receipt


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
        # The source-type retrieval profile (schema SSOT) is BOTH the requested
        # property set and the strict validation spec the transport enforces on
        # every hit (N11).
        rows = self.client.search_objects(
            collection=self.collection,
            query=query,
            search_mode=search_mode,
            project_id=project_id,
            source_type=source_type,
            filters=filters,
            limit=limit,
            property_spec=search_property_spec(source_type),
        )
        return [{**props, "score": score, "snippet": str(props.get("content", ""))[:200]} for _uid, props, score in rows]

    def list_sources(self, *, project_id: str) -> Sequence[Mapping[str, object]]:
        from agentkit.backend.vectordb.ingest.classify import PRODUCER_BY_SOURCE_TYPE

        receipts = self.store.list_receipts(project_id=project_id)
        producer_completions = self.store.list_producer_completions(
            project_id=project_id
        )
        # AG3-177 (c): the authoritative generation per source comes from the SAME
        # completion set this listing already reads, so making the residual
        # detectable costs no additional transport.
        authority = authoritative_generations(receipts)
        out: list[Mapping[str, object]] = []
        for source_type, producer in PRODUCER_BY_SOURCE_TYPE.items():
            rows = self.store.list_objects_for_source_types(project_id=project_id, source_types=(source_type,))
            files = {str(r.get("source_file")) for r in rows}
            out.append(
                {
                    "project_id": project_id,
                    "source_type": source_type,
                    "producer": producer,
                    "source_count": len(files),
                    "chunk_count": len(rows),
                    # N04/D1: the revision of the LAST SUCCESSFUL COMPLETION for
                    # this source type (persisted completion order, not a
                    # lexicographic maximum over content digests).
                    "last_revision": _last_completed_revision(
                        receipts,
                        producer_completions,
                        source_type,
                    ),
                    # AG3-177: the EXACT predicate of :func:`stale_chunk_count` --
                    # rows below their source's authoritative generation, rows with
                    # no generation, rows with an unusable one. > 0 is an actionable
                    # finding, NOT proof of a takeover residual: a sync resolves the
                    # first two classes and REFUSES the third by name (FK-04 §4.5.14).
                    # ``chunk_count`` stays the PHYSICAL count -- (c) changes
                    # detectability, not visibility.
                    "stale_chunk_count": stale_chunk_count(rows, authority),
                }
            )
        return out


def authoritative_generations(
    receipts: Sequence[SyncReceipt],
) -> Mapping[str, int]:
    """Return ``{source_file: authoritative generation}`` from the completions (AG3-177).

    The authoritative generation of a source is the HIGHEST generation among its
    verified, completed records -- the same ordering :meth:`WeaviateCorpusStore.
    get_receipt` uses to answer "which completion counts" (N39). A source with no
    completion has no authority and does not appear here.

    Args:
        receipts: The project's verified completions, as read.

    Returns:
        The authoritative generation per source file.
    """
    out: dict[str, int] = {}
    for receipt in receipts:
        if receipt.state.value != "completed":
            continue
        if receipt.generation > out.get(receipt.source_file, 0):
            out[receipt.source_file] = receipt.generation
    return out


def stale_chunk_count(rows: Sequence[Mapping[str, object]], authority: Mapping[str, int]) -> int:
    """Count the rows matching the EXACT predicate below (AG3-177).

    This is NOT "every row that is not part of the authoritative generation": a row of a
    HIGHER generation is not part of it either and is deliberately not counted. Reading
    the figure as a complete non-authoritative count would make a zero look like proof
    that nothing is in flight, which it is not.

    Counted, each row against the authoritative generation of ITS source, using the one
    classification ladder :func:`classify_owning_generation` (so the sync and this
    listing can never disagree about what a row is):

    - :attr:`GenerationClass.ORDERED` strictly BELOW the authority -- the takeover
      residual, and exactly what the next sync's ordered delete removes;
    - :attr:`GenerationClass.MISSING` (absent or ``null``) -- a legacy row predating the
      ordering property; the next sync converges it under its IS-NULL condition;
    - :attr:`GenerationClass.UNUSABLE` -- present but not orderable. It is certainly not
      authoritative, and it needs ATTENTION rather than a sync: the sync refuses it by
      name instead of cleaning it up.

    NOT counted:

    - rows of a source that has no completion at all -- there is no authority to judge
      them against, and inventing one would be a guess;
    - rows of a generation ABOVE the authoritative one: that is an in-flight newer
      generation whose completion is not published yet, not a remnant.

    Because the three counted classes carry DIFFERENT remedies, a value ``> 0`` is an
    actionable finding, not proof of a takeover residual (FK-04 §4.5.14).

    Args:
        rows: The source rows as read (uuid, source_file, writing generation).
        authority: The authoritative generation per source file.

    Returns:
        The number of rows matching the predicate.
    """
    count = 0
    for row in rows:
        authoritative = authority.get(str(row.get("source_file", "")))
        if authoritative is None:
            continue
        raw = row.get(OWNING_GENERATION_PROPERTY)
        if not is_ordered_generation(raw):
            count += 1  # MISSING (legacy) or UNUSABLE (a named error, not a sync case)
            continue
        if raw < authoritative:
            count += 1
    return count


def _last_completed_revision(
    receipts: Sequence[SyncReceipt],
    producer_completions: Sequence[ProducerCompletion],
    source_type: str,
) -> str:
    """Return the revision of the LAST successful completion of a source type (N04).

    Ordering is the persisted completion ``sequence`` (store-monotonic); the
    ``completed_at`` timestamp and the source file break ties deterministically.
    An unfinished (``in_progress``) receipt is not a completion.
    """
    source_candidates = [
        (receipt.sequence, receipt.completed_at, receipt.source_file, receipt.corpus_revision)
        for receipt in receipts
        if receipt.source_type == source_type and receipt.state.value == "completed"
    ]
    producer_candidates = [
        (completion.sequence, "", completion.producer, completion.corpus_revision)
        for completion in producer_completions
        if source_type in completion.source_types
    ]
    completed = source_candidates + producer_candidates
    if not completed:
        return ""
    return max(completed)[3]


def ensure_corpus_collections(client: CorpusClientPort) -> None:
    """Create OR verify the three corpus collections against the schema SSOT.

    Shared by EVERY write path into ``StoryContext`` (N38): the MCP runtime and the
    story-export/split/repair sync owner bootstrap the same schema, so a collection
    can never be created without the ownership-ordering property the destructive
    delete conditions on.

    The auxiliary receipt/claim collections are ensured too and NOT suppressed -- a
    failure must surface fail-closed (N08), since completion/claim persistence is
    required for the freshness and D3 contracts.
    """
    from agentkit.backend.vectordb.schema import (
        FK13_VECTOR_SOURCE_PROPERTIES,
        FK13_VECTORIZER,
        FK13_VECTORIZER_MODEL,
        weaviate_property_specs,
    )

    client.ensure_collection(
        collection=STORY_CONTEXT_COLLECTION,
        property_specs=weaviate_property_specs(),
        vectorizer=FK13_VECTORIZER,
        vectorizer_model=FK13_VECTORIZER_MODEL,
        vector_source_properties=FK13_VECTOR_SOURCE_PROPERTIES,
    )
    client.ensure_collection(
        collection=RECEIPT_COLLECTION,
        property_specs=_receipt_property_specs(),
        vectorizer="self_provided",
    )
    client.ensure_collection(
        collection=RUN_RECEIPT_COLLECTION,
        property_specs=_aux_property_specs(RUN_RECEIPT_PROPERTIES),
        vectorizer="self_provided",
    )
    client.ensure_collection(
        collection=CLAIM_COLLECTION,
        property_specs=_aux_property_specs(CLAIM_PROPERTIES),
        vectorizer="self_provided",
    )


def connect_real_client(binding: RuntimeBinding) -> CorpusClientPort:
    """Build a real Weaviate client from the binding's EXACT endpoints (R02/R03).

    Both endpoints come verbatim from the registered env (D2) and are passed into
    ``weaviate.connect_to_custom`` -- the only connect API of the pinned client
    that accepts a DISTINCT gRPC host (``connect_to_local`` does not, R03).
    Raises :class:`VectorDbUnavailableError` fail-closed.
    """
    from agentkit.integration_clients.vectordb.weaviate_adapter import _build_real_client

    http_host, http_port, http_secure = _split_endpoint(binding.weaviate_http_endpoint)
    grpc_host, grpc_port, grpc_secure = _split_grpc(binding.weaviate_grpc_endpoint)
    return _build_real_client(  # type: ignore[return-value]
        http_host=http_host,
        http_port=http_port,
        http_secure=http_secure,
        grpc_host=grpc_host,
        grpc_port=grpc_port,
        grpc_secure=grpc_secure,
    )


#: ``_split_endpoint`` / ``_split_grpc`` now live in ``vectordb.endpoints`` as a
#: PUBLIC seam (PO decision D-2): removing ``vectordb.host``/``port`` made the
#: configured endpoint the only way to say where Weaviate is, so the readiness
#: probe and the story-creation adapter must split it too. Re-exported here under
#: the historical names so there is ONE implementation and no drift between the
#: MCP runtime and those consumers.
_split_endpoint = split_http_endpoint
_split_grpc = split_grpc_endpoint


def compose_runtime(
    env: Mapping[str, str],
    *,
    concepts_dir: Path,
    stories_dir: Path,
    client: CorpusClientPort | None = None,
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


def _aux_property_specs(names: Sequence[str]) -> list[dict[str, object]]:
    """Property specs of an auxiliary bookkeeping collection.

    Auxiliary records are pure state (receipts, claims, sequence tokens): every
    field is an exact-match identifier, so nothing is vectorised, nothing is
    BM25-searchable and everything stays whole-value tokenised.
    """
    return [
        {
            "name": name,
            "data_type": "TEXT",
            "skip_vectorization": True,
            "vectorize_property_name": False,
            "filterable": True,
            "tokenization": "FIELD",
            "searchable": False,
        }
        for name in names
    ]


def _receipt_property_specs() -> list[dict[str, object]]:
    """Property specs of the auxiliary receipt collection."""
    return _aux_property_specs(RECEIPT_PROPERTIES)


def run_stdio_server(service: object) -> None:
    """Run the FastMCP server over stdio for the composed service (R02)."""
    from agentkit.backend.vectordb.mcp_server import build_mcp_server

    server = build_mcp_server(service)  # type: ignore[arg-type]
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
    "RECEIPT_PROPERTIES",
    "RUN_RECEIPT_COLLECTION",
    "RUN_RECEIPT_PROPERTIES",
    "WeaviateCorpusStore",
    "WeaviateRetrievalPort",
    "compose_runtime",
    "connect_real_client",
    "main",
    "receipt_from_props",
    "run_stdio_server",
]
