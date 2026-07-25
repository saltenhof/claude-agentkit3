"""Bounded-window sync tests (FK-13 §13.9.9, Review 174-P1-1, AC6, D3, N13).

The double lives ONLY at the Weaviate CLIENT boundary
(:class:`RecordingWeaviateClient`), so the REAL ``WeaviateCorpusStore`` runs
underneath the ``SyncService``: the bounded-window ordering, the digest-bound
receipt, crash/retry reconciliation, the atomic claim (D3), the per-object target
validation (N13) and the full_reindex source-type isolation all execute
productively.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from tests.unit.vectordb.corpus_doubles import (
    RecordingWeaviateClient,
    chunk_object,
    corpus_store,
)

from agentkit.backend.vectordb.engine import (
    CLAIM_COLLECTION,
    RECEIPT_COLLECTION,
    WeaviateCorpusStore,
)
from agentkit.backend.vectordb.schema import (
    STORY_CONTEXT_COLLECTION,
    StoryContextObject,
    deterministic_uuid,
)
from agentkit.backend.vectordb.sync import (
    ClaimSupersededError,
    ConcurrentSyncRejectedError,
    PartialWriteError,
    ReceiptState,
    SyncError,
    SyncReceipt,
    SyncService,
    parse_utc_timestamp,
    utc_now,
)

if TYPE_CHECKING:
    from collections.abc import Callable


def claim_uuid_for(project_id: str, source_file: str, epoch: int) -> str:
    """The store's deterministic claim uuid for one generation (N15)."""
    return WeaviateCorpusStore._claim_uuid(project_id, source_file, epoch)  # noqa: SLF001


def _seed(client: RecordingWeaviateClient, obj: StoryContextObject) -> None:
    client.objects[obj.uuid] = {**obj.properties, "uuid": obj.uuid}


# --------------------------------------------------------------------------- #
# Bounded-window ordering
# --------------------------------------------------------------------------- #


def test_sync_writes_new_then_deletes_old_then_receipt() -> None:
    client = RecordingWeaviateClient()
    old = chunk_object("acme", "concept/a.md", "old")
    _seed(client, old)
    store = corpus_store(client)
    service = SyncService(store=store)

    new = chunk_object("acme", "concept/a.md", "new")
    result = service.sync_source(
        project_id="acme", source_file="concept/a.md", source_type="concept",
        objects=[new], corpus_revision="rev-1",
    )
    assert new.uuid in client.objects
    assert old.uuid not in client.objects
    assert result.deleted == 1
    assert result.written == 1
    receipt = store.get_receipt(project_id="acme", source_file="concept/a.md")
    assert receipt is not None
    assert receipt.state is ReceiptState.COMPLETED
    assert receipt.corpus_revision == "rev-1"
    assert receipt.digest == result.receipt_digest
    assert receipt.sequence == 1
    receipt.verify()  # digest binds identity AND ordering fields (N16)


def test_idempotent_resync_writes_one_record() -> None:
    client = RecordingWeaviateClient()
    store = corpus_store(client)
    service = SyncService(store=store)
    obj = chunk_object("acme", "concept/a.md", "c1")
    r1 = service.sync_source(
        project_id="acme", source_file="concept/a.md", source_type="concept",
        objects=[obj], corpus_revision="rev-1",
    )
    r2 = service.sync_source(
        project_id="acme", source_file="concept/a.md", source_type="concept",
        objects=[obj], corpus_revision="rev-1",
    )
    # The INDEXED generation is idempotent: the same single object, same identity.
    objs = store.list_objects_for_source(project_id="acme", source_file="concept/a.md")
    assert len(objs) == 1
    assert str(objs[0]["uuid"]) == obj.uuid
    # One receipt RECORD per source, with an ADVANCING completion order (N04/N16):
    # the digest binds the ordering fields, so the second completion necessarily
    # carries a different -- and still self-verifying -- digest.
    assert len(client.receipts) == 1
    assert r1.receipt_digest != r2.receipt_digest
    latest = store.get_receipt(project_id="acme", source_file="concept/a.md")
    assert latest is not None
    assert latest.sequence == 2
    assert latest.digest == r2.receipt_digest
    latest.verify()


