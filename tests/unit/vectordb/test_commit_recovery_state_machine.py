"""Real-boundary proofs for the VectorDB completion recovery state machine."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from tests.unit.vectordb.corpus_doubles import (
    RealQueryBoundaryWeaviateClient,
    RecordingWeaviateClient,
    chunk_object,
)

from agentkit.backend.story_creation.weaviate_index import WeaviateStoryIndex
from agentkit.backend.vectordb import commit_recovery, completion_ledger
from agentkit.backend.vectordb.commit_recovery import (
    CommitRecoveryState,
    CompletionCommitJournalEntry,
    FileCommitRecoveryJournal,
    project_commit_recovery_journal,
)
from agentkit.backend.vectordb.completion_ledger import RUN_RECEIPT_COLLECTION
from agentkit.backend.vectordb.completion_records import (
    render_producer_completions,
    run_receipt_digest,
)
from agentkit.backend.vectordb.corpus_store import WeaviateCorpusStore
from agentkit.backend.vectordb.sync import (
    CommitOutcomeUnknownError,
    ProducerCompletion,
    completion_run_id,
)
from agentkit.integration_clients.vectordb.errors import (
    VectorDbUnavailableError,
    VectorDbWriteError,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


def _producer(revision: str) -> tuple[ProducerCompletion, ...]:
    return (
        ProducerCompletion(
            project_id="AG3",
            producer="concept_sync",
            source_types=("concept",),
            corpus_revision=revision,
        ),
    )


def _competing_properties(
    properties: Mapping[str, object],
) -> dict[str, object]:
    sequence = int(str(properties["sequence_end"]))
    revision = f"competing-revision-{sequence}"
    producer = _producer(revision)
    producer_json = render_producer_completions(
        (producer[0].stamped(sequence=sequence),)
    )
    run_id = completion_run_id("AG3", (), producer)
    completed_at = str(properties["completed_at"])
    sequence_start = int(str(properties["sequence_start"]))
    sequence_end = int(str(properties["sequence_end"]))
    return {
        **properties,
        "run_id": run_id,
        "producer_completions_json": producer_json,
        "batch_digest": run_receipt_digest(
            project_id="AG3",
            run_id=run_id,
            receipts_json=str(properties["receipts_json"]),
            producer_completions_json=producer_json,
            completed_at=completed_at,
            sequence_start=sequence_start,
            sequence_end=sequence_end,
        ),
    }


class _CollisionClient(RecordingWeaviateClient):
    collide: bool = True
    fail_collision_read: bool = False

    def insert_object(
        self,
        *,
        collection: str,
        uuid: str,
        properties: Mapping[str, object],
    ) -> bool:
        if collection != RUN_RECEIPT_COLLECTION or not self.collide:
            return super().insert_object(
                collection=collection,
                uuid=uuid,
                properties=properties,
            )
        self.receipt_runs[uuid] = _competing_properties(properties)
        if self.fail_collision_read:
            self.fail_run_receipt_reads = True
        return False


def _terminal_entry(root: Path) -> CompletionCommitJournalEntry:
    paths = tuple(root.glob("*.json"))
    assert len(paths) == 1
    return CompletionCommitJournalEntry.model_validate_json(paths[0].read_bytes())


def test_writable_store_requires_a_durable_recovery_owner() -> None:
    """A publication-capable store cannot even be built without its journal."""
    client = RecordingWeaviateClient()

    with pytest.raises(TypeError, match="recovery_journal"):
        WeaviateCorpusStore(client=client)  # type: ignore[call-arg]


def test_exhausted_range_retry_finishes_not_committed_and_never_recovers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A known final collision is terminal and resolve can never publish it."""
    monkeypatch.setattr(completion_ledger, "_COMPLETION_ATTEMPT_LIMIT", 2)
    client = _CollisionClient()
    root = tmp_path / "journal"
    journal = FileCommitRecoveryJournal(root)
    store = WeaviateCorpusStore(client=client, recovery_journal=journal)
    producer = _producer("target-revision")
    target_run = completion_run_id("AG3", (), producer)

    with pytest.raises(VectorDbWriteError, match="after 2 attempts"):
        store.set_receipts(
            run_id=target_run,
            receipts=(),
            producer_completions=producer,
        )

    assert journal.list_pending("AG3") == ()
    assert _terminal_entry(root).state is CommitRecoveryState.NOT_COMMITTED
    before = dict(client.receipt_runs)
    client.collide = False
    store.resolve_pending_commits(project_id="AG3")
    assert client.receipt_runs == before
    assert all(row["run_id"] != target_run for row in client.receipt_runs.values())


