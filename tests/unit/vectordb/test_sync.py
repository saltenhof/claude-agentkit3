"""Bounded-window sync tests (FK-13 §13.9.9, Review 174-P1-1, AC6, D3).

Fakes live ONLY at the CorpusStorePort (the external Weaviate boundary). The
bounded-window ordering, the digest-bound receipt, crash/retry reconciliation,
concurrent-reject (D3) and full_reindex source-type isolation run for real.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.vectordb.schema import StoryContextObject, deterministic_uuid
from agentkit.backend.vectordb.sync import (
    ConcurrentSyncRejectedError,
    ReceiptState,
    SyncReceipt,
    SyncService,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


@dataclass
class FakeCorpusStore:
    """In-memory CorpusStorePort double (the only permitted fake location)."""

    objects: dict[str, dict[str, object]] = field(default_factory=dict)
    receipts: dict[str, SyncReceipt] = field(default_factory=dict)
    crash_after_write: bool = False
    delete_calls: list[list[str]] = field(default_factory=list)

    def list_objects_for_source(
        self, *, project_id: str, source_file: str
    ) -> Sequence[Mapping[str, object]]:
        return [
            {"uuid": uid, "source_file": o["source_file"], "source_type": o["source_type"],
             "project_id": o["project_id"], "content_hash": o.get("content_hash", "")}
            for uid, o in self.objects.items()
            if o["project_id"] == project_id and o["source_file"] == source_file
        ]

    def list_objects_for_source_types(
        self, *, project_id: str, source_types: Sequence[str]
    ) -> Sequence[Mapping[str, object]]:
        types = set(source_types)
        return [
            {"uuid": uid, "source_file": o["source_file"], "source_type": o["source_type"],
             "project_id": o["project_id"]}
            for uid, o in self.objects.items()
            if o["project_id"] == project_id and o["source_type"] in types
        ]

    def upsert_objects(self, *, objects: Sequence[StoryContextObject]) -> int:
        written = 0
        for obj in objects:
            props = dict(obj.properties)
            props["uuid"] = obj.uuid
            self.objects[obj.uuid] = props
            written += 1
        if self.crash_after_write:
            self.crash_after_write = False
            raise RuntimeError("simulated crash after write")
        return written

    def delete_objects(self, *, uuids: Sequence[str]) -> int:
        self.delete_calls.append(list(uuids))
        deleted = 0
        for uid in uuids:
            if uid in self.objects:
                del self.objects[uid]
                deleted += 1
        return deleted

    def get_receipt(self, *, project_id: str, source_file: str) -> SyncReceipt | None:
        return self.receipts.get(f"{project_id}|{source_file}")

    def set_receipt(self, *, receipt: SyncReceipt) -> None:
        self.receipts[f"{receipt.project_id}|{receipt.source_file}"] = receipt


def _obj(
    project_id: str, source_file: str, chunk_id: str, *, source_type: str = "concept"
) -> StoryContextObject:
    props = {
        "content": f"content-{chunk_id}",
        "source_type": source_type,
        "source_file": source_file,
        "project_id": project_id,
        "content_hash": f"hash-{chunk_id}",
        "section_heading": "h",
        "concept_id": "FK-1",
    }
    return StoryContextObject(uuid=deterministic_uuid(project_id, source_file, chunk_id), properties=props)


# --------------------------------------------------------------------------- #
# Bounded-window ordering
# --------------------------------------------------------------------------- #


def test_sync_writes_new_then_deletes_old_then_receipt() -> None:
    store = FakeCorpusStore()
    # Seed an OLD object for the source.
    old = _obj("acme", "concept/a.md", "old")
    store.objects[old.uuid] = {**old.properties, "uuid": old.uuid}
    service = SyncService(store=store)

    new = _obj("acme", "concept/a.md", "new")
    result = service.sync_source(
        project_id="acme", source_file="concept/a.md", source_type="concept",
        objects=[new], corpus_revision="rev-1",
    )
    # New generation present, old deleted, receipt completed with revision.
    assert new.uuid in store.objects
    assert old.uuid not in store.objects
    assert result.deleted == 1
    assert result.written == 1
    receipt = store.get_receipt(project_id="acme", source_file="concept/a.md")
    assert receipt is not None
    assert receipt.state is ReceiptState.COMPLETED
    assert receipt.corpus_revision == "rev-1"
    assert receipt.digest == result.receipt_digest


def test_idempotent_resync_writes_one_record() -> None:
    store = FakeCorpusStore()
    service = SyncService(store=store)
    obj = _obj("acme", "concept/a.md", "c1")
    r1 = service.sync_source(
        project_id="acme", source_file="concept/a.md", source_type="concept",
        objects=[obj], corpus_revision="rev-1",
    )
    r2 = service.sync_source(
        project_id="acme", source_file="concept/a.md", source_type="concept",
        objects=[obj], corpus_revision="rev-1",
    )
    assert r1.receipt_digest == r2.receipt_digest
    # Exactly one object for the source after two syncs.
    objs = store.list_objects_for_source(project_id="acme", source_file="concept/a.md")
    assert len(objs) == 1


def test_vanished_source_file_is_deleted() -> None:
    store = FakeCorpusStore()
    stale = _obj("acme", "concept/gone.md", "g1")
    store.objects[stale.uuid] = {**stale.properties, "uuid": stale.uuid}
    service = SyncService(store=store)
    service.full_reindex(
        project_id="acme", producer="concept_sync",
        objects_by_source={"concept/a.md": [_obj("acme", "concept/a.md", "a1")]},
        corpus_revision="rev-1",
    )
    assert stale.uuid not in store.objects


# --------------------------------------------------------------------------- #
# Crash / retry reconciliation
# --------------------------------------------------------------------------- #


def test_crash_before_receipt_leaves_marker_then_retry_cleans() -> None:
    store = FakeCorpusStore()
    # Pre-existing completed receipt for an OLD generation.
    old_receipt = SyncReceipt.for_completion("acme", "concept/a.md", "concept", "old-rev")
    store.set_receipt(receipt=old_receipt)
    old = _obj("acme", "concept/a.md", "old")
    store.objects[old.uuid] = {**old.properties, "uuid": old.uuid}
    service = SyncService(store=store)

    store.crash_after_write = True
    new = _obj("acme", "concept/a.md", "new")
    with pytest.raises(RuntimeError, match="crash after write"):
        service.sync_source(
            project_id="acme", source_file="concept/a.md", source_type="concept",
            objects=[new], corpus_revision="new-rev",
        )
    # After crash: the last COMPLETED marker is unchanged (still old-rev), and a
    # transitional state exists (new gen written, old not yet deleted).
    receipt = store.get_receipt(project_id="acme", source_file="concept/a.md")
    assert receipt is not None
    assert receipt.corpus_revision == "old-rev"
    assert new.uuid in store.objects
    assert old.uuid in store.objects  # transitional: both generations visible

    # Retry (a fresh, non-concurrent call) reconciles deterministically.
    store.crash_after_write = False
    result = service.sync_source(
        project_id="acme", source_file="concept/a.md", source_type="concept",
        objects=[new], corpus_revision="new-rev",
    )
    assert old.uuid not in store.objects
    assert new.uuid in store.objects
    assert result.deleted == 1
    receipt = store.get_receipt(project_id="acme", source_file="concept/a.md")
    assert receipt is not None
    assert receipt.corpus_revision == "new-rev"


# --------------------------------------------------------------------------- #
# Concurrent-reject (D3)
# --------------------------------------------------------------------------- #


def test_concurrent_sync_same_source_rejected() -> None:
    store = FakeCorpusStore()
    service = SyncService(store=store)
    # Simulate an in-flight sync by pre-claiming the key.
    service._inflight.add(("acme", "concept/a.md"))
    with pytest.raises(ConcurrentSyncRejectedError, match="concurrent sync"):
        service.sync_source(
            project_id="acme", source_file="concept/a.md", source_type="concept",
            objects=[_obj("acme", "concept/a.md", "c1")], corpus_revision="rev",
        )


# --------------------------------------------------------------------------- #
# full_reindex source-type isolation (both orders)
# --------------------------------------------------------------------------- #


def test_full_reindex_story_does_not_touch_concept_and_vice_versa() -> None:
    store = FakeCorpusStore()
    concept_obj = _obj("acme", "concept/c.md", "c1", source_type="concept")
    story_obj = _obj("acme", "stories/x/story.md", "s1", source_type="story")
    store.objects[concept_obj.uuid] = {**concept_obj.properties, "uuid": concept_obj.uuid}
    store.objects[story_obj.uuid] = {**story_obj.properties, "uuid": story_obj.uuid}
    service = SyncService(store=store)

    # story_sync full_reindex -- must NOT delete the concept chunk.
    service.full_reindex(
        project_id="acme", producer="story_sync",
        objects_by_source={"stories/x/story.md": [story_obj]}, corpus_revision="rev",
    )
    assert concept_obj.uuid in store.objects
    assert story_obj.uuid in store.objects

    # concept_sync full_reindex -- must NOT delete the story chunk.
    service.full_reindex(
        project_id="acme", producer="concept_sync",
        objects_by_source={"concept/c.md": [concept_obj]}, corpus_revision="rev",
    )
    assert concept_obj.uuid in store.objects
    assert story_obj.uuid in store.objects


def test_project_isolation_two_projects() -> None:
    store = FakeCorpusStore()
    a = _obj("acme", "concept/a.md", "a1")
    b = _obj("other", "concept/a.md", "a1")  # same source_file, different project
    store.objects[a.uuid] = {**a.properties, "uuid": a.uuid}
    store.objects[b.uuid] = {**b.properties, "uuid": b.uuid}
    service = SyncService(store=store)
    service.sync_source(
        project_id="acme", source_file="concept/a.md", source_type="concept",
        objects=[], corpus_revision="rev",  # empty should-set -> deletes acme's only
    )
    assert a.uuid not in store.objects
    assert b.uuid in store.objects  # other project untouched