def test_vanished_source_file_is_deleted_and_counted() -> None:
    """R12: a full_reindex reports the vanished-source deletes in its counters."""
    client = RecordingWeaviateClient()
    stale = chunk_object("acme", "concept/gone.md", "g1")
    _seed(client, stale)
    service = SyncService(store=corpus_store(client))
    results = service.full_reindex(
        project_id="acme", producer="concept_sync",
        objects_by_source={"concept/a.md": [chunk_object("acme", "concept/a.md", "a1")]},
        corpus_revision="rev-1",
    )
    assert stale.uuid not in client.objects
    vanished = [r for r in results if r.source_file == "concept/gone.md"]
    assert vanished, "the vanished source must appear in the returned counters (R12)"
    assert vanished[0].deleted == 1
    assert sum(r.deleted for r in results) == 1


def test_full_reindex_partial_vanished_delete_is_rejected() -> None:
    """R12: an unconfirmed delete blocks the reindex instead of counting a phantom."""
    client = RecordingWeaviateClient()
    _seed(client, chunk_object("acme", "concept/gone.md", "g1"))
    client.delete_confirmed_override = 0  # transport confirms nothing
    service = SyncService(store=corpus_store(client))
    with pytest.raises(PartialWriteError, match="partial delete"):
        service.full_reindex(
            project_id="acme", producer="concept_sync",
            objects_by_source={}, corpus_revision="rev-1",
        )


# --------------------------------------------------------------------------- #
# Crash / retry reconciliation
# --------------------------------------------------------------------------- #


def test_crash_before_receipt_leaves_marker_then_retry_cleans() -> None:
    client = RecordingWeaviateClient()
    store = corpus_store(client)
    service = SyncService(store=store)
    # Pre-existing COMPLETED receipt for an OLD generation (written for real).
    old = chunk_object("acme", "concept/a.md", "old")
    service.sync_source(
        project_id="acme", source_file="concept/a.md", source_type="concept",
        objects=[old], corpus_revision="old-rev",
    )

    client.crash_after_write = True
    new = chunk_object("acme", "concept/a.md", "new")
    with pytest.raises(RuntimeError, match="crash after write"):
        service.sync_source(
            project_id="acme", source_file="concept/a.md", source_type="concept",
            objects=[new], corpus_revision="new-rev",
        )
    receipt = store.get_receipt(project_id="acme", source_file="concept/a.md")
    assert receipt is not None
    assert receipt.corpus_revision == "old-rev"
    assert new.uuid in client.objects
    assert old.uuid in client.objects  # transitional: both generations visible

    # Retry (a fresh, non-concurrent call) reconciles deterministically.
    result = service.sync_source(
        project_id="acme", source_file="concept/a.md", source_type="concept",
        objects=[new], corpus_revision="new-rev",
    )
    assert old.uuid not in client.objects
    assert new.uuid in client.objects
    assert result.deleted == 1
    receipt = store.get_receipt(project_id="acme", source_file="concept/a.md")
    assert receipt is not None
    assert receipt.corpus_revision == "new-rev"


def test_partial_write_rejected_before_receipt() -> None:
    client = RecordingWeaviateClient()
    client.upsert_written_override = 0
    store = corpus_store(client)
    service = SyncService(store=store)
    with pytest.raises(PartialWriteError, match="partial write"):
        service.sync_source(
            project_id="acme", source_file="concept/a.md", source_type="concept",
            objects=[chunk_object("acme", "concept/a.md", "c1")], corpus_revision="rev",
        )
    assert store.get_receipt(project_id="acme", source_file="concept/a.md") is None


def test_should_set_not_persisted_is_rejected() -> None:
    client = RecordingWeaviateClient()
    client.suppress_source_fetch = True  # write "succeeds" but nothing is persisted
    service = SyncService(store=corpus_store(client))
    with pytest.raises(PartialWriteError, match="should-set not persisted"):
        service.sync_source(
            project_id="acme", source_file="concept/a.md", source_type="concept",
            objects=[chunk_object("acme", "concept/a.md", "c1")], corpus_revision="rev",
        )


# --------------------------------------------------------------------------- #
# N13: per-object validation BEFORE the first write
# --------------------------------------------------------------------------- #


