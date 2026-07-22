"""AG3-176 AC3/R4: first-index receipts — real boundary, no vacuum success."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from tests.support.vectordb.project_fixtures import make_fk13_project

from agentkit.backend.vectordb.completion_store import completion_path, load_completion
from agentkit.backend.vectordb.first_index import FirstIndexError, run_first_index
from agentkit.backend.vectordb.indexing_receipt import load_indexing_receipt, receipt_path
from agentkit.backend.vectordb.project_binding import bind_project

if TYPE_CHECKING:
    from pathlib import Path


class _MemStore:
    """Minimal IngestStorePort + raw_client for first-index unit tests."""

    def __init__(self) -> None:
        self._rows: list[dict[str, object]] = []
        self.collections = _Collections(self)

    @property
    def raw_client(self) -> _MemStore:
        return self

    def upsert(
        self,
        *,
        collection: str,
        objects: list[dict[str, object]],
        uuids: list[str] | None = None,
    ) -> int:
        del collection
        for i, obj in enumerate(objects):
            uid = uuids[i] if uuids else str(obj.get("chunk_uuid") or i)
            props = dict(obj)
            props["_uuid"] = uid
            self._rows = [r for r in self._rows if r.get("chunk_uuid") != uid]
            self._rows.append(props)
        return len(objects)

    def delete_by_filter(
        self,
        *,
        collection: str,
        project_id: str,
        source_types: list[str] | None = None,
        source_file: str | None = None,
        generation_id_not: str | None = None,
    ) -> int:
        del collection, source_file
        before = len(self._rows)
        kept: list[dict[str, object]] = []
        for row in self._rows:
            if str(row.get("project_id") or "") != project_id:
                kept.append(row)
                continue
            st = str(row.get("source_type") or "")
            if source_types is not None and st not in source_types:
                kept.append(row)
                continue
            if generation_id_not is not None and str(row.get("generation_id") or "") == generation_id_not:
                kept.append(row)
                continue
            continue
        self._rows = kept
        return before - len(kept)

    def fetch(
        self,
        *,
        collection: str,
        project_id: str,
        source_types: list[str] | None = None,
        filters: dict[str, object] | None = None,
    ) -> list[dict[str, object]]:
        del collection, filters
        out = []
        for row in self._rows:
            if str(row.get("project_id") or "") != project_id:
                continue
            if source_types is not None and str(row.get("source_type") or "") not in source_types:
                continue
            out.append(row)
        return out

    def close(self) -> None:
        return


class _Collections:
    def __init__(self, store: _MemStore) -> None:
        self._store = store
        self._exists = False

    def exists(self, name: str) -> bool:
        del name
        return self._exists

    def create(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        self._exists = True


def _patch_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    import agentkit.backend.vectordb.first_index as fi

    monkeypatch.setattr(fi, "ensure_story_context_schema", lambda client: False)


def test_first_index_empty_corpus_success_with_two_zero_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """empty_corpus=true is success with two null-set receipts (AC3) — no except-success."""
    root = make_fk13_project(tmp_path, "P1")
    for p in (root / "concepts").glob("*.md"):
        p.unlink()
    for p in (root / "stories").rglob("*"):
        if p.is_file():
            p.unlink()

    binding = bind_project(root)
    store = _MemStore()
    _patch_schema(monkeypatch)

    # If concept validation blocks empty dirs, skip is NOT success — fail the test
    # only when validation is the reason; empty discovery after valid empty is OK.
    result = run_first_index(binding, store)

    assert result.story_receipt.failed == 0
    assert result.concept_receipt.failed == 0
    assert result.story_receipt.discovered == 0 or result.story_receipt.empty_corpus
    assert result.concept_receipt.discovered == 0 or result.concept_receipt.empty_corpus
    sp = receipt_path(root, binding.project_id, "story_sync")
    cp = receipt_path(root, binding.project_id, "concept_sync")
    assert load_indexing_receipt(sp) is not None
    assert load_indexing_receipt(cp) is not None
    # Completions published only after both
    assert load_completion(root, binding.project_id, "story_sync") is not None
    assert load_completion(root, binding.project_id, "concept_sync") is not None


def test_first_index_with_corpus_produces_typed_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_fk13_project(tmp_path, "P1")
    binding = bind_project(root)
    store = _MemStore()
    _patch_schema(monkeypatch)

    result = run_first_index(binding, store)

    for receipt in (result.story_receipt, result.concept_receipt):
        assert receipt.project_id == "P1"
        assert receipt.producer_tool in {"story_sync", "concept_sync"}
        assert receipt.failed == 0
        assert isinstance(receipt.discovered, int)
        assert isinstance(receipt.upserted, int)
        assert isinstance(receipt.deleted, int)
        assert isinstance(receipt.unchanged, int)
        assert receipt.end_revision or receipt.empty_corpus
    result2 = run_first_index(binding, store)
    assert result2.story_receipt.failed == 0


def test_concept_sync_failure_leaves_story_completion_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R4: concept_sync failure must not advance story freshness (staged)."""
    root = make_fk13_project(tmp_path, "P1")
    binding = bind_project(root)
    store = _MemStore()
    _patch_schema(monkeypatch)

    prev_story = completion_path(root, binding.project_id, "story_sync")
    prev_bytes = prev_story.read_bytes() if prev_story.is_file() else None

    import agentkit.backend.vectordb.first_index as fi
    from agentkit.backend.vectordb.concept_corpus.sync import ConceptSyncBlockedError
    from agentkit.backend.vectordb.ingest.engine import IngestEngine

    real_story = IngestEngine.story_sync

    def story_ok(self, *a, **k):  # type: ignore[no-untyped-def]
        return real_story(self, *a, **k)

    monkeypatch.setattr(IngestEngine, "story_sync", story_ok)

    def boom(*a, **k):  # type: ignore[no-untyped-def]
        del a, k
        validation = MagicMock()
        validation.exit_code = 2
        raise ConceptSyncBlockedError(validation)

    monkeypatch.setattr(fi, "concept_sync_bounded_window", boom)

    with pytest.raises(FirstIndexError) as ei:
        run_first_index(binding, store)
    assert ei.value.reason == "concept_sync_blocked"

    cur = prev_story.read_bytes() if prev_story.is_file() else None
    assert cur == prev_bytes
    # No success receipts
    assert load_indexing_receipt(
        receipt_path(root, binding.project_id, "story_sync")
    ) is None or load_completion(root, binding.project_id, "story_sync") is None


def test_receipt_write_failure_after_story_receipt_rolls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R4: second receipt failure leaves no story success receipt + no completion advance."""
    root = make_fk13_project(tmp_path, "P1")
    binding = bind_project(root)
    store = _MemStore()
    _patch_schema(monkeypatch)

    import agentkit.backend.vectordb.first_index as fi

    calls = {"n": 0}
    real_publish = fi.publish_indexing_receipt

    def flaky(path, receipt):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk full")
        return real_publish(path, receipt)

    monkeypatch.setattr(fi, "publish_indexing_receipt", flaky)

    prev_story = completion_path(root, binding.project_id, "story_sync")
    prev_bytes = prev_story.read_bytes() if prev_story.is_file() else None

    with pytest.raises(FirstIndexError) as ei:
        run_first_index(binding, store)
    assert ei.value.reason == "receipt_publish_failed"

    sp = receipt_path(root, binding.project_id, "story_sync")
    cp = receipt_path(root, binding.project_id, "concept_sync")
    assert not sp.is_file()
    assert not cp.is_file()
    cur = prev_story.read_bytes() if prev_story.is_file() else None
    assert cur == prev_bytes
