"""Transport-level proofs against the REAL ``weaviate-client`` API surface.

Scope: R03 (``connect_to_custom`` -- ``connect_to_local`` cannot take a distinct
gRPC host), N02 (near_text ranks by DISTANCE, bm25 must request its score),
N11 (no ``setdefault`` repair default for hit properties), N12 (an existing
collection is verified, not accepted blindly), R12 (``delete_by_id`` returns a
bool) and N03 (conditional create).

The double sits at the deepest possible seam -- the Weaviate ``collections``
facade / the ``connect_*`` factory -- and every faked call is BOUND against the
REAL library signature, so a fake can never be more permissive than the API it
stands in for (that is exactly how R03's production bug stayed hidden).
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
import weaviate
from weaviate.classes.config import DataType, Tokenization
from weaviate.collections.classes.config import (
    Vectorizers,
    _NamedVectorConfig,
    _NamedVectorizerConfig,
    _Property,
    _PropertyVectorizerConfig,
    _VectorizerConfig,
)
from weaviate.collections.data import _DataCollection
from weaviate.collections.queries.bm25.query import _BM25Query
from weaviate.collections.queries.hybrid.query import _HybridQuery
from weaviate.collections.queries.near_text.query import _NearTextQuery

from agentkit.backend.vectordb.engine import (
    WeaviateCorpusStore,
    WeaviateRetrievalPort,
    connect_real_client,
)
from agentkit.backend.vectordb.runtime_binding import RuntimeBinding
from agentkit.backend.vectordb.schema import (
    STORY_CONTEXT_COLLECTION,
    weaviate_property_specs,
)
from agentkit.integration_clients.vectordb.errors import (
    VectorDbUnavailableError,
    VectorDbWriteError,
)
from agentkit.integration_clients.vectordb.weaviate_adapter import (
    _RealWeaviateClient,
    configured_vector_source_properties,
    configured_vectorizer_model,
)

_ENV = {
    "PROJECT_ID": "acme",
    "WEAVIATE_HTTP_ENDPOINT": "http://weaviate.acme.local:8080",
    "WEAVIATE_GRPC_ENDPOINT": "weaviate.acme.local:50051",
}


def _binding() -> RuntimeBinding:
    return RuntimeBinding.from_env(_ENV, command="python", args=(), cwd=".")


# --------------------------------------------------------------------------- #
# Faithful doubles of the Weaviate collection facade
# --------------------------------------------------------------------------- #


def _bind_real(method: Any, kwargs: dict[str, object]) -> None:
    """Assert the call is valid for the REAL library method (fake parity)."""
    inspect.signature(method).bind(None, **kwargs)


class _Meta:
    def __init__(self, **kwargs: float | None) -> None:
        # Only the metadata the response actually carries is set, exactly like
        # Weaviate: asking for 'distance' does NOT populate 'score'.
        self.score: float | None = kwargs.get("score")
        self.distance: float | None = kwargs.get("distance")


class _Obj:
    def __init__(self, uuid: str, properties: dict[str, object], metadata: _Meta) -> None:
        self.uuid = uuid
        self.properties = properties
        self.metadata = metadata


@dataclass
class _Response:
    objects: list[_Obj]


@dataclass
class _FakeQuery:
    response: _Response
    calls: list[dict[str, object]] = field(default_factory=list)

    def hybrid(self, **kwargs: object) -> _Response:
        _bind_real(_HybridQuery.hybrid, kwargs)
        self.calls.append({"kind": "hybrid", **kwargs})
        return self.response

    def bm25(self, **kwargs: object) -> _Response:
        _bind_real(_BM25Query.bm25, kwargs)
        self.calls.append({"kind": "bm25", **kwargs})
        return self.response

    def near_text(self, **kwargs: object) -> _Response:
        _bind_real(_NearTextQuery.near_text, kwargs)
        self.calls.append({"kind": "near_text", **kwargs})
        return self.response


@dataclass
class _FakeData:
    delete_results: dict[str, bool] = field(default_factory=dict)
    delete_raises: set[str] = field(default_factory=set)
    existing_ids: set[str] = field(default_factory=set)
    inserted: list[dict[str, object]] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    #: Every conditional delete production issued (D9): (kwargs incl. the filter).
    delete_many_calls: list[dict[str, object]] = field(default_factory=list)
    #: Queued ``(successful, failed)`` outcomes for consecutive conditional deletes.
    delete_many_results: list[tuple[int, int]] = field(default_factory=list)
    delete_many_raises: bool = False

    def delete_by_id(self, uuid: str) -> bool:
        _bind_real(_DataCollection.delete_by_id, {"uuid": uuid})
        if uuid in self.delete_raises:
            raise RuntimeError("transport error during delete")
        self.deleted.append(uuid)
        return self.delete_results.get(uuid, True)

    def insert(self, **kwargs: object) -> str:
        _bind_real(_DataCollection.insert, kwargs)
        uid = str(kwargs["uuid"])
        if uid in self.existing_ids:
            from weaviate.exceptions import ObjectAlreadyExistsException

            raise ObjectAlreadyExistsException(uid)
        self.existing_ids.add(uid)
        self.inserted.append(dict(kwargs))
        return uid

    def delete_many(self, **kwargs: object) -> object:
        """Record the FILTER production sent and report the configured outcome (D9)."""
        _bind_real(_DataCollection.delete_many, kwargs)
        from weaviate.collections.classes.batch import DeleteManyReturn

        self.delete_many_calls.append(dict(kwargs))
        if self.delete_many_raises:
            raise RuntimeError("transport error during conditional delete")
        outcome = self.delete_many_results.pop(0) if self.delete_many_results else (1, 0)
        successful, failed = outcome
        return DeleteManyReturn(
            failed=failed, matches=successful + failed, objects=None, successful=successful
        )


@dataclass
class _ConfigView:
    """Mirror of the fields production reads from ``_CollectionConfig`` (N12/N30)."""

    properties: list[_Property]
    vectorizer: Vectorizers | None = None
    vector_config: dict[str, _NamedVectorConfig] | None = None
    vectorizer_config: _VectorizerConfig | None = None


@dataclass
class _FakeConfig:
    view: _ConfigView

    def get(self) -> _ConfigView:
        return self.view


@dataclass
class _FakeCollection:
    query: _FakeQuery
    data: _FakeData
    config: _FakeConfig


@dataclass
class _FakeCollections:
    collection: _FakeCollection
    existing: set[str] = field(default_factory=set)
    created: list[dict[str, object]] = field(default_factory=list)
    requested: list[str] = field(default_factory=list)

    def exists(self, name: str) -> bool:
        return name in self.existing

    def get(self, name: str) -> _FakeCollection:
        self.requested.append(name)
        return self.collection

    def create(self, **kwargs: object) -> None:
        self.created.append(kwargs)


@dataclass
class _FakeConnection:
    collections: _FakeCollections


def _collection(
    response: _Response | None = None,
    *,
    data: _FakeData | None = None,
    config: _ConfigView | None = None,
) -> _FakeCollection:
    return _FakeCollection(
        query=_FakeQuery(response or _Response([])),
        data=data or _FakeData(),
        config=_FakeConfig(config or _ConfigView(properties=[])),
    )


def _client(collection: _FakeCollection, *, existing: set[str] | None = None) -> _RealWeaviateClient:
    collections = _FakeCollections(collection=collection, existing=existing or set())
    return _RealWeaviateClient(_FakeConnection(collections))


def _retrieval(client: _RealWeaviateClient) -> WeaviateRetrievalPort:
    store = WeaviateCorpusStore(client=client)  # type: ignore[arg-type]
    return WeaviateRetrievalPort(client=client, store=store, binding=_binding())  # type: ignore[arg-type]


def _concept_props(**overrides: object) -> dict[str, object]:
    props: dict[str, object] = {
        "content": "text",
        "title": "Retrieval",
        "module": "vectordb",
        "source_type": "concept",
        "source_file": "technical-design/13.md",
        "section_heading": "Purpose",
        "section_number": "1",
        "content_hash": "h",
        "project_id": "acme",
        "concept_id": "FK-13",
        "is_appendix": False,
        "parent_concept_id": "",
        "defers_to": [],
        "authority_over": [],
        "normative_rules": "",
        "concept_status": "active",
    }
    props.update(overrides)
    return props


# --------------------------------------------------------------------------- #
# R03: the real connect API
# --------------------------------------------------------------------------- #


def test_r03_connect_to_local_cannot_carry_a_distinct_grpc_host() -> None:
    """The documented root cause: the pinned client has no ``grpc_host`` there."""
    with pytest.raises(TypeError):
        inspect.signature(weaviate.connect_to_local).bind(
            host="weaviate.acme.local", port=8080,
            grpc_host="weaviate.acme.local", grpc_port=50051,
        )
    # ...while connect_to_custom accepts exactly the six values production sends.
    inspect.signature(weaviate.connect_to_custom).bind(
        http_host="weaviate.acme.local", http_port=8080, http_secure=False,
        grpc_host="weaviate.acme.local", grpc_port=50051, grpc_secure=False,
    )


def test_r03_production_connects_via_connect_to_custom(monkeypatch: pytest.MonkeyPatch) -> None:
    """The engine passes BOTH env endpoints through the real connect signature."""
    captured: dict[str, object] = {}
    real_custom = weaviate.connect_to_custom

    def _recording_custom(*args: object, **kwargs: object) -> object:
        inspect.signature(real_custom).bind(*args, **kwargs)  # no extra leniency
        captured.update(kwargs)
        return _FakeConnection(_FakeCollections(collection=_collection()))

    def _forbidden_local(*_a: object, **_k: object) -> object:
        raise AssertionError("production must not fall back to connect_to_local (R03)")

    monkeypatch.setattr(weaviate, "connect_to_custom", _recording_custom)
    monkeypatch.setattr(weaviate, "connect_to_local", _forbidden_local)

    connect_real_client(_binding())

    assert captured == {
        "http_host": "weaviate.acme.local",
        "http_port": 8080,
        "http_secure": False,
        "grpc_host": "weaviate.acme.local",
        "grpc_port": 50051,
        "grpc_secure": False,
    }


def test_r03_tls_endpoints_are_carried_as_secure(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        weaviate,
        "connect_to_custom",
        lambda **kwargs: (captured.update(kwargs), _FakeConnection(_FakeCollections(_collection())))[1],
    )
    binding = RuntimeBinding.from_env(
        {
            "PROJECT_ID": "acme",
            "WEAVIATE_HTTP_ENDPOINT": "https://weaviate.acme.local:443",
            "WEAVIATE_GRPC_ENDPOINT": "grpcs://weaviate.acme.local:50051",
        },
        command="python", args=(), cwd=".",
    )
    connect_real_client(binding)
    assert captured["http_secure"] is True
    assert captured["grpc_secure"] is True


# --------------------------------------------------------------------------- #
# N02: the ranking metric each mode actually yields
# --------------------------------------------------------------------------- #


def test_n02_vector_mode_requests_distance_and_ranks_by_it() -> None:
    near = _Response(
        [
            _Obj("u-far", _concept_props(concept_id="FK-FAR"), _Meta(distance=0.9)),
            _Obj("u-near", _concept_props(concept_id="FK-NEAR"), _Meta(distance=0.1)),
        ]
    )
    collection = _collection(near)
    hits = _retrieval(_client(collection)).search(
        project_id="acme", source_type="concept", query="retrieval",
        search_mode="vector", limit=10, filters={},
    )
    call = collection.query.calls[0]
    assert call["kind"] == "near_text"
    assert call["return_metadata"] == ["distance"]  # NOT score (N02)
    # The closer object (smaller distance) must get the HIGHER score.
    by_id = {h["concept_id"]: float(str(h["score"])) for h in hits}
    assert by_id["FK-NEAR"] > by_id["FK-FAR"]


def test_n02_keyword_mode_requests_the_score_metadata_it_needs() -> None:
    response = _Response([_Obj("u1", _concept_props(), _Meta(score=0.42))])
    collection = _collection(response)
    hits = _retrieval(_client(collection)).search(
        project_id="acme", source_type="concept", query="retrieval",
        search_mode="keyword", limit=10, filters={},
    )
    call = collection.query.calls[0]
    assert call["kind"] == "bm25"
    assert call["return_metadata"] == ["score"]
    assert hits[0]["score"] == pytest.approx(0.42)


def test_n02_near_text_hit_without_distance_is_fail_closed() -> None:
    """A near_text response carrying only a score must NOT be ranked by it."""
    response = _Response([_Obj("u1", _concept_props(), _Meta(score=0.9))])
    with pytest.raises(VectorDbUnavailableError, match="distance"):
        _retrieval(_client(_collection(response))).search(
            project_id="acme", source_type="concept", query="q",
            search_mode="vector", limit=10, filters={},
        )


def test_n02_hybrid_mode_requests_score() -> None:
    response = _Response([_Obj("u1", _concept_props(), _Meta(score=0.7))])
    collection = _collection(response)
    _retrieval(_client(collection)).search(
        project_id="acme", source_type="concept", query="q",
        search_mode="hybrid", limit=5, filters={"concept_status": "active"},
    )
    call = collection.query.calls[0]
    assert call["kind"] == "hybrid"
    assert call["return_metadata"] == ["score"]
    assert call["limit"] == 5


# --------------------------------------------------------------------------- #
# D9: the destructive delete carries its ownership condition to the store
# --------------------------------------------------------------------------- #


def _conditional_delete(
    uuids: list[str],
    *,
    results: list[tuple[int, int]] | None = None,
    raises: bool = False,
) -> tuple[int, _FakeData]:
    data = _FakeData(
        delete_many_results=list(results or []), delete_many_raises=raises
    )
    collection = _collection()
    collection.data = data
    client = _client(collection)
    deleted = client.delete_by_ids_if_property_below(
        collection=STORY_CONTEXT_COLLECTION,
        uuids=uuids,
        prop="owning_generation",
        limit=7,
    )
    return deleted, data


def test_d9_the_condition_travels_with_the_delete() -> None:
    """The ownership condition is part of the DELETE, not a preceding check."""
    from weaviate.collections.classes.filters import _FilterAnd

    uid = "11111111-1111-5111-8111-111111111111"
    deleted, data = _conditional_delete([uid], results=[(1, 0)])
    assert deleted == 1
    assert len(data.delete_many_calls) == 1
    where = data.delete_many_calls[0]["where"]
    assert isinstance(where, _FilterAnd)
    targets = {p.target: p for p in where.filters}  # type: ignore[attr-defined]
    assert targets["_id"].value == [uid]
    assert targets["owning_generation"].value == 7
    # An ORDERING, not an equality: that is what authorises the delete (N37).
    assert str(targets["owning_generation"].operator).endswith("LESS_THAN")


def test_d9_a_condition_that_no_longer_matches_deletes_nothing() -> None:
    """The store simply removes nothing -- the caller sees the short count."""
    deleted, _data = _conditional_delete(
        ["11111111-1111-5111-8111-111111111111"], results=[(0, 0)]
    )
    assert deleted == 0


def test_d9_a_failed_conditional_delete_is_fail_closed() -> None:
    """A reported failure must never be counted as a delete (R12)."""
    with pytest.raises(VectorDbWriteError, match=r"object\(s\) failed"):
        _conditional_delete(
            ["11111111-1111-5111-8111-111111111111"], results=[(0, 1)]
        )


def test_d9_a_transport_fault_during_the_conditional_delete_raises() -> None:
    with pytest.raises(VectorDbWriteError, match="conditional delete failed"):
        _conditional_delete(["11111111-1111-5111-8111-111111111111"], raises=True)


def test_d9_ids_are_sent_in_bounded_batches_and_counted_exactly() -> None:
    """Batching bounds the filter payload, never the guarantee."""
    from agentkit.integration_clients.vectordb.weaviate_adapter import (
        MAX_CONDITIONAL_DELETE_IDS,
    )

    total = MAX_CONDITIONAL_DELETE_IDS + 5
    uuids = [f"{i:08d}-1111-5111-8111-111111111111" for i in range(total)]
    outcomes = [(MAX_CONDITIONAL_DELETE_IDS, 0), (5, 0)]
    deleted, data = _conditional_delete(uuids, results=outcomes)
    assert deleted == total
    assert len(data.delete_many_calls) == 2
    first = data.delete_many_calls[0]["where"]
    ids = next(
        p.value for p in first.filters if p.target == "_id"  # type: ignore[attr-defined]
    )
    assert len(ids) == MAX_CONDITIONAL_DELETE_IDS
    # Every id of the batch still carries the SAME ownership condition.
    condition = next(
        p.value
        for p in first.filters  # type: ignore[attr-defined]
        if p.target == "owning_generation"
    )
    assert condition == 7


# --------------------------------------------------------------------------- #
# D8: a set-valued filter becomes a REAL server-side condition
# --------------------------------------------------------------------------- #


def _emitted_filter(filters: dict[str, object], hits: int = 1) -> object:
    """Return the Weaviate filter object the adapter actually sent."""
    objs = [_Obj(f"u{i}", _concept_props(), _Meta(score=0.5)) for i in range(hits)]
    collection = _collection(_Response(objs))
    _retrieval(_client(collection)).search(
        project_id="acme", source_type="concept", query="q",
        search_mode="hybrid", limit=5, filters=filters,
    )
    return collection.query.calls[0]["filters"]


def test_d8_a_status_set_is_sent_as_a_real_or_of_equalities() -> None:
    """The set must be evaluated by Weaviate, never post-filtered on the client."""
    from weaviate.collections.classes.filters import _FilterOr

    flt = _emitted_filter({"concept_status": ("active", "draft")})
    # The whole condition is an AND of (project_id, source_type, status-set).
    status_parts = [
        part for part in flt.filters if isinstance(part, _FilterOr)  # type: ignore[attr-defined]
    ]
    assert len(status_parts) == 1
    values = {p.value for p in status_parts[0].filters}  # type: ignore[attr-defined]
    targets = {p.target for p in status_parts[0].filters}  # type: ignore[attr-defined]
    assert values == {"active", "draft"}
    assert targets == {"concept_status"}


def test_d8_a_single_status_stays_a_plain_equality() -> None:
    """The default query keeps the exact condition it has always issued."""
    from weaviate.collections.classes.filters import _FilterOr

    flt = _emitted_filter({"concept_status": ("active",)})
    assert not any(isinstance(part, _FilterOr) for part in flt.filters)  # type: ignore[attr-defined]
    status = [p for p in flt.filters if p.target == "concept_status"]  # type: ignore[attr-defined]
    assert [p.value for p in status] == ["active"]


def test_d8_an_empty_filter_set_is_fail_closed() -> None:
    """An empty set selects nothing; it must never widen to "no filter"."""
    with pytest.raises(VectorDbUnavailableError, match="empty set"):
        _emitted_filter({"concept_status": ()})


# --------------------------------------------------------------------------- #
# N11: no repair default for hit properties
# --------------------------------------------------------------------------- #


def test_n11_missing_required_property_is_a_hard_error() -> None:
    broken = _concept_props()
    del broken["concept_id"]
    response = _Response([_Obj("u1", broken, _Meta(score=0.5))])
    with pytest.raises(VectorDbUnavailableError, match="missing the required property 'concept_id'"):
        _retrieval(_client(_collection(response))).search(
            project_id="acme", source_type="concept", query="q",
            search_mode="hybrid", limit=10, filters={},
        )


def test_n11_wrongly_typed_property_is_a_hard_error() -> None:
    response = _Response([_Obj("u1", _concept_props(is_appendix="yes"), _Meta(score=0.5))])
    with pytest.raises(VectorDbUnavailableError, match="property 'is_appendix' is str"):
        _retrieval(_client(_collection(response))).search(
            project_id="acme", source_type="concept", query="q",
            search_mode="hybrid", limit=10, filters={},
        )


def test_n11_empty_mandatory_property_is_a_hard_error() -> None:
    response = _Response([_Obj("u1", _concept_props(concept_id=""), _Meta(score=0.5))])
    with pytest.raises(VectorDbUnavailableError, match="'concept_id' is empty"):
        _retrieval(_client(_collection(response))).search(
            project_id="acme", source_type="concept", query="q",
            search_mode="hybrid", limit=10, filters={},
        )


def test_n11_story_profile_does_not_require_concept_properties() -> None:
    """The profile is per source type: a story hit carries no concept fields."""
    story_props: dict[str, object] = {
        "content": "text", "story_id": "AG3-1", "title": "T", "status": "Done",
        "story_type": "implementation", "module": "backend", "epic": "retrieval",
        "source_type": "story",
        "source_file": "stories/AG3-1/story.md", "section_heading": "Problem",
        "section_number": "1", "content_hash": "h", "project_id": "acme",
    }
    response = _Response([_Obj("u1", story_props, _Meta(score=0.5))])
    hits = _retrieval(_client(_collection(response))).search(
        project_id="acme", source_type="story", query="q",
        search_mode="hybrid", limit=10, filters={},
    )
    assert hits[0]["story_id"] == "AG3-1"


# --------------------------------------------------------------------------- #
# R12: delete_by_id returns a bool
# --------------------------------------------------------------------------- #


def test_r12_unconfirmed_delete_is_not_counted() -> None:
    data = _FakeData(delete_results={"missing-uuid": False, "present-uuid": True})
    client = _client(_collection(data=data))
    deleted = client.delete_by_ids(
        collection=STORY_CONTEXT_COLLECTION, uuids=["present-uuid", "missing-uuid"]
    )
    assert deleted == 1  # NOT 2: the absent uuid deleted nothing (R12)


def test_r12_delete_transport_fault_is_a_partial_delete_error() -> None:
    data = _FakeData(delete_raises={"boom"})
    client = _client(_collection(data=data))
    with pytest.raises(VectorDbWriteError, match="partial delete"):
        client.delete_by_ids(collection=STORY_CONTEXT_COLLECTION, uuids=["boom"])


# --------------------------------------------------------------------------- #
# N03: conditional create is the claim primitive
# --------------------------------------------------------------------------- #


def test_n03_insert_object_reports_the_loser_of_a_conditional_create() -> None:
    data = _FakeData(existing_ids={"claim-1"})
    client = _client(_collection(data=data))
    assert client.insert_object(
        collection="__agentkit_source_claims", uuid="claim-2", properties={"state": "claimed"}
    ) is True
    assert client.insert_object(
        collection="__agentkit_source_claims", uuid="claim-1", properties={"state": "claimed"}
    ) is False


# --------------------------------------------------------------------------- #
# N12: an existing collection is VERIFIED, not accepted blindly
# --------------------------------------------------------------------------- #


def test_n12_config_view_mirrors_the_real_weaviate_dataclasses() -> None:
    """Guard: production reads attributes that really exist on the real config."""
    import dataclasses

    from weaviate.collections.classes.config import _CollectionConfig, _Property

    config_fields = {f.name for f in dataclasses.fields(_CollectionConfig)}
    assert {"properties", "vectorizer", "vector_config"} <= config_fields
    property_fields = {f.name for f in dataclasses.fields(_Property)}
    assert {"name", "data_type"} <= property_fields
    assert {f.name for f in dataclasses.fields(_ConfigView)} <= config_fields


def _read_property(
    name: str,
    data_type: DataType,
    *,
    skip_vectorization: bool = True,
    vectorize_property_name: bool = False,
    tokenization: Tokenization | None = None,
    searchable: bool = False,
    filterable: bool = True,
) -> _Property:
    """Build a REAL read-side ``_Property`` (the shape ``config.get()`` returns)."""
    return _Property(
        name=name,
        description=None,
        data_type=data_type,
        index_filterable=filterable,
        index_range_filters=False,
        index_searchable=searchable,
        nested_properties=None,
        text_analyzer=None,
        tokenization=tokenization,
        vectorizer_config=_PropertyVectorizerConfig(
            skip=skip_vectorization, vectorize_property_name=vectorize_property_name
        ),
        vectorizer=None,
        vectorizer_configs=None,
    )


_TYPE_MAP = {
    "TEXT": DataType.TEXT,
    "BOOL": DataType.BOOL,
    "TEXT[]": DataType.TEXT_ARRAY,
    "INT": DataType.INT,
}
_TOKEN_MAP = {"WORD": Tokenization.WORD, "FIELD": Tokenization.FIELD}


def _schema_properties() -> list[_Property]:
    """The read-back view of a collection created EXACTLY per the schema SSOT."""
    props: list[_Property] = []
    for spec in weaviate_property_specs():
        token = spec.get("tokenization")
        props.append(
            _read_property(
                str(spec["name"]),
                _TYPE_MAP[str(spec["data_type"])],
                skip_vectorization=bool(spec["skip_vectorization"]),
                vectorize_property_name=bool(spec.get("vectorize_property_name", False)),
                tokenization=_TOKEN_MAP[str(token)] if token else None,
                searchable=bool(spec.get("searchable", False)),
                filterable=bool(spec.get("filterable", True)),
            )
        )
    return props


def _ensure(config: _ConfigView, vectorizer: str) -> None:
    """Verify an EXISTING collection against the schema SSOT (model + sources)."""
    from agentkit.backend.vectordb.schema import (
        FK13_VECTOR_SOURCE_PROPERTIES,
        FK13_VECTORIZER_MODEL,
    )

    server_side = vectorizer == "text2vec_transformers"
    client = _client(_collection(config=config), existing={STORY_CONTEXT_COLLECTION})
    client.ensure_collection(
        collection=STORY_CONTEXT_COLLECTION,
        property_specs=weaviate_property_specs(),
        vectorizer=vectorizer,
        vectorizer_model=FK13_VECTORIZER_MODEL if server_side else None,
        vector_source_properties=FK13_VECTOR_SOURCE_PROPERTIES if server_side else None,
    )


def test_n12_existing_collection_with_self_provided_vectorizer_fails_closed() -> None:
    config = _ConfigView(properties=_schema_properties(), vectorizer=Vectorizers.NONE)
    with pytest.raises(VectorDbWriteError, match="vectorizer 'self_provided'"):
        _ensure(config, "text2vec_transformers")


def test_n12_existing_collection_with_property_drift_fails_closed() -> None:
    props = _schema_properties()[:-1]  # one schema property missing
    config = _ConfigView(properties=props, vector_config=_named_vector_config())
    with pytest.raises(VectorDbWriteError, match="configuration drifted"):
        _ensure(config, "text2vec_transformers")


def test_n12_existing_collection_with_wrong_data_type_fails_closed() -> None:
    props = _schema_properties()
    props[0] = _read_property(str(props[0].name), DataType.BOOL)  # content: TEXT -> BOOL
    config = _ConfigView(properties=props, vector_config=_named_vector_config())
    with pytest.raises(VectorDbWriteError, match="'data_type': 'boolean'"):
        _ensure(config, "text2vec_transformers")


def test_n12_matching_existing_collection_is_accepted() -> None:
    config = _ConfigView(
        properties=_schema_properties(), vector_config=_named_vector_config()
    )
    _ensure(config, "text2vec_transformers")  # no raise


def _named_vector_config(
    vectorizer: Vectorizers = Vectorizers.TEXT2VEC_TRANSFORMERS,
    *,
    source_properties: list[str] | None = None,
    **model: object,
) -> dict[str, _NamedVectorConfig]:
    """Build the REAL read-back named-vector config of the installed client (N30).

    The previous test fabricated an object exposing ``vectorize_collection_name``,
    an attribute ``_NamedVectorizerConfig`` does NOT have -- which is exactly how
    the production check could look at the wrong place and still pass. Everything
    here comes from the installed classes, and ALL THREE of the class's
    behaviour-defining fields (``vectorizer``, ``model``, ``source_properties``) are
    settable so each of them can be drifted independently (N35).
    """
    settings: dict[str, object] = {
        "poolingStrategy": "masked_mean",
        "vectorizeClassName": False,
    }
    settings.update(model)
    return {
        "default": _NamedVectorConfig(
            vectorizer=_NamedVectorizerConfig(
                vectorizer=vectorizer, model=settings, source_properties=source_properties
            ),
            vector_index_config=None,
        )
    }


def test_n30_named_vectorizer_config_has_no_vectorize_collection_name_attribute() -> None:
    """Guard the CLASS SHAPE the production check depends on (N30)."""
    import dataclasses

    fields = {f.name for f in dataclasses.fields(_NamedVectorizerConfig)}
    assert fields == {"vectorizer", "model", "source_properties"}
    assert "vectorize_collection_name" not in fields
    # The legacy surface is the one that carries the flag directly.
    legacy_fields = {f.name for f in dataclasses.fields(_VectorizerConfig)}
    assert {"vectorizer", "model", "vectorize_collection_name"} <= legacy_fields


def test_n12_named_vector_config_is_the_authoritative_surface() -> None:
    """With named vectors the legacy ``vectorizer`` field is None -- use vector_config."""
    config = _ConfigView(
        properties=_schema_properties(),
        vectorizer=None,
        vector_config=_named_vector_config(),
    )
    _ensure(config, "text2vec_transformers")
    drifted = _ConfigView(
        properties=_schema_properties(),
        vectorizer=None,
        vector_config=_named_vector_config(Vectorizers.NONE),
    )
    with pytest.raises(VectorDbWriteError, match="vectorizer 'self_provided'"):
        _ensure(drifted, "text2vec_transformers")


def test_n30_model_settings_are_read_from_the_real_named_config() -> None:
    """The MODEL is where vectorizeClassName / poolingStrategy actually live."""
    config = _ConfigView(
        properties=_schema_properties(),
        vectorizer=None,
        vector_config=_named_vector_config(),
    )
    assert configured_vectorizer_model(config) == {
        "poolingStrategy": "masked_mean",
        "vectorizeClassName": False,
    }


@pytest.mark.parametrize(
    "drift,match",
    [
        ({"vectorizeClassName": True}, "vectorizeClassName"),
        ({"poolingStrategy": "cls"}, "poolingStrategy"),
    ],
)
def test_n30_drifted_vectorizer_model_fails_closed(
    drift: dict[str, object], match: str
) -> None:
    """A real config with a drifted MODEL must NOT pass verification (N30)."""
    config = _ConfigView(
        properties=_schema_properties(),
        vectorizer=None,
        vector_config=_named_vector_config(**drift),
    )
    with pytest.raises(VectorDbWriteError, match=match):
        _ensure(config, "text2vec_transformers")


def test_n30_legacy_vectorizer_surface_is_also_checked() -> None:
    """The pre-named-vector surface carries the flag as its own attribute."""
    config = _ConfigView(
        properties=_schema_properties(),
        vectorizer=Vectorizers.TEXT2VEC_TRANSFORMERS,
        vector_config=None,
        vectorizer_config=_VectorizerConfig(
            vectorizer=Vectorizers.TEXT2VEC_TRANSFORMERS,
            model={"poolingStrategy": "masked_mean"},
            vectorize_collection_name=True,
        ),
    )
    with pytest.raises(VectorDbWriteError, match="vectorizeClassName"):
        _ensure(config, "text2vec_transformers")


def test_n30_created_collection_uses_the_ssot_model() -> None:
    """Creation takes the pooling strategy / class-name flag from the schema SSOT."""
    from agentkit.backend.vectordb.schema import FK13_VECTORIZER_MODEL

    collections = _FakeCollections(collection=_collection())
    client = _RealWeaviateClient(_FakeConnection(collections))
    client.ensure_collection(
        collection=STORY_CONTEXT_COLLECTION,
        property_specs=weaviate_property_specs(),
        vectorizer="text2vec_transformers",
        vectorizer_model=FK13_VECTORIZER_MODEL,
    )
    created = collections.created[0]["vector_config"]
    inner = created.vectorizer  # type: ignore[union-attr]
    assert inner.poolingStrategy == FK13_VECTORIZER_MODEL["poolingStrategy"]
    assert inner.vectorizeClassName == FK13_VECTORIZER_MODEL["vectorizeClassName"]


# --------------------------------------------------------------------------- #
# N35: source_properties decide WHAT is embedded and are part of the contract
# --------------------------------------------------------------------------- #


def test_n35_source_properties_are_read_from_the_installed_named_config() -> None:
    """The read-back projection returns the EXPLICIT selection, in order."""
    config = _ConfigView(
        properties=_schema_properties(),
        vectorizer=None,
        vector_config=_named_vector_config(source_properties=["content", "title"]),
    )
    assert configured_vector_source_properties(config) == ("content", "title")


def test_n35_matching_explicit_source_properties_are_accepted() -> None:
    """A collection that embeds exactly the SSOT-selected properties passes."""
    from agentkit.backend.vectordb.schema import FK13_VECTOR_SOURCE_PROPERTIES

    config = _ConfigView(
        properties=_schema_properties(),
        vectorizer=None,
        vector_config=_named_vector_config(
            source_properties=list(FK13_VECTOR_SOURCE_PROPERTIES)
        ),
    )
    _ensure(config, "text2vec_transformers")  # no raise


@pytest.mark.parametrize(
    "drifted",
    [
        pytest.param(["title"], id="title-only"),
        pytest.param(["content"], id="body-only"),
        pytest.param(["content", "title", "section_heading", "module"], id="extra-property"),
        pytest.param(["title", "content", "section_heading"], id="reordered"),
        pytest.param([], id="nothing-vectorised"),
    ],
)
def test_n35_drifted_source_properties_fail_closed(drifted: list[str]) -> None:
    """Pooling + vectorizeClassName matching is NOT enough (N35).

    This is the exact hole: a collection configured to embed only ``title`` passed
    composition because the model settings were identical, and semantic search then
    answered from titles alone.
    """
    config = _ConfigView(
        properties=_schema_properties(),
        vectorizer=None,
        vector_config=_named_vector_config(source_properties=drifted),
    )
    with pytest.raises(VectorDbWriteError, match="SOURCE PROPERTIES drifted"):
        _ensure(config, "text2vec_transformers")


def test_n35_drift_is_caught_even_when_the_model_is_perfect() -> None:
    """Isolate the finding: ONLY source_properties differ, everything else matches."""
    config = _ConfigView(
        properties=_schema_properties(),
        vectorizer=None,
        vector_config=_named_vector_config(source_properties=["title"]),
    )
    assert configured_vectorizer_model(config) == {
        "poolingStrategy": "masked_mean",
        "vectorizeClassName": False,
    }
    with pytest.raises(VectorDbWriteError, match="vectorises only the title"):
        _ensure(config, "text2vec_transformers")


def test_n35_absent_selection_is_governed_by_the_per_property_skip_flags() -> None:
    """``source_properties=None`` is the server-derived set, not drift.

    The client reports ``None`` when the server derives the embedded set from the
    per-property ``skip_vectorization`` flags -- and those are verified property by
    property by the same call, so treating ``None`` as drift would reject a
    correctly configured collection. Deliberate, and pinned here so the semantics
    cannot be changed silently.
    """
    config = _ConfigView(
        properties=_schema_properties(), vectorizer=None,
        vector_config=_named_vector_config(source_properties=None),
    )
    assert configured_vector_source_properties(config) is None
    _ensure(config, "text2vec_transformers")  # no raise
    # ... and the skip flags themselves are still enforced: flipping the body to
    # "skip" is caught, so nothing about WHAT is embedded goes unchecked.
    props = _schema_properties()
    props[0] = _read_property(str(props[0].name), DataType.TEXT, skip_vectorization=True)
    drifted = _ConfigView(
        properties=props, vectorizer=None,
        vector_config=_named_vector_config(source_properties=None),
    )
    with pytest.raises(VectorDbWriteError, match="skip_vectorization"):
        _ensure(drifted, "text2vec_transformers")


def test_n35_created_collection_declares_the_ssot_source_properties() -> None:
    """Creation declares the selection EXPLICITLY so a read-back can prove it.

    The installed client puts the selection in DIFFERENT places on the two sides:
    the create model ``_VectorConfigCreate`` carries it as ``properties`` (the inner
    ``_Text2VecTransformersConfig`` has no such field at all), while the read model
    exposes it as ``_NamedVectorizerConfig.source_properties``. Asserted against the
    real create model rather than against an assumed attribute name.
    """
    from agentkit.backend.vectordb.schema import (
        FK13_VECTOR_SOURCE_PROPERTIES,
        FK13_VECTORIZER_MODEL,
    )

    collections = _FakeCollections(collection=_collection())
    client = _RealWeaviateClient(_FakeConnection(collections))
    client.ensure_collection(
        collection=STORY_CONTEXT_COLLECTION,
        property_specs=weaviate_property_specs(),
        vectorizer="text2vec_transformers",
        vectorizer_model=FK13_VECTORIZER_MODEL,
        vector_source_properties=FK13_VECTOR_SOURCE_PROPERTIES,
    )
    created = collections.created[0]["vector_config"]
    assert created.properties == list(FK13_VECTOR_SOURCE_PROPERTIES)  # type: ignore[union-attr]
    assert not hasattr(created.vectorizer, "sourceProperties")  # type: ignore[union-attr]


def test_n35_ssot_source_properties_are_the_vectorised_schema_properties() -> None:
    """The list is DERIVED from the schema, never hand-maintained beside it."""
    from agentkit.backend.vectordb.schema import (
        FK13_VECTOR_SOURCE_PROPERTIES,
        weaviate_property_specs,
    )

    derived = tuple(
        str(spec["name"])
        for spec in weaviate_property_specs()
        if not bool(spec["skip_vectorization"])
    )
    assert derived == FK13_VECTOR_SOURCE_PROPERTIES
    assert derived  # a corpus that embeds nothing would be a broken schema


def test_n12_creation_uses_the_fk13_server_side_vectorizer() -> None:
    """FK-13 §13.2: the StoryContext collection is created with text2vec-transformers."""
    collections = _FakeCollections(collection=_collection())
    client = _RealWeaviateClient(_FakeConnection(collections))
    client.ensure_collection(
        collection=STORY_CONTEXT_COLLECTION,
        property_specs=weaviate_property_specs(),
        vectorizer="text2vec_transformers",
    )
    assert len(collections.created) == 1
    vector_config = collections.created[0]["vector_config"]
    inner = vector_config.vectorizer  # type: ignore[union-attr]
    assert inner.vectorizer is Vectorizers.TEXT2VEC_TRANSFORMERS
    created_names = [p.name for p in collections.created[0]["properties"]]  # type: ignore[union-attr]
    assert set(created_names) == {str(s["name"]) for s in weaviate_property_specs()}


# --------------------------------------------------------------------------- #
# AC10 pagination: a filtered read is COMPLETE or a hard error, never truncated
# --------------------------------------------------------------------------- #


@dataclass
class _PagingQuery:
    """Fake fetch_objects that pages like Weaviate (offset + limit)."""

    total: int
    calls: list[dict[str, object]] = field(default_factory=list)
    overflow: bool = False

    def fetch_objects(self, **kwargs: object) -> _Response:
        from weaviate.collections.queries.fetch_objects.query import _FetchObjectsQuery

        _bind_real(_FetchObjectsQuery.fetch_objects, kwargs)
        self.calls.append(dict(kwargs))
        limit = int(str(kwargs["limit"]))
        offset = int(str(kwargs["offset"]))
        if self.overflow:
            limit += 1  # malformed: more objects than the page requested
        page = [
            _Obj(f"u{i}", {"project_id": "acme"}, _Meta(score=1.0))
            for i in range(offset, min(offset + limit, self.total))
        ]
        return _Response(page)


def _paging_client(query: _PagingQuery) -> _RealWeaviateClient:
    collection = _FakeCollection(
        query=query,  # type: ignore[arg-type]
        data=_FakeData(),
        config=_FakeConfig(_ConfigView(properties=[])),
    )
    return _RealWeaviateClient(_FakeConnection(_FakeCollections(collection=collection)))


def test_pagination_reads_every_page_of_a_large_result_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agentkit.integration_clients.vectordb import weaviate_adapter

    monkeypatch.setattr(weaviate_adapter, "FETCH_PAGE_SIZE", 10)
    query = _PagingQuery(total=25)
    rows = _paging_client(query).fetch_by_property(
        collection=STORY_CONTEXT_COLLECTION,
        prop="project_id",
        value="acme",
        return_props=("project_id",),
    )
    assert len(rows) == 25  # NOT truncated at the page size
    assert [c["offset"] for c in query.calls] == [0, 10, 20]


def test_pagination_beyond_the_hard_ceiling_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agentkit.integration_clients.vectordb import weaviate_adapter

    monkeypatch.setattr(weaviate_adapter, "FETCH_PAGE_SIZE", 10)
    monkeypatch.setattr(weaviate_adapter, "MAX_FETCH_OBJECTS", 20)
    with pytest.raises(VectorDbUnavailableError, match="refusing a truncated answer"):
        _paging_client(_PagingQuery(total=1000)).fetch_by_property(
            collection=STORY_CONTEXT_COLLECTION,
            prop="project_id",
            value="acme",
            return_props=("project_id",),
        )


def test_malformed_pagination_page_is_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    from agentkit.integration_clients.vectordb import weaviate_adapter

    monkeypatch.setattr(weaviate_adapter, "FETCH_PAGE_SIZE", 10)
    with pytest.raises(VectorDbUnavailableError, match="malformed pagination"):
        _paging_client(_PagingQuery(total=100, overflow=True)).fetch_by_property_any(
            collection=STORY_CONTEXT_COLLECTION,
            prop="source_type",
            values=("concept",),
            return_props=("project_id",),
        )


# --------------------------------------------------------------------------- #
# R05/N01: EVERY typed filter reaches Weaviate as a hard filter (none ignored)
# --------------------------------------------------------------------------- #


def _filter_pairs(flt: Any) -> set[tuple[str, object]]:
    """Flatten a REAL Weaviate filter expression into (target, value) pairs."""
    leaves = getattr(flt, "filters", None)
    if leaves is None:
        return {(str(flt.target), flt.value)}
    pairs: set[tuple[str, object]] = set()
    for leaf in leaves:
        pairs |= _filter_pairs(leaf)
    return pairs


def test_every_typed_filter_is_applied_as_a_weaviate_filter() -> None:
    response = _Response([_Obj("u1", _concept_props(), _Meta(score=0.5))])
    collection = _collection(response)
    _retrieval(_client(collection)).search(
        project_id="acme",
        source_type="concept",
        query="q",
        search_mode="hybrid",
        limit=10,
        filters={"concept_status": "draft", "is_appendix": True, "module": "vectordb"},
    )
    pairs = _filter_pairs(collection.query.calls[0]["filters"])
    assert ("project_id", "acme") in pairs
    assert ("source_type", "concept") in pairs
    assert ("concept_status", "draft") in pairs
    assert ("module", "vectordb") in pairs
    # A boolean filter keeps its type (no str() coercion of a BOOL property).
    assert ("is_appendix", True) in pairs


# --------------------------------------------------------------------------- #
# N14: the REAL duplicate-object response of the installed client
# --------------------------------------------------------------------------- #


def _duplicate_response(uuid: str) -> httpx.Response:
    """The response Weaviate answers a duplicate object id with (REST /objects)."""
    return httpx.Response(
        status_code=422,
        json={"error": [{"message": f"id '{uuid}' already exists"}]},
        request=httpx.Request("POST", "http://weaviate.acme.local:8080/v1/objects"),
    )


def _server_error_response() -> httpx.Response:
    return httpx.Response(
        status_code=500,
        json={"error": [{"message": "internal server error"}]},
        request=httpx.Request("POST", "http://weaviate.acme.local:8080/v1/objects"),
    )


@dataclass
class _RaisingData(_FakeData):
    """``data.insert`` raising a REAL client exception instance."""

    error: Exception | None = None
    exists_result: bool = False

    def insert(self, **kwargs: object) -> str:
        _bind_real(_DataCollection.insert, kwargs)
        if self.error is not None:
            raise self.error
        return str(kwargs["uuid"])

    def exists(self, uuid: str) -> bool:
        return self.exists_result


def test_n14_object_already_exists_exception_is_also_a_lost_claim() -> None:
    """BEHAVIOURAL (P2-1): both real exception shapes are handled as a lost claim.

    ``insert`` routes a duplicate id through ``UnexpectedStatusCodeError`` (covered
    by the constructed-response tests); other client paths raise
    ``ObjectAlreadyExistsException``. Production must treat BOTH as "the claim is
    taken", and neither as a write error.
    """
    from weaviate.exceptions import ObjectAlreadyExistsException

    data = _RaisingData(error=ObjectAlreadyExistsException("claim-1"))
    client = _client(_collection(data=data))
    assert (
        client.insert_object(
            collection="__agentkit_source_claims", uuid="claim-1", properties={"state": "claimed"}
        )
        is False
    )


def test_n14_real_duplicate_response_is_a_lost_claim() -> None:
    from weaviate.exceptions import UnexpectedStatusCodeError

    uuid = "3f0b0c1e-0000-4000-8000-000000000001"
    data = _RaisingData(
        error=UnexpectedStatusCodeError("Object was not added", _duplicate_response(uuid))
    )
    client = _client(_collection(data=data))
    assert (
        client.insert_object(
            collection="__agentkit_source_claims", uuid=uuid, properties={"state": "claimed"}
        )
        is False
    )


def test_n14_other_unexpected_status_is_a_write_error_not_a_lost_claim() -> None:
    from weaviate.exceptions import UnexpectedStatusCodeError

    data = _RaisingData(
        error=UnexpectedStatusCodeError("Object was not added", _server_error_response())
    )
    client = _client(_collection(data=data))
    with pytest.raises(VectorDbWriteError, match="status 500"):
        client.insert_object(
            collection="__agentkit_source_claims", uuid="u1", properties={"state": "claimed"}
        )


def test_n14_existence_probe_settles_an_ambiguous_failure() -> None:
    """A non-duplicate error plus a PRESENT object still means the claim is taken."""
    from weaviate.exceptions import UnexpectedStatusCodeError

    data = _RaisingData(
        error=UnexpectedStatusCodeError("Object was not added", _server_error_response()),
        exists_result=True,
    )
    client = _client(_collection(data=data))
    assert (
        client.insert_object(
            collection="__agentkit_source_claims", uuid="u1", properties={"state": "claimed"}
        )
        is False
    )


# --------------------------------------------------------------------------- #
# N18: narrative fields are TERM-tokenised so keyword search can match a word
# --------------------------------------------------------------------------- #


def test_n18_narrative_fields_are_word_tokenised_and_searchable() -> None:
    collections = _FakeCollections(collection=_collection())
    client = _RealWeaviateClient(_FakeConnection(collections))
    client.ensure_collection(
        collection=STORY_CONTEXT_COLLECTION,
        property_specs=weaviate_property_specs(),
        vectorizer="text2vec_transformers",
    )
    created = {p.name: p for p in collections.created[0]["properties"]}  # type: ignore[union-attr]
    # The vectorised narrative fields must be word-tokenised AND BM25-searchable:
    # with FIELD tokenisation "Vector retrieval engine" is ONE token and the
    # keyword query "retrieval" cannot match it (N18).
    for name in ("content", "title", "section_heading"):
        assert created[name].tokenization is Tokenization.WORD, name
        assert created[name].indexSearchable is True, name
    # Identifier/enum fields stay whole-value so the hard filters compare exactly.
    for name in ("project_id", "source_type", "source_file", "concept_id", "status"):
        assert created[name].tokenization is Tokenization.FIELD, name
        assert created[name].indexSearchable is False, name
    # A boolean property must carry NO tokenisation (Weaviate rejects it there).
    assert created["is_appendix"].tokenization is None
    # The property NAME is never folded into the embedding.
    assert all(p.vectorize_property_name is False for p in created.values())


def test_n18_existing_collection_with_field_tokenised_content_fails_closed() -> None:
    """The N12 verification must catch the tokenisation drift too."""
    props = _schema_properties()
    content_index = next(i for i, p in enumerate(props) if p.name == "content")
    props[content_index] = _read_property(
        "content",
        DataType.TEXT,
        skip_vectorization=False,
        tokenization=Tokenization.FIELD,  # drifted: whole-value narrative field
        searchable=True,
    )
    config = _ConfigView(properties=props, vector_config=_named_vector_config())
    with pytest.raises(VectorDbWriteError, match="'tokenization': 'field'"):
        _ensure(config, "text2vec_transformers")


def test_n18_existing_collection_with_unsearchable_content_fails_closed() -> None:
    props = _schema_properties()
    content_index = next(i for i, p in enumerate(props) if p.name == "content")
    props[content_index] = _read_property(
        "content",
        DataType.TEXT,
        skip_vectorization=False,
        tokenization=Tokenization.WORD,
        searchable=False,  # drifted: BM25 cannot use it at all
    )
    config = _ConfigView(properties=props, vector_config=_named_vector_config())
    with pytest.raises(VectorDbWriteError, match="'searchable': False"):
        _ensure(config, "text2vec_transformers")


def test_n12_drifted_per_property_vectorisation_fails_closed() -> None:
    props = _schema_properties()
    story_id_index = next(i for i, p in enumerate(props) if p.name == "story_id")
    props[story_id_index] = _read_property(
        "story_id",
        DataType.TEXT,
        skip_vectorization=False,  # drifted: an identifier in the embedding
        tokenization=Tokenization.FIELD,
    )
    config = _ConfigView(properties=props, vector_config=_named_vector_config())
    with pytest.raises(VectorDbWriteError, match="'skip_vectorization': False"):
        _ensure(config, "text2vec_transformers")


def test_pagination_at_the_exact_ceiling_is_complete_not_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """N25: reaching the ceiling exactly is a COMPLETE read, not a truncation."""
    from agentkit.integration_clients.vectordb import weaviate_adapter

    monkeypatch.setattr(weaviate_adapter, "FETCH_PAGE_SIZE", 10)
    monkeypatch.setattr(weaviate_adapter, "MAX_FETCH_OBJECTS", 20)
    query = _PagingQuery(total=20)
    rows = _paging_client(query).fetch_by_property(
        collection=STORY_CONTEXT_COLLECTION,
        prop="project_id",
        value="acme",
        return_props=("project_id",),
    )
    assert len(rows) == 20
    # The last call is the single-object PROBE that proves nothing follows.
    assert query.calls[-1]["limit"] == 1
    assert query.calls[-1]["offset"] == 20


@dataclass
class _NonAdvancingQuery:
    """A server that returns the SAME page again for the next offset."""

    calls: list[dict[str, object]] = field(default_factory=list)

    def fetch_objects(self, **kwargs: object) -> _Response:
        from weaviate.collections.queries.fetch_objects.query import _FetchObjectsQuery

        _bind_real(_FetchObjectsQuery.fetch_objects, kwargs)
        self.calls.append(dict(kwargs))
        limit = int(str(kwargs["limit"]))
        return _Response(
            [
                _Obj(f"u{i}", {"project_id": "acme"}, _Meta(score=1.0))
                for i in range(limit)
            ]
        )


def test_pagination_repeating_a_page_is_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """N25: a duplicated uuid across pages means the set is both dup'd and short."""
    from agentkit.integration_clients.vectordb import weaviate_adapter

    monkeypatch.setattr(weaviate_adapter, "FETCH_PAGE_SIZE", 5)
    collection = _FakeCollection(
        query=_NonAdvancingQuery(),  # type: ignore[arg-type]
        data=_FakeData(),
        config=_FakeConfig(_ConfigView(properties=[])),
    )
    client = _RealWeaviateClient(_FakeConnection(_FakeCollections(collection=collection)))
    with pytest.raises(VectorDbUnavailableError, match="appeared twice"):
        client.fetch_by_property(
            collection=STORY_CONTEXT_COLLECTION,
            prop="project_id",
            value="acme",
            return_props=("project_id",),
        )