def test_n13_foreign_project_object_is_rejected_before_any_write() -> None:
    """An object carrying a FOREIGN project_id must never reach the store (D2)."""
    client = RecordingWeaviateClient()
    service = SyncService(store=corpus_store(client))
    foreign = chunk_object("other", "concept/a.md", "c1")
    with pytest.raises(SyncError, match="project_id='other'"):
        service.sync_source(
            project_id="acme", source_file="concept/a.md", source_type="concept",
            objects=[foreign], corpus_revision="rev",
        )
    assert client.objects == {}, "no object may be written before validation"
    assert client.receipts == {}


def test_n13_foreign_source_file_object_is_rejected_before_any_write() -> None:
    client = RecordingWeaviateClient()
    service = SyncService(store=corpus_store(client))
    stray = chunk_object("acme", "concept/other.md", "c1")
    with pytest.raises(SyncError, match="source_file="):
        service.sync_source(
            project_id="acme", source_file="concept/a.md", source_type="concept",
            objects=[stray], corpus_revision="rev",
        )
    assert client.objects == {}


def test_n13_non_deterministic_identity_is_rejected_before_any_write() -> None:
    client = RecordingWeaviateClient()
    service = SyncService(store=corpus_store(client))
    good = chunk_object("acme", "concept/a.md", "c1")
    tampered = StoryContextObject(
        uuid=deterministic_uuid("acme", "concept/a.md", "SOMETHING-ELSE"),
        chunk_id=good.chunk_id,
        properties=dict(good.properties),
    )
    with pytest.raises(SyncError, match="identity mismatch"):
        service.sync_source(
            project_id="acme", source_file="concept/a.md", source_type="concept",
            objects=[tampered], corpus_revision="rev",
        )
    assert client.objects == {}


def test_n13_duplicate_uuid_in_generation_is_rejected() -> None:
    client = RecordingWeaviateClient()
    service = SyncService(store=corpus_store(client))
    obj = chunk_object("acme", "concept/a.md", "c1")
    with pytest.raises(SyncError, match="duplicate object uuid"):
        service.sync_source(
            project_id="acme", source_file="concept/a.md", source_type="concept",
            objects=[obj, obj], corpus_revision="rev",
        )
    assert client.objects == {}


def test_n13_wrong_source_type_object_is_rejected() -> None:
    client = RecordingWeaviateClient()
    service = SyncService(store=corpus_store(client))
    story = chunk_object("acme", "concept/a.md", "c1", source_type="story")
    with pytest.raises(SyncError, match="source_type="):
        service.sync_source(
            project_id="acme", source_file="concept/a.md", source_type="concept",
            objects=[story], corpus_revision="rev",
        )
    assert client.objects == {}


# --------------------------------------------------------------------------- #
# full_reindex source-type isolation (both orders) + project isolation
# --------------------------------------------------------------------------- #


def test_full_reindex_story_does_not_touch_concept_and_vice_versa() -> None:
    client = RecordingWeaviateClient()
    concept_obj = chunk_object("acme", "concept/c.md", "c1", source_type="concept")
    story_obj = chunk_object("acme", "stories/x/story.md", "s1", source_type="story")
    _seed(client, concept_obj)
    _seed(client, story_obj)
    service = SyncService(store=corpus_store(client))

    service.full_reindex(
        project_id="acme", producer="story_sync",
        objects_by_source={"stories/x/story.md": [story_obj]}, corpus_revision="rev",
    )
    assert concept_obj.uuid in client.objects
    assert story_obj.uuid in client.objects

    service.full_reindex(
        project_id="acme", producer="concept_sync",
        objects_by_source={"concept/c.md": [concept_obj]}, corpus_revision="rev",
    )
    assert concept_obj.uuid in client.objects
    assert story_obj.uuid in client.objects


def test_project_isolation_two_projects() -> None:
    """Removing a source is the VANISHED-source path (an empty entry is invalid, N29)."""
    client = RecordingWeaviateClient()
    a = chunk_object("acme", "concept/a.md", "a1")
    b = chunk_object("other", "concept/a.md", "a1")  # same source, other project
    _seed(client, a)
    _seed(client, b)
    service = SyncService(store=corpus_store(client))
    service.reconcile_sources(
        project_id="acme", producer="concept_sync",
        objects_by_source={}, corpus_revision="rev",
    )
    assert a.uuid not in client.objects
    assert b.uuid in client.objects  # other project untouched


