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
    _Property,
    _PropertyVectorizerConfig,
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
from agentkit.integration_clients.vectordb.weaviate_adapter import _RealWeaviateClient

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


@dataclass
class _ConfigView:
    """Mirror of the fields production reads from ``_CollectionConfig`` (N12)."""

    properties: list[_Property]
    vectorizer: Vectorizers | None = None
    vector_config: dict[str, object] | None = None


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


_TYPE_MAP = {"TEXT": DataType.TEXT, "BOOL": DataType.BOOL, "TEXT[]": DataType.TEXT_ARRAY}
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
    client = _client(_collection(config=config), existing={STORY_CONTEXT_COLLECTION})
    client.ensure_collection(
        collection=STORY_CONTEXT_COLLECTION,
        property_specs=weaviate_property_specs(),
        vectorizer=vectorizer,
    )


def test_n12_existing_collection_with_self_provided_vectorizer_fails_closed() -> None:
    config = _ConfigView(properties=_schema_properties(), vectorizer=Vectorizers.NONE)
    with pytest.raises(VectorDbWriteError, match="vectorizer 'self_provided'"):
        _ensure(config, "text2vec_transformers")


def test_n12_existing_collection_with_property_drift_fails_closed() -> None:
    props = _schema_properties()[:-1]  # one schema property missing
    config = _ConfigView(
        properties=props, vectorizer=Vectorizers.TEXT2VEC_TRANSFORMERS
    )
    with pytest.raises(VectorDbWriteError, match="configuration drifted"):
        _ensure(config, "text2vec_transformers")


def test_n12_existing_collection_with_wrong_data_type_fails_closed() -> None:
    props = _schema_properties()
    props[0] = _read_property(str(props[0].name), DataType.BOOL)  # content: TEXT -> BOOL
    config = _ConfigView(properties=props, vectorizer=Vectorizers.TEXT2VEC_TRANSFORMERS)
    with pytest.raises(VectorDbWriteError, match="'data_type': 'boolean'"):
        _ensure(config, "text2vec_transformers")


def test_n12_matching_existing_collection_is_accepted() -> None:
    config = _ConfigView(
        properties=_schema_properties(), vectorizer=Vectorizers.TEXT2VEC_TRANSFORMERS
    )
    _ensure(config, "text2vec_transformers")  # no raise


def test_n12_named_vector_config_is_the_authoritative_surface() -> None:
    """With named vectors the legacy ``vectorizer`` field is None -- use vector_config."""

    @dataclass
    class _VecCfg:
        vectorizer: object

    @dataclass
    class _Inner:
        vectorizer: Vectorizers

    config = _ConfigView(
        properties=_schema_properties(),
        vectorizer=None,
        vector_config={"default": _VecCfg(vectorizer=_Inner(Vectorizers.TEXT2VEC_TRANSFORMERS))},
    )
    _ensure(config, "text2vec_transformers")
    drifted = _ConfigView(
        properties=_schema_properties(),
        vectorizer=None,
        vector_config={"default": _VecCfg(vectorizer=_Inner(Vectorizers.NONE))},
    )
    with pytest.raises(VectorDbWriteError, match="vectorizer 'self_provided'"):
        _ensure(drifted, "text2vec_transformers")


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


def test_n14_installed_client_routes_duplicates_through_unexpected_status_code() -> None:
    """Documents the REAL behaviour: ``insert`` does not raise ObjectAlreadyExists."""
    from weaviate.exceptions import ObjectAlreadyExistsException, UnexpectedStatusCodeError

    source = inspect.getsource(_DataCollection.insert)
    assert "UnexpectedStatusCodeError" in source
    assert "already exists" in source
    assert ObjectAlreadyExistsException is not UnexpectedStatusCodeError


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
    config = _ConfigView(properties=props, vectorizer=Vectorizers.TEXT2VEC_TRANSFORMERS)
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
    config = _ConfigView(properties=props, vectorizer=Vectorizers.TEXT2VEC_TRANSFORMERS)
    with pytest.raises(VectorDbWriteError, match="'searchable': False"):
        _ensure(config, "text2vec_transformers")


def test_n12_existing_collection_that_vectorises_the_name_fails_closed() -> None:
    @dataclass
    class _VecCfg:
        vectorizer: object

    @dataclass
    class _Inner:
        vectorizer: Vectorizers
        vectorize_collection_name: bool

    config = _ConfigView(
        properties=_schema_properties(),
        vectorizer=None,
        vector_config={
            "default": _VecCfg(
                vectorizer=_Inner(Vectorizers.TEXT2VEC_TRANSFORMERS, True)
            )
        },
    )
    with pytest.raises(VectorDbWriteError, match="collection NAME"):
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
    config = _ConfigView(properties=props, vectorizer=Vectorizers.TEXT2VEC_TRANSFORMERS)
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