# --------------------------------------------------------------------------- #
# N44: the conditional-delete counters are EXACT -- a regression of R12
#
# The first version of this transport used getattr(..., 0), `or 0` and int(...), so a
# missing field, a numeric string or a boolean passed as a confirmed delete. A new
# transport call inherits the AC10 strictness obligation; it does not start permissive.
# --------------------------------------------------------------------------- #


class _LooseReturn:
    """A delete_many return whose counters are whatever the server felt like."""

    def __init__(self, **fields: object) -> None:
        for name, value in fields.items():
            setattr(self, name, value)


def _delete_with(result: object, *, requested: int = 1) -> int:
    from agentkit.integration_clients.vectordb.weaviate_adapter import (
        _conditional_delete_counts,
    )

    return _conditional_delete_counts(
        result, prop="owning_generation", limit=7, requested=requested
    )


def test_n44_a_missing_counter_is_never_a_zero() -> None:
    """`successful="1"` with `failed` absent must NOT read as a confirmed delete."""
    with pytest.raises(VectorDbWriteError, match="no 'failed' count"):
        _delete_with(_LooseReturn(successful="1"))
    with pytest.raises(VectorDbWriteError, match="no 'successful' count"):
        _delete_with(_LooseReturn(failed=0))


@pytest.mark.parametrize(
    ("fields", "match"),
    [
        pytest.param({"successful": "1", "failed": 0}, "not an\ninteger", id="string"),
        pytest.param({"successful": 1.0, "failed": 0}, "not an", id="float"),
        pytest.param({"successful": True, "failed": 0}, "not an", id="bool-successful"),
        pytest.param({"successful": 1, "failed": False}, "not an", id="bool-failed"),
        pytest.param({"successful": None, "failed": 0}, "not an", id="none"),
    ],
)
def test_n44_a_non_integer_counter_is_never_coerced(
    fields: dict[str, object], match: str
) -> None:
    del match
    with pytest.raises(VectorDbWriteError, match="no coercion"):
        _delete_with(_LooseReturn(**fields))