def test_n29_empty_generation_is_not_a_sync_target() -> None:
    client = RecordingWeaviateClient()
    service = SyncService(store=corpus_store(client))
    with pytest.raises(SyncError, match="carries no objects"):
        service.sync_source(
            project_id="acme", source_file="concept/a.md", source_type="concept",
            objects=[], corpus_revision="rev",
        )
    assert client.claims == {}


def test_n29_empty_matrix_entry_mutates_nothing_at_all() -> None:
    """N29: the empty entry is rejected BEFORE the vanished-source delete runs."""
    client = RecordingWeaviateClient()
    stale = chunk_object("acme", "concept/gone.md", "g1")
    _seed(client, stale)
    service = SyncService(store=corpus_store(client))
    with pytest.raises(SyncError, match="carries no objects"):
        service.reconcile_sources(
            project_id="acme", producer="concept_sync",
            objects_by_source={"concept/a.md": []}, corpus_revision="rev",
        )
    assert stale.uuid in client.objects, "the vanished delete must not have run"
    assert client.claims == {}
    assert client.receipts == {}


def test_n29_a_malformed_receipt_is_never_persisted() -> None:
    """N29: the sealed receipt is verified BEFORE it is written."""
    client = RecordingWeaviateClient()
    store = corpus_store(client)
    malformed = SyncReceipt.for_completion("acme", "concept/a.md", "", "rev")
    with pytest.raises(SyncError, match="source_type"):
        store.set_receipt(receipt=malformed)
    assert client.receipts == {}, "an unverified receipt must never reach the store"


# --------------------------------------------------------------------------- #
# N34: the pre-mutation gate covers the RECEIPT'S INPUTS, not only the objects
# --------------------------------------------------------------------------- #


def _assert_zero_mutation(
    client: RecordingWeaviateClient, seeded: StoryContextObject
) -> None:
    """Assert a rejected run left NO trace at all (claim, write, delete, receipt)."""
    assert client.claims == {}, "no claim may be written for an unpublishable run"
    assert client.upsert_calls == [], "nothing may be written"
    assert client.receipts == {}, "no completion may be reserved"
    assert seeded.uuid in client.objects, "the persisted generation must survive"


@pytest.mark.parametrize("revision", ["", "   "])
def test_n34_a_blank_corpus_revision_mutates_nothing_at_all(revision: str) -> None:
    """Valid objects + an unpublishable revision must not claim, write or delete.

    Before this fix the run claimed the source, wrote the new generation and
    DELETED the old one, and only then failed when the sealed receipt was verified
    at publication time -- a mutated corpus with no completion (N34).
    """
    client = RecordingWeaviateClient()
    old = chunk_object("acme", "concept/a.md", "old")
    _seed(client, old)
    service = SyncService(store=corpus_store(client))
    with pytest.raises(SyncError, match="corpus_revision"):
        service.sync_source(
            project_id="acme", source_file="concept/a.md", source_type="concept",
            objects=[chunk_object("acme", "concept/a.md", "new")],
            corpus_revision=revision,
        )
    _assert_zero_mutation(client, old)


def test_n34_reconcile_with_a_blank_revision_spares_the_vanished_source() -> None:
    """The matrix gate must reject before the vanished-source DELETE happens."""
    client = RecordingWeaviateClient()
    vanished = chunk_object("acme", "concept/gone.md", "g1")
    _seed(client, vanished)
    service = SyncService(store=corpus_store(client))
    with pytest.raises(SyncError, match="corpus_revision"):
        service.reconcile_sources(
            project_id="acme",
            producer="concept_sync",
            objects_by_source={
                "concept/a.md": [chunk_object("acme", "concept/a.md", "a1")]
            },
            corpus_revision="",
        )
    _assert_zero_mutation(client, vanished)


def test_n34_full_reindex_with_a_blank_revision_deletes_nothing() -> None:
    """The full-reindex path is gated by the same completion-input validation."""
    client = RecordingWeaviateClient()
    stored = chunk_object("acme", "concept/old.md", "o1")
    _seed(client, stored)
    service = SyncService(store=corpus_store(client))
    with pytest.raises(SyncError, match="corpus_revision"):
        service.full_reindex(
            project_id="acme",
            producer="concept_sync",
            objects_by_source={
                "concept/a.md": [chunk_object("acme", "concept/a.md", "a1")]
            },
            corpus_revision="",
        )
    _assert_zero_mutation(client, stored)


