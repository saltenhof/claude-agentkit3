"""Doubles at the EXTERNAL Weaviate boundary only (the narrow mock exception).

One shared recording double for the thin-adapter corpus client
(:class:`~agentkit.backend.vectordb.engine.CorpusClientPort`) so every test drives
the REAL production stack above it (``WeaviateCorpusStore``, ``SyncService``,
``WeaviateRetrievalPort``, ``McpToolService``).

Two properties make the double honest rather than convenient:

* the method signatures mirror the real ``_RealWeaviateClient`` exactly, and
  returned hits are validated with the REAL adapter helper
  :func:`_validated_hit_properties`, so the double is never MORE PERMISSIVE than
  the transport it stands in for;
* ``insert_object`` implements Weaviate's object-id uniqueness as a genuinely
  atomic compare-and-create, while ``fetch_by_property`` is NOT atomic -- so a
  read-then-write claim would really lose a race here.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

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
from agentkit.integration_clients.vectordb.weaviate_adapter import (
    _validated_hit_properties,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


@dataclass
class RecordingWeaviateClient:
    """Recording double of the thin Weaviate corpus client.

    Attributes:
        upsert_written_override: When set, the NEXT StoryContext upsert reports
            this count instead of the real one (partial-write probe, R12).
        delete_confirmed_override: When set, the NEXT delete reports this count
            (partial-delete probe, R12).
        crash_after_write: Raise after the next StoryContext upsert (crash probe).
        suppress_source_fetch: Return an EMPTY should-set read (persisted-gap probe).
        insert_barrier: Optional barrier hit inside ``insert_object`` so two
            writers contend for the claim at the same instant (N03 race).
        fetch_barrier: Optional barrier hit on a CLAIM-collection read; a
            read-then-write claim implementation would let both writers pass it.
    """

    objects: dict[str, dict[str, object]] = field(default_factory=dict)
    receipts: dict[str, dict[str, object]] = field(default_factory=dict)
    claims: dict[str, dict[str, object]] = field(default_factory=dict)
    search_calls: list[dict[str, object]] = field(default_factory=list)
    ensure_calls: list[dict[str, object]] = field(default_factory=list)
    search_results: list[tuple[str, dict[str, object], float]] = field(default_factory=list)
    upsert_written_override: int | None = None
    delete_confirmed_override: int | None = None
    crash_after_write: bool = False
    suppress_source_fetch: bool = False
    insert_barrier: threading.Barrier | None = None
    fetch_barrier: threading.Barrier | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # -- reads ------------------------------------------------------------- #
    def fetch_by_property(
        self, *, collection: str, prop: str, value: str, return_props: Sequence[str]
    ) -> Sequence[tuple[str, dict[str, object]]]:
        if collection == CLAIM_COLLECTION and self.fetch_barrier is not None:
            self.fetch_barrier.wait()
        if collection == STORY_CONTEXT_COLLECTION and self.suppress_source_fetch:
            return []
        return self._fetch(collection, lambda p: p.get(prop) == value, return_props)

    def fetch_by_property_any(
        self, *, collection: str, prop: str, values: Sequence[str], return_props: Sequence[str]
    ) -> Sequence[tuple[str, dict[str, object]]]:
        wanted = set(values)
        return self._fetch(collection, lambda p: p.get(prop) in wanted, return_props)

    def _fetch(
        self,
        collection: str,
        predicate: object,
        return_props: Sequence[str],
    ) -> Sequence[tuple[str, dict[str, object]]]:
        store = self._store_for(collection)
        keep = set(return_props)
        with self._lock:
            rows = list(store.items())
        return [
            (uid, {k: v for k, v in props.items() if k != "uuid" and k in keep})
            for uid, props in rows
            if predicate(props)  # type: ignore[operator]
        ]

    def _store_for(self, collection: str) -> dict[str, dict[str, object]]:
        if collection == RECEIPT_COLLECTION:
            return self.receipts
        if collection == CLAIM_COLLECTION:
            return self.claims
        return self.objects

    # -- search (the REAL retrieval path) ---------------------------------- #
    def search_objects(
        self,
        *,
        collection: str,
        query: str,
        search_mode: str,
        project_id: str,
        source_type: str,
        filters: Mapping[str, object],
        limit: int,
        property_spec: Sequence[tuple[str, str, bool]],
    ) -> Sequence[tuple[str, dict[str, object], float]]:
        self.search_calls.append(
            {
                "collection": collection,
                "query": query,
                "search_mode": search_mode,
                "project_id": project_id,
                "source_type": source_type,
                "filters": dict(filters),
                "limit": limit,
                "property_spec": tuple(property_spec),
            }
        )
        # The real query filters server-side on project_id AND source_type.
        results = [
            r
            for r in self.search_results
            if r[1].get("source_type") == source_type
            and r[1].get("project_id") == project_id
        ]
        # Hold the double to the SAME strictness as the real transport (N11).
        for uid, props, _score in results:
            _validated_hit_properties(uid, props, property_spec)
        return results[:limit]

    # -- mutations --------------------------------------------------------- #
    def upsert(self, *, collection: str, objects: Sequence[Mapping[str, object]]) -> int:
        store = self._store_for(collection)
        written = 0
        with self._lock:
            for obj in objects:
                uid = str(obj.get("uuid", ""))
                if not uid:
                    continue
                store[uid] = dict(obj)
                written += 1
        if collection == STORY_CONTEXT_COLLECTION and self.crash_after_write:
            self.crash_after_write = False
            raise RuntimeError("simulated crash after write")
        if collection == STORY_CONTEXT_COLLECTION and self.upsert_written_override is not None:
            override = self.upsert_written_override
            self.upsert_written_override = None
            return override
        return written

    def insert_object(
        self, *, collection: str, uuid: str, properties: Mapping[str, object]
    ) -> bool:
        # The barrier is used TWICE when set: once so both writers arrive at the
        # conditional create together, once so neither proceeds (and the winner
        # cannot release its claim) before both have decided. That makes the race
        # deterministic without weakening it.
        if self.insert_barrier is not None:
            self.insert_barrier.wait()
        store = self._store_for(collection)
        with self._lock:
            won = uuid not in store
            if won:
                store[uuid] = dict(properties)
        if self.insert_barrier is not None:
            self.insert_barrier.wait()
        return won

    def delete_by_ids(self, *, collection: str, uuids: Sequence[str]) -> int:
        if self.delete_confirmed_override is not None:
            override = self.delete_confirmed_override
            self.delete_confirmed_override = None
            return override
        store = self._store_for(collection)
        deleted = 0
        with self._lock:
            for uid in uuids:
                if str(uid) in store:
                    del store[str(uid)]
                    deleted += 1
        return deleted

    def ensure_collection(
        self,
        *,
        collection: str,
        property_specs: Sequence[Mapping[str, object]],
        vectorizer: str = "self_provided",
    ) -> None:
        self.ensure_calls.append(
            {
                "collection": collection,
                "vectorizer": vectorizer,
                "properties": tuple(str(s["name"]) for s in property_specs),
            }
        )


def corpus_store(client: RecordingWeaviateClient | None = None) -> WeaviateCorpusStore:
    """Build the REAL production store over the recording client double."""
    return WeaviateCorpusStore(client=client or RecordingWeaviateClient())


def chunk_object(
    project_id: str,
    source_file: str,
    chunk_id: str,
    source_type: str = "concept",
) -> StoryContextObject:
    """Build a schema-valid object with the deterministic identity (N13)."""
    props: dict[str, object] = {
        "content": f"content-{chunk_id}",
        "source_type": source_type,
        "source_file": source_file,
        "project_id": project_id,
        "content_hash": f"hash-{chunk_id}",
        "section_heading": "h",
        "section_number": "1",
    }
    return StoryContextObject(
        uuid=deterministic_uuid(project_id, source_file, chunk_id),
        chunk_id=chunk_id,
        properties=props,
    )


def concept_hit(
    uuid: str,
    concept_id: str,
    score: float,
    *,
    project_id: str = "acme",
    source_file: str = "technical-design/13_retrieval.md",
    section_heading: str = "Purpose",
    section_number: str = "1",
    module: str = "vectordb",
    is_appendix: bool = False,
    concept_status: str = "active",
) -> tuple[str, dict[str, object], float]:
    """Build a COMPLETE concept hit (every profile property present + typed)."""
    return (
        uuid,
        {
            "content": f"body of {concept_id}",
            "title": f"title {concept_id}",
            "module": module,
            "source_type": "concept",
            "source_file": source_file,
            "section_heading": section_heading,
            "section_number": section_number,
            "content_hash": f"hash-{uuid}",
            "project_id": project_id,
            "concept_id": concept_id,
            "is_appendix": is_appendix,
            "parent_concept_id": "",
            "defers_to": [],
            "authority_over": [],
            "normative_rules": "",
            "concept_status": concept_status,
        },
        score,
    )


def story_hit(
    uuid: str,
    story_id: str,
    score: float,
    *,
    source_type: str = "story",
    project_id: str = "acme",
    source_file: str | None = None,
    status: str = "Done",
    story_type: str = "implementation",
) -> tuple[str, dict[str, object], float]:
    """Build a COMPLETE story/research hit (every profile property present)."""
    rel = source_file if source_file is not None else f"stories/{story_id}/story.md"
    return (
        uuid,
        {
            "content": f"body of {story_id}",
            "story_id": story_id,
            "title": f"title {story_id}",
            "status": status,
            "story_type": story_type,
            "source_type": source_type,
            "source_file": rel,
            "section_heading": "Problem",
            "section_number": "1",
            "content_hash": f"hash-{uuid}",
            "project_id": project_id,
        },
        score,
    )


__all__ = [
    "RecordingWeaviateClient",
    "chunk_object",
    "concept_hit",
    "corpus_store",
    "story_hit",
]