def test_n44_a_negative_counter_is_fail_closed() -> None:
    with pytest.raises(VectorDbWriteError, match="negative"):
        _delete_with(_LooseReturn(successful=-1, failed=0))


def test_n44_a_reported_failure_is_fail_closed() -> None:
    with pytest.raises(VectorDbWriteError, match="failed; fail-closed"):
        _delete_with(_LooseReturn(successful=0, failed=1))


def test_n44_an_impossible_count_is_never_a_success() -> None:
    """More deleted than requested is a fault, not a bonus."""
    with pytest.raises(VectorDbWriteError, match="impossible count"):
        _delete_with(_LooseReturn(successful=2, failed=0), requested=1)


def test_n44_exact_integers_are_accepted() -> None:
    assert _delete_with(_LooseReturn(successful=1, failed=0)) == 1
    assert _delete_with(_LooseReturn(successful=0, failed=0)) == 0


def test_n44_the_real_transport_uses_the_strict_counters() -> None:
    """The strictness must live on the REAL call path, not only in a helper."""
    data = _FakeData(delete_many_results=[])
    data.delete_many_results = []
    collection = _collection()
    collection.data = data

    class _Loose(_FakeData):
        def delete_many(self, **kwargs: object) -> object:
            self.delete_many_calls.append(dict(kwargs))
            return _LooseReturn(successful="1")

    loose = _Loose()
    collection.data = loose
    client = _client(collection)
    with pytest.raises(VectorDbWriteError, match="count"):
        client.delete_by_ids_if_property_below(
            collection=STORY_CONTEXT_COLLECTION,
            uuids=["11111111-1111-5111-8111-111111111111"],
            prop="owning_generation",
            limit=7,
        )