def test_n34_every_mandatory_completion_input_is_gated() -> None:
    """The gate covers ALL caller-supplied receipt fields, not just the revision."""
    for name in ("project_id", "source_file", "source_type", "corpus_revision"):
        client = RecordingWeaviateClient()
        old = chunk_object("acme", "concept/a.md", "old")
        _seed(client, old)
        service = SyncService(store=corpus_store(client))
        args: dict[str, object] = {
            "project_id": "acme",
            "source_file": "concept/a.md",
            "source_type": "concept",
            "corpus_revision": "rev",
        }
        args[name] = ""
        with pytest.raises(SyncError, match=name):
            service.sync_source(
                objects=[chunk_object("acme", "concept/a.md", "new")],
                **args,  # type: ignore[arg-type]
            )
        _assert_zero_mutation(client, old)


def test_n34_a_blank_receipt_field_is_still_rejected_at_publication() -> None:
    """The receipt's own verification stays as strict as before (defence in depth)."""
    blank = SyncReceipt.for_completion("acme", "concept/a.md", "concept", "   ")
    with pytest.raises(SyncError, match="corpus_revision"):
        blank.stamped(sequence=1).verify()


def test_n27_vanished_delete_is_fenced_before_it_deletes() -> None:
    """N27: a takeover DURING the vanished-source delete must prevent the delete."""
    client = RecordingWeaviateClient()
    stale = chunk_object("acme", "concept/gone.md", "g1")
    _seed(client, stale)
    store = corpus_store(client)

    def _take_over(collection: str, _uuid: str) -> None:
        if collection != CLAIM_COLLECTION:
            return
        # The instant writer A holds its claim, an operator hands the source to B.
        client.after_insert = None
        store.reclaim_source(
            project_id="acme", source_file="concept/gone.md",
            owner_id="writer-b", reason="test takeover",
        )

    client.after_insert = _take_over
    with pytest.raises(ClaimSupersededError, match="superseded"):
        SyncService(store=store, owner_id="writer-a").reconcile_sources(
            project_id="acme", producer="concept_sync",
            objects_by_source={}, corpus_revision="rev",
        )
    assert stale.uuid in client.objects, "a superseded writer must not delete"


def test_n29_producer_closure_is_validated_for_the_whole_matrix() -> None:
    """A producer may not write another producer's source type (N29)."""
    client = RecordingWeaviateClient()
    service = SyncService(store=corpus_store(client))
    with pytest.raises(SyncError, match="does not own"):
        service.reconcile_sources(
            project_id="acme", producer="concept_sync",
            objects_by_source={
                "stories/x/story.md": [
                    chunk_object("acme", "stories/x/story.md", "s1", "story")
                ]
            },
            corpus_revision="rev",
        )
    assert client.claims == {}
    assert client.objects == {}


# --------------------------------------------------------------------------- #
# Concurrent-reject (D3) -- see test_engine_realpath.py for the racing proof
# --------------------------------------------------------------------------- #


def test_second_writer_of_a_claimed_source_is_rejected() -> None:
    client = RecordingWeaviateClient()
    store = corpus_store(client)
    writer_b = SyncService(store=store)
    held = store.try_claim_source(
        project_id="acme", source_file="concept/a.md", owner_id="writer-a"
    )
    assert held is not None
    with pytest.raises(ConcurrentSyncRejectedError, match="concurrent sync"):
        writer_b.sync_source(
            project_id="acme", source_file="concept/a.md", source_type="concept",
            objects=[chunk_object("acme", "concept/a.md", "c1")], corpus_revision="rev",
        )
    store.release_source(claim=held)
    res = writer_b.sync_source(
        project_id="acme", source_file="concept/a.md", source_type="concept",
        objects=[chunk_object("acme", "concept/a.md", "c1")], corpus_revision="rev",
    )
    assert res.written == 1


# --------------------------------------------------------------------------- #
# N17: ZERO mutation before the COMPLETE matrix is validated
# --------------------------------------------------------------------------- #


def test_n17_no_claim_is_written_before_objects_are_validated() -> None:
    """The claim record is itself a mutation -- validation must precede it."""
    client = RecordingWeaviateClient()
    service = SyncService(store=corpus_store(client))
    with pytest.raises(SyncError, match="project_id='other'"):
        service.sync_source(
            project_id="acme", source_file="concept/a.md", source_type="concept",
            objects=[chunk_object("other", "concept/a.md", "c1")], corpus_revision="rev",
        )
    assert client.claims == {}, "no claim may be written for an invalid object set"
    assert client.objects == {}
    assert client.receipts == {}