def test_collision_read_failure_is_terminal_without_rollback_republish(
    tmp_path: Path,
) -> None:
    """insert=False plus unreadable owner is a normal terminal failure, not unknown."""
    client = _CollisionClient()
    client.fail_collision_read = True
    root = tmp_path / "journal"
    journal = FileCommitRecoveryJournal(root)
    store = WeaviateCorpusStore(client=client, recovery_journal=journal)
    producer = _producer("target-revision")
    target_run = completion_run_id("AG3", (), producer)

    with pytest.raises(
        VectorDbUnavailableError,
        match="definitively not committed",
    ) as failure:
        store.set_receipts(
            run_id=target_run,
            receipts=(),
            producer_completions=producer,
        )

    assert not isinstance(failure.value, CommitOutcomeUnknownError)
    assert journal.list_pending("AG3") == ()
    assert _terminal_entry(root).state is CommitRecoveryState.NOT_COMMITTED
    client.fail_run_receipt_reads = False
    client.collide = False
    before = dict(client.receipt_runs)
    store.resolve_pending_commits(project_id="AG3")
    assert client.receipt_runs == before
    assert all(row["run_id"] != target_run for row in client.receipt_runs.values())


def test_real_weaviate_query_transport_keeps_terminal_and_unknown_outcomes_distinct(
    tmp_path: Path,
) -> None:
    """The concrete read seam preserves terminal collision and unknown ACK semantics."""
    client = RealQueryBoundaryWeaviateClient()
    root = tmp_path / "journal"
    journal = FileCommitRecoveryJournal(root)
    store = WeaviateCorpusStore(client=client, recovery_journal=journal)
    terminal_producer = _producer("terminal-revision")
    terminal_run = completion_run_id("AG3", (), terminal_producer)
    client.reject_next_run_insert = True

    with pytest.raises(
        VectorDbUnavailableError,
        match="definitively not committed",
    ) as terminal_failure:
        store.set_receipts(
            run_id=terminal_run,
            receipts=(),
            producer_completions=terminal_producer,
        )

    assert not isinstance(terminal_failure.value, CommitOutcomeUnknownError)
    assert journal.list_pending("AG3") == ()
    assert _terminal_entry(root).state is CommitRecoveryState.NOT_COMMITTED
    terminal_attempts = client.run_insert_attempts
    client.fail_real_run_reads = False
    restarted_store = WeaviateCorpusStore(
        client=client,
        recovery_journal=FileCommitRecoveryJournal(root),
    )
    restarted_store.resolve_pending_commits(project_id="AG3")
    assert client.run_insert_attempts == terminal_attempts
    assert all(
        row["run_id"] != terminal_run for row in client.receipt_runs.values()
    )

    unknown_producer = _producer("unknown-revision")
    client.lose_run_receipt_ack_after_insert = True
    client.fail_real_read_after_run_write_error = True
    with pytest.raises(CommitOutcomeUnknownError, match="acknowledgement was lost"):
        restarted_store.set_receipts(
            run_id=completion_run_id("AG3", (), unknown_producer),
            receipts=(),
            producer_completions=unknown_producer,
        )

    pending = journal.list_pending("AG3")
    assert len(pending) == 1
    assert pending[0].state is CommitRecoveryState.OUTCOME_UNKNOWN


