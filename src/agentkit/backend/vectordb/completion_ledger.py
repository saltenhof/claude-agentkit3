"""Authoritative publication and recovery of position-bound sync completions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from agentkit.backend.vectordb.commit_recovery import (
    CommitRecoveryState,
    CompletionCommitJournalEntry,
    FileCommitRecoveryJournal,
)
from agentkit.backend.vectordb.completion_records import (
    _CompletionRunRecord,
    _parse_run_record,
    _render_receipt_batch,
    _unstamp_producer_completion,
    _unstamp_receipt,
    _verify_global_completion_ranges,
    completion_position_uuid,
    receipt_from_props,
    render_producer_completions,
    run_position_uuid,
    run_receipt_digest,
)
from agentkit.backend.vectordb.record_fields import iso, positive_int, utc_clock
from agentkit.backend.vectordb.sync import (
    CommitOutcomeUnknownError,
    ProducerCompletion,
    SyncReceipt,
    completion_run_id,
)
from agentkit.integration_clients.vectordb.errors import (
    VectorDbUnavailableError,
    VectorDbWriteError,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import datetime

    from agentkit.backend.vectordb.client_port import CorpusClientPort

#: Weaviate collection of the per-source completion ledger (FK-13 §13.3.0).
#:
#: The name follows the FK-13 §13.3.0 convention -- initial CAPITAL, ``Ak3``
#: prefix. Weaviate rejects anything else with HTTP 422
#: (``is not a valid class name``); the former ``__agentkit_sync_receipts`` was a
#: Python "private" spelling on a foreign system that never accepted it.
RECEIPT_COLLECTION = "Ak3SyncReceipts"
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
#: Weaviate collection of the per-run ledger receipts (FK-13 §13.3.0 naming).
RUN_RECEIPT_COLLECTION = "Ak3SyncRuns"
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
_COMPLETION_ATTEMPT_LIMIT: Final[int] = 256


@dataclass
class CompletionLedger:
    """Publish and read authoritative completions and resolve uncertain commits."""

    client: CorpusClientPort
    recovery_journal: FileCommitRecoveryJournal
    clock: Callable[[], datetime] = utc_clock

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
            raise VectorDbWriteError(f"source type {receipt.source_type!r} has no completion producer")
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
            raise VectorDbWriteError("completion run has no producer-wide completion summary")
        project_ids = {receipt.project_id for receipt in candidates}
        project_ids.update(item.project_id for item in producer_candidates)
        identities = {(receipt.source_file, receipt.generation) for receipt in candidates}
        producers = {item.producer for item in producer_candidates}
        if len(project_ids) != 1 or len(identities) != len(candidates) or len(producers) != len(producer_candidates):
            raise VectorDbWriteError("completion run must contain one project and unique sources/producers")
        project_id = next(iter(project_ids))
        expected_run_id = completion_run_id(
            project_id,
            candidates,
            producer_candidates,
        )
        if run_id != expected_run_id:
            raise VectorDbWriteError("completion run_id does not bind the exact semantic payload")
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
            producer_completions=tuple(_unstamp_producer_completion(item) for item in parsed.producer_completions),
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
        raise VectorDbWriteError(f"could not atomically reserve a completion range after {_COMPLETION_ATTEMPT_LIMIT} attempts")

    def _build_run_record(
        self,
        *,
        project_id: str,
        run_id: str,
        receipts: tuple[SyncReceipt, ...],
        producer_completions: tuple[ProducerCompletion, ...],
        sequence_start: int,
    ) -> _CompletionRunRecord:
        sealed = tuple(receipt.stamped(sequence=sequence_start + offset) for offset, receipt in enumerate(receipts))
        sequence_end = sequence_start + max(1, len(sealed)) - 1
        sealed_producers = tuple(completion.stamped(sequence=sequence_end) for completion in producer_completions)
        completed_at = iso(self.clock())
        receipts_json = _render_receipt_batch(sealed)
        producer_json = render_producer_completions(sealed_producers)
        digest = run_receipt_digest(
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
            uuid=run_position_uuid(project_id, sequence_start),
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
            raise VectorDbUnavailableError(f"completion position {record_uuid!r} is duplicated")
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
            raise VectorDbUnavailableError(f"completion run_id {run_id!r} is duplicated")
        return _parse_run_record(rows[0][0], rows[0][1], project_id=project_id) if rows else None

    def _assert_semantic_run_match(
        self,
        record: _CompletionRunRecord,
        receipts: tuple[SyncReceipt, ...],
        producer_completions: tuple[ProducerCompletion, ...],
    ) -> None:
        actual_receipts = tuple(_unstamp_receipt(item) for item in record.receipts)
        actual_producers = tuple(_unstamp_producer_completion(item) for item in record.producer_completions)
        if actual_receipts != receipts or actual_producers != producer_completions:
            raise VectorDbUnavailableError(
                f"completion run {record.properties['run_id']!r} does not match its deterministic semantic payload"
            )

    def _clear_recovery(self, run_id: str) -> None:
        try:
            self.recovery_journal.finish_committed(run_id)
        except (OSError, VectorDbWriteError) as exc:
            raise CommitOutcomeUnknownError(
                f"completion run {run_id!r} committed, but its durable recovery entry could not be cleared"
            ) from exc

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
            highest = max(highest, positive_int(props.get("sequence"), field_name="sequence"))
        for _uid, props in self.client.fetch_by_property(
            collection=RUN_RECEIPT_COLLECTION,
            project_id=project_id,
            prop="project_id",
            value=project_id,
            return_props=RUN_RECEIPT_PROPERTIES,
        ):
            highest = max(
                highest,
                positive_int(props.get("sequence_end"), field_name="sequence_end"),
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
            completion_position_uuid(current.project_id, receipt.sequence)
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
            expected_uuid = completion_position_uuid(project_id, completion.sequence)
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
            + [(record.sequence_start, record.sequence_end) for record in run_records]
        )
        out.extend(receipt for record in run_records for receipt in record.receipts)
        return out

    def _list_run_receipts(self, project_id: str) -> list[SyncReceipt]:
        """Read and verify atomically published multi-source run records."""
        return [receipt for record in self._list_run_records(project_id) for receipt in record.receipts]

    def list_producer_completions(
        self,
        *,
        project_id: str,
    ) -> Sequence[ProducerCompletion]:
        """Return producer-wide completions, including zero-source successes."""
        records = self._list_run_records(project_id)
        _verify_global_completion_ranges([(record.sequence_start, record.sequence_end) for record in records])
        return [completion for record in records for completion in record.producer_completions]

    def _list_run_records(self, project_id: str) -> list[_CompletionRunRecord]:
        """Read every immutable run record strictly."""
        rows = self.client.fetch_by_property(
            collection=RUN_RECEIPT_COLLECTION,
            project_id=project_id,
            prop="project_id",
            value=project_id,
            return_props=RUN_RECEIPT_PROPERTIES,
        )
        records = [_parse_run_record(uid, props, project_id=project_id) for uid, props in rows]
        run_ids = [record.properties["run_id"] for record in records]
        if len(run_ids) != len(set(run_ids)):
            raise VectorDbUnavailableError("completion run_id is not globally unique")
        return records


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


__all__ = [
    "CompletionLedger",
    "RECEIPT_COLLECTION",
    "RECEIPT_PROPERTIES",
    "RUN_RECEIPT_COLLECTION",
    "RUN_RECEIPT_PROPERTIES",
]
