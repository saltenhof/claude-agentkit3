"""Integration gate: full non-MCP pipeline against a FAKE at the Weaviate port.

Proves the integration BEFORE the MCP layer is layered on (impl-plan gate).
Pipeline: discover -> validate -> build -> ingest-adapter -> bounded-window sync
-> authority-ranked search, with project isolation and producer/delete closure.

The fake implements BOTH the corpus-store port (sync) and retrieval (search);
it lives ONLY at the external Weaviate boundary (the narrow mock exception).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from textwrap import dedent
from typing import TYPE_CHECKING

from agentkit.backend.vectordb.concept_corpus.builder import build_artifacts
from agentkit.backend.vectordb.concept_corpus.graph import build_graph
from agentkit.backend.vectordb.concept_corpus.resolver import rank_hits
from agentkit.backend.vectordb.concept_corpus.validator import validate_corpus
from agentkit.backend.vectordb.ingest.adapter import concept_chunks_to_objects
from agentkit.backend.vectordb.sync import SyncReceipt, SyncService
from agentkit.concepts.parser import discover_concept_files

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from agentkit.backend.vectordb.schema import StoryContextObject


@dataclass
class IndexingFakeStore:
    """Fake at the external boundary: stores objects + supports retrieval."""

    objects: dict[str, dict[str, object]] = field(default_factory=dict)
    receipts: dict[str, SyncReceipt] = field(default_factory=dict)
    _claims: set[tuple[str, str]] = field(default_factory=set)

    def try_claim_source(self, *, project_id: str, source_file: str) -> bool:
        key = (project_id, source_file)
        if key in self._claims:
            return False
        self._claims.add(key)
        return True

    def release_source(self, *, project_id: str, source_file: str) -> None:
        self._claims.discard((project_id, source_file))

    # -- CorpusStorePort --
    def list_objects_for_source(self, *, project_id: str, source_file: str) -> Sequence[Mapping[str, object]]:
        return [
            {"uuid": uid, "source_file": o["source_file"], "source_type": o["source_type"],
             "project_id": o["project_id"]}
            for uid, o in self.objects.items()
            if o["project_id"] == project_id and o["source_file"] == source_file
        ]

    def list_objects_for_source_types(self, *, project_id: str, source_types: Sequence[str]) -> Sequence[Mapping[str, object]]:
        types = set(source_types)
        return [
            {"uuid": uid, **{k: v for k, v in o.items() if k != "uuid"}}
            for uid, o in self.objects.items()
            if o["project_id"] == project_id and o["source_type"] in types
        ]

    def upsert_objects(self, *, objects: Sequence[StoryContextObject]) -> int:
        for obj in objects:
            self.objects[obj.uuid] = {**obj.properties, "uuid": obj.uuid}
        return len(objects)

    def delete_objects(self, *, uuids: Sequence[str]) -> int:
        n = 0
        for uid in uuids:
            if uid in self.objects:
                del self.objects[uid]
                n += 1
        return n

    def get_receipt(self, *, project_id: str, source_file: str) -> SyncReceipt | None:
        return self.receipts.get(f"{project_id}|{source_file}")

    def set_receipt(self, *, receipt: SyncReceipt) -> None:
        self.receipts[f"{receipt.project_id}|{receipt.source_file}"] = receipt

    # -- retrieval (simulated Weaviate search over indexed objects) --
    def query(self, *, project_id: str, source_type: str, limit: int = 10) -> list[Mapping[str, object]]:
        out = [
            {**o, "score": 0.8}
            for o in self.objects.values()
            if o["project_id"] == project_id and o["source_type"] == source_type
        ]
        return out[:limit]


CONCEPT_DOC = dedent(
    """\
    ---
    concept_id: FK-13
    title: Retrieval
    module: vectordb
    status: active
    doc_kind: core
    authority_over:
      - scope: vectordb
    ---

    # 13 Retrieval

    ## Purpose

    Semantic search over stories and concepts.
    """
)


def _corpus(tmp_path: Path) -> Path:
    root = tmp_path / "concept" / "technical-design"
    root.mkdir(parents=True)
    (root / "13_retrieval.md").write_text(CONCEPT_DOC, encoding="utf-8")
    return tmp_path / "concept"


def test_full_pipeline_discover_validate_build_sync_search(tmp_path: Path) -> None:
    root = _corpus(tmp_path)
    # (1) discover (SSOT)
    discovery = discover_concept_files(root)
    assert discovery.documents
    # (2) validate (no errors -> sync precondition met)
    report = validate_corpus(discovery)
    assert not report.has_errors
    # (3) build artifacts (shared revision)
    arts = build_artifacts(discovery)
    assert arts.corpus_revision == discovery.corpus_revision
    # (4) ingest adapter -> StoryContext objects
    objects = concept_chunks_to_objects("acme", discovery)
    assert objects
    # group by source_file for sync
    by_source: dict[str, list[StoryContextObject]] = {}
    for obj in objects:
        by_source.setdefault(obj.properties["source_file"], []).append(obj)
    # (5) bounded-window sync (bounded window -> receipt)
    store = IndexingFakeStore()
    service = SyncService(store=store)
    results = service.full_reindex(
        project_id="acme", producer="concept_sync",
        objects_by_source=by_source, corpus_revision=arts.corpus_revision,
    )
    assert results
    assert all(r.corpus_revision == arts.corpus_revision for r in results)
    # (6) authority-ranked search returns concept chunks only
    graph = build_graph(discovery)
    hits = store.query(project_id="acme", source_type="concept")
    assert hits
    ranked = rank_hits(graph, hits, query_module="vectordb")
    assert ranked
    assert all("concept_id" in h for h in hits)


def test_pipeline_project_isolation(tmp_path: Path) -> None:
    root = _corpus(tmp_path)
    discovery = discover_concept_files(root)
    objects = concept_chunks_to_objects("acme", discovery)
    store = IndexingFakeStore()
    service = SyncService(store=store)
    by_source: dict[str, list[StoryContextObject]] = {}
    for obj in objects:
        by_source.setdefault(obj.properties["source_file"], []).append(obj)
    service.full_reindex(
        project_id="acme", producer="concept_sync",
        objects_by_source=by_source, corpus_revision=discovery.corpus_revision,
    )
    # Querying a different project returns nothing.
    assert store.query(project_id="other", source_type="concept") == []


def test_pipeline_producer_closure_story_does_not_touch_concept(tmp_path: Path) -> None:
    root = _corpus(tmp_path)
    discovery = discover_concept_files(root)
    concept_objects = concept_chunks_to_objects("acme", discovery)
    store = IndexingFakeStore()
    service = SyncService(store=store)
    # Index concepts first.
    by_source: dict[str, list[StoryContextObject]] = {}
    for obj in concept_objects:
        by_source.setdefault(obj.properties["source_file"], []).append(obj)
    service.full_reindex(
        project_id="acme", producer="concept_sync",
        objects_by_source=by_source, corpus_revision=discovery.corpus_revision,
    )
    concept_count = len([o for o in store.objects.values() if o["source_type"] == "concept"])
    # A story_sync full_reindex with empty story sources must not delete concepts.
    service.full_reindex(
        project_id="acme", producer="story_sync",
        objects_by_source={}, corpus_revision=discovery.corpus_revision,
    )
    after = len([o for o in store.objects.values() if o["source_type"] == "concept"])
    assert after == concept_count
