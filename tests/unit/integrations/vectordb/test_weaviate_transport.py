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
from typing import TYPE_CHECKING, Any

import pytest
import weaviate
from weaviate.classes.config import DataType
from weaviate.collections.classes.config import Vectorizers, _Property
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

if TYPE_CHECKING:
    from collections.abc import Sequence

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
        "story_type": "implementation", "source_type": "story",
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


def _read_property(name: str, data_type: DataType) -> _Property:
    """Build a REAL read-side ``_Property`` (the shape ``config.get()`` returns)."""
    return _Property(
        name=name,
        description=None,
        data_type=data_type,
        index_filterable=True,
        index_range_filters=False,
        index_searchable=False,
        nested_properties=None,
        text_analyzer=None,
        tokenization=None,
        vectorizer_config=None,
        vectorizer=None,
        vectorizer_configs=None,
    )


def _schema_properties() -> list[_Property]:
    type_map = {"TEXT": DataType.TEXT, "BOOL": DataType.BOOL, "TEXT[]": DataType.TEXT_ARRAY}
    return [
        _read_property(str(spec["name"]), type_map[str(spec["data_type"])])
        for spec in weaviate_property_specs()
    ]


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
    with pytest.raises(VectorDbWriteError, match="property set drifted"):
        _ensure(config, "text2vec_transformers")


def test_n12_existing_collection_with_wrong_data_type_fails_closed() -> None:
    props = _schema_properties()
    props[0] = _read_property(str(props[0].name), DataType.BOOL)
    config = _ConfigView(properties=props, vectorizer=Vectorizers.TEXT2VEC_TRANSFORMERS)
    with pytest.raises(VectorDbWriteError, match="wrong_data_type"):
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


def _names(specs: Sequence[dict[str, object]]) -> set[str]:
    return {str(s["name"]) for s in specs}
