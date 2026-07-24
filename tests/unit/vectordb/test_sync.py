"""Bounded-window sync tests (FK-13 §13.9.9, Review 174-P1-1, AC6, D3, N13).

The double lives ONLY at the Weaviate CLIENT boundary
(:class:`RecordingWeaviateClient`), so the REAL ``WeaviateCorpusStore`` runs
underneath the ``SyncService``: the bounded-window ordering, the digest-bound
receipt, crash/retry reconciliation, the atomic claim (D3), the per-object target
validation (N13) and the full_reindex source-type isolation all execute
productively.
"""

from __future__ import annotations

import pytest
from tests.unit.vectordb.corpus_doubles import (
    RecordingWeaviateClient,
    chunk_object,
    corpus_store,
)

from agentkit.backend.vectordb.schema import StoryContextObject, deterministic_uuid
from agentkit.backend.vectordb.sync import (
    ConcurrentSyncRejectedError,
    PartialWriteError,
    ReceiptState,
    SyncError,
    SyncService,
)


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
    assert r1.receipt_digest == r2.receipt_digest
    objs = store.list_objects_for_source(project_id="acme", source_file="concept/a.md")
    assert len(objs) == 1
    # One receipt RECORD per source, with an advancing completion sequence (N04).
    assert len(client.receipts) == 1
    latest = store.get_receipt(project_id="acme", source_file="concept/a.md")
    assert latest is not None and latest.sequence == 2


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
    client = RecordingWeaviateClient()
    a = chunk_object("acme", "concept/a.md", "a1")
    b = chunk_object("other", "concept/a.md", "a1")  # same source, other project
    _seed(client, a)
    _seed(client, b)
    service = SyncService(store=corpus_store(client))
    service.sync_source(
        project_id="acme", source_file="concept/a.md", source_type="concept",
        objects=[], corpus_revision="rev",  # empty should-set -> delete acme's only
    )
    assert a.uuid not in client.objects
    assert b.uuid in client.objects  # other project untouched


# --------------------------------------------------------------------------- #
# Concurrent-reject (D3) -- see test_engine_realpath.py for the racing proof
# --------------------------------------------------------------------------- #


def test_second_writer_of_a_claimed_source_is_rejected() -> None:
    client = RecordingWeaviateClient()
    store = corpus_store(client)
    writer_b = SyncService(store=store)
    assert store.try_claim_source(project_id="acme", source_file="concept/a.md") is True
    with pytest.raises(ConcurrentSyncRejectedError, match="concurrent sync"):
        writer_b.sync_source(
            project_id="acme", source_file="concept/a.md", source_type="concept",
            objects=[chunk_object("acme", "concept/a.md", "c1")], corpus_revision="rev",
        )
    store.release_source(project_id="acme", source_file="concept/a.md")
    res = writer_b.sync_source(
        project_id="acme", source_file="concept/a.md", source_type="concept",
        objects=[chunk_object("acme", "concept/a.md", "c1")], corpus_revision="rev",
    )
    assert res.written == 1
