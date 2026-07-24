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

#: gRPC port documented for the Weaviate container in FK-13 §13.2.
FK13_GRPC_PORT: Final[int] = 50051

#: Page size for filtered full reads (the set is paged, never truncated, AC10).
FETCH_PAGE_SIZE: Final[int] = 1000

#: Hard ceiling for one filtered result set; beyond it the read fails closed.
MAX_FETCH_OBJECTS: Final[int] = 200_000

#: Schema data-type token -> the Weaviate wire name reported by the server.
WEAVIATE_DATA_TYPE_NAMES: Final[dict[str, str]] = {
    "TEXT": "text",
    "BOOL": "boolean",
    "TEXT[]": "text[]",
}

#: Schema data-type token -> the python type a returned property must have.
_EXPECTED_PROPERTY_TYPES: Final[dict[str, type]] = {
    "TEXT": str,
    "BOOL": bool,
    "TEXT[]": list,
}


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
    def connect(
        cls,
        *,
        host: str,
        port: int,
        grpc_host: str | None = None,
        grpc_port: int = FK13_GRPC_PORT,
    ) -> WeaviateStoryAdapter:
        """Build an adapter from a real ``weaviate-client`` connection.

        Args:
            host: Weaviate server hostname or IP (HTTP endpoint).
            port: Weaviate server HTTP port.
            grpc_host: gRPC hostname; defaults to ``host`` (single-host
                deployment as documented in FK-13 §13.2). The MCP runtime never
                uses this default -- it passes both endpoints explicitly from the
                registered env (D2).
            grpc_port: gRPC port; defaults to the FK-13 §13.2 documented
                ``50051``.

        Returns:
            A connected :class:`WeaviateStoryAdapter`.

        Raises:
            VectorDbUnavailableError: When ``weaviate-client`` is not installed
                or the connection cannot be established (fail-closed, FK-13
                §13.2).
        """
        client = _build_real_client(
            http_host=host,
            http_port=port,
            http_secure=False,
            grpc_host=grpc_host if grpc_host else host,
            grpc_port=grpc_port,
            grpc_secure=False,
        )
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


