"""Unit tests for the thin Weaviate story adapter (AG3-068 / FK-13 §13.2).

Mocks live ONLY at the adapter's client boundary (``WeaviateClientPort``) -- the
mocks exception (LLM/Weaviate boundary only). The adapter's fail-closed error
normalisation and hit coercion run for real.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.integration_clients.vectordb import (
    VectorDbUnavailableError,
    VectorDbWriteError,
    WeaviateStoryAdapter,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


class _FakeClient:
    """Test double at the Weaviate transport boundary."""

    def __init__(
        self,
        *,
        ready: bool = True,
        hits: Sequence[Mapping[str, object]] | None = None,
        raise_on_search: bool = False,
        raise_on_upsert: bool = False,
        raise_on_ready: bool = False,
    ) -> None:
        self._ready = ready
        self._hits = list(hits or [])
        self._raise_on_search = raise_on_search
        self._raise_on_upsert = raise_on_upsert
        self._raise_on_ready = raise_on_ready
        self.closed = False

    def is_ready(self) -> bool:
        if self._raise_on_ready:
            raise RuntimeError("node down")
        return self._ready

    def close(self) -> None:
        self.closed = True

    def search(
        self,
        *,
        collection: str,
        query: str,
        search_mode: str,
        project_id: str,
        limit: int,
    ) -> Sequence[Mapping[str, object]]:
        del collection, query, search_mode, project_id, limit
        if self._raise_on_search:
            raise RuntimeError("connection refused")
        return self._hits

    def upsert(
        self,
        *,
        collection: str,
        objects: Sequence[Mapping[str, object]],
    ) -> int:
        del collection
        if self._raise_on_upsert:
            raise RuntimeError("write rejected")
        return len(objects)


def test_is_ready_true() -> None:
    adapter = WeaviateStoryAdapter(_FakeClient(ready=True))
    assert adapter.is_ready() is True


def test_is_ready_false_does_not_raise() -> None:
    adapter = WeaviateStoryAdapter(_FakeClient(ready=False))
    assert adapter.is_ready() is False


def test_is_ready_transport_fault_fails_closed() -> None:
    adapter = WeaviateStoryAdapter(_FakeClient(raise_on_ready=True))
    with pytest.raises(VectorDbUnavailableError):
        adapter.is_ready()


def test_story_search_coerces_hits() -> None:
    client = _FakeClient(
        hits=[
            {"story_id": "AG3-001", "title": "T1", "score": 0.91, "snippet": "s1"},
            {"story_id": "AG3-002", "title": "T2", "score": 0.42, "snippet": "s2"},
        ]
    )
    adapter = WeaviateStoryAdapter(client)
    hits = adapter.story_search("query", project_id="AG3", limit=20)
    assert [h.story_id for h in hits] == ["AG3-001", "AG3-002"]
    assert hits[0].score == pytest.approx(0.91)


def test_story_search_unavailable_blocks_fail_closed() -> None:
    """NEGATIVE: Weaviate outage raises, never a silent empty result (§21.4.3)."""
    adapter = WeaviateStoryAdapter(_FakeClient(raise_on_search=True))
    with pytest.raises(VectorDbUnavailableError):
        adapter.story_search("query", project_id="AG3", limit=20)


def test_story_search_malformed_hit_fails_closed() -> None:
    adapter = WeaviateStoryAdapter(
        _FakeClient(hits=[{"title": "no id", "score": 0.9}])
    )
    with pytest.raises(VectorDbUnavailableError):
        adapter.story_search("query", project_id="AG3", limit=20)


def test_story_sync_returns_count() -> None:
    adapter = WeaviateStoryAdapter(_FakeClient())
    written = adapter.story_sync(objects=[{"story_id": "AG3-001"}])
    assert written == 1


def test_story_sync_write_failure_blocks_fail_closed() -> None:
    """NEGATIVE: an indexing write failure raises a typed write error."""
    adapter = WeaviateStoryAdapter(_FakeClient(raise_on_upsert=True))
    with pytest.raises(VectorDbWriteError):
        adapter.story_sync(objects=[{"story_id": "AG3-001"}])


def test_close_is_best_effort() -> None:
    client = _FakeClient()
    adapter = WeaviateStoryAdapter(client)
    adapter.close()
    assert client.closed is True


def test_close_swallows_errors() -> None:
    class _Boom:
        def close(self) -> None:
            raise RuntimeError("nope")

    # close() must never raise (best-effort).
    WeaviateStoryAdapter(_Boom()).close()  # type: ignore[arg-type]


def test_connect_connection_failure_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """NEGATIVE: a connect fault (package present) surfaces as unavailable."""
    import sys
    import types

    fake_weaviate = types.ModuleType("weaviate")

    def _boom(**_kwargs: object) -> object:
        raise OSError("connection refused")

    fake_weaviate.connect_to_local = _boom  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "weaviate", fake_weaviate)
    with pytest.raises(VectorDbUnavailableError):
        WeaviateStoryAdapter.connect(host="localhost", port=8080)


def test_connect_without_weaviate_client_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """NEGATIVE: a missing weaviate-client surfaces as VectorDbUnavailableError."""
    import builtins

    real_import = builtins.__import__

    def _fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "weaviate" or name.startswith("weaviate."):
            raise ImportError("No module named 'weaviate'")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    with pytest.raises(VectorDbUnavailableError):
        WeaviateStoryAdapter.connect(host="localhost", port=8080)


# ---------------------------------------------------------------------------
# _RealWeaviateClient shape translation (duck-typed connection, no live server)
# ---------------------------------------------------------------------------


class _FakeMetadata:
    def __init__(self, score: float | None) -> None:
        self.score = score


class _FakeObj:
    def __init__(self, properties: dict[str, object], score: float | None) -> None:
        self.properties = properties
        self.metadata = _FakeMetadata(score)


class _FakeResponse:
    def __init__(self, objects: list[_FakeObj]) -> None:
        self.objects = objects


class _FakeQuery:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.last_kwargs: dict[str, object] = {}

    def hybrid(self, **kwargs: object) -> _FakeResponse:
        self.last_kwargs = kwargs
        return self._response


class _FakeBatchCtx:
    def __init__(self) -> None:
        self.added: list[dict[str, object]] = []

    def __enter__(self) -> _FakeBatchCtx:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def add_object(self, *, properties: dict[str, object]) -> None:
        self.added.append(properties)


class _FakeBatch:
    def __init__(self, ctx: _FakeBatchCtx) -> None:
        self._ctx = ctx

    def dynamic(self) -> _FakeBatchCtx:
        return self._ctx


class _FakeCollection:
    def __init__(self, *, query: _FakeQuery, batch: _FakeBatch) -> None:
        self.query = query
        self.batch = batch


class _FakeCollections:
    def __init__(self, collection: _FakeCollection) -> None:
        self._collection = collection
        self.requested: list[str] = []

    def get(self, name: str) -> _FakeCollection:
        self.requested.append(name)
        return self._collection


class _FakeConnection:
    def __init__(self, collection: _FakeCollection, *, ready: bool = True) -> None:
        self.collections = _FakeCollections(collection)
        self._ready = ready
        self.closed = False

    def is_ready(self) -> bool:
        return self._ready

    def close(self) -> None:
        self.closed = True


def _install_fake_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject a fake ``weaviate.classes.query.Filter`` so ``_project_filter`` runs."""
    import sys
    import types

    weaviate_mod = types.ModuleType("weaviate")
    classes_mod = types.ModuleType("weaviate.classes")
    query_mod = types.ModuleType("weaviate.classes.query")

    class _FilterBuilder:
        def __init__(self, prop: str) -> None:
            self.prop = prop

        def equal(self, value: object) -> tuple[str, object]:
            return (self.prop, value)

    class _Filter:
        @staticmethod
        def by_property(prop: str) -> _FilterBuilder:
            return _FilterBuilder(prop)

    query_mod.Filter = _Filter  # type: ignore[attr-defined]
    classes_mod.query = query_mod  # type: ignore[attr-defined]
    weaviate_mod.classes = classes_mod  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "weaviate", weaviate_mod)
    monkeypatch.setitem(sys.modules, "weaviate.classes", classes_mod)
    monkeypatch.setitem(sys.modules, "weaviate.classes.query", query_mod)