def test_n17_invalid_later_source_prevents_the_vanished_delete() -> None:
    """reconcile validates the WHOLE matrix before deleting a vanished source."""
    client = RecordingWeaviateClient()
    stale = chunk_object("acme", "concept/gone.md", "g1")
    _seed(client, stale)
    service = SyncService(store=corpus_store(client))
    matrix = {
        "concept/a.md": [chunk_object("acme", "concept/a.md", "a1")],
        # The SECOND source is invalid (foreign project); neither the first source
        # nor the vanished delete may have happened when it is rejected.
        "concept/b.md": [chunk_object("other", "concept/b.md", "b1")],
    }
    with pytest.raises(SyncError, match="project_id='other'"):
        service.reconcile_sources(
            project_id="acme", producer="concept_sync",
            objects_by_source=matrix, corpus_revision="rev",
        )
    assert stale.uuid in client.objects, "the vanished source must NOT be deleted yet"
    assert client.claims == {}
    assert client.receipts == {}


def test_n17_full_reindex_validates_before_deleting() -> None:
    client = RecordingWeaviateClient()
    stale = chunk_object("acme", "concept/gone.md", "g1")
    _seed(client, stale)
    service = SyncService(store=corpus_store(client))
    with pytest.raises(SyncError, match="source_file="):
        service.full_reindex(
            project_id="acme", producer="concept_sync",
            objects_by_source={"concept/a.md": [chunk_object("acme", "concept/other.md", "x")]},
            corpus_revision="rev",
        )
    assert stale.uuid in client.objects
    assert client.claims == {}


def test_n17_mixed_source_types_in_one_source_are_rejected() -> None:
    client = RecordingWeaviateClient()
    service = SyncService(store=corpus_store(client))
    matrix = {
        "concept/a.md": [
            chunk_object("acme", "concept/a.md", "a1", "concept"),
            chunk_object("acme", "concept/a.md", "a2", "story"),
        ]
    }
    with pytest.raises(SyncError, match="mixes source types"):
        service.reconcile_sources(
            project_id="acme", producer="concept_sync",
            objects_by_source=matrix, corpus_revision="rev",
        )
    assert client.objects == {}


# --------------------------------------------------------------------------- #
# N15/N27: claims carry owner + epoch + an acquisition TIMESTAMP (no expiry) and
# are FENCED; a held claim is released only by an explicit administrative reclaim
# --------------------------------------------------------------------------- #


def _clock(start: datetime) -> tuple[Callable[[], datetime], list[datetime]]:
    """A controllable UTC clock; entry 0 of the returned list is 'now'."""
    now = [start]

    def read() -> datetime:
        return now[0]

    return read, now


def test_n15_claim_record_carries_owner_and_epoch_but_no_expiry() -> None:
    """N27: a claim carries owner + epoch and NO expiry field at all."""
    client = RecordingWeaviateClient()
    store = corpus_store(client)
    claim = store.try_claim_source(
        project_id="acme", source_file="concept/a.md", owner_id="writer-a"
    )
    assert claim is not None
    assert claim.owner_id == "writer-a"
    assert claim.epoch == 1
    assert claim.reclaimed_from == ""
    record = next(iter(client.claims.values()))
    assert record["owner_id"] == "writer-a"
    assert record["epoch"] == "1"
    parse_utc_timestamp(str(record["claimed_at"]))
    assert "expires_at" not in record, "a claim must not carry a wall-clock expiry (N27)"
    assert not hasattr(claim, "expires_at")


def test_n27_a_claim_never_expires_by_time() -> None:
    """D3 admits NO time-based exception: a held claim rejects forever (N27)."""
    client = RecordingWeaviateClient()
    start = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
    read, now = _clock(start)
    store = corpus_store(client, clock=read)
    crashed = store.try_claim_source(
        project_id="acme", source_file="concept/a.md", owner_id="crashed-writer"
    )
    assert crashed is not None
    # A YEAR later the claim is STILL rejected -- no automatic takeover.
    now[0] = start + timedelta(days=365)
    assert (
        store.try_claim_source(
            project_id="acme", source_file="concept/a.md", owner_id="writer-b"
        )
        is None
    )
    # ...and a normal sync of another writer is rejected, not silently taken over.
    with pytest.raises(ConcurrentSyncRejectedError, match="administrative reclaim"):
        SyncService(store=store, owner_id="writer-b").sync_source(
            project_id="acme", source_file="concept/a.md", source_type="concept",
            objects=[chunk_object("acme", "concept/a.md", "c1")], corpus_revision="rev",
        )
    assert client.objects == {}