def _build_real_client(
    *,
    http_host: str,
    http_port: int,
    http_secure: bool,
    grpc_host: str,
    grpc_port: int,
    grpc_secure: bool,
) -> WeaviateClientPort:
    """Build a real ``weaviate-client``-backed transport (fail-closed, R03).

    The pinned ``weaviate-client`` (>=4.9,<5.0) does NOT accept a distinct gRPC
    HOST in ``connect_to_local`` -- that helper derives the gRPC host from the
    single ``host`` argument. Passing ``grpc_host`` to it is a ``TypeError``
    against the real library. To honour BOTH env-bound endpoints verbatim (D2)
    the adapter therefore uses ``weaviate.connect_to_custom``, the only connect
    API that takes the HTTP and gRPC endpoints independently.

    All six values are supplied by the caller; nothing is defaulted here.
    """
    try:
        # PLC0415: transport dependency, import-guarded so the module imports
        # cleanly and a missing package surfaces as a typed error at call time.
        import weaviate  # noqa: PLC0415
    except ImportError as exc:
        raise VectorDbUnavailableError(
            "weaviate-client is not installed; the VectorDB is mandatory "
            "infrastructure (FK-13 §13.2) -- fail-closed, no silent skip."
        ) from exc

    try:
        connection = weaviate.connect_to_custom(
            http_host=http_host,
            http_port=http_port,
            http_secure=http_secure,
            grpc_host=grpc_host,
            grpc_port=grpc_port,
            grpc_secure=grpc_secure,
        )
    except Exception as exc:  # noqa: BLE001 -- any connect fault is fail-closed
        raise VectorDbUnavailableError(
            f"Could not connect to Weaviate at {http_host}:{http_port} "
            f"(grpc {grpc_host}:{grpc_port}): {exc} (fail-closed, FK-13 §13.2)."
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
        """Story-shaped legacy search (project-scoped). See :meth:`search_objects`
        for the full-property, source_type+filter-scoped retrieval (N01/R05)."""
        if search_mode not in SEARCH_MODES:
            raise VectorDbUnavailableError(
                f"unsupported search_mode {search_mode!r}; must be one of {SEARCH_MODES} "
                "(AC10: no leniency)."
            )
        coll = self._connection.collections.get(collection)  # type: ignore[attr-defined]
        from weaviate.classes.query import Filter  # noqa: PLC0415 (optional dependency)

        response = self._run_query(
            coll, query=query, search_mode=search_mode, limit=limit,
            flt=Filter.by_property("project_id").equal(project_id),
        )
        return self._coerce_response(response, search_mode)

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
        """Full-property retrieval scoped by project_id AND source_type AND typed
        filters (N01/R02/R05). Returns ``(uuid, properties, score)`` triples.

        Every filter (status, story_type, concept_status, is_appendix,
        concept_id, module) is applied as a hard Weaviate filter -- none is
        ignored.

        ``property_spec`` is the caller's source-type profile as
        ``(name, data_type, non_empty)`` triples. Every entry MUST be present and
        correctly typed on every hit: a missing or wrongly-typed required
        property is a NAMED hard error -- there is no ``setdefault`` repair
        default (AC10 / N11). The ranking metric is the one the requested mode
        actually produces (N02).
        """
        if search_mode not in SEARCH_MODES:
            raise VectorDbUnavailableError(
                f"unsupported search_mode {search_mode!r} (AC10)."
            )
        from weaviate.classes.query import Filter  # noqa: PLC0415 (transport dependency)

        coll = self._connection.collections.get(collection)  # type: ignore[attr-defined]
        parts = [
            Filter.by_property("project_id").equal(project_id),
            Filter.by_property("source_type").equal(source_type),
        ]
        for prop, value in filters.items():
            if isinstance(value, bool):
                parts.append(Filter.by_property(prop).equal(value))
            else:
                parts.append(Filter.by_property(prop).equal(str(value)))
        flt = Filter.all_of(parts) if len(parts) > 1 else parts[0]
        response = self._run_query(
            coll,
            query=query,
            search_mode=search_mode,
            limit=limit,
            flt=flt,
            property_spec=property_spec,
        )
        out: list[tuple[str, dict[str, object], float]] = []
        for obj in response.objects:
            uid = str(obj.uuid)
            props = _validated_hit_properties(uid, dict(obj.properties), property_spec)
            out.append((uid, props, _ranking_metric(obj, search_mode)))
        return out

    def _run_query(
        self,
        coll: Any,
        *,
        query: str,
        search_mode: str,
        limit: int,
        flt: Any,
        property_spec: Sequence[tuple[str, str, bool]] = (),
    ) -> Any:
        """Dispatch to the Weaviate query API for the requested search_mode.

        The three effective modes (FK-13 §13.4.2) map to distinct Weaviate query
        kinds; search_mode is NEVER ignored. Server-side vectorisation is done by
        the configured text2vec module (FK-13 §13.2, N02).

        The requested metadata matches what the mode actually yields (N02):
        ``hybrid`` and ``keyword`` (bm25) yield ``score`` (higher = better) --
        bm25 MUST request it explicitly or the response carries none --, while
        ``vector`` (near_text) ranks by ``distance`` (lower = closer).
        """
        return_properties = [name for name, _dt, _ne in property_spec] or None
        if search_mode == "hybrid":
            return coll.query.hybrid(
                query=query,
                limit=limit,
                filters=flt,
                return_properties=return_properties,
                return_metadata=["score"],
            )
        if search_mode == "keyword":
            return coll.query.bm25(
                query=query,
                limit=limit,
                filters=flt,
                return_properties=return_properties,
                return_metadata=["score"],
            )
        # vector: near_text ranks by VECTOR DISTANCE, not by score (N02).
        return coll.query.near_text(
            query=query,
            limit=limit,
            filters=flt,
            return_properties=return_properties,
            return_metadata=["distance"],
        )

    def _coerce_response(
        self, response: Any, search_mode: str = DEFAULT_SEARCH_MODE
    ) -> Sequence[Mapping[str, object]]:
        hits: list[Mapping[str, object]] = []
        for obj in response.objects:
            props = dict(obj.properties)
            hits.append(
                {
                    "story_id": props.get("story_id"),
                    "title": props.get("title"),
                    "score": _ranking_metric(obj, search_mode),
                    "snippet": props.get("snippet") or props.get("content"),
                }
            )
        return hits

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
        """Fetch ``(uuid, properties)`` for objects where ``prop == value``."""
        from weaviate.classes.query import Filter  # noqa: PLC0415 (transport dependency)

        return self._fetch_all_pages(
            collection=collection,
            flt=Filter.by_property(prop).equal(value),
            return_props=return_props,
        )

    def fetch_by_property_any(
        self,
        *,
        collection: str,
        prop: str,
        values: Sequence[str],
        return_props: Sequence[str],
    ) -> Sequence[tuple[str, dict[str, object]]]:
        """Fetch ``(uuid, properties)`` where ``prop`` is in ``values``."""
        from weaviate.classes.query import Filter  # noqa: PLC0415 (transport dependency)

        return self._fetch_all_pages(
            collection=collection,
            flt=Filter.by_property(prop).contains_any(list(values)),
            return_props=return_props,
        )

    def _fetch_all_pages(
        self,
        *,
        collection: str,
        flt: Any,
        return_props: Sequence[str],
    ) -> Sequence[tuple[str, dict[str, object]]]:
        """Read a filtered result set COMPLETELY, page by page (AC10 pagination).

        A single capped ``limit`` would silently truncate a large corpus, which
        would make the delete closure miss objects. Pages are read until a short
        page ends the set; a set larger than :data:`MAX_FETCH_OBJECTS` is a hard,
        named error rather than a silently truncated answer. A page that returns
        MORE objects than requested is malformed pagination and also fails closed.
        """
        coll = self._connection.collections.get(collection)  # type: ignore[attr-defined]
        out: list[tuple[str, dict[str, object]]] = []
        offset = 0
        while True:
            page = coll.query.fetch_objects(
                filters=flt,
                return_properties=list(return_props),
                limit=FETCH_PAGE_SIZE,
                offset=offset,
            )
            objects = list(page.objects)
            if len(objects) > FETCH_PAGE_SIZE:
                raise VectorDbUnavailableError(
                    f"Weaviate returned {len(objects)} objects for a page of "
                    f"{FETCH_PAGE_SIZE}; malformed pagination (fail-closed, AC10)."
                )
            for obj in objects:
                out.append((str(obj.uuid), dict(obj.properties)))
            if len(objects) < FETCH_PAGE_SIZE:
                return out
            offset += FETCH_PAGE_SIZE
            if offset >= MAX_FETCH_OBJECTS:
                raise VectorDbUnavailableError(
                    f"filtered result set exceeds {MAX_FETCH_OBJECTS} objects in "
                    f"{collection!r}; refusing a truncated answer (fail-closed, AC10)."
                )

    def insert_object(
        self, *, collection: str, uuid: str, properties: Mapping[str, object]
    ) -> bool:
        """Conditionally CREATE one object; ``False`` when the uuid already exists.

        This is the store-level atomic compare-and-create primitive the source
        claim relies on (N03/D3): Weaviate rejects an insert for an existing
        object id with ``ObjectAlreadyExistsException``. The rejection is the
        LOSER signal of a genuine race -- it is never turned into an upsert.

        Raises:
            VectorDbWriteError: On any other write fault (fail-closed).
        """
        from weaviate.exceptions import (  # noqa: PLC0415 (transport dependency)
            ObjectAlreadyExistsException,
        )

        coll = self._connection.collections.get(collection)  # type: ignore[attr-defined]
        try:
            coll.data.insert(properties=dict(properties), uuid=uuid)
        except ObjectAlreadyExistsException:
            return False
        except Exception as exc:  # noqa: BLE001 -- normalise any client fault
            raise VectorDbWriteError(
                f"conditional insert of {uuid!r} into {collection!r} failed: {exc} "
                "(fail-closed, N03)."
            ) from exc
        return True

    def delete_by_ids(self, *, collection: str, uuids: Sequence[str]) -> int:
        """Delete objects by uuid; return the EXACT count confirmed deleted (R12).

        ``Collection.data.delete_by_id`` returns a BOOL: ``False`` means the uuid
        was not present, so nothing was deleted. Only a ``True`` return increments
        the counter -- an unconditional increment would report a phantom delete
        and let a partial window pass as complete (R12).
        """
        coll = self._connection.collections.get(collection)  # type: ignore[attr-defined]
        deleted = 0
        for uid in uuids:
            try:
                confirmed = coll.data.delete_by_id(str(uid))
            except Exception as exc:  # noqa: BLE001 -- surface partial delete
                raise VectorDbWriteError(
                    f"delete failed for {uid!r}: {exc} (R12 partial delete)."
                ) from exc
            if confirmed:
                deleted += 1
        return deleted

    def ensure_collection(
        self,
        *,
        collection: str,
        property_specs: Sequence[Mapping[str, object]],
        vectorizer: str = "self_provided",
    ) -> None:
        """Create OR VERIFY a collection against the schema-owner's specs (R02/N12).

        ``vectorizer`` selects the FK-13 §13.2 server-side ``text2vec_transformers``
        (StoryContext) vs ``self_provided`` (auxiliary collections like receipts).

        An EXISTING collection is not accepted blindly (N12): its configured
        property set and vectorizer are read back and compared against the schema
        SSOT. Any drift (a missing/extra property, a wrong data type, or a
        ``self_provided`` collection where ``text2vec_transformers`` is required)
        fails closed -- otherwise a drifted collection would pass composition and
        only break later inside the semantic search modes.
        """
        from weaviate.classes.config import (  # noqa: PLC0415 (transport dependency)
            Configure,
            DataType,
            Property,
            Tokenization,
        )

        collections = self._connection.collections  # type: ignore[attr-defined]
        if collections.exists(collection):
            self._verify_existing_collection(
                collections, collection, property_specs, vectorizer
            )
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
        if vectorizer == "text2vec_transformers":
            vector_config = Configure.Vectors.text2vec_transformers(
                pooling_strategy="masked_mean", vectorize_collection_name=False
            )
        else:
            vector_config = Configure.Vectors.self_provided()
        collections.create(
            name=collection,
            vector_config=vector_config,
            properties=properties,
        )

    def _verify_existing_collection(
        self,
        collections: Any,
        collection: str,
        property_specs: Sequence[Mapping[str, object]],
        vectorizer: str,
    ) -> None:
        """Fail closed when an existing collection drifts from the SSOT (N12)."""
        try:
            config = collections.get(collection).config.get()
        except Exception as exc:  # noqa: BLE001 -- unreadable config is fail-closed
            raise VectorDbWriteError(
                f"could not read the configuration of existing collection "
                f"{collection!r}: {exc} (fail-closed, N12)."
            ) from exc
        configured_vectorizer = _configured_vectorizer(config)
        required_vectorizer = _canonical_vectorizer(vectorizer)
        if configured_vectorizer != required_vectorizer:
            raise VectorDbWriteError(
                f"collection {collection!r} has vectorizer {configured_vectorizer!r} "
                f"but the schema requires {required_vectorizer!r}; fail-closed "
                "(N12: a drifted collection must not pass composition)."
            )
        configured_properties = _configured_properties(config)
        expected_properties = {
            str(spec["name"]): WEAVIATE_DATA_TYPE_NAMES[str(spec["data_type"])]
            for spec in property_specs
        }
        if configured_properties != expected_properties:
            missing = sorted(set(expected_properties) - set(configured_properties))
            extra = sorted(set(configured_properties) - set(expected_properties))
            wrong_type = sorted(
                name
                for name, data_type in expected_properties.items()
                if name in configured_properties
                and configured_properties[name] != data_type
            )
            raise VectorDbWriteError(
                f"collection {collection!r} property set drifted from the schema "
                f"SSOT: missing={missing}, unexpected={extra}, "
                f"wrong_data_type={wrong_type}; fail-closed (N12)."
            )


def _configured_vectorizer(config: Any) -> str:
    """Return the canonical vectorizer name of an existing collection (N12).

    ``vector_config`` (named vectors) is the authoritative surface of the pinned
    client; the legacy ``vectorizer`` field is consulted only when no named
    vector config is present.
    """
    vector_config = getattr(config, "vector_config", None)
    entries: list[Any] = []
    if isinstance(vector_config, dict):
        entries = list(vector_config.values())
    elif vector_config:
        entries = list(vector_config)
    names = {
        _canonical_vectorizer(
            _enum_value(getattr(getattr(entry, "vectorizer", None), "vectorizer", None))
        )
        for entry in entries
    }
    names.discard("")
    if not names:
        return _canonical_vectorizer(_enum_value(getattr(config, "vectorizer", None)))
    if len(names) > 1:
        raise VectorDbWriteError(
            f"collection carries multiple vectorizers {sorted(names)}; fail-closed (N12)."
        )
    return names.pop()


def _configured_properties(config: Any) -> dict[str, str]:
    """Map an existing collection's property names to their Weaviate type names."""
    out: dict[str, str] = {}
    for prop in getattr(config, "properties", None) or []:
        name = str(getattr(prop, "name", ""))
        if not name:
            continue
        out[name] = _enum_value(getattr(prop, "data_type", None))
    return out


def _enum_value(value: Any) -> str:
    """Return an enum's ``value`` (or its string form) as a plain string."""
    if value is None:
        return ""
    return str(getattr(value, "value", value))


def _canonical_vectorizer(raw: str) -> str:
    """Normalise a vectorizer name to the schema token used by the app layer."""
    token = raw.strip().lower().replace("-", "_")
    if token in {"", "none"}:
        return "self_provided"
    return token


def _validated_hit_properties(
    uid: str,
    props: dict[str, object],
    property_spec: Sequence[tuple[str, str, bool]],
) -> dict[str, object]:
    """Validate a hit's properties against the caller's profile (N11/AC10).

    Every profile entry MUST be present and of the declared type; entries marked
    ``non_empty`` must additionally carry a value. There is NO repair default: a
    malformed hit raises instead of being returned as empty-but-successful.
    """
    for name, data_type, non_empty in property_spec:
        if name not in props:
            raise VectorDbUnavailableError(
                f"Weaviate hit {uid!r} is missing the required property {name!r} "
                "(no repair default; fail-closed, AC10/N11)."
            )
        value = props[name]
        expected = _EXPECTED_PROPERTY_TYPES[data_type]
        # bool is a subclass of int: never let a boolean satisfy another type.
        valid = (
            isinstance(value, bool)
            if expected is bool
            else isinstance(value, expected) and not isinstance(value, bool)
        )
        if not valid:
            raise VectorDbUnavailableError(
                f"Weaviate hit {uid!r} property {name!r} is "
                f"{type(value).__name__}, expected {expected.__name__} "
                "(no coercion; fail-closed, AC10/N11)."
            )
        if non_empty and not value:
            raise VectorDbUnavailableError(
                f"Weaviate hit {uid!r} property {name!r} is empty but mandatory "
                "(fail-closed, AC10/N11)."
            )
    return props


def _ranking_metric(obj: Any, search_mode: str) -> float:
    """Return the ranking metric the requested search mode actually yields (N02).

    - ``hybrid`` / ``keyword`` (bm25): ``metadata.score`` (higher = better).
    - ``vector`` (near_text): ``metadata.distance`` (lower = closer), mapped
      monotonically onto ``1/(1+distance)`` so the app layer can compare it with
      the score-based modes.

    A missing or non-finite metric is a hard, named error (AC10) -- never a
    ``0.0`` repair, and never the WRONG metric for the mode.
    """
    meta = getattr(obj, "metadata", None)
    if search_mode == "vector":
        distance = getattr(meta, "distance", None) if meta is not None else None
        if distance is None or isinstance(distance, bool) or not isinstance(distance, (int, float)):
            raise VectorDbUnavailableError(
                f"near_text hit has no numeric 'distance' (got {distance!r}); "
                "vector search ranks by distance, not score (fail-closed, AC10/N02)."
            )
        value = float(distance)
        if value != value or value in (float("inf"), float("-inf")):
            raise VectorDbUnavailableError(
                "near_text hit has a non-finite 'distance'; fail-closed (AC10)."
            )
        return 1.0 / (1.0 + max(0.0, value))
    score = getattr(meta, "score", None) if meta is not None else None
    if score is None or isinstance(score, bool) or not isinstance(score, (int, float)):
        raise VectorDbUnavailableError(
            f"Weaviate hit has no numeric 'score' (got {score!r}); fail-closed (AC10)."
        )
    value = float(score)
    if value != value or value in (float("inf"), float("-inf")):
        raise VectorDbUnavailableError(
            "Weaviate hit has a non-finite 'score'; fail-closed (AC10)."
        )
    return value


def _project_filter(project_id: str) -> object:
    """Build a project-scope filter for the Weaviate query (kept for callers)."""
    from weaviate.classes.query import Filter  # noqa: PLC0415 (optional dependency)

    return Filter.by_property("project_id").equal(project_id)


__all__ = [
    "DEFAULT_SEARCH_LIMIT",
    "DEFAULT_SEARCH_MODE",
    "FETCH_PAGE_SIZE",
    "FK13_GRPC_PORT",
    "MAX_FETCH_OBJECTS",
    "SEARCH_MODES",
    "STORY_COLLECTION",
    "WEAVIATE_DATA_TYPE_NAMES",
    "StorySearchHit",
    "WeaviateClientPort",
    "WeaviateStoryAdapter",
]