def test_terminal_journal_failure_is_visible_as_outcome_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failure to persist NOT_COMMITTED cannot be presented as rollback-safe."""
    monkeypatch.setattr(completion_ledger, "_COMPLETION_ATTEMPT_LIMIT", 1)
    client = _CollisionClient()
    journal = FileCommitRecoveryJournal(tmp_path / "journal")
    store = WeaviateCorpusStore(client=client, recovery_journal=journal)

    def fail_terminal(_entry: CompletionCommitJournalEntry) -> None:
        raise VectorDbWriteError("simulated terminal journal failure")

    monkeypatch.setattr(journal, "finish_not_committed", fail_terminal)
    producer = _producer("target-revision")
    with pytest.raises(
        CommitOutcomeUnknownError,
        match="terminal journal state could not be persisted",
    ):
        store.set_receipts(
            run_id=completion_run_id("AG3", (), producer),
            receipts=(),
            producer_completions=producer,
        )

    pending = journal.list_pending("AG3")
    assert len(pending) == 1
    assert pending[0].state is CommitRecoveryState.OUTCOME_UNKNOWN


def test_story_index_owns_durable_recovery_and_resolves_before_next_mutation(
    tmp_path: Path,
) -> None:
    """The productive story-index path blocks all new writes on unresolved state."""
    client = RecordingWeaviateClient()

    class _Adapter:
        @property
        def corpus_client(self) -> object:
            return client

    journal = project_commit_recovery_journal(tmp_path)
    index = WeaviateStoryIndex(
        _Adapter(),  # type: ignore[arg-type]
        recovery_journal=journal,
    )
    first = (
        chunk_object(
            "AG3",
            "stories/AG3-1/story.md",
            "first",
            source_type="story",
        ),
    )
    second = (
        chunk_object(
            "AG3",
            "stories/AG3-2/story.md",
            "second",
            source_type="story",
        ),
    )
    client.lose_run_receipt_ack_after_insert = True
    client.fail_run_receipt_readback_after_lost_ack = True

    with pytest.raises(CommitOutcomeUnknownError):
        index.index_story(story_id="AG3-1", project_id="AG3", objects=first)
    assert len(client.upsert_calls) == 1
    assert len(journal.list_pending("AG3")) == 1

    with pytest.raises(CommitOutcomeUnknownError):
        index.index_story(story_id="AG3-2", project_id="AG3", objects=second)
    assert len(client.upsert_calls) == 1

    client.fail_run_receipt_reads = False
    assert (
        index.index_story(story_id="AG3-2", project_id="AG3", objects=second)
        == 1
    )
    assert len(client.upsert_calls) == 2
    assert journal.list_pending("AG3") == ()


def test_journal_scan_ignores_its_atomic_write_temp_file(tmp_path: Path) -> None:
    root = tmp_path / "journal"
    root.mkdir()
    (root / f"{'a' * 64}.json.tmp").write_text("incomplete", encoding="utf-8")

    assert FileCommitRecoveryJournal(root).list_pending("AG3") == ()


def test_journal_write_must_make_the_rename_directory_durable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "journal"
    root.mkdir()
    entry = CompletionCommitJournalEntry(
        state=CommitRecoveryState.OUTCOME_UNKNOWN,
        project_id="AG3",
        run_id="a" * 64,
        record_uuid="record-1",
        properties={"run_id": "a" * 64},
    )

    def fail_directory_sync(_path: Path) -> None:
        raise OSError("simulated directory sync failure")

    monkeypatch.setattr(commit_recovery, "_sync_directory", fail_directory_sync)

    with pytest.raises(OSError, match="directory sync failure"):
        FileCommitRecoveryJournal(root).stage_unknown(entry)


def test_first_journal_write_persists_each_created_directory_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / ".agentkit" / "receipts" / "vectordb" / "pending-commits"
    entry = CompletionCommitJournalEntry(
        state=CommitRecoveryState.OUTCOME_UNKNOWN,
        project_id="AG3",
        run_id="a" * 64,
        record_uuid="record-1",
        properties={"run_id": "a" * 64},
    )
    synced: list[Path] = []
    monkeypatch.setattr(commit_recovery, "_sync_directory", synced.append)

    FileCommitRecoveryJournal(root).stage_unknown(entry)

    assert synced == [
        tmp_path,
        tmp_path / ".agentkit",
        tmp_path / ".agentkit" / "receipts",
        tmp_path / ".agentkit" / "receipts" / "vectordb",
        root,
    ]


def test_journal_directory_creation_fails_at_an_unavailable_filesystem_anchor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(type(tmp_path), "exists", lambda _path: False)

    with pytest.raises(OSError, match="filesystem anchor is unavailable"):
        commit_recovery._create_directory_tree(tmp_path / "journal")


@pytest.mark.parametrize(
    "entry_name,as_directory",
    [
        pytest.param(f"{'a' * 64}.json.tmp", True, id="temp-directory"),
        pytest.param("foreign.json.tmp", False, id="foreign-temp-name"),
        pytest.param(f"{'a' * 64}.json.part", False, id="unknown-suffix"),
    ],
)
def test_journal_scan_rejects_every_non_owned_entry(
    tmp_path: Path,
    entry_name: str,
    as_directory: bool,
) -> None:
    root = tmp_path / "journal"
    root.mkdir()
    entry = root / entry_name
    if as_directory:
        entry.mkdir()
    else:
        entry.write_text("foreign", encoding="utf-8")

    with pytest.raises(VectorDbWriteError, match="journal entry is invalid"):
        FileCommitRecoveryJournal(root).list_pending("AG3")