def test_n43_the_unstamped_delete_sends_an_is_null_condition() -> None:
    """The legacy backfill's condition must be IS-NULL, evaluated by the store (N43).

    An ordering condition (`< 1`) would match nothing and quietly do nothing; only
    IS-NULL selects exactly the rows that predate the ownership-ordering property.
    """
    from weaviate.collections.classes.filters import _FilterAnd

    uid = "11111111-1111-5111-8111-111111111111"
    data = _FakeData(delete_many_results=[(1, 0)])
    collection = _collection()
    collection.data = data
    client = _client(collection)
    deleted = client.delete_by_ids_if_property_absent(
        collection=STORY_CONTEXT_COLLECTION,
        uuids=[uid],
        prop="owning_generation",
    )
    assert deleted == 1
    where = data.delete_many_calls[0]["where"]
    assert isinstance(where, _FilterAnd)
    targets = {p.target: p for p in where.filters}  # type: ignore[attr-defined]
    assert targets["_id"].value == [uid]
    assert str(targets["owning_generation"].operator).endswith("IS_NULL")
    assert targets["owning_generation"].value is True


def test_n43_the_unstamped_delete_counts_are_exact() -> None:
    """A NEW transport call inherits the AC10 strictness obligation (N44 lesson)."""
    data = _FakeData()

    class _Loose(_FakeData):
        def delete_many(self, **kwargs: object) -> object:
            self.delete_many_calls.append(dict(kwargs))
            return _LooseReturn(successful="1")

    del data
    collection = _collection()
    collection.data = _Loose()
    client = _client(collection)
    with pytest.raises(VectorDbWriteError, match="count"):
        client.delete_by_ids_if_property_absent(
            collection=STORY_CONTEXT_COLLECTION,
            uuids=["11111111-1111-5111-8111-111111111111"],
            prop="owning_generation",
        )
