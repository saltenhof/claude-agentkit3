"""Integrationsgate: source/producer/delete closure + project isolation (R04/R12)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from tests.support.vectordb.memory_store import MemoryWeaviateClient
from tests.support.vectordb.project_fixtures import make_fk13_project

from agentkit.backend.concept_catalog.corpus.discovery import discover_concept_files
from agentkit.backend.vectordb.concept_corpus.sync import (
    ConceptSyncBlockedError,
    concept_sync_bounded_window,
)
from agentkit.backend.vectordb.concept_corpus.validate import validate_corpus
from agentkit.backend.vectordb.ingest.engine import IngestEngine, IngestError
from agentkit.backend.vectordb.ingest.source_routing import classify_markdown_path
from agentkit.backend.vectordb.project_binding import bind_project
from agentkit.backend.vectordb.schema import STORY_COLLECTION

if TYPE_CHECKING:
    from pathlib import Path


def test_source_routing_positive_and_negative() -> None:
    assert classify_markdown_path("stories/S-001/story.md").value == "story"
    assert classify_markdown_path("stories/S-001/research/notes.md").value == "research"
    assert classify_markdown_path("stories/S-001/review-1.md") is None


def test_full_reindex_both_orders_preserves_source_classes(tmp_path: Path) -> None:
    root = make_fk13_project(tmp_path, "P1")
    binding = bind_project(root)
    client = MemoryWeaviateClient()
    engine = IngestEngine(client, lock_dir=root / ".locks")

    engine.story_sync(binding, full_reindex=True)
    concept_sync_bounded_window(binding, engine, full_reindex=True)
    rows_a = client.fetch(collection=STORY_COLLECTION, project_id="P1")
    types_a = {str(r.get("source_type")) for r in rows_a}
    assert "story" in types_a and "research" in types_a and "concept" in types_a

    client2 = MemoryWeaviateClient()
    engine2 = IngestEngine(client2, lock_dir=root / ".locks2")
    concept_sync_bounded_window(binding, engine2, full_reindex=True)
    engine2.story_sync(binding, full_reindex=True)
    rows_b = client2.fetch(collection=STORY_COLLECTION, project_id="P1")
    types_b = {str(r.get("source_type")) for r in rows_b}
    assert types_a == types_b
    sources = {str(r.get("source_file")) for r in rows_b}
    assert not any("review" in s for s in sources)


def test_project_isolation(tmp_path: Path) -> None:
    r1 = make_fk13_project(tmp_path, "PA")
    r2 = make_fk13_project(tmp_path, "PB")
    b1 = bind_project(r1)
    b2 = bind_project(r2)
    client = MemoryWeaviateClient()
    engine = IngestEngine(client, lock_dir=tmp_path / ".locks")
    engine.story_sync(b1, full_reindex=True)
    engine.story_sync(b2, full_reindex=True)
    only_a = client.fetch(collection=STORY_COLLECTION, project_id="PA")
    only_b = client.fetch(collection=STORY_COLLECTION, project_id="PB")
    assert only_a and only_b
    assert all(r["project_id"] == "PA" for r in only_a)
    assert all(r["project_id"] == "PB" for r in only_b)


def test_hash_based_incremental_skips_unchanged(tmp_path: Path) -> None:
    root = make_fk13_project(tmp_path, "P1")
    binding = bind_project(root)
    client = MemoryWeaviateClient()
    engine = IngestEngine(client, lock_dir=root / ".locks")
    r1 = engine.story_sync(binding, full_reindex=True)
    assert r1.counters.written >= 1
    r2 = engine.story_sync(binding, full_reindex=False)
    assert r2.counters.skipped >= 1
    assert r2.counters.written == 0


def test_partial_write_does_not_delete_or_receipt(tmp_path: Path) -> None:
    """R04: upsert returning 0 aborts before delete/receipt."""
    root = make_fk13_project(tmp_path, "P1")
    binding = bind_project(root)
    client = MemoryWeaviateClient()
    engine = IngestEngine(client, lock_dir=root / ".locks")
    # Seed a good generation
    concept_sync_bounded_window(binding, engine, full_reindex=True)
    before = client.fetch(collection=STORY_COLLECTION, project_id="P1")
    assert before

    class _Partial:
        def __init__(self, inner: MemoryWeaviateClient) -> None:
            self._inner = inner

        def upsert(self, **kwargs: object) -> int:
            return 0

        def delete_by_filter(self, **kwargs: object) -> int:
            raise AssertionError("delete must not run after partial write")

        def delete_by_ids(self, **kwargs: object) -> int:
            raise AssertionError("delete must not run after partial write")

        def fetch(self, **kwargs: object):  # type: ignore[no-untyped-def]
            return self._inner.fetch(**kwargs)

    bad = IngestEngine(_Partial(client), lock_dir=root / ".locks-b")  # type: ignore[arg-type]
    with pytest.raises(IngestError, match="partial write"):
        bad.concept_sync(binding, full_reindex=True)
    after = client.fetch(collection=STORY_COLLECTION, project_id="P1")
    assert len(after) == len(before)


def test_validate_blocks_sync(tmp_path: Path) -> None:
    root = make_fk13_project(tmp_path, "Pbad")
    (root / "concepts" / "bad.md").write_text("no fm\n", encoding="utf-8")
    binding = bind_project(root)
    engine = IngestEngine(MemoryWeaviateClient(), lock_dir=root / ".locks")
    with pytest.raises(ConceptSyncBlockedError):
        concept_sync_bounded_window(binding, engine, full_reindex=True)


def test_bounded_window_receipt_after_delete(tmp_path: Path) -> None:
    root = make_fk13_project(tmp_path, "P1")
    binding = bind_project(root)
    client = MemoryWeaviateClient()
    engine = IngestEngine(client, lock_dir=root / ".locks")
    result = concept_sync_bounded_window(binding, engine, full_reindex=True)
    assert result.receipt.corpus_revision.startswith("sha256:")
    assert result.receipt_path.is_file()
    assert result.ingest.counters.written >= 1


def test_discovery_set_equal_validate_build_sync(tmp_path: Path) -> None:
    root = make_fk13_project(tmp_path, "P1")
    concepts = root / "concepts"
    d1 = {d.rel_path for d in discover_concept_files(concepts).documents}
    v = validate_corpus(concepts)
    d2 = {d.rel_path for d in v.documents}
    assert d1 == d2


def test_story_list_sources_shape(tmp_path: Path) -> None:
    root = make_fk13_project(tmp_path, "P1")
    binding = bind_project(root)
    client = MemoryWeaviateClient()
    engine = IngestEngine(client, lock_dir=root / ".locks")
    engine.story_sync(binding, full_reindex=True)
    concept_sync_bounded_window(binding, engine, full_reindex=True)
    sources = engine.list_sources(binding)
    assert sources
    for s in sources:
        assert s["project_id"] == "P1"
        assert s["source_type"] in {"story", "research", "concept"}
        assert "producer" in s
        assert "chunk_count" in s
        assert "freshness_status" in s
