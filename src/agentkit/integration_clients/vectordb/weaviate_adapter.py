"""Thin Weaviate runtime adapter for the story knowledge base (FK-13 §13.2).

This is an ``integrations/`` *adapter*: it owns ONLY the transport to Weaviate
via the optional ``weaviate-client`` dependency. It carries no business rule --
the two-stage reconciliation, the threshold filter, the readiness *decision* and
the export indexing policy live in the app layer (``story_creation`` /
``agentkit.backend.vectordb``). The adapter never returns a silent empty result on an
outage: every transport failure raises a typed
:class:`~agentkit.integration_clients.vectordb.errors.VectorDbError` so the caller can
fail closed (FK-21 §21.4.3 / §21.11.4).

``weaviate-client`` is an OPTIONAL dependency (``pip install
'agentkit[weaviate]'``). The import is guarded; when the package is absent any
operation raises :class:`VectorDbUnavailableError` rather than crashing at import
time, so the fail-closed path stays testable without the package installed.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Protocol, runtime_checkable

from agentkit.integration_clients.vectordb.errors import (
    VectorDbUnavailableError,
    VectorDbWriteError,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

#: Fixed pre-filter search limit (FK-13 §13.5.2: "fest im Code").
DEFAULT_SEARCH_LIMIT: Final[int] = 20

#: Fixed search mode (FK-13 §13.5.2: "fest im Code").
DEFAULT_SEARCH_MODE: Final[str] = "hybrid"

#: The three effective search modes (FK-13 §13.4.2).
SEARCH_MODES: Final[tuple[str, ...]] = ("hybrid", "vector", "keyword")

#: Weaviate collection holding the indexed ``story.md`` chunks (FK-13 §13.7).
STORY_COLLECTION: Final[str] = "StoryContext"


@dataclass(frozen=True)
class StorySearchHit:
    """One similarity hit from ``story_search`` (transport-level record).

    Attributes:
        story_id: Story display-ID of the matched story (e.g. ``"AK3-042"``).
        title: Indexed story title.
        score: Similarity score in ``[0.0, 1.0]`` (higher = more similar).
        snippet: Short excerpt of the matched chunk (problem / solution text).
    """

    story_id: str
    title: str
    score: float
    snippet: str


def _require_str(raw: Mapping[str, object], key: str) -> str:
    """Return a mandatory string field, fail-closed (no empty-string repair)."""
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise VectorDbUnavailableError(
            f"Weaviate hit is missing a non-empty string {key!r} (got {value!r}); "
            "fail-closed (FK-21 §21.4.3 / AC10)."
        )
    return value


def _require_score(raw: Mapping[str, object]) -> float:
    """Return a mandatory, finite numeric score (no ``0.0`` repair, AC10)."""
    score = raw.get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise VectorDbUnavailableError(
            f"Weaviate hit has a non-numeric 'score' ({score!r}); fail-closed (AC10)."
        )
    f = float(score)
    if f != f or f in (float("inf"), float("-inf")):  # NaN / Infinity
        raise VectorDbUnavailableError(
            f"Weaviate hit has a non-finite 'score' ({f!r}); fail-closed (AC10)."
        )
    return f


@runtime_checkable
class WeaviateClientPort(Protocol):
    """Minimal transport surface the adapter needs from a Weaviate client.

    A thin seam so the fail-closed and search/sync paths stay unit-testable
    with a double at the adapter boundary (mocks exception) without requiring a
    live Weaviate or the optional ``weaviate-client`` package.
    """

    def is_ready(self) -> bool:
        """Return ``True`` when the Weaviate node reports ready."""
        ...

    def close(self) -> None:
        """Release the underlying connection."""
        ...

    def search(
        self,
        *,
        collection: str,
        query: str,
        search_mode: str,
        project_id: str,
        limit: int,
    ) -> Sequence[Mapping[str, object]]:
        """Run a similarity search; return raw hit mappings."""
        ...

    def upsert(
        self,
        *,
        collection: str,
        objects: Sequence[Mapping[str, object]],
    ) -> int:
        """Index/update objects; return the number written."""
        ...


def _coerce_hit(raw: Mapping[str, object]) -> StorySearchHit:
    """Map a raw transport mapping into a typed :class:`StorySearchHit`.

    Fail-closed: a malformed hit (missing/non-string ``story_id``/``title``/
    ``snippet``, or a non-finite ``score``) raises
    :class:`VectorDbUnavailableError` rather than degrading the result set
    silently with empty-string / ``0.0`` repairs (FK-21 §21.4.3 / AC10).
    """
    return StorySearchHit(
        story_id=_require_str(raw, "story_id"),
        title=_require_str(raw, "title"),
        snippet=_require_str(raw, "snippet"),
        score=_require_score(raw),
    )


class WeaviateStoryAdapter:
    """Thin transport adapter to the Weaviate story knowledge base.

    The adapter is constructed with an explicit :class:`WeaviateClientPort`.
    Use :meth:`connect` to build one from a host/port via the optional
    ``weaviate-client`` package (fail-closed when the package is absent).
    """

    def __init__(self, client: WeaviateClientPort) -> None:
        """Initialise the adapter with a connected client port.

        Args:
            client: A connected Weaviate client transport.
        """
        self._client = client

    @classmethod
    def connect(cls, *, host: str, port: int) -> WeaviateStoryAdapter:
        """Build an adapter from a real ``weaviate-client`` connection.

        Args:
            host: Weaviate server hostname or IP.
            port: Weaviate server HTTP port.

        Returns:
            A connected :class:`WeaviateStoryAdapter`.

        Raises:
            VectorDbUnavailableError: When ``weaviate-client`` is not installed
                (optional dependency absent) or the connection cannot be
                established (fail-closed, FK-13 §13.2).
        """
        client = _build_real_client(host=host, port=port)
        return cls(client)

    def is_ready(self) -> bool:
        """Return whether Weaviate reports ready.

        Returns:
            ``True`` if the node is ready, ``False`` otherwise. Never raises on
            a plain "not ready" answer; only a hard transport fault raises.

        Raises:
            VectorDbUnavailableError: On a transport fault while probing.
        """
        try:
            return bool(self._client.is_ready())
        except VectorDbUnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001 -- normalise any client fault
            raise VectorDbUnavailableError(
                f"Weaviate readiness probe failed: {exc} (fail-closed, FK-13 §13.2)."
            ) from exc

    def story_search(
        self,
        query: str,
        *,
        search_mode: str = DEFAULT_SEARCH_MODE,
        project_id: str,
        limit: int = DEFAULT_SEARCH_LIMIT,
    ) -> list[StorySearchHit]:
        """Run a similarity search over the story knowledge base.

        Args:
            query: The new story description to match against.
            search_mode: Search mode (``hybrid``/``vector``/``keyword``); validated
                strictly (AC10) -- never ignored.
            project_id: Project-prefix scope for the search (FK-21 §21.4.1).
            limit: Pre-filter result cap; fixed ``20`` per FK-13 §13.5.2.

        Returns:
            The transport-level hits (unfiltered; the threshold filter is an
            app-layer concern).

        Raises:
            VectorDbUnavailableError: On any transport failure, an unsupported
                search_mode, or a malformed hit -- the caller MUST treat this as a
                hard blocker, never an empty result (FK-21 §21.4.3 / AC10).
        """
        if search_mode not in SEARCH_MODES:
            raise VectorDbUnavailableError(
                f"unsupported search_mode {search_mode!r}; must be one of {SEARCH_MODES} "
                "(AC10: no leniency)."
            )
        try:
            raw_hits = self._client.search(
                collection=STORY_COLLECTION,
                query=query,
                search_mode=search_mode,
                project_id=project_id,
                limit=limit,
            )
        except VectorDbUnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001 -- normalise any client fault
            raise VectorDbUnavailableError(
                f"Weaviate story_search failed for project_id={project_id!r}: "
                f"{exc} (fail-closed: no silent empty result, FK-21 §21.4.3)."
            ) from exc
        return [_coerce_hit(hit) for hit in raw_hits]

    def story_sync(
        self,
        *,
        objects: Sequence[Mapping[str, object]],
    ) -> int:
        """Index/update story objects in the knowledge base (FK-13 §13.7).

        Args:
            objects: The story chunks to upsert (title, problem, solution,
                metadata) keyed by ``story_id``.

        Returns:
            The number of objects written.

        Raises:
            VectorDbWriteError: When the indexing write fails -- a hard blocker
                for the export (FK-21 §21.11.4, fail-closed, no catch-up).
        """
        try:
            return int(
                self._client.upsert(collection=STORY_COLLECTION, objects=objects)
            )
        except Exception as exc:  # noqa: BLE001 -- normalise any client fault
            raise VectorDbWriteError(
                f"Weaviate story_sync indexing failed for {len(objects)} object(s): "
                f"{exc} (fail-closed: indexing failure blocks export, FK-21 §21.11.4)."
            ) from exc

    def close(self) -> None:
        """Release the underlying Weaviate connection (best-effort)."""
        with contextlib.suppress(Exception):
            self._client.close()


def _build_real_client(*, host: str, port: int) -> WeaviateClientPort:
    """Build a real ``weaviate-client``-backed transport (fail-closed).

    Imported lazily and guarded so the module imports cleanly without the
    optional ``weaviate-client`` package; a missing package surfaces as a
    typed :class:`VectorDbUnavailableError` at call time.
    """
    try:
        # PLC0415: optional dependency, import-guarded.
        import weaviate  # noqa: PLC0415
    except ImportError as exc:
        raise VectorDbUnavailableError(
            "weaviate-client is not installed; the VectorDB is mandatory "
            "infrastructure (FK-13 §13.2). Install the optional extra "
            "(pip install 'agentkit[weaviate]') -- fail-closed, no silent skip."
        ) from exc

    try:
        connection = weaviate.connect_to_local(host=host, port=port)
    except Exception as exc:  # noqa: BLE001 -- any connect fault is fail-closed
        raise VectorDbUnavailableError(
            f"Could not connect to Weaviate at {host}:{port}: {exc} "
            "(fail-closed, FK-13 §13.2)."
        ) from exc
    return _RealWeaviateClient(connection)


class _RealWeaviateClient:
    """Adapts the concrete ``weaviate-client`` API to :class:`WeaviateClientPort`.

    Kept intentionally tiny: it only translates method shapes. All policy stays
    in the app layer; all error normalisation stays in
    :class:`WeaviateStoryAdapter`.
    """

    def __init__(self, connection: object) -> None:
        self._connection = connection

    @property
    def collections(self) -> Any:
        """Expose the raw collections facade for the schema-owner creator (R02)."""
        return self._connection.collections  # type: ignore[attr-defined]

    def is_ready(self) -> bool:
        is_ready = self._connection.is_ready  # type: ignore[attr-defined]
        return bool(is_ready())

    def close(self) -> None:
        close = getattr(self._connection, "close", None)
        if callable(close):
            close()

    def search(
        self,
        *,
        collection: str,
        query: str,
        search_mode: str,
        project_id: str,
        limit: int,
    ) -> Sequence[Mapping[str, object]]:
        if search_mode not in SEARCH_MODES:
            raise VectorDbUnavailableError(
                f"unsupported search_mode {search_mode!r}; must be one of {SEARCH_MODES} "
                "(AC10: no leniency)."
            )
        coll = self._connection.collections.get(collection)  # type: ignore[attr-defined]
        response = self._run_query(coll, query=query, search_mode=search_mode, limit=limit, project_id=project_id)
        hits: list[Mapping[str, object]] = []
        for obj in response.objects:
            props = dict(obj.properties)
            score = getattr(obj.metadata, "score", None)
            if score is None:
                # Missing score is a hard error, NOT a 0.0 repair (AC10).
                raise VectorDbUnavailableError(
                    f"Weaviate hit {props.get('story_id')!r} has no 'score'; fail-closed (AC10)."
                )
            hits.append(
                {
                    "story_id": props.get("story_id"),
                    "title": props.get("title"),
                    "score": score,
                    "snippet": props.get("snippet") or props.get("content"),
                }
            )
        return hits

    def _run_query(
        self, coll: Any, *, query: str, search_mode: str, limit: int, project_id: str
    ) -> Any:
        """Dispatch to the Weaviate query API for the requested search_mode.

        The three effective modes (FK-13 §13.4.2) map to distinct Weaviate query
        kinds; search_mode is NEVER ignored. Server-side vectorisation is done by
        the configured text2vec module.
        """
        from weaviate.classes.query import Filter  # noqa: PLC0415 (optional dependency)

        flt = Filter.by_property("project_id").equal(project_id)
        if search_mode == "hybrid":
            return coll.query.hybrid(
                query=query, limit=limit, filters=flt, return_metadata=["score"]
            )
        if search_mode == "keyword":
            return coll.query.bm25(
                query=query, limit=limit, filters=flt
            )
        # vector
        return coll.query.near_text(
            query=query, limit=limit, filters=flt, return_metadata=["score"]
        )

    def upsert(
        self,
        *,
        collection: str,
        objects: Sequence[Mapping[str, object]],
    ) -> int:
        """Batch insert objects; return the EXACT count confirmed written (R12).

        Objects MAY carry a ``uuid`` key (deterministic identity) which is passed
        to ``add_object``. ``batch.failed_objects`` is inspected so a partial
        batch is NOT reported as success.
        """
        coll = self._connection.collections.get(collection)  # type: ignore[attr-defined]
        with coll.batch.dynamic() as batch:
            for obj in objects:
                props = {k: v for k, v in obj.items() if k != "uuid"}
                uid = obj.get("uuid")
                if uid:
                    batch.add_object(properties=props, uuid=str(uid))
                else:
                    batch.add_object(properties=props)
        failed = getattr(coll.batch, "failed_objects", []) or []
        if failed:
            raise VectorDbWriteError(
                f"batch insert had {len(failed)} failed object(s); "
                f"first: {getattr(failed[0], 'message', failed[0])!r} (R12 partial write)."
            )
        return len(objects)

    def fetch_by_property(
        self,
        *,
        collection: str,
        prop: str,
        value: str,
        return_props: Sequence[str],
    ) -> Sequence[tuple[str, dict[str, object]]]:
        """Fetch ``(uuid, properties)`` for objects where ``prop == value`` (paginated)."""
        from weaviate.classes.query import Filter  # noqa: PLC0415 (optional dependency)

        coll = self._connection.collections.get(collection)  # type: ignore[attr-defined]
        result = coll.query.fetch_objects(
            filters=Filter.by_property(prop).equal(value),
            return_properties=list(return_props),
            limit=10000,
        )
        out: list[tuple[str, dict[str, object]]] = []
        for obj in result.objects:
            out.append((str(obj.uuid), dict(obj.properties)))
        return out

    def fetch_by_property_any(
        self,
        *,
        collection: str,
        prop: str,
        values: Sequence[str],
        return_props: Sequence[str],
    ) -> Sequence[tuple[str, dict[str, object]]]:
        """Fetch ``(uuid, properties)`` where ``prop`` is in ``values`` (paginated)."""
        from weaviate.classes.query import Filter  # noqa: PLC0415 (optional dependency)

        coll = self._connection.collections.get(collection)  # type: ignore[attr-defined]
        result = coll.query.fetch_objects(
            filters=Filter.by_property(prop).contains_any(list(values)),
            return_properties=list(return_props),
            limit=10000,
        )
        out: list[tuple[str, dict[str, object]]] = []
        for obj in result.objects:
            out.append((str(obj.uuid), dict(obj.properties)))
        return out

    def delete_by_ids(self, *, collection: str, uuids: Sequence[str]) -> int:
        """Delete objects by uuid; return the EXACT count confirmed deleted (R12)."""
        coll = self._connection.collections.get(collection)  # type: ignore[attr-defined]
        deleted = 0
        for uid in uuids:
            try:
                coll.data.delete_by_id(str(uid))
                deleted += 1
            except Exception as exc:  # noqa: BLE001 -- surface partial delete
                raise VectorDbWriteError(
                    f"delete failed for {uid!r}: {exc} (R12 partial delete)."
                ) from exc
        return deleted

    def ensure_collection(self, *, collection: str, property_specs: Sequence[Mapping[str, object]]) -> None:
        """Create a collection idempotently from the schema-owner's specs (R02)."""
        from weaviate.classes.config import (  # noqa: PLC0415 (optional dependency)
            Configure,
            DataType,
            Property,
            Tokenization,
        )

        collections = self._connection.collections  # type: ignore[attr-defined]
        if collections.exists(collection):
            return
        _type_map = {"TEXT": DataType.TEXT, "BOOL": DataType.BOOL, "TEXT[]": DataType.TEXT_ARRAY}
        properties = [
            Property(
                name=str(spec["name"]),
                data_type=_type_map[str(spec["data_type"])],
                tokenization=Tokenization.FIELD,
                skip_vectorization=bool(spec["skip_vectorization"]),
            )
            for spec in property_specs
        ]
        collections.create(
            name=collection,
            vector_config=Configure.Vectors.self_provided(),
            properties=properties,
        )


def _project_filter(project_id: str) -> object:
    """Build a project-scope filter for the Weaviate query (kept for callers)."""
    from weaviate.classes.query import Filter  # noqa: PLC0415 (optional dependency)

    return Filter.by_property("project_id").equal(project_id)


__all__ = [
    "DEFAULT_SEARCH_LIMIT",
    "DEFAULT_SEARCH_MODE",
    "SEARCH_MODES",
    "STORY_COLLECTION",
    "StorySearchHit",
    "WeaviateClientPort",
    "WeaviateStoryAdapter",
]