def test_n27_explicit_administrative_reclaim_takes_over_and_fences() -> None:
    """The ONLY recovery is the explicit operator reclaim (N27)."""
    client = RecordingWeaviateClient()
    store = corpus_store(client)
    crashed = store.try_claim_source(
        project_id="acme", source_file="concept/a.md", owner_id="crashed-writer"
    )
    assert crashed is not None
    service = SyncService(store=store, owner_id="writer-b", reclaim=True)
    result = service.sync_source(
        project_id="acme", source_file="concept/a.md", source_type="concept",
        objects=[chunk_object("acme", "concept/a.md", "c1")], corpus_revision="rev",
    )
    assert result.written == 1
    # The reclaim is RECORDED (who was taken over, and why).
    reclaim_record = next(
        r for r in client.claim_history if r.get("reclaimed_from") == "crashed-writer"
    )
    assert reclaim_record["epoch"] == "2"
    assert reclaim_record["reclaim_reason"]
    # The crashed holder is fenced out for good.
    with pytest.raises(ClaimSupersededError, match="superseded"):
        store.assert_claim_held(claim=crashed)


def test_n27_stale_writer_cannot_write_after_an_administrative_takeover() -> None:
    """The FIRST fence sits before the first WRITE, not after it (N27).

    Writer A pauses, B is administratively granted the claim and completes, A
    resumes -- A must not write a single stale chunk.
    """
    client = RecordingWeaviateClient()
    store = corpus_store(client)
    writer_a = SyncService(store=store, owner_id="writer-a")
    claim_a = store.try_claim_source(
        project_id="acme", source_file="concept/a.md", owner_id="writer-a"
    )
    assert claim_a is not None
    # B takes over administratively and completes the source.
    SyncService(store=store, owner_id="writer-b", reclaim=True).sync_source(
        project_id="acme", source_file="concept/a.md", source_type="concept",
        objects=[chunk_object("acme", "concept/a.md", "from-b")], corpus_revision="rev-b",
    )
    written_by_b = dict(client.objects)
    receipts_after_b = dict(client.receipts)
    # A resumes with its stale claim: it must abort BEFORE writing anything.
    with pytest.raises(ClaimSupersededError, match="superseded"):
        writer_a._sync_impl(  # noqa: SLF001 -- the resumed in-flight window
            claim=claim_a,
            source_type="concept",
            objects=[chunk_object("acme", "concept/a.md", "stale-from-a")],
            corpus_revision="rev-a",
        )
    assert client.objects == written_by_b, "no stale chunk may be written"
    assert client.receipts == receipts_after_b, "no stale completion may be published"


def test_n15_superseded_writer_cannot_publish_a_receipt() -> None:
    """A taken-over writer must not publish a completion marker (fence)."""
    client = RecordingWeaviateClient()
    store = corpus_store(client)
    service = SyncService(store=store, owner_id="writer-a")
    old = chunk_object("acme", "concept/a.md", "old")
    _seed(client, old)

    def _take_over(collection: str) -> None:
        if collection != STORY_CONTEXT_COLLECTION:
            return
        client.after_upsert = None
        # A concurrent owner takes the claim over mid-window (epoch 2).
        client.insert_object(
            collection=CLAIM_COLLECTION,
            uuid=claim_uuid_for("acme", "concept/a.md", 2),
            properties={
                "project_id": "acme",
                "source_file": "concept/a.md",
                "state": "claimed",
                "owner_id": "writer-b",
                "epoch": "2",
                "claimed_at": utc_now(),
                "reclaimed_from": "writer-a",
                "reclaim_reason": "test takeover",
            },
        )

    client.after_upsert = _take_over
    with pytest.raises(ClaimSupersededError, match="superseded"):
        service.sync_source(
            project_id="acme", source_file="concept/a.md", source_type="concept",
            objects=[chunk_object("acme", "concept/a.md", "new")], corpus_revision="rev",
        )
    assert client.receipts == {}, "a superseded writer must not publish a receipt"
    assert old.uuid in client.objects, "and must not delete the old generation"


