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
from typing import TYPE_CHECKING, Final

from agentkit.backend.vectordb.engine import (
    CLAIM_COLLECTION,
    CLAIM_STATE_HELD,
    CLAIM_STATE_RELEASED,
    RECEIPT_COLLECTION,
    WeaviateCorpusStore,
)
from agentkit.backend.vectordb.schema import (
    OWNING_GENERATION_PROPERTY,
    STORY_CONTEXT_COLLECTION,
    StoryContextObject,
    deterministic_uuid,
)
from agentkit.integration_clients.vectordb.errors import VectorDbWriteError
from agentkit.integration_clients.vectordb.weaviate_adapter import (
    _validated_hit_properties,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from datetime import datetime


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
    #: Every upsert call (a completion must NEVER be an upsert, N28).
    upsert_calls: list[str] = field(default_factory=list)
    #: Every claim record ever created, including superseded generations (N27).
    claim_history: list[dict[str, object]] = field(default_factory=list)
    #: Every STORAGE-CONDITIONAL delete (a destructive delete must be one, D9).
    conditional_delete_calls: list[dict[str, object]] = field(default_factory=list)
    #: Probe: the store REJECTS the claim release marker (N45 -- the source stays held).
    fail_release: bool = False
    #: Probe: the store neither creates the release marker nor holds it (N45).
    deny_release_insert: bool = False
    search_results: list[tuple[str, dict[str, object], float]] = field(default_factory=list)
    upsert_written_override: int | None = None
    delete_confirmed_override: int | None = None
    crash_after_write: bool = False
    suppress_source_fetch: bool = False
    insert_barrier: threading.Barrier | None = None
    fetch_barrier: threading.Barrier | None = None
    #: Called with the collection name AFTER an upsert -- the seam a concurrent
    #: writer would act through (used to stage a mid-window claim takeover, N15).
    after_upsert: Callable[[str], None] | None = None
    #: Called with the collection name BEFORE a delete -- the seam a concurrent
    #: administrative reclaim would act through (N27 vanished-delete fence).
    before_delete: Callable[[str], None] | None = None
    #: Called with (collection, uuid) after a successful conditional create -- the
    #: instant a concurrent writer could act on a freshly acquired claim (N27).
    after_insert: Callable[[str, str], None] | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _local: threading.local = field(default_factory=threading.local)

    # -- reads ------------------------------------------------------------- #
    def fetch_by_property(
        self, *, collection: str, prop: str, value: str, return_props: Sequence[str]
    ) -> Sequence[tuple[str, dict[str, object]]]:
        # Synchronise the FIRST claim read of each thread: both a read-then-write
        # claim (which would then race) and the conditional-create claim pass here,
        # so the race is real for either implementation. Later reads (e.g. the
        # fence) must not wait again.
        if (
            collection == CLAIM_COLLECTION
            and self.fetch_barrier is not None
            and not getattr(self._local, "fetch_barrier_used", False)
        ):
            self._local.fetch_barrier_used = True
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

    @staticmethod
    def matches_filters(
        props: Mapping[str, object], filters: Mapping[str, object]
    ) -> bool:
        """Apply the caller filters exactly as the real transport does (D8/N36)."""
        return _matches_filters(props, filters)

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
        # The real query filters server-side on project_id AND source_type AND
        # EVERY caller filter (N36/D8): the double used to ignore the filters, which
        # is how a "draft" query could observe an ACTIVE hit that a real Weaviate
        # filter would have excluded. A set-valued filter is membership, a scalar is
        # equality -- the same semantics the adapter builds.
        results = [
            r
            for r in self.search_results
            if r[1].get("source_type") == source_type
            and r[1].get("project_id") == project_id
            and _matches_filters(r[1], filters)
        ]
        # Hold the double to the SAME strictness as the real transport (N11).
        for uid, props, _score in results:
            _validated_hit_properties(uid, props, property_spec)
        return results[:limit]

    # -- mutations --------------------------------------------------------- #
    def upsert(self, *, collection: str, objects: Sequence[Mapping[str, object]]) -> int:
        self.upsert_calls.append(collection)
        store = self._store_for(collection)
        written = 0
        with self._lock:
            for obj in objects:
                uid = str(obj.get("uuid", ""))
                if not uid:
                    continue
                store[uid] = dict(obj)
                written += 1
        if self.after_upsert is not None:
            self.after_upsert(collection)
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
        # The barrier is used TWICE per THREAD when set: once so both writers arrive
        # at the conditional create together, once so neither proceeds (and the
        # winner cannot release its claim) before both have decided. Only the FIRST
        # conditional create of a thread participates, so a retry (e.g. the next
        # sequence candidate) cannot unbalance the barrier.
        released = collection == CLAIM_COLLECTION and properties.get("state") == (
            CLAIM_STATE_RELEASED
        )
        if released and self.fail_release:
            raise VectorDbWriteError("release marker rejected by the store (probe)")
        if released and self.deny_release_insert:
            # The store neither creates the marker nor already holds it (N45).
            return False
        use_barrier = self.insert_barrier is not None and not getattr(
            self._local, "barrier_used", False
        )
        if use_barrier:
            self._local.barrier_used = True
            assert self.insert_barrier is not None
            self.insert_barrier.wait()
        store = self._store_for(collection)
        with self._lock:
            won = uuid not in store
            if won:
                store[uuid] = dict(properties)
                if collection == CLAIM_COLLECTION:
                    self.claim_history.append(dict(properties))
        if use_barrier:
            assert self.insert_barrier is not None
            self.insert_barrier.wait()
        if won and self.after_insert is not None:
            self.after_insert(collection, uuid)
        return won

    def delete_by_ids(self, *, collection: str, uuids: Sequence[str]) -> int:
        if self.before_delete is not None:
            self.before_delete(collection)
        # The probe is about the CORPUS delete (R12); auxiliary ladder/receipt
        # housekeeping must not consume it.
        if (
            self.delete_confirmed_override is not None
            and collection == STORY_CONTEXT_COLLECTION
        ):
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

    def delete_by_ids_if_property_below(
        self, *, collection: str, uuids: Sequence[str], prop: str, limit: int
    ) -> int:
        """Delete ONLY the ids whose numeric ``prop`` is strictly below ``limit`` (N37).

        Held to the same semantics as ``data.delete_many(where=...)``: the condition
        is evaluated together with the delete, atomically per object, so an object a
        NEWER generation wrote is simply not matched -- in either race order.
        """
        self.conditional_delete_calls.append(
            {"collection": collection, "prop": prop, "limit": limit, "uuids": tuple(uuids)}
        )
        if self.before_delete is not None:
            self.before_delete(collection)
        store = self._store_for(collection)
        deleted = 0
        with self._lock:
            for uid in uuids:
                props = store.get(str(uid))
                if props is None:
                    continue
                value = props.get(prop)
                if isinstance(value, bool) or not isinstance(value, int):
                    continue
                if value >= limit:
                    continue
                del store[str(uid)]
                deleted += 1
        if (
            self.delete_confirmed_override is not None
            and collection == STORY_CONTEXT_COLLECTION
        ):
            # Probe: the store confirms FEWER objects than were requested (R12).
            override, self.delete_confirmed_override = self.delete_confirmed_override, None
            return override
        return deleted

    def delete_by_ids_if_property_absent(
        self, *, collection: str, uuids: Sequence[str], prop: str
    ) -> int:
        """Delete ONLY the ids that carry NO value for ``prop`` at all (N43).

        Same semantics as ``delete_many(where=Filter.by_property(p).is_none(True))``:
        the condition is evaluated together with the delete, so a row written by ANY
        generation is structurally out of reach.
        """
        self.conditional_delete_calls.append(
            {"collection": collection, "prop": prop, "absent": True, "uuids": tuple(uuids)}
        )
        if self.before_delete is not None:
            self.before_delete(collection)
        store = self._store_for(collection)
        deleted = 0
        with self._lock:
            for uid in uuids:
                props = store.get(str(uid))
                if props is None or props.get(prop) is not None:
                    continue
                del store[str(uid)]
                deleted += 1
        if (
            self.delete_confirmed_override is not None
            and collection == STORY_CONTEXT_COLLECTION
        ):
            override, self.delete_confirmed_override = self.delete_confirmed_override, None
            return override
        return deleted

    def ensure_collection(
        self,
        *,
        collection: str,
        property_specs: Sequence[Mapping[str, object]],
        vectorizer: str = "self_provided",
        vectorizer_model: Mapping[str, object] | None = None,
        vector_source_properties: Sequence[str] | None = None,
    ) -> None:
        self.ensure_calls.append(
            {
                "collection": collection,
                "vectorizer": vectorizer,
                "vectorizer_model": dict(vectorizer_model or {}),
                # What the embedding is built FROM is part of the contract (N35).
                "vector_source_properties": (
                    tuple(vector_source_properties)
                    if vector_source_properties is not None
                    else None
                ),
                "properties": tuple(str(s["name"]) for s in property_specs),
            }
        )


#: Source generation a SEEDED object carries, i.e. what a previous, finished
#: generation wrote. Production stamps every write (N37/N38), so seeded fixtures must
#: too -- an unstamped object is a separate, explicitly tested fail-closed case.
PREVIOUS_GENERATION: Final[int] = 1


def seed_object(
    client: RecordingWeaviateClient,
    obj: StoryContextObject,
    *,
    owning_generation: int | None = PREVIOUS_GENERATION,
) -> None:
    """Seed an already-persisted object as a PREVIOUS generation wrote it (N37).

    A persisted object implies a FINISHED generation of its source, so the claim
    ladder is seeded to match: the generation's claim and release markers are written
    too, which is what makes the next acquisition strictly higher. Without that the
    fixture would describe an impossible corpus -- objects from generation N with a
    ladder that has never reached N.
    """
    props: dict[str, object] = {**obj.properties, "uuid": obj.uuid}
    if owning_generation is not None:
        props[OWNING_GENERATION_PROPERTY] = owning_generation
        seed_generation_history(
            client,
            project_id=str(obj.properties["project_id"]),
            source_file=str(obj.properties["source_file"]),
            generation=owning_generation,
        )
    client.objects[obj.uuid] = props


def seed_generation_history(
    client: RecordingWeaviateClient,
    *,
    project_id: str,
    source_file: str,
    generation: int,
    owner_id: str = "previous-owner",
) -> None:
    """Seed the ladder of a source as a FINISHED generation left it (N37)."""
    now = "2026-07-25T00:00:00Z"
    base = {
        "project_id": project_id,
        "source_file": source_file,
        "owner_id": owner_id,
        "generation": str(generation),
        "claimed_at": now,
        "reclaimed_from": "",
        "reclaim_reason": "",
    }
    client.claims[
        WeaviateCorpusStore._claim_uuid(project_id, source_file, generation)  # noqa: SLF001
    ] = {**base, "state": CLAIM_STATE_HELD}
    client.claims[
        WeaviateCorpusStore._release_uuid(project_id, source_file, generation)  # noqa: SLF001
    ] = {**base, "state": CLAIM_STATE_RELEASED}


def _matches_filters(
    props: Mapping[str, object], filters: Mapping[str, object]
) -> bool:
    """Return whether one hit satisfies EVERY caller filter (D8/N36).

    Mirrors :meth:`_RealWeaviateClient.search_objects`: a set-valued filter is a
    membership test (the real adapter emits an OR of equalities), everything else is
    equality. Booleans compare as booleans; other scalars compare as strings, which
    is what the adapter sends over the wire.
    """
    for prop, expected in filters.items():
        actual = props.get(prop)
        if isinstance(expected, (list, tuple, set, frozenset)):
            if str(actual) not in {str(v) for v in expected}:
                return False
        elif isinstance(expected, bool):
            if actual is not expected:
                return False
        elif str(actual) != str(expected):
            return False
    return True


def corpus_store(
    client: RecordingWeaviateClient | None = None,
    *,
    clock: Callable[[], datetime] | None = None,
) -> WeaviateCorpusStore:
    """Build the REAL production store over the recording client double.

    ``clock`` drives the claim/completion TIMESTAMPS deterministically. A claim
    never expires (N27): the timestamp is diagnostic, there is no lease, and only
    an explicit administrative reclaim releases a held claim.
    """
    store = WeaviateCorpusStore(client=client or RecordingWeaviateClient())
    if clock is not None:
        store = WeaviateCorpusStore(client=store.client, clock=clock)
    return store


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
    module: str = "backend",
    epic: str = "retrieval",
) -> tuple[str, dict[str, object], float]:
    """Build a COMPLETE story/research hit (every profile property present).

    ``module``/``epic`` are part of the advertised ``story_search`` response
    (FK-13 §13.4.1), so a realistic hit carries them (N19).
    """
    rel = source_file if source_file is not None else f"stories/{story_id}/story.md"
    return (
        uuid,
        {
            "content": f"body of {story_id}",
            "story_id": story_id,
            "title": f"title {story_id}",
            "status": status,
            "story_type": story_type,
            "module": module,
            "epic": epic,
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