def _real_client(connection: _FakeConnection) -> object:
    from agentkit.integration_clients.vectordb.weaviate_adapter import _RealWeaviateClient

    return _RealWeaviateClient(connection)


def test_real_client_search_maps_properties_and_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_filter(monkeypatch)
    query = _FakeQuery(
        _FakeResponse(
            [
                _FakeObj(
                    {"story_id": "AG3-001", "title": "T1", "snippet": "s1"}, 0.88
                ),
                _FakeObj({"story_id": "AG3-002", "title": "T2"}, None),
            ]
        )
    )
    collection = _FakeCollection(query=query, batch=_FakeBatch(_FakeBatchCtx()))
    connection = _FakeConnection(collection)
    adapter = WeaviateStoryAdapter(_real_client(connection))  # type: ignore[arg-type]

    hits = adapter.story_search("q", project_id="AG3", limit=20)

    assert [h.story_id for h in hits] == ["AG3-001", "AG3-002"]
    assert hits[0].score == pytest.approx(0.88)
    assert hits[1].score == pytest.approx(0.0)  # missing score => 0.0
    assert connection.collections.requested == ["StoryContext"]
    assert query.last_kwargs["query"] == "q"
    assert query.last_kwargs["limit"] == 20


def test_real_client_upsert_counts_objects() -> None:
    ctx = _FakeBatchCtx()
    collection = _FakeCollection(
        query=_FakeQuery(_FakeResponse([])), batch=_FakeBatch(ctx)
    )
    connection = _FakeConnection(collection)
    adapter = WeaviateStoryAdapter(_real_client(connection))  # type: ignore[arg-type]

    written = adapter.story_sync(objects=[{"story_id": "A"}, {"story_id": "B"}])

    assert written == 2
    assert [o["story_id"] for o in ctx.added] == ["A", "B"]


def test_real_client_is_ready_and_close() -> None:
    collection = _FakeCollection(
        query=_FakeQuery(_FakeResponse([])), batch=_FakeBatch(_FakeBatchCtx())
    )
    connection = _FakeConnection(collection, ready=True)
    adapter = WeaviateStoryAdapter(_real_client(connection))  # type: ignore[arg-type]

    assert adapter.is_ready() is True
    adapter.close()
    assert connection.closed is True


def test_connect_builds_real_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """The connect() happy path returns an adapter over a _RealWeaviateClient."""
    import sys
    import types

    collection = _FakeCollection(
        query=_FakeQuery(_FakeResponse([])), batch=_FakeBatch(_FakeBatchCtx())
    )
    connection = _FakeConnection(collection)

    fake_weaviate = types.ModuleType("weaviate")
    fake_weaviate.connect_to_local = (  # type: ignore[attr-defined]
        lambda **_kwargs: connection
    )
    monkeypatch.setitem(sys.modules, "weaviate", fake_weaviate)

    adapter = WeaviateStoryAdapter.connect(host="localhost", port=8080)
    assert adapter.is_ready() is True