def test_n15_vanished_source_delete_requires_the_claim() -> None:
    """A vanished-source DELETE is a mutation and must be claimed too (D3)."""
    client = RecordingWeaviateClient()
    stale = chunk_object("acme", "concept/gone.md", "g1")
    _seed(client, stale)
    store = corpus_store(client)
    other_writer = store.try_claim_source(
        project_id="acme", source_file="concept/gone.md", owner_id="writer-a"
    )
    assert other_writer is not None
    with pytest.raises(ConcurrentSyncRejectedError, match="concurrent sync"):
        SyncService(store=store, owner_id="writer-b").reconcile_sources(
            project_id="acme", producer="concept_sync",
            objects_by_source={}, corpus_revision="rev",
        )
    assert stale.uuid in client.objects, "an unclaimed vanished delete must not happen"


# --------------------------------------------------------------------------- #
# N16: the completion order is reserved ATOMICALLY and fully digest-bound
# --------------------------------------------------------------------------- #


def test_n28_each_completion_is_one_immutable_conditional_create() -> None:
    client = RecordingWeaviateClient()
    store = corpus_store(client)
    for source in ("concept/a.md", "concept/b.md", "concept/c.md"):
        SyncService(store=store).sync_source(
            project_id="acme", source_file=source, source_type="concept",
            objects=[chunk_object("acme", source, "c1")], corpus_revision="rev",
        )
    # The completion RECORD itself is the position: one conditional create per
    # completion, never a reservation followed by a separate publish.
    assert RECEIPT_COLLECTION not in client.upsert_calls, (
        "a completion must never be an upsert -- only an immutable create (N28)"
    )
    receipts = sorted(store.list_receipts(project_id="acme"), key=lambda r: r.sequence)
    assert [r.sequence for r in receipts] == [1, 2, 3]
    for receipt in receipts:
        receipt.verify()


def test_n28_two_concurrent_completions_get_distinct_positions() -> None:
    client = RecordingWeaviateClient()
    client.insert_barrier = threading.Barrier(2, timeout=10)
    store = corpus_store(client)
    outcomes: list[int] = []
    lock = threading.Lock()

    def _complete(source: str) -> None:
        sealed = store.set_receipt(
            receipt=SyncReceipt.for_completion("acme", source, "concept", "rev")
        )
        with lock:
            outcomes.append(sealed.sequence)

    threads = [
        threading.Thread(target=_complete, args=("concept/a.md",)),
        threading.Thread(target=_complete, args=("concept/b.md",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert sorted(outcomes) == [1, 2], "two racing completions must not share a sequence"


@pytest.mark.parametrize(
    "field_name,value",
    [
        ("sequence", 99),
        ("completed_at", "2026-07-25T00:00:00Z"),
        ("state", ReceiptState.IN_PROGRESS),
        ("source_type", "story"),
        ("corpus_revision", "other-rev"),
        ("source_file", "concept/other.md"),
        ("project_id", "other"),
    ],
)
def test_n16_every_ordering_and_identity_field_is_digest_bound(
    field_name: str, value: object
) -> None:
    """Editing ANY bound field invalidates the digest (replay protection)."""
    import dataclasses

    sealed = SyncReceipt.for_completion("acme", "concept/a.md", "concept", "rev").stamped(
        sequence=7
    )
    sealed.verify()
    tampered = dataclasses.replace(sealed, **{field_name: value})
    with pytest.raises(SyncError, match="does not bind"):
        tampered.verify()


def test_n16_receipt_timestamp_must_be_utc() -> None:
    import dataclasses

    sealed = SyncReceipt.for_completion("acme", "concept/a.md", "concept", "rev").stamped(
        sequence=1
    )
    naive = dataclasses.replace(sealed, completed_at="2026-07-25T00:00:00")
    resealed = dataclasses.replace(naive, digest=naive.expected_digest())
    with pytest.raises(SyncError, match="not UTC|not an ISO-8601"):
        resealed.verify()


def test_n16_unstamped_receipt_never_verifies() -> None:
    unstamped = SyncReceipt.for_completion("acme", "concept/a.md", "concept", "rev")
    with pytest.raises(SyncError):
        unstamped.verify()
