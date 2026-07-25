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
from agentkit.backend.vectordb.schema import OWNING_GENERATION_PROPERTY
from agentkit.backend.vectordb.sync import (
    ClaimSupersededError,
    SourceClaim,
    SyncReceipt,
    SyncService,
    utc_now,
)
from agentkit.concepts.parser import discover_concept_files

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from agentkit.backend.vectordb.schema import StoryContextObject


@dataclass
class IndexingFakeStore:
    """Fake at the external boundary: stores objects + supports retrieval.

    Implements the FULL :class:`CorpusStorePort`, including the fenced source claim
    and the PERSISTENT monotonic source generation (N15/N37) plus the atomic
    completion position (N16).
    """

    objects: dict[str, dict[str, object]] = field(default_factory=dict)
    receipts: dict[str, SyncReceipt] = field(default_factory=dict)
    _claims: dict[tuple[str, str], SourceClaim] = field(default_factory=dict)
    #: Highest generation EVER allocated per source -- survives a release (N37).
    _generations: dict[tuple[str, str], int] = field(default_factory=dict)
    _sequence: int = 0

    def try_claim_source(
        self, *, project_id: str, source_file: str, owner_id: str
    ) -> SourceClaim | None:
        key = (project_id, source_file)
        if key in self._claims:
            return None  # N27: never a time-based takeover
        return self._allocate(key, owner_id=owner_id, reclaimed_from="")

    def reclaim_source(
        self, *, project_id: str, source_file: str, owner_id: str, reason: str
    ) -> SourceClaim:
        del reason
        key = (project_id, source_file)
        previous = self._claims.get(key)
        return self._allocate(
            key,
            owner_id=owner_id,
            reclaimed_from=previous.owner_id if previous else "",
        )

    def _allocate(
        self, key: tuple[str, str], *, owner_id: str, reclaimed_from: str
    ) -> SourceClaim:
        """Allocate the NEXT generation of a source; the ladder never resets (N37)."""
        generation = self._generations.get(key, 0) + 1
        self._generations[key] = generation
        claim = SourceClaim(
            project_id=key[0],
            source_file=key[1],
            owner_id=owner_id,
            generation=generation,
            claimed_at=utc_now(),
            reclaimed_from=reclaimed_from,
        )
        self._claims[key] = claim
        return claim

    def assert_claim_held(self, *, claim: SourceClaim) -> None:
        held = self._claims.get((claim.project_id, claim.source_file))
        if held != claim:
            raise ClaimSupersededError(f"claim {claim!r} superseded by {held!r}")

    def release_source(self, *, claim: SourceClaim) -> None:
        held = self._claims.get((claim.project_id, claim.source_file))
        if held is not None and held.generation == claim.generation:
            # Only the HOLDER releases; the ladder position stays (N37).
            del self._claims[(claim.project_id, claim.source_file)]

    # -- CorpusStorePort --
    def list_objects_for_source(self, *, project_id: str, source_file: str) -> Sequence[Mapping[str, object]]:
        return [
            {"uuid": uid, "source_file": o["source_file"], "source_type": o["source_type"],
             "project_id": o["project_id"],
             OWNING_GENERATION_PROPERTY: o.get(OWNING_GENERATION_PROPERTY)}
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

    def upsert_objects(
        self, *, objects: Sequence[StoryContextObject], owning_generation: int
    ) -> int:
        """Write objects stamped with the writing source generation (N37)."""
        if owning_generation < 1:
            raise AssertionError("an object version must never be written unstamped")
        for obj in objects:
            self.objects[obj.uuid] = {
                **obj.properties,
                "uuid": obj.uuid,
                OWNING_GENERATION_PROPERTY: owning_generation,
            }
        return len(objects)

    def delete_objects_older_than(
        self, *, uuids: Sequence[str], owning_generation: int
    ) -> int:
        """Delete ONLY objects written by a strictly OLDER generation (N37)."""
        if owning_generation < 1:
            raise AssertionError("a delete must be ordered against a generation")
        n = 0
        for uid in uuids:
            props = self.objects.get(uid)
            written = props.get(OWNING_GENERATION_PROPERTY) if props else None
            if not isinstance(written, int) or written >= owning_generation:
                continue
            del self.objects[uid]
            n += 1
        return n

    def delete_objects_without_generation(self, *, uuids: Sequence[str]) -> int:
        """Delete ONLY rows that carry no writing generation at all (N43)."""
        n = 0
        for uid in uuids:
            props = self.objects.get(uid)
            if props is None or props.get(OWNING_GENERATION_PROPERTY) is not None:
                continue
            del self.objects[uid]
            n += 1
        return n

    def get_receipt(self, *, project_id: str, source_file: str) -> SyncReceipt | None:
        return self.receipts.get(f"{project_id}|{source_file}")

    def list_receipts(self, *, project_id: str) -> list[SyncReceipt]:
        return [r for r in self.receipts.values() if r.project_id == project_id]

    def set_receipt(self, *, receipt: SyncReceipt) -> SyncReceipt:
        self._sequence += 1
        sealed = receipt.stamped(sequence=self._sequence)
        self.receipts[f"{sealed.project_id}|{sealed.source_file}"] = sealed
        return sealed

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
