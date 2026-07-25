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
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from tests.unit.vectordb.corpus_doubles import (
    PREVIOUS_GENERATION,
    RecordingWeaviateClient,
    chunk_object,
    corpus_store,
    seed_object,
)

from agentkit.backend.vectordb.engine import (
    CLAIM_COLLECTION,
    RECEIPT_COLLECTION,
    WeaviateCorpusStore,
)
from agentkit.backend.vectordb.schema import (
    OWNING_GENERATION_PROPERTY,
    STORY_CONTEXT_COLLECTION,
    StoryContextObject,
    deterministic_uuid,
)
from agentkit.backend.vectordb.sync import (
    ClaimReleaseFailedError,
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
from agentkit.integration_clients.vectordb.errors import (
    VectorDbUnavailableError,
    VectorDbWriteError,
)

if TYPE_CHECKING:
    from collections.abc import Callable


def claim_uuid_for(project_id: str, source_file: str, generation: int) -> str:
    """The store's deterministic claim uuid for one generation (N15/N37)."""
    return WeaviateCorpusStore._claim_uuid(project_id, source_file, generation)  # noqa: SLF001


def _seed(
    client: RecordingWeaviateClient,
    obj: StoryContextObject,
    *,
    owning_generation: int | None = PREVIOUS_GENERATION,
) -> None:
    """Seed a persisted object as a PREVIOUS source generation wrote it (N37)."""
    seed_object(client, obj, owning_generation=owning_generation)


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
    """R12: an unconfirmed delete blocks the reindex instead of counting a phantom.

    The destructive delete is storage-CONDITIONAL (N37), so a short confirmed count
    means at least one object is not older than this claim's generation. Either way
    the run fails closed and reports no completion; the mechanism changed the NAME of
    the fault, not the guarantee.
    """
    client = RecordingWeaviateClient()
    _seed(client, chunk_object("acme", "concept/gone.md", "g1"))
    client.delete_confirmed_override = 0  # the store confirms nothing
    service = SyncService(store=corpus_store(client))
    with pytest.raises(ClaimSupersededError, match="not older than this claim"):
        service.full_reindex(
            project_id="acme", producer="concept_sync",
            objects_by_source={}, corpus_revision="rev-1",
        )
    assert client.receipts == {}, "an unconfirmed delete must not report a completion"


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
    ladder = dict(client.claims)
    service = SyncService(store=corpus_store(client))
    with pytest.raises(SyncError, match="carries no objects"):
        service.reconcile_sources(
            project_id="acme", producer="concept_sync",
            objects_by_source={"concept/a.md": []}, corpus_revision="rev",
        )
    assert stale.uuid in client.objects, "the vanished delete must not have run"
    assert client.claims == ladder, "no claim beyond the seeded history"
    assert client.receipts == {}


def test_n29_a_malformed_receipt_is_never_persisted() -> None:
    """N29: the sealed receipt is verified BEFORE it is written."""
    client = RecordingWeaviateClient()
    store = corpus_store(client)
    malformed = SyncReceipt.for_completion(
        "acme", "concept/a.md", "", "rev", generation=1
    )
    with pytest.raises(SyncError, match="source_type"):
        store.set_receipt(receipt=malformed)
    assert client.receipts == {}, "an unverified receipt must never reach the store"


# --------------------------------------------------------------------------- #
# N34: the pre-mutation gate covers the RECEIPT'S INPUTS, not only the objects
# --------------------------------------------------------------------------- #


def _assert_zero_mutation(
    client: RecordingWeaviateClient,
    seeded: StoryContextObject,
    *,
    ladder_before: dict[str, dict[str, object]] | None = None,
) -> None:
    """Assert a rejected run left NO trace at all (claim, write, delete, receipt).

    ``ladder_before`` is the claim ladder as the fixture seeded it: a persisted object
    implies a finished generation, so the ladder is NOT empty at the start. The
    assertion is that the run added nothing to it.
    """
    assert client.claims == (ladder_before or {}), (
        "no claim may be written for an unpublishable run"
    )
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
    ladder = dict(client.claims)
    service = SyncService(store=corpus_store(client))
    with pytest.raises(SyncError, match="corpus_revision"):
        service.sync_source(
            project_id="acme", source_file="concept/a.md", source_type="concept",
            objects=[chunk_object("acme", "concept/a.md", "new")],
            corpus_revision=revision,
        )
    _assert_zero_mutation(client, old, ladder_before=ladder)


def test_n34_reconcile_with_a_blank_revision_spares_the_vanished_source() -> None:
    """The matrix gate must reject before the vanished-source DELETE happens."""
    client = RecordingWeaviateClient()
    vanished = chunk_object("acme", "concept/gone.md", "g1")
    _seed(client, vanished)
    ladder = dict(client.claims)
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
    _assert_zero_mutation(client, vanished, ladder_before=ladder)


def test_n34_full_reindex_with_a_blank_revision_deletes_nothing() -> None:
    """The full-reindex path is gated by the same completion-input validation."""
    client = RecordingWeaviateClient()
    stored = chunk_object("acme", "concept/old.md", "o1")
    _seed(client, stored)
    ladder = dict(client.claims)
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
    _assert_zero_mutation(client, stored, ladder_before=ladder)


def test_n34_every_mandatory_completion_input_is_gated() -> None:
    """The gate covers ALL caller-supplied receipt fields, not just the revision."""
    for name in ("project_id", "source_file", "source_type", "corpus_revision"):
        client = RecordingWeaviateClient()
        old = chunk_object("acme", "concept/a.md", "old")
        _seed(client, old)
        ladder = dict(client.claims)
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
        _assert_zero_mutation(client, old, ladder_before=ladder)


def test_n34_a_blank_receipt_field_is_still_rejected_at_publication() -> None:
    """The receipt's own verification stays as strict as before (defence in depth)."""
    blank = SyncReceipt.for_completion(
        "acme", "concept/a.md", "concept", "   ", generation=1
    )
    with pytest.raises(SyncError, match="corpus_revision"):
        blank.stamped(sequence=1).verify()


# --------------------------------------------------------------------------- #
# N37: the DESTRUCTIVE delete is storage-conditional on the GENERATION ORDER
#
# The condition is "written by a generation strictly OLDER than mine", where mine is
# the deleting claim's own generation. Both race orders are covered: the newer owner
# writing BEFORE this writer reads, and AFTER. The previous model (equality against
# an OBSERVED token) survived only the second order -- it authorised the delete from
# whatever it happened to read, which is exactly how a resumed writer could remove a
# newer generation's data.
# --------------------------------------------------------------------------- #


def _writer(store: WeaviateCorpusStore, owner: str) -> SyncService:
    return SyncService(store=store, owner_id=owner)


def test_n37_superseded_holder_cannot_delete_a_newer_generation_written_after_it_read(
) -> None:
    """ORDER 1: the newer owner rewrites the objects AFTER this writer read them."""
    client = RecordingWeaviateClient()
    stale = chunk_object("acme", "concept/gone.md", "g1")
    _seed(client, stale)
    store = corpus_store(client)

    def _take_over_and_rewrite(collection: str) -> None:
        if collection != STORY_CONTEXT_COLLECTION:
            return
        client.before_delete = None
        new_claim = store.reclaim_source(
            project_id="acme", source_file="concept/gone.md",
            owner_id="writer-b", reason="test takeover",
        )
        store.upsert_objects(objects=[stale], owning_generation=new_claim.generation)

    client.before_delete = _take_over_and_rewrite
    with pytest.raises(ClaimSupersededError, match="not older than this claim"):
        _writer(store, "writer-a").reconcile_sources(
            project_id="acme", producer="concept_sync",
            objects_by_source={}, corpus_revision="rev",
        )
    assert stale.uuid in client.objects, "the newer generation's data must survive"
    assert client.objects[stale.uuid][OWNING_GENERATION_PROPERTY] == 3
    # The protection is STORAGE-side: the delete was attempted and could not match.
    assert client.conditional_delete_calls, "the delete must have been attempted"
    assert client.conditional_delete_calls[-1]["limit"] == 2


def test_n37_superseded_holder_cannot_delete_a_newer_generation_written_before_it_read(
) -> None:
    """ORDER 2 (the counter-scenario): the newer owner writes and COMPLETES first.

    Writer A passes its fence, B reclaims and finishes, and only THEN does A resume
    and read. A now reads B's chunks; under the superseded observed-token model A
    would group them under B's token and delete them. Ordered against A's OWN
    generation they are not older, so A cannot touch them.
    """
    client = RecordingWeaviateClient()
    store = corpus_store(client)
    writer_a = _writer(store, "writer-a")
    stale = chunk_object("acme", "concept/gone.md", "g1")
    _seed(client, stale)

    # A acquires its generation and is then superseded BEFORE it reads anything.
    claim_a = store.try_claim_source(
        project_id="acme", source_file="concept/gone.md", owner_id="writer-a"
    )
    assert claim_a is not None
    store.assert_claim_held(claim=claim_a)  # A's fence passes here
    claim_b = store.reclaim_source(
        project_id="acme", source_file="concept/gone.md",
        owner_id="writer-b", reason="test takeover",
    )
    store.upsert_objects(objects=[stale], owning_generation=claim_b.generation)
    store.release_source(claim=claim_b)  # B is done and gone

    # A resumes and drives its OWN delete with the rows it now reads.
    rows = store.list_objects_for_source_types(
        project_id="acme", source_types=("concept",)
    )
    with pytest.raises(ClaimSupersededError, match="not older than this claim"):
        writer_a._delete_older_generations(rows, claim=claim_a)  # noqa: SLF001
    assert stale.uuid in client.objects, "the newer generation's data must survive"
    assert client.objects[stale.uuid][OWNING_GENERATION_PROPERTY] == claim_b.generation


def test_n37_end_to_end_a_writer_that_reads_a_newer_generation_cannot_delete_it(
) -> None:
    """ORDER 2, END-TO-END through ``sync_source`` (P2-6).

    The previous order-2 proof drove the private delete helper. Here the whole entry
    path runs: A claims, writes its own generation, and the takeover happens BEFORE A
    re-reads the source -- so A genuinely READS B's newer rows, computes them as
    "not mine, therefore stale", and attempts to delete them. The storage condition
    still refuses, because the bound is A's own generation.

    Note on the OTHER entry path: in ``reconcile_sources`` the vanished-source read
    happens BEFORE the claim is acquired, and a newer generation can only exist via a
    reclaim OF that claim. A "read after the newer write" order is therefore
    structurally impossible there, and the two orders coincide -- the condition is
    evaluated by the store at delete time either way (covered by the two tests above).
    """
    client = RecordingWeaviateClient()
    store = corpus_store(client)
    old = chunk_object("acme", "concept/a.md", "old")
    _seed(client, old)

    def _take_over_and_write(collection: str) -> None:
        if collection != STORY_CONTEXT_COLLECTION:
            return
        client.after_upsert = None
        newer = store.reclaim_source(
            project_id="acme", source_file="concept/a.md",
            owner_id="writer-b", reason="test takeover",
        )
        # B writes a chunk of its OWN generation that A will read and consider stale.
        store.upsert_objects(
            objects=[chunk_object("acme", "concept/a.md", "b-only")],
            owning_generation=newer.generation,
        )

    client.after_upsert = _take_over_and_write
    with pytest.raises(ClaimSupersededError, match="superseded"):
        SyncService(store=store, owner_id="writer-a").sync_source(
            project_id="acme", source_file="concept/a.md", source_type="concept",
            objects=[chunk_object("acme", "concept/a.md", "a-new")],
            corpus_revision="rev",
        )
    # B's chunk survives: A read it and could not even TREAT it as a candidate, because
    # the classification only ever offers rows strictly below A's own generation. (With
    # the required delete moved before the receipt (N46), A is then stopped at the fence
    # rather than by a short delete count -- the protection is the predicate either way.)
    b_only = deterministic_uuid("acme", "concept/a.md", "b-only")
    assert b_only in client.objects
    assert client.objects[b_only][OWNING_GENERATION_PROPERTY] == 3
    assert client.receipts == {}, "and A publishes no completion"


def test_n37_the_ladder_is_persistent_across_normal_releases() -> None:
    """A normal release must NOT reset the generation (the old model's fatal gap)."""
    client = RecordingWeaviateClient()
    store = corpus_store(client)
    seen: list[int] = []
    for owner in ("w1", "w2", "w3"):
        claim = store.try_claim_source(
            project_id="acme", source_file="concept/a.md", owner_id=owner
        )
        assert claim is not None
        seen.append(claim.generation)
        store.release_source(claim=claim)
    assert seen == [1, 2, 3], "every acquisition allocates the NEXT generation"
    # A reclaim continues the same ladder rather than starting its own.
    taken = store.reclaim_source(
        project_id="acme", source_file="concept/a.md", owner_id="w4", reason="test"
    )
    assert taken.generation == 4


def test_n37_a_released_generation_does_not_block_the_next_writer() -> None:
    """D3 still holds: a HELD generation rejects, a RELEASED one does not."""
    client = RecordingWeaviateClient()
    store = corpus_store(client)
    held = store.try_claim_source(
        project_id="acme", source_file="concept/a.md", owner_id="w1"
    )
    assert held is not None
    assert (
        store.try_claim_source(
            project_id="acme", source_file="concept/a.md", owner_id="w2"
        )
        is None
    ), "a held generation rejects a concurrent writer (D3)"
    store.release_source(claim=held)
    nxt = store.try_claim_source(
        project_id="acme", source_file="concept/a.md", owner_id="w2"
    )
    assert nxt is not None and nxt.generation == 2


def test_n37_superseded_holder_cannot_delete_the_new_generation_mid_window() -> None:
    """Same guarantee inside the per-source window (the old-generation delete)."""
    client = RecordingWeaviateClient()
    old = chunk_object("acme", "concept/a.md", "old")
    _seed(client, old)
    store = corpus_store(client)

    def _take_over_and_rewrite(collection: str) -> None:
        if collection != STORY_CONTEXT_COLLECTION:
            return
        client.before_delete = None
        new_claim = store.reclaim_source(
            project_id="acme", source_file="concept/a.md",
            owner_id="writer-b", reason="test takeover",
        )
        store.upsert_objects(objects=[old], owning_generation=new_claim.generation)

    client.before_delete = _take_over_and_rewrite
    with pytest.raises(ClaimSupersededError):
        _writer(store, "writer-a").sync_source(
            project_id="acme", source_file="concept/a.md", source_type="concept",
            objects=[chunk_object("acme", "concept/a.md", "new")], corpus_revision="rev",
        )
    assert old.uuid in client.objects, "the newer generation's version must survive"
    assert client.receipts == {}, "and no completion may be published"


def test_n37_the_legitimate_delete_still_removes_every_old_chunk() -> None:
    """The condition must not cost the delete closure (R05): all old chunks go."""
    client = RecordingWeaviateClient()
    old = [chunk_object("acme", "concept/gone.md", f"g{i}") for i in range(3)]
    for obj in old:
        _seed(client, obj)
    service = SyncService(store=corpus_store(client))
    results = service.reconcile_sources(
        project_id="acme", producer="concept_sync",
        objects_by_source={}, corpus_revision="rev",
    )
    assert client.objects == {}, "every old chunk of a vanished source is removed"
    assert sum(r.deleted for r in results) == 3


def test_n37_old_chunks_of_several_generations_are_all_removed() -> None:
    """Chunks written by DIFFERENT previous generations are all caught at once.

    One ordering condition covers them all -- no grouping by an observed value, which
    is what made the previous model both fragile and unauthorised.
    """
    client = RecordingWeaviateClient()
    store = corpus_store(client)
    for chunk_id, generation in (("g1", 1), ("g2", 3), ("g3", 5)):
        _seed(
            client,
            chunk_object("acme", "concept/gone.md", chunk_id),
            owning_generation=generation,
        )
    # Seeding the objects also seeded the ladder, so the high-water is 5 and this
    # run's claim is 6 -- one condition strictly above every seeded generation.
    results = SyncService(store=store, owner_id="writer-now").reconcile_sources(
        project_id="acme", producer="concept_sync",
        objects_by_source={}, corpus_revision="rev",
    )
    assert client.objects == {}
    assert sum(r.deleted for r in results) == 3
    assert client.conditional_delete_calls[-1]["limit"] == 6


def test_n37_an_unorderable_object_is_never_ordered_against_a_claim() -> None:
    """Fail-closed: an object with an UNUSABLE generation is never ordered or guessed.

    An ABSENT generation is a legacy row and converges through the backfill (N43); a
    generation that is PRESENT but unusable is neither, so it is a named error.
    """
    client = RecordingWeaviateClient()
    broken = chunk_object("acme", "concept/a.md", "c1")
    _seed(client, broken, owning_generation=None)
    client.objects[broken.uuid][OWNING_GENERATION_PROPERTY] = "not-a-number"
    service = SyncService(store=corpus_store(client))
    with pytest.raises(SyncError, match="unusable writing generation"):
        service.sync_source(
            project_id="acme", source_file="concept/a.md", source_type="concept",
            objects=[chunk_object("acme", "concept/a.md", "c2")], corpus_revision="rev",
        )
    assert broken.uuid in client.objects, "never deleted on a guess"


# --------------------------------------------------------------------------- #
# N41 (shape 3): the post-completion sweep closes the stale-WRITE window
#
# The race that exposed this needs DIFFERING content: with the same content the stale
# write lands on the same uuid and is simply overwritten, which is why the old
# "same content" premise hid the defect. With changed content the uuids differ, so the
# stale rows are genuinely distinct rows that nothing else in the window touches.
# --------------------------------------------------------------------------- #


def test_n41_a_stale_write_with_differing_content_is_swept_at_the_completion() -> None:
    """A superseded writer's rows must not survive the newer owner's completion."""
    client = RecordingWeaviateClient()
    store = corpus_store(client)
    # A holds generation 1 and passes its fence; B then takes over as generation 2 and
    # runs a COMPLETE sync with different content.
    claim_a = store.try_claim_source(
        project_id="acme", source_file="concept/a.md", owner_id="writer-a"
    )
    assert claim_a is not None
    store.assert_claim_held(claim=claim_a)  # A's fence passes here
    claim_b = store.reclaim_source(
        project_id="acme", source_file="concept/a.md",
        owner_id="writer-b", reason="test takeover",
    )
    store.release_source(claim=claim_b)
    # A resumes and appends ITS generation's objects -- different content, so a
    # different uuid that B's generation never overwrites.
    stale = chunk_object("acme", "concept/a.md", "a-only")
    store.upsert_objects(objects=[stale], owning_generation=claim_a.generation)
    assert stale.uuid in client.objects

    # B now completes its own sync. Its sweep must remove A's leftover row.
    result = SyncService(store=store, owner_id="writer-b2").sync_source(
        project_id="acme", source_file="concept/a.md", source_type="concept",
        objects=[chunk_object("acme", "concept/a.md", "b-current")],
        corpus_revision="rev-b",
    )
    assert stale.uuid not in client.objects, "the stale row must not survive"
    assert set(client.objects) == {
        deterministic_uuid("acme", "concept/a.md", "b-current")
    }
    assert result.deleted >= 1
    # The sweep is STORAGE-conditional on the same predicate, not an app-side check.
    bounds = [
        c["limit"] for c in client.conditional_delete_calls if "limit" in c
    ]
    assert bounds and all(b == 3 for b in bounds)


def test_n41_a_stale_write_landing_before_the_final_delete_is_removed() -> None:
    """The final delete reads FRESH, so it also covers a write that landed after ours.

    The stale row is injected after this generation's upsert, i.e. after the point the
    first read saw. Only a delete that re-reads immediately before the completion can
    remove it -- and it must run BEFORE the receipt, so freshness never advances past a
    destructive step that has not happened (AC6 receipt-last, N46).
    """
    client = RecordingWeaviateClient()
    store = corpus_store(client)
    stale = chunk_object("acme", "concept/a.md", "stale-late")

    def _inject(collection: str) -> None:
        if collection != STORY_CONTEXT_COLLECTION:
            return
        client.after_upsert = None
        # A superseded writer of an EARLIER generation appends its own object.
        store.upsert_objects(objects=[stale], owning_generation=1)

    # Advance the ladder so the syncing writer is generation 2 and the stale row is 1.
    first = store.try_claim_source(
        project_id="acme", source_file="concept/a.md", owner_id="w0"
    )
    assert first is not None
    store.release_source(claim=first)

    client.after_upsert = _inject
    result = SyncService(store=store, owner_id="writer-a").sync_source(
        project_id="acme", source_file="concept/a.md", source_type="concept",
        objects=[chunk_object("acme", "concept/a.md", "current")],
        corpus_revision="rev",
    )
    assert stale.uuid not in client.objects, "the final delete must remove it"
    assert result.deleted == 1
    assert client.receipts, "and the completion was published AFTER the delete"


def test_n41_the_sweep_cannot_delete_the_newer_owners_rows() -> None:
    """A generation >= mine is not a sweep candidate: it is the new owner's data.

    P2-8, corrected: the earlier rationale -- "a taken-over holder never reaches its
    completion, because the receipt fence rejects it" -- was FALSE. The fence is a read
    followed by a separate write, so a takeover landing after it still lets the
    superseded holder publish a lower-generation completion and run its own final
    delete. What protects the newer rows is therefore ONLY the ordering PREDICATE, never
    the fence; so the predicate is what this test exercises directly.
    """
    client = RecordingWeaviateClient()
    store = corpus_store(client)
    service = SyncService(store=store, owner_id="writer-a")
    claim = store.try_claim_source(
        project_id="acme", source_file="concept/a.md", owner_id="writer-a"
    )
    assert claim is not None
    newer = chunk_object("acme", "concept/a.md", "newer-owner")
    store.upsert_objects(objects=[newer], owning_generation=claim.generation + 1)
    _legacy, older = service._classify_source_rows(  # noqa: SLF001
        store.list_objects_for_source(
            project_id="acme", source_file="concept/a.md"
        ),
        claim=claim,
        should_uuids=set(),
    )
    assert older == [], "a newer generation's row is not even a delete candidate"
    removed = service._delete_older_generations(older, claim=claim)  # noqa: SLF001
    assert removed == 0
    assert newer.uuid in client.objects, "a newer generation's row is untouchable"

    # ... and the SAME pass does remove a row of an older generation, so the exclusion
    # above is the predicate at work and not an empty candidate set. (P2-11: the
    # previous trailing setup was dead for a generation-1 fixture and asserted nothing;
    # the ladder is advanced here so an older generation actually exists.)
    store.release_source(claim=claim)
    later = store.try_claim_source(
        project_id="acme", source_file="concept/a.md", owner_id="writer-b"
    )
    assert later is not None and later.generation > claim.generation
    old_row = chunk_object("acme", "concept/a.md", "older")
    store.upsert_objects(objects=[old_row], owning_generation=claim.generation)
    _legacy2, older2 = service._classify_source_rows(  # noqa: SLF001
        store.list_objects_for_source(project_id="acme", source_file="concept/a.md"),
        claim=later,
        should_uuids=set(),
    )
    assert [str(row["uuid"]) for row in older2] == [old_row.uuid]
    assert service._delete_older_generations(older2, claim=later) == 1  # noqa: SLF001
    assert old_row.uuid not in client.objects
    assert newer.uuid in client.objects, "and the newer row still survives"


def test_n41_the_sweep_is_bounded_by_the_holders_own_generation() -> None:
    """The sweep's bound is the claim's OWN generation -- never a value it read.

    A stale row is injected at the completion so the sweep really issues a conditional
    delete: otherwise the sweep has no candidates and its bound is never observed.
    """
    client = RecordingWeaviateClient()
    store = corpus_store(client)
    service = SyncService(store=store, owner_id="writer-a")
    for _ in range(3):  # advance the ladder so the bound is unmistakable
        claim = store.try_claim_source(
            project_id="acme", source_file="concept/a.md", owner_id="w"
        )
        assert claim is not None
        store.release_source(claim=claim)
    _seed(client, chunk_object("acme", "concept/a.md", "old"), owning_generation=2)

    def _inject(collection: str) -> None:
        if collection != STORY_CONTEXT_COLLECTION:
            return
        client.after_upsert = None
        store.upsert_objects(
            objects=[chunk_object("acme", "concept/a.md", "stale-late")],
            owning_generation=1,
        )

    client.after_upsert = _inject
    service.sync_source(
        project_id="acme", source_file="concept/a.md", source_type="concept",
        objects=[chunk_object("acme", "concept/a.md", "new")], corpus_revision="rev",
    )
    ordered = [c for c in client.conditional_delete_calls if "limit" in c]
    assert ordered, "the final delete must be observed"
    assert {c["limit"] for c in ordered} == {4}, (
        "every conditional delete uses the holder's own generation"
    )
    assert {c["project_id"] for c in ordered} == {"acme"}, "and its project scope"


# --------------------------------------------------------------------------- #
# N43: pre-existing UNSTAMPED rows converge instead of blocking every retry
# --------------------------------------------------------------------------- #


def _seed_unstamped(
    client: RecordingWeaviateClient, obj: StoryContextObject
) -> None:
    """Seed a row as it existed BEFORE the ownership-ordering property (N43)."""
    seed_object(client, obj, owning_generation=None)


def test_n43_a_legacy_row_does_not_block_the_sync_forever() -> None:
    """The scenario that could never converge: current rows written, one legacy row.

    Before the backfill the run wrote the current rows and then died on the legacy row,
    so freshness was never published and the legacy row was never removed -- and every
    retry repeated exactly that.
    """
    client = RecordingWeaviateClient()
    legacy = chunk_object("acme", "concept/a.md", "legacy")
    _seed_unstamped(client, legacy)
    store = corpus_store(client)
    service = SyncService(store=store)
    result = service.sync_source(
        project_id="acme", source_file="concept/a.md", source_type="concept",
        objects=[chunk_object("acme", "concept/a.md", "current")],
        corpus_revision="rev-1",
    )
    assert legacy.uuid not in client.objects, "the legacy row converged"
    assert result.backfilled == 1, "and the repair is RECORDED, not silent"
    receipt = store.get_receipt(project_id="acme", source_file="concept/a.md")
    assert receipt is not None and receipt.corpus_revision == "rev-1"
    # A second run is a clean no-op: convergence, not oscillation.
    again = service.sync_source(
        project_id="acme", source_file="concept/a.md", source_type="concept",
        objects=[chunk_object("acme", "concept/a.md", "current")],
        corpus_revision="rev-2",
    )
    assert again.backfilled == 0
    assert set(client.objects) == {
        deterministic_uuid("acme", "concept/a.md", "current")
    }


def test_n43_a_legacy_row_that_is_still_current_is_stamped_by_the_write() -> None:
    """A legacy row that IS part of the new generation is adopted by being rewritten."""
    client = RecordingWeaviateClient()
    current = chunk_object("acme", "concept/a.md", "c1")
    _seed_unstamped(client, current)
    service = SyncService(store=corpus_store(client))
    result = service.sync_source(
        project_id="acme", source_file="concept/a.md", source_type="concept",
        objects=[current], corpus_revision="rev-1",
    )
    assert result.backfilled == 0, "nothing to remove -- the upsert stamped it"
    assert client.objects[current.uuid][OWNING_GENERATION_PROPERTY] == 1


def test_n43_a_vanished_legacy_source_converges() -> None:
    """A vanished source made only of legacy rows must be removable."""
    client = RecordingWeaviateClient()
    legacy = chunk_object("acme", "concept/gone.md", "g1")
    _seed_unstamped(client, legacy)
    service = SyncService(store=corpus_store(client))
    results = service.reconcile_sources(
        project_id="acme", producer="concept_sync",
        objects_by_source={}, corpus_revision="rev",
    )
    assert client.objects == {}, "the legacy vanished source converged"
    assert sum(r.deleted for r in results) == 1


def test_n43_a_vanished_source_with_mixed_rows_converges() -> None:
    """Stamped and unstamped rows of one vanished source are both removed."""
    client = RecordingWeaviateClient()
    legacy = chunk_object("acme", "concept/gone.md", "g1")
    stamped = chunk_object("acme", "concept/gone.md", "g2")
    _seed_unstamped(client, legacy)
    _seed(client, stamped)
    service = SyncService(store=corpus_store(client))
    results = service.reconcile_sources(
        project_id="acme", producer="concept_sync",
        objects_by_source={}, corpus_revision="rev",
    )
    assert client.objects == {}
    assert sum(r.deleted for r in results) == 2


def test_n43_the_backfill_only_ever_touches_unstamped_rows() -> None:
    """The backfill's SCOPE is unstamped rows: a stamped row is never in its list.

    The condition is an IS-NULL evaluated by the store, so a stamped row could not be
    matched even if it were sent -- but it is not even sent: the classification puts
    stamped rows under the generation ordering, where they belong.
    """
    client = RecordingWeaviateClient()
    legacy = chunk_object("acme", "concept/a.md", "legacy")
    stamped = chunk_object("acme", "concept/a.md", "stamped-old")
    _seed_unstamped(client, legacy)
    _seed(client, stamped)  # a previous, properly stamped generation
    service = SyncService(store=corpus_store(client))
    result = service.sync_source(
        project_id="acme", source_file="concept/a.md", source_type="concept",
        objects=[chunk_object("acme", "concept/a.md", "mine")], corpus_revision="rev",
    )
    assert legacy.uuid not in client.objects, "the legacy row converged"
    assert result.backfilled == 1
    absent_calls = [c for c in client.conditional_delete_calls if c.get("absent")]
    assert absent_calls, "the backfill must use the IS-NULL condition"
    for call in absent_calls:
        assert tuple(call["uuids"]) == (legacy.uuid,)  # type: ignore[arg-type]
    # The stamped old row was removed by the ORDERING predicate instead.
    assert stamped.uuid not in client.objects
    ordered_calls = [c for c in client.conditional_delete_calls if "limit" in c]
    assert any(stamped.uuid in tuple(c["uuids"]) for c in ordered_calls)  # type: ignore[arg-type]


def test_n43_the_backfill_runs_under_the_held_claim() -> None:
    """Claim-owned: a source held by another writer is not converged behind its back."""
    client = RecordingWeaviateClient()
    legacy = chunk_object("acme", "concept/a.md", "legacy")
    _seed_unstamped(client, legacy)
    store = corpus_store(client)
    held = store.try_claim_source(
        project_id="acme", source_file="concept/a.md", owner_id="other-writer"
    )
    assert held is not None
    with pytest.raises(ConcurrentSyncRejectedError, match="concurrent sync"):
        SyncService(store=store, owner_id="me").sync_source(
            project_id="acme", source_file="concept/a.md", source_type="concept",
            objects=[chunk_object("acme", "concept/a.md", "mine")],
            corpus_revision="rev",
        )
    assert legacy.uuid in client.objects, "no unclaimed backfill"


def test_n43_a_partial_backfill_is_fail_closed() -> None:
    """A backfill that did not fully converge must not report success."""
    client = RecordingWeaviateClient()
    _seed_unstamped(client, chunk_object("acme", "concept/a.md", "legacy"))
    client.delete_confirmed_override = 0  # the store confirms nothing
    service = SyncService(store=corpus_store(client))
    with pytest.raises(SyncError, match="did not converge"):
        service.sync_source(
            project_id="acme", source_file="concept/a.md", source_type="concept",
            objects=[chunk_object("acme", "concept/a.md", "current")],
            corpus_revision="rev",
        )
    assert client.receipts == {}, "and no completion is published"


def test_n37_every_write_carries_the_writing_generation() -> None:
    """The stamp is applied by the store, so an unstamped write is impossible."""
    client = RecordingWeaviateClient()
    service = SyncService(store=corpus_store(client), owner_id="writer-a")
    service.sync_source(
        project_id="acme", source_file="concept/a.md", source_type="concept",
        objects=[chunk_object("acme", "concept/a.md", "c1")], corpus_revision="rev",
    )
    stored = next(iter(client.objects.values()))
    assert stored[OWNING_GENERATION_PROPERTY] == 1


def test_n37_the_store_refuses_an_unstamped_write() -> None:
    """The generation is mandatory at the store boundary (no unorderable objects)."""
    store = corpus_store(RecordingWeaviateClient())
    with pytest.raises(VectorDbUnavailableError, match="non-positive owning generation"):
        store.upsert_objects(
            objects=[chunk_object("acme", "concept/a.md", "c1")], owning_generation=0
        )


# --------------------------------------------------------------------------- #
# N39: a superseded completion can never become freshness-authoritative
# --------------------------------------------------------------------------- #


def test_n39_a_stale_completion_appended_after_a_newer_one_never_wins() -> None:
    """ORDER 1: the newer generation publishes FIRST, the superseded one appends."""
    client = RecordingWeaviateClient()
    store = corpus_store(client)
    newer = store.set_receipt(
        receipt=SyncReceipt.for_completion(
            "acme", "concept/a.md", "concept", "rev-b", generation=6
        )
    )
    stale = store.set_receipt(
        receipt=SyncReceipt.for_completion(
            "acme", "concept/a.md", "concept", "rev-a", generation=5
        )
    )
    assert stale.sequence > newer.sequence, "the stale writer took a LATER position"
    winner = store.get_receipt(project_id="acme", source_file="concept/a.md")
    assert winner is not None
    assert winner.corpus_revision == "rev-b", "freshness follows the GENERATION"
    assert winner.generation == 6
    # ... and the stale append must not have pruned the newer, valid completion.
    revisions = {
        r.corpus_revision for r in store.list_receipts(project_id="acme")
    }
    assert "rev-b" in revisions


def test_n39_a_newer_completion_supersedes_and_prunes_the_older_one() -> None:
    """ORDER 2: the normal order still supersedes and prunes as before."""
    client = RecordingWeaviateClient()
    store = corpus_store(client)
    store.set_receipt(
        receipt=SyncReceipt.for_completion(
            "acme", "concept/a.md", "concept", "rev-a", generation=5
        )
    )
    store.set_receipt(
        receipt=SyncReceipt.for_completion(
            "acme", "concept/a.md", "concept", "rev-b", generation=6
        )
    )
    winner = store.get_receipt(project_id="acme", source_file="concept/a.md")
    assert winner is not None and winner.corpus_revision == "rev-b"
    revisions = {r.corpus_revision for r in store.list_receipts(project_id="acme")}
    assert revisions == {"rev-b"}, "the superseded generation is pruned"


def test_n39_a_completion_without_a_generation_is_rejected() -> None:
    """A completion that cannot be ordered against a takeover is never trusted."""
    unordered = SyncReceipt.for_completion("acme", "concept/a.md", "concept", "rev")
    with pytest.raises(SyncError, match="not a positive source generation"):
        unordered.stamped(sequence=1).verify()


def test_n39_the_digest_binds_the_generation() -> None:
    """The generation decides freshness, so it must be part of the binding (N16)."""
    sealed = SyncReceipt.for_completion(
        "acme", "concept/a.md", "concept", "rev", generation=5
    ).stamped(sequence=1)
    sealed.verify()
    forged = replace(sealed, generation=9)
    with pytest.raises(SyncError, match="does not bind its own fields"):
        forged.verify()


def test_n39_the_published_completion_carries_the_claim_generation() -> None:
    """The sync publishes under the generation it actually held."""
    client = RecordingWeaviateClient()
    store = corpus_store(client)
    for _ in range(2):  # advance the ladder
        claim = store.try_claim_source(
            project_id="acme", source_file="concept/a.md", owner_id="w"
        )
        assert claim is not None
        store.release_source(claim=claim)
    result = SyncService(store=store).sync_source(
        project_id="acme", source_file="concept/a.md", source_type="concept",
        objects=[chunk_object("acme", "concept/a.md", "c1")], corpus_revision="rev",
    )
    assert result.written == 1
    receipt = store.get_receipt(project_id="acme", source_file="concept/a.md")
    assert receipt is not None and receipt.generation == 3


# --------------------------------------------------------------------------- #
# N40: an EMPTY matrix must not skip the completion-input gate
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("revision", ["", "   "])
def test_n40_reconcile_with_an_empty_matrix_and_blank_revision_deletes_nothing(
    revision: str,
) -> None:
    """The run-wide gate runs at ENTRY, before the vanished-source delete."""
    client = RecordingWeaviateClient()
    vanished = chunk_object("acme", "concept/gone.md", "g1")
    _seed(client, vanished)
    ladder = dict(client.claims)
    service = SyncService(store=corpus_store(client))
    with pytest.raises(SyncError, match="corpus_revision"):
        service.reconcile_sources(
            project_id="acme", producer="concept_sync",
            objects_by_source={}, corpus_revision=revision,
        )
    _assert_zero_mutation(client, vanished, ladder_before=ladder)


def test_n40_full_reindex_with_an_empty_matrix_and_blank_revision_deletes_nothing(
) -> None:
    client = RecordingWeaviateClient()
    vanished = chunk_object("acme", "concept/gone.md", "g1")
    _seed(client, vanished)
    ladder = dict(client.claims)
    service = SyncService(store=corpus_store(client))
    with pytest.raises(SyncError, match="corpus_revision"):
        service.full_reindex(
            project_id="acme", producer="concept_sync",
            objects_by_source={}, corpus_revision="",
        )
    _assert_zero_mutation(client, vanished, ladder_before=ladder)


def test_n40_an_empty_matrix_with_a_blank_project_id_deletes_nothing() -> None:
    """Every RUN-WIDE completion input is gated, not just the revision."""
    client = RecordingWeaviateClient()
    vanished = chunk_object("acme", "concept/gone.md", "g1")
    _seed(client, vanished)
    ladder = dict(client.claims)
    service = SyncService(store=corpus_store(client))
    with pytest.raises(SyncError, match="project_id"):
        service.reconcile_sources(
            project_id="", producer="concept_sync",
            objects_by_source={}, corpus_revision="rev",
        )
    _assert_zero_mutation(client, vanished, ladder_before=ladder)


def test_n40_the_gate_is_derived_from_the_receipt_contract() -> None:
    """P2-5: a new mandatory receipt field cannot silently miss the gate."""
    from agentkit.backend.vectordb.sync import (
        COMPLETION_INPUT_FIELDS,
        RECEIPT_MANDATORY_FIELDS,
        RECEIPT_SEALED_FIELDS,
        RUN_WIDE_COMPLETION_INPUTS,
    )

    assert set(COMPLETION_INPUT_FIELDS) == set(RECEIPT_MANDATORY_FIELDS) - set(
        RECEIPT_SEALED_FIELDS
    )
    assert set(RUN_WIDE_COMPLETION_INPUTS) <= set(COMPLETION_INPUT_FIELDS)


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
    ladder = dict(client.claims)
    service = SyncService(store=corpus_store(client))
    with pytest.raises(SyncError, match="project_id='other'"):
        service.sync_source(
            project_id="acme", source_file="concept/a.md", source_type="concept",
            objects=[chunk_object("other", "concept/a.md", "c1")], corpus_revision="rev",
        )
    assert client.claims == ladder, "no claim may be written for an invalid object set"
    assert client.objects == {}
    assert client.receipts == {}


def test_n17_invalid_later_source_prevents_the_vanished_delete() -> None:
    """reconcile validates the WHOLE matrix before deleting a vanished source."""
    client = RecordingWeaviateClient()
    stale = chunk_object("acme", "concept/gone.md", "g1")
    _seed(client, stale)
    ladder = dict(client.claims)
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
    assert client.claims == ladder, "no claim beyond the seeded history"
    assert client.receipts == {}


def test_n17_full_reindex_validates_before_deleting() -> None:
    client = RecordingWeaviateClient()
    stale = chunk_object("acme", "concept/gone.md", "g1")
    _seed(client, stale)
    ladder = dict(client.claims)
    service = SyncService(store=corpus_store(client))
    with pytest.raises(SyncError, match="source_file="):
        service.full_reindex(
            project_id="acme", producer="concept_sync",
            objects_by_source={"concept/a.md": [chunk_object("acme", "concept/other.md", "x")]},
            corpus_revision="rev",
        )
    assert stale.uuid in client.objects
    assert client.claims == ladder, "no claim beyond the seeded history"


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
# N15/N27/N37: claims carry owner + a PERSISTENT generation + an acquisition
# TIMESTAMP (never an expiry) and are FENCED.
#
# P2-4, precisely: EVERY normal sync releases its claim in a ``finally`` block, and
# the release keeps the ladder position (N37). Only a claim left behind by a CRASHED
# writer still needs an explicit administrative reclaim -- there is no time-based
# takeover for it, no matter how old it is.
# --------------------------------------------------------------------------- #


def _clock(start: datetime) -> tuple[Callable[[], datetime], list[datetime]]:
    """A controllable UTC clock; entry 0 of the returned list is 'now'."""
    now = [start]

    def read() -> datetime:
        return now[0]

    return read, now


def test_n15_claim_record_carries_owner_and_generation_but_no_expiry() -> None:
    """N27: a claim carries owner + generation and NO expiry field at all."""
    client = RecordingWeaviateClient()
    store = corpus_store(client)
    claim = store.try_claim_source(
        project_id="acme", source_file="concept/a.md", owner_id="writer-a"
    )
    assert claim is not None
    assert claim.owner_id == "writer-a"
    assert claim.generation == 1
    assert claim.reclaimed_from == ""
    record = next(iter(client.claims.values()))
    assert record["owner_id"] == "writer-a"
    assert record["generation"] == "1"
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
    assert reclaim_record["generation"] == "2"
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
        # A concurrent owner takes the claim over mid-window with the NEXT generation
        # (the seeded history put the holder at 2, so the takeover is 3).
        client.insert_object(
            collection=CLAIM_COLLECTION,
            uuid=claim_uuid_for("acme", "concept/a.md", 3),
            properties={
                "project_id": "acme",
                "source_file": "concept/a.md",
                "state": "claimed",
                "owner_id": "writer-b",
                "generation": "3",
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
    # Whether the OLD generation survives is no longer the guarantee: D9 protects
    # what the NEW OWNER wrote (proven by the two d9 takeover tests below), and the
    # bounded switch window is documented rather than claimed away.


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
            receipt=SyncReceipt.for_completion(
                "acme", source, "concept", "rev", generation=1
            )
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

    sealed = SyncReceipt.for_completion(
        "acme", "concept/a.md", "concept", "rev", generation=1
    ).stamped(
        sequence=7
    )
    sealed.verify()
    tampered = dataclasses.replace(sealed, **{field_name: value})
    with pytest.raises(SyncError, match="does not bind"):
        tampered.verify()


def test_n16_receipt_timestamp_must_be_utc() -> None:
    import dataclasses

    sealed = SyncReceipt.for_completion(
        "acme", "concept/a.md", "concept", "rev", generation=1
    ).stamped(
        sequence=1
    )
    naive = dataclasses.replace(sealed, completed_at="2026-07-25T00:00:00")
    resealed = dataclasses.replace(naive, digest=naive.expected_digest())
    with pytest.raises(SyncError, match="not UTC|not an ISO-8601"):
        resealed.verify()


def test_n16_unstamped_receipt_never_verifies() -> None:
    unstamped = SyncReceipt.for_completion(
        "acme", "concept/a.md", "concept", "rev", generation=1
    )
    with pytest.raises(SyncError):
        unstamped.verify()


# --------------------------------------------------------------------------- #
# N45: a claim release is CONFIRMED -- never silently turned into success
# --------------------------------------------------------------------------- #


def test_n45_a_release_failure_after_a_successful_sync_is_surfaced() -> None:
    """A source that stays HELD must not be reported as a clean sync."""
    client = RecordingWeaviateClient()
    client.fail_release = True
    service = SyncService(store=corpus_store(client))
    with pytest.raises(ClaimReleaseFailedError, match="stays HELD"):
        service.sync_source(
            project_id="acme", source_file="concept/a.md", source_type="concept",
            objects=[chunk_object("acme", "concept/a.md", "c1")], corpus_revision="rev",
        )
    # The window itself completed -- that is exactly why silence was dangerous.
    assert client.objects, "the generation was written"
    assert client.receipts, "and the completion was published"


def test_n45_a_release_failure_does_not_replace_the_primary_sync_fault() -> None:
    """When BOTH fail, the sync's own fault surfaces; the release is attached to it.

    A plain ``finally`` substituted the release fault for the real cause of the run's
    failure, which is the worst of both worlds: the operator sees the symptom and loses
    the diagnosis.
    """
    client = RecordingWeaviateClient()
    client.fail_release = True
    store = corpus_store(client)
    service = SyncService(store=store)
    claim = store.try_claim_source(
        project_id="acme", source_file="concept/a.md", owner_id="w"
    )
    assert claim is not None

    def _boom() -> None:
        raise PartialWriteError("the window itself failed")

    with pytest.raises(PartialWriteError, match="the window itself failed") as caught:
        service._with_release(claim, _boom)  # noqa: SLF001
    notes = getattr(caught.value, "__notes__", [])
    assert any("could NOT be released" in note for note in notes), notes


def test_n45_the_vanished_delete_path_also_confirms_its_release() -> None:
    client = RecordingWeaviateClient()
    _seed(client, chunk_object("acme", "concept/gone.md", "g1"))
    client.fail_release = True
    service = SyncService(store=corpus_store(client))
    with pytest.raises(ClaimReleaseFailedError, match="stays HELD"):
        service.reconcile_sources(
            project_id="acme", producer="concept_sync",
            objects_by_source={}, corpus_revision="rev",
        )


def test_n45_releasing_twice_is_idempotent() -> None:
    """A repeated release is not a fault -- the marker already exists."""
    client = RecordingWeaviateClient()
    store = corpus_store(client)
    claim = store.try_claim_source(
        project_id="acme", source_file="concept/a.md", owner_id="w"
    )
    assert claim is not None
    store.release_source(claim=claim)
    store.release_source(claim=claim)  # no raise


def test_n45_a_denied_release_marker_is_surfaced() -> None:
    """If the store neither creates nor holds the marker, the source stays held."""
    client = RecordingWeaviateClient()
    client.deny_release_insert = True
    store = corpus_store(client)
    claim = store.try_claim_source(
        project_id="acme", source_file="concept/a.md", owner_id="w"
    )
    assert claim is not None
    with pytest.raises(ClaimReleaseFailedError, match="neither created nor holds"):
        store.release_source(claim=claim)


# --------------------------------------------------------------------------- #
# N46/N47: the mandated order -- prevalidate, write, verify, delete, receipt LAST
# --------------------------------------------------------------------------- #


def test_n47_a_failed_write_leaves_the_legacy_rows_intact() -> None:
    """The legacy cleanup must NOT precede the write (N47).

    Deleting first meant a failed upsert left the source with neither its old rows nor
    a complete replacement, and no completion either -- the success test never exercised
    the intervening write failure.
    """

    class _FailingUpsert(RecordingWeaviateClient):
        def upsert(self, *, collection: str, objects: object) -> int:  # type: ignore[override]
            raise VectorDbWriteError("transport rejected the batch")

    client = _FailingUpsert()
    legacy = chunk_object("acme", "concept/a.md", "legacy")
    _seed(client, legacy, owning_generation=None)
    service = SyncService(store=corpus_store(client))
    with pytest.raises(VectorDbWriteError, match="rejected"):
        service.sync_source(
            project_id="acme", source_file="concept/a.md", source_type="concept",
            objects=[chunk_object("acme", "concept/a.md", "current")],
            corpus_revision="rev",
        )
    assert legacy.uuid in client.objects, "the old rows must survive a failed write"
    assert client.receipts == {}, "and no completion may be published"


def test_n47_a_partial_write_leaves_the_old_generation_intact() -> None:
    """Same guarantee for a partial (not raising) write: nothing is deleted."""
    client = RecordingWeaviateClient()
    old = chunk_object("acme", "concept/a.md", "old")
    _seed(client, old)
    client.upsert_written_override = 0  # the transport confirms nothing
    service = SyncService(store=corpus_store(client))
    with pytest.raises(PartialWriteError, match="partial write"):
        service.sync_source(
            project_id="acme", source_file="concept/a.md", source_type="concept",
            objects=[chunk_object("acme", "concept/a.md", "new")],
            corpus_revision="rev",
        )
    assert old.uuid in client.objects
    assert client.receipts == {}


def test_n46_the_receipt_is_published_after_every_required_delete() -> None:
    """AC6 receipt-last: freshness must not advance before the delete happened."""
    client = RecordingWeaviateClient()
    store = corpus_store(client)
    order: list[str] = []

    def _note_delete(collection: str) -> None:
        if collection == STORY_CONTEXT_COLLECTION:
            order.append("delete")

    def _note_receipt(collection: str, _uuid: str) -> None:
        if collection == RECEIPT_COLLECTION:
            order.append("receipt")

    client.before_delete = _note_delete
    client.after_insert = _note_receipt
    _seed(client, chunk_object("acme", "concept/a.md", "old"))
    SyncService(store=store).sync_source(
        project_id="acme", source_file="concept/a.md", source_type="concept",
        objects=[chunk_object("acme", "concept/a.md", "new")], corpus_revision="rev",
    )
    assert "delete" in order and "receipt" in order
    assert order.index("delete") < order.index("receipt"), (
        "every required destructive step precedes the completion"
    )


def test_n46_a_failing_final_delete_publishes_no_completion() -> None:
    """If the required delete cannot be confirmed, freshness must not advance."""
    client = RecordingWeaviateClient()
    _seed(client, chunk_object("acme", "concept/a.md", "old"))
    client.delete_confirmed_override = 0  # the store confirms nothing
    service = SyncService(store=corpus_store(client))
    with pytest.raises(ClaimSupersededError, match="not older than this claim"):
        service.sync_source(
            project_id="acme", source_file="concept/a.md", source_type="concept",
            objects=[chunk_object("acme", "concept/a.md", "new")],
            corpus_revision="rev",
        )
    assert client.receipts == {}, "no completion after a failed required delete"


def test_n47_an_unusable_generation_stops_the_run_before_any_write() -> None:
    """Prevalidation: a row nobody may touch aborts while the corpus is untouched."""
    client = RecordingWeaviateClient()
    broken = chunk_object("acme", "concept/a.md", "broken")
    _seed(client, broken, owning_generation=None)
    client.objects[broken.uuid][OWNING_GENERATION_PROPERTY] = 0
    service = SyncService(store=corpus_store(client))
    with pytest.raises(SyncError, match="unusable writing generation"):
        service.sync_source(
            project_id="acme", source_file="concept/a.md", source_type="concept",
            objects=[chunk_object("acme", "concept/a.md", "new")],
            corpus_revision="rev",
        )
    assert client.upsert_calls == [], "nothing was written"
    assert broken.uuid in client.objects
    assert client.receipts == {}


# --------------------------------------------------------------------------- #
# N49: the vanished path validates the COMPLETE row set before the first delete
# --------------------------------------------------------------------------- #


def test_n49_a_vanished_source_validates_before_it_deletes_anything() -> None:
    """A legacy row must still be there when an unusable one aborts the run."""
    client = RecordingWeaviateClient()
    legacy = chunk_object("acme", "concept/gone.md", "legacy")
    broken = chunk_object("acme", "concept/gone.md", "broken")
    _seed(client, legacy, owning_generation=None)
    _seed(client, broken, owning_generation=None)
    client.objects[broken.uuid][OWNING_GENERATION_PROPERTY] = -1
    service = SyncService(store=corpus_store(client))
    with pytest.raises(SyncError, match="unusable writing generation"):
        service.reconcile_sources(
            project_id="acme", producer="concept_sync",
            objects_by_source={}, corpus_revision="rev",
        )
    assert legacy.uuid in client.objects, "nothing is deleted before validation"
    assert broken.uuid in client.objects


def test_n49_the_vanished_path_records_its_backfill() -> None:
    """A vanished-source run that repaired legacy rows reports it (N49)."""
    client = RecordingWeaviateClient()
    _seed(client, chunk_object("acme", "concept/gone.md", "legacy"), owning_generation=None)
    _seed(client, chunk_object("acme", "concept/gone.md", "stamped"))
    service = SyncService(store=corpus_store(client))
    results = service.reconcile_sources(
        project_id="acme", producer="concept_sync",
        objects_by_source={}, corpus_revision="rev",
    )
    assert client.objects == {}
    assert sum(r.deleted for r in results) == 2
    assert sum(r.backfilled for r in results) == 1


# --------------------------------------------------------------------------- #
# N50: the release marker is validated in FULL, not just by its uuid
# --------------------------------------------------------------------------- #


def test_n50_a_malformed_duplicate_marker_does_not_count_as_released() -> None:
    """A row at the marker's uuid that is not a RELEASED marker is not a release."""
    client = RecordingWeaviateClient()
    store = corpus_store(client)
    claim = store.try_claim_source(
        project_id="acme", source_file="concept/a.md", owner_id="w"
    )
    assert claim is not None
    # A malformed duplicate occupies the marker uuid: the insert then reports "not
    # created", and accepting it would report a successful release for a HELD source.
    client.claims[
        WeaviateCorpusStore._release_uuid("acme", "concept/a.md", claim.generation)  # noqa: SLF001
    ] = {
        "project_id": "acme",
        "source_file": "concept/a.md",
        "state": "claimed",  # NOT a release marker
        "owner_id": "w",
        "generation": str(claim.generation),
        "claimed_at": utc_now(),
        "reclaimed_from": "",
        "reclaim_reason": "",
    }
    with pytest.raises(ClaimReleaseFailedError, match="neither created nor holds"):
        store.release_source(claim=claim)


@pytest.mark.parametrize(
    "override",
    [
        pytest.param({"project_id": "other"}, id="foreign-project"),
        pytest.param({"source_file": "concept/other.md"}, id="foreign-source"),
        pytest.param({"owner_id": "someone-else"}, id="foreign-owner"),
        pytest.param({"generation": "99"}, id="wrong-generation"),
    ],
)
def test_n50_a_marker_that_does_not_match_the_claim_is_not_a_release(
    override: dict[str, str],
) -> None:
    """Project, source, owner AND generation are all part of the proof."""
    client = RecordingWeaviateClient()
    store = corpus_store(client)
    claim = store.try_claim_source(
        project_id="acme", source_file="concept/a.md", owner_id="w"
    )
    assert claim is not None
    record = {
        "project_id": "acme",
        "source_file": "concept/a.md",
        "state": "released",
        "owner_id": "w",
        "generation": str(claim.generation),
        "claimed_at": utc_now(),
        "reclaimed_from": "",
        "reclaim_reason": "",
    }
    record.update(override)
    client.claims[
        WeaviateCorpusStore._release_uuid("acme", "concept/a.md", claim.generation)  # noqa: SLF001
    ] = record
    with pytest.raises(ClaimReleaseFailedError, match="neither created nor holds"):
        store.release_source(claim=claim)


def test_n50_a_complete_matching_marker_is_an_idempotent_release() -> None:
    """The legitimate case still passes: releasing twice is not a fault."""
    client = RecordingWeaviateClient()
    store = corpus_store(client)
    claim = store.try_claim_source(
        project_id="acme", source_file="concept/a.md", owner_id="w"
    )
    assert claim is not None
    store.release_source(claim=claim)
    store.release_source(claim=claim)  # no raise


# --------------------------------------------------------------------------- #
# Transport-call audit, enforced structurally (N44/N48 lesson)
# --------------------------------------------------------------------------- #


def test_every_storycontext_delete_is_conditional_and_scoped() -> None:
    """No StoryContext row may be deleted through an UNCONDITIONAL, unscoped call.

    Two findings in a row (N44 counters, N48 project isolation) were new code paths that
    did not inherit an established obligation. This pins the rule structurally: the
    corpus store's only StoryContext deletes are the two conditional, project- and
    source-scoped ones; the unconditional ``delete_by_ids`` is reserved for the
    auxiliary claim/receipt collections, whose ids fold in project and source.
    """
    import ast
    import inspect
    import textwrap

    from agentkit.backend.vectordb import engine

    source = inspect.getsource(engine.WeaviateCorpusStore)
    tree = ast.parse(textwrap.dedent(source))

    # Spellings that denote the corpus collection. A future path must not reach the
    # unconditional delete through ANY of them -- the previous string scan only saw
    # `self.collection` and a `collection=STORY_CONTEXT_COLLECTION` call would have
    # evaded it (P2-13).
    corpus_spellings = {"collection", "STORY_CONTEXT_COLLECTION", "STORY_CONTEXT"}

    def _denotes_corpus(node: ast.expr) -> bool:
        if isinstance(node, ast.Attribute):
            return node.attr in corpus_spellings
        if isinstance(node, ast.Name):
            return node.id in corpus_spellings
        return False

    unconditional = 0
    for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
        target = call.func
        if not isinstance(target, ast.Attribute) or target.attr != "delete_by_ids":
            continue
        unconditional += 1
        for kw in call.keywords:
            if kw.arg == "collection":
                assert not _denotes_corpus(kw.value), (
                    "the unconditional delete_by_ids must never target the corpus "
                    f"collection (line {call.lineno})"
                )
    assert unconditional, "no unconditional delete_by_ids call found -- guard is dead"

    # Both corpus deletes pass the authoritative scope.
    for name in ("delete_by_ids_if_property_below", "delete_by_ids_if_property_absent"):
        scoped = [
            c
            for c in ast.walk(tree)
            if isinstance(c, ast.Call)
            and isinstance(c.func, ast.Attribute)
            and c.func.attr == name
        ]
        assert scoped, name
        for call in scoped:
            passed = {kw.arg for kw in call.keywords if kw.arg is not None}
            assert {"project_id", "source_file"} <= passed, (name, sorted(passed))

