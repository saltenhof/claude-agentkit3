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

#: Ids per conditional (``delete_many``) delete batch. The condition travels WITH
#: the delete, so the batch size only bounds the filter payload -- never the
#: guarantee (D9).
MAX_CONDITIONAL_DELETE_IDS: Final[int] = 100

#: Sentinel for an ABSENT delete counter. A missing count is a fault, never a zero
#: (N44: the whole point of R12 was to stop defaults from reporting false success).
_MISSING_COUNT: Final[object] = object()

#: Schema data-type token -> the Weaviate wire name reported by the server.
WEAVIATE_DATA_TYPE_NAMES: Final[dict[str, str]] = {
    "TEXT": "text",
    "BOOL": "boolean",
    "TEXT[]": "text[]",
    "INT": "int",
}

#: Schema data-type token -> the python type a returned property must have.
_EXPECTED_PROPERTY_TYPES: Final[dict[str, type]] = {
    "TEXT": str,
    "BOOL": bool,
    "TEXT[]": list,
    "INT": int,
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

    @property
    def corpus_client(self) -> WeaviateClientPort:
        """Return the thin corpus client for the claim-aware sync owner (N38).

        There is exactly ONE write path into ``StoryContext``: the sync owner, which
        claims the source, stamps the writing generation and publishes a completion.
        This adapter therefore no longer offers a ``story_sync`` of its own -- an
        unclaimed, unstamped write would produce objects that the delete closure
        cannot touch and that a later sync would have to reject.
        """
        return self._client

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
            elif isinstance(value, (list, tuple, set, frozenset)):
                # A SET filter is evaluated server-side as a real OR of equalities
                # (D8): the caller may ask for several concept statuses at once, and
                # post-filtering on the client would break `limit` and the server's
                # own ranking. A single value keeps the plain equality the default
                # query has always issued.
                values = [str(v) for v in value]
                if not values:
                    raise VectorDbUnavailableError(
                        f"filter {prop!r} is an empty set; an empty set selects "
                        "nothing (fail-closed, D8)."
                    )
                parts.append(
                    Filter.by_property(prop).equal(values[0])
                    if len(values) == 1
                    else Filter.any_of(
                        [Filter.by_property(prop).equal(v) for v in values]
                    )
                )
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
        project_id: str,
        prop: str,
        value: str,
        return_props: Sequence[str],
    ) -> Sequence[tuple[str, dict[str, object]]]:
        """Fetch ``(uuid, properties)`` for objects where ``prop == value``, scoped
        to ``project_id`` SERVER-SIDE (AC4/N51)."""
        from weaviate.classes.query import Filter  # noqa: PLC0415 (transport dependency)

        return self._fetch_all_pages(
            collection=collection,
            flt=_scoped_read_condition(
                project_id=project_id,
                predicate=None if prop == "project_id" else Filter.by_property(prop).equal(value),
            ),
            return_props=return_props,
        )

    def fetch_by_property_any(
        self,
        *,
        collection: str,
        project_id: str,
        prop: str,
        values: Sequence[str],
        return_props: Sequence[str],
    ) -> Sequence[tuple[str, dict[str, object]]]:
        """Fetch ``(uuid, properties)`` where ``prop`` is in ``values``, scoped to
        ``project_id`` SERVER-SIDE (AC4/N51)."""
        from weaviate.classes.query import Filter  # noqa: PLC0415 (transport dependency)

        return self._fetch_all_pages(
            collection=collection,
            flt=_scoped_read_condition(
                project_id=project_id,
                predicate=Filter.by_property(prop).contains_any(list(values)),
            ),
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
        page ends the set. Fail-closed conditions (never a truncated answer):

        - a page returning MORE objects than requested (malformed pagination);
        - a uuid appearing in more than one page (inconsistent pagination -- the
          set would be both duplicated and incomplete);
        - a set that genuinely exceeds :data:`MAX_FETCH_OBJECTS`. Reaching the
          ceiling exactly is NOT an error by itself: one extra object is probed,
          and only its existence proves the set is larger than the ceiling (N25).
        """
        coll = self._connection.collections.get(collection)  # type: ignore[attr-defined]
        out: list[tuple[str, dict[str, object]]] = []
        seen: set[str] = set()
        offset = 0
        while True:
            objects = self._fetch_page(coll, flt, return_props, offset, FETCH_PAGE_SIZE)
            if len(objects) > FETCH_PAGE_SIZE:
                raise VectorDbUnavailableError(
                    f"Weaviate returned {len(objects)} objects for a page of "
                    f"{FETCH_PAGE_SIZE}; malformed pagination (fail-closed, AC10)."
                )
            for obj in objects:
                uid = str(obj.uuid)
                if uid in seen:
                    raise VectorDbUnavailableError(
                        f"object {uid!r} appeared twice while paging {collection!r}; "
                        "inconsistent pagination (fail-closed, AC10/N25)."
                    )
                seen.add(uid)
                out.append((uid, dict(obj.properties)))
            if len(objects) < FETCH_PAGE_SIZE:
                return out
            offset += FETCH_PAGE_SIZE
            if offset >= MAX_FETCH_OBJECTS:
                # Probe for ONE more object: the ceiling itself is a valid, fully
                # read set -- only a further object means the answer is truncated.
                if self._fetch_page(coll, flt, return_props, offset, 1):
                    raise VectorDbUnavailableError(
                        f"filtered result set exceeds {MAX_FETCH_OBJECTS} objects in "
                        f"{collection!r}; refusing a truncated answer (fail-closed, AC10)."
                    )
                return out

    def _fetch_page(
        self,
        coll: Any,
        flt: Any,
        return_props: Sequence[str],
        offset: int,
        limit: int,
    ) -> list[Any]:
        """Fetch ONE page of a filtered read."""
        page = coll.query.fetch_objects(
            filters=flt,
            return_properties=list(return_props),
            limit=limit,
            offset=offset,
        )
        return list(page.objects)

    def insert_object(
        self, *, collection: str, uuid: str, properties: Mapping[str, object]
    ) -> bool:
        """Conditionally CREATE one object; ``False`` when the uuid already exists.

        This is the store-level atomic compare-and-create primitive the source
        claim relies on (N03/D3). The pinned ``weaviate-client`` (4.9-5.0) routes a
        duplicate object id through ``UnexpectedStatusCodeError`` -- its own
        docstring says "for example the given UUID already exists" -- and only
        some paths raise ``ObjectAlreadyExistsException``. Both are handled, and
        the duplicate response is identified STRICTLY:

        1. the documented duplicate status code + "already exists" body, or
        2. an authoritative ``data.exists(uuid)`` probe confirming the id is taken.

        Anything else is a transport fault and fails closed -- a lost claim is
        NEVER inferred from an unexplained error.

        Raises:
            VectorDbWriteError: On any write fault that is not a duplicate id.
        """
        from weaviate.exceptions import (  # noqa: PLC0415 (transport dependency)
            ObjectAlreadyExistsException,
            UnexpectedStatusCodeError,
        )

        coll = self._connection.collections.get(collection)  # type: ignore[attr-defined]
        try:
            coll.data.insert(properties=dict(properties), uuid=uuid)
        except ObjectAlreadyExistsException:
            return False
        except UnexpectedStatusCodeError as exc:
            if _is_duplicate_object_error(exc) or _object_exists(coll, uuid):
                return False
            raise VectorDbWriteError(
                f"conditional insert of {uuid!r} into {collection!r} failed with "
                f"status {exc.status_code}: {exc} (fail-closed, N03/N14)."
            ) from exc
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

    def delete_by_ids_if_property_below(
        self,
        *,
        collection: str,
        uuids: Sequence[str],
        prop: str,
        limit: int,
        project_id: str,
        source_file: str,
    ) -> int:
        """Delete the given uuids ONLY where ``prop`` is strictly below ``limit`` (N37).

        This is the one storage-side precondition the pinned client offers for a
        destructive operation: ``data.delete_many`` takes a FILTER, so the condition
        is evaluated by Weaviate together with the delete. ``delete_by_id`` and
        ``update``/``replace`` accept no precondition at all, which is why an
        application-side ownership check can always be overtaken between the check
        and the mutation.

        The condition is an ORDERING against a value the CALLER owns (its own
        generation), not an equality against a value it happened to READ. That is the
        difference that matters: reading a value and deleting "whatever still carries
        it" only closes the interval between the read and the delete -- it never
        establishes WHOSE generation that value belonged to, so a resumed writer could
        authorise itself to delete a newer generation's data.

        The ids are sent in bounded batches, and every batch is counted exactly: a
        batch that reports a failure raises, and the returned total is the number of
        objects Weaviate confirms it removed. A total below ``len(uuids)`` means at
        least one object is NOT older than the caller's generation -- the CALLER
        decides what that means (for the sync it means it was superseded).

        Args:
            collection: Collection to delete from.
            uuids: Candidate object ids.
            prop: Numeric property carrying the ordering value.
            limit: Exclusive upper bound; only strictly smaller values are deleted.
            project_id: Authoritative bound project -- part of the condition (AC4).
            source_file: The claimed source -- part of the condition (AC4).

        Returns:
            The exact number of objects Weaviate confirmed deleted.

        Raises:
            VectorDbWriteError: When Weaviate reports a failed delete.
        """
        from weaviate.classes.query import Filter  # noqa: PLC0415 (transport dependency)

        coll = self._connection.collections.get(collection)  # type: ignore[attr-defined]
        ids = [str(uid) for uid in uuids]
        deleted = 0
        for start in range(0, len(ids), MAX_CONDITIONAL_DELETE_IDS):
            batch = ids[start : start + MAX_CONDITIONAL_DELETE_IDS]
            condition = _scoped_delete_condition(
                batch,
                project_id=project_id,
                source_file=source_file,
                predicate=Filter.by_property(prop).less_than(limit),
            )
            try:
                result = coll.data.delete_many(where=condition)
            except Exception as exc:  # noqa: BLE001 -- surface a partial delete
                raise VectorDbWriteError(
                    f"conditional delete failed for {len(batch)} object(s) with "
                    f"{prop} < {limit}: {exc} (R12 partial delete)."
                ) from exc
            confirmed = _conditional_delete_counts(
                result, prop=prop, limit=limit, requested=len(batch)
            )
            deleted += confirmed
        return deleted

    def delete_by_ids_if_property_absent(
        self,
        *,
        collection: str,
        uuids: Sequence[str],
        prop: str,
        project_id: str,
        source_file: str,
    ) -> int:
        """Delete the given uuids ONLY where ``prop`` is NOT SET at all (N43).

        The condition is an IS-NULL on the storage side, so it can only ever match rows
        that carry no value for ``prop``. That is what makes the legacy backfill safe
        without adopting anything: a row written by ANY generation is stamped, so this
        condition structurally cannot touch it -- not the caller's own, and not a newer
        owner's.

        Counters are validated exactly and the condition carries project/source
        isolation, like every other transport call (AC10/R12/AC4): a new call inherits
        those obligations instead of starting permissive.

        Args:
            collection: Collection to delete from.
            uuids: Candidate object ids.
            prop: Property that must be absent for a row to be deleted.
            project_id: Authoritative bound project -- part of the condition (AC4).
            source_file: The claimed source -- part of the condition (AC4).

        Returns:
            The exact number of objects the store confirms deleted.

        Raises:
            VectorDbWriteError: On a transport fault, a reported failure or a
                missing/invalid/impossible count.
        """
        from weaviate.classes.query import Filter  # noqa: PLC0415 (transport dependency)

        coll = self._connection.collections.get(collection)  # type: ignore[attr-defined]
        ids = [str(uid) for uid in uuids]
        deleted = 0
        for start in range(0, len(ids), MAX_CONDITIONAL_DELETE_IDS):
            batch = ids[start : start + MAX_CONDITIONAL_DELETE_IDS]
            condition = _scoped_delete_condition(
                batch,
                project_id=project_id,
                source_file=source_file,
                predicate=Filter.by_property(prop).is_none(True),
            )
            try:
                result = coll.data.delete_many(where=condition)
            except Exception as exc:  # noqa: BLE001 -- surface a partial delete
                raise VectorDbWriteError(
                    f"unstamped-row delete failed for {len(batch)} object(s) with "
                    f"{prop} unset: {exc} (R12 partial delete)."
                ) from exc
            deleted += _conditional_delete_counts(
                result, prop=f"{prop} IS NULL", limit=0, requested=len(batch)
            )
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
        """Create OR VERIFY a collection against the schema-owner's specs (R02/N12).

        ``vectorizer`` selects the FK-13 §13.2 server-side ``text2vec_transformers``
        (StoryContext) vs ``self_provided`` (auxiliary collections like receipts).

        An EXISTING collection is not accepted blindly (N12): the FULL read-back
        configuration is compared against the schema SSOT -- property names, data
        types, per-property vectorisation, TOKENISATION, searchability,
        filterability and ALL behaviour-defining named-vector settings, i.e. the
        vectorizer, its ``model`` AND its ``source_properties`` (N35). Any drift
        fails closed; otherwise a collection whose narrative fields are whole-value
        tokenised (so ``keyword`` search cannot match a word inside them, N18), or
        one that embeds only ``title`` instead of the narrative properties (N35),
        would pass composition and only fail semantically at query time.
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
                collections,
                collection,
                property_specs,
                vectorizer,
                vectorizer_model or {},
                vector_source_properties,
            )
            return
        type_map = {
            "TEXT": DataType.TEXT,
            "BOOL": DataType.BOOL,
            "TEXT[]": DataType.TEXT_ARRAY,
            "INT": DataType.INT,
        }
        token_map = {
            "WORD": Tokenization.WORD,
            "FIELD": Tokenization.FIELD,
            "WHITESPACE": Tokenization.WHITESPACE,
            "LOWERCASE": Tokenization.LOWERCASE,
        }
        properties = []
        for spec in property_specs:
            kwargs: dict[str, object] = {
                "name": str(spec["name"]),
                "data_type": type_map[str(spec["data_type"])],
                "skip_vectorization": bool(spec["skip_vectorization"]),
                "vectorize_property_name": bool(spec.get("vectorize_property_name", False)),
                "index_filterable": bool(spec.get("filterable", True)),
            }
            # Tokenisation / searchability exist only for text types; Weaviate
            # rejects them on a boolean property.
            if "tokenization" in spec:
                kwargs["tokenization"] = token_map[str(spec["tokenization"])]
                kwargs["index_searchable"] = bool(spec.get("searchable", False))
            properties.append(Property(**kwargs))  # type: ignore[arg-type]
        if vectorizer == "text2vec_transformers":
            model = dict(vectorizer_model or {})
            pooling = str(model.get("poolingStrategy", "masked_mean"))
            if pooling not in ("masked_mean", "cls"):
                raise VectorDbWriteError(
                    f"pooling strategy {pooling!r} is not supported by the pinned "
                    "client (masked_mean|cls); fail-closed (N30)."
                )
            vector_config = Configure.Vectors.text2vec_transformers(
                pooling_strategy=pooling,  # type: ignore[arg-type]  # validated above
                vectorize_collection_name=bool(model.get("vectorizeClassName", False)),
                # The embedding must be built from the SSOT-selected narrative
                # properties, declared EXPLICITLY so a later read-back can prove it
                # (N35) instead of relying on a server-side default.
                source_properties=(
                    list(vector_source_properties)
                    if vector_source_properties is not None
                    else None
                ),
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
        vectorizer_model: Mapping[str, object],
        vector_source_properties: Sequence[str] | None = None,
    ) -> None:
        """Fail closed when an existing collection drifts from the SSOT (N12/N18/N35)."""
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
        if vectorizer_model:
            configured_model = configured_vectorizer_model(config)
            model_drift = sorted(
                f"{key}: expected {value!r}, configured {configured_model.get(key)!r}"
                for key, value in vectorizer_model.items()
                if configured_model.get(key) != value
            )
            if model_drift:
                raise VectorDbWriteError(
                    f"collection {collection!r} vectorizer MODEL drifted from the "
                    f"schema SSOT: {model_drift}; fail-closed (N12/N30: the pooling "
                    "strategy and vectorizeClassName are part of the contract -- a "
                    "drifted model silently changes every embedding)."
                )
        if vector_source_properties is not None:
            configured_sources = configured_vector_source_properties(config)
            expected_sources = tuple(vector_source_properties)
            if configured_sources is not None and configured_sources != expected_sources:
                raise VectorDbWriteError(
                    f"collection {collection!r} vectorizer SOURCE PROPERTIES drifted "
                    f"from the schema SSOT: expected {list(expected_sources)}, "
                    f"configured {list(configured_sources)}; fail-closed (N35: the "
                    "source properties decide WHAT is embedded -- a collection that "
                    "vectorises only the title answers semantic search from titles "
                    "alone while pooling and vectorizeClassName still match)."
                )
        expected = {str(spec["name"]): _expected_property_view(spec) for spec in property_specs}
        configured = _configured_properties(config)
        drift = sorted(
            f"{name}: expected {expected[name]}, configured {configured.get(name)}"
            for name in expected
            if configured.get(name) != expected[name]
        )
        unexpected = sorted(set(configured) - set(expected))
        if drift or unexpected:
            raise VectorDbWriteError(
                f"collection {collection!r} configuration drifted from the schema "
                f"SSOT: {drift}; unexpected properties={unexpected}; fail-closed "
                "(N12/N18: names, data types, vectorisation, tokenisation, "
                "searchability and filterability are all part of the contract)."
            )


#: HTTP status codes Weaviate answers a duplicate object id with (N14).
_DUPLICATE_STATUS_CODES: Final[frozenset[int]] = frozenset({409, 422})

#: Marker Weaviate puts in the duplicate-id error body (N14).
_DUPLICATE_MARKER: Final[str] = "already exists"


def _is_duplicate_object_error(exc: Any) -> bool:
    """Identify the REAL duplicate-object response of the pinned client (N14).

    Strict: the status code must be one Weaviate uses for a rejected duplicate id
    AND the response body must carry its ``already exists`` marker. Any other
    unexpected status is a transport fault, never a lost claim.
    """
    status = getattr(exc, "status_code", None)
    if status not in _DUPLICATE_STATUS_CODES:
        return False
    body = f"{getattr(exc, 'error', '') or ''} {exc}"
    return _DUPLICATE_MARKER in body.lower()


def _object_exists(coll: Any, uuid: str) -> bool:
    """Authoritative existence probe after a failed conditional create (N14).

    If the id is present the claim IS taken, whatever the client reported. A
    failing probe is inconclusive and must NOT be read as "taken".
    """
    try:
        return bool(coll.data.exists(uuid))
    except Exception:  # noqa: BLE001 -- inconclusive probe -> not a duplicate
        return False


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


def _expected_property_view(spec: Mapping[str, object]) -> dict[str, object]:
    """Project a schema property spec into the comparable read-back view (N12/N18)."""
    view: dict[str, object] = {
        "data_type": WEAVIATE_DATA_TYPE_NAMES[str(spec["data_type"])],
        "skip_vectorization": bool(spec["skip_vectorization"]),
        "vectorize_property_name": bool(spec.get("vectorize_property_name", False)),
        "filterable": bool(spec.get("filterable", True)),
    }
    if "tokenization" in spec:
        view["tokenization"] = str(spec["tokenization"]).lower()
        view["searchable"] = bool(spec.get("searchable", False))
    return view


def _configured_properties(config: Any) -> dict[str, dict[str, object]]:
    """Project an existing collection's properties into the comparable view.

    Covers the BEHAVIOURAL configuration, not just names/types: per-property
    vectorisation (``skip`` / ``vectorize_property_name``), tokenisation,
    searchability and filterability (N12/N18).
    """
    out: dict[str, dict[str, object]] = {}
    for prop in getattr(config, "properties", None) or []:
        name = str(getattr(prop, "name", ""))
        if not name:
            continue
        vec = getattr(prop, "vectorizer_config", None)
        view: dict[str, object] = {
            "data_type": _enum_value(getattr(prop, "data_type", None)),
            "skip_vectorization": bool(getattr(vec, "skip", False)),
            "vectorize_property_name": bool(getattr(vec, "vectorize_property_name", False)),
            "filterable": bool(getattr(prop, "index_filterable", False)),
        }
        tokenization = _enum_value(getattr(prop, "tokenization", None))
        if tokenization:
            view["tokenization"] = tokenization
            view["searchable"] = bool(getattr(prop, "index_searchable", False))
        out[name] = view
    return out


def configured_vectorizer_model(config: Any) -> dict[str, object]:
    """Return the MODEL settings of an existing collection's vectorizer (N30).

    The pinned client models the two surfaces differently, which is exactly where
    the previous check went wrong:

    - NAMED vectors (``config.vector_config``) expose
      ``_NamedVectorConfig.vectorizer`` -> ``_NamedVectorizerConfig`` with a
      ``model`` MAPPING that carries ``vectorizeClassName`` / ``poolingStrategy``.
      There is NO ``vectorize_collection_name`` attribute there.
    - the LEGACY surface (``config.vectorizer_config`` -> ``_VectorizerConfig``)
      has ``model`` plus a separate ``vectorize_collection_name`` flag.

    Both are normalised onto the wire keys the schema SSOT declares.
    """
    entries = _vector_config_entries(config)
    model: dict[str, object] = {}
    for entry in entries:
        inner = getattr(entry, "vectorizer", None)
        raw_model = getattr(inner, "model", None)
        if isinstance(raw_model, dict):
            model.update(raw_model)
    if model:
        return model
    legacy = getattr(config, "vectorizer_config", None)
    raw_legacy = getattr(legacy, "model", None)
    if isinstance(raw_legacy, dict):
        model.update(raw_legacy)
    if legacy is not None and hasattr(legacy, "vectorize_collection_name"):
        model.setdefault(
            "vectorizeClassName", bool(legacy.vectorize_collection_name)
        )
    return model


def _scoped_read_condition(*, project_id: str, predicate: Any | None) -> Any:
    """Build a project-scoped READ filter (AC4/N51).

    Every read carries the project filter on the SERVER, not as a post-filter in the
    app layer. Post-filtering was not merely redundant: the paginated read still had to
    transport another project's rows, so a foreign project holding the same source -- or
    simply enough rows to pass ``MAX_FETCH_OBJECTS`` -- could change the OUTCOME of this
    project's operation (a truncation refusal that has nothing to do with this project's
    data). AC4 covers reads, not only mutations.

    Args:
        project_id: The authoritative bound project.
        predicate: The read's own condition, or ``None`` when the project scope IS the
            whole condition (then exactly one clause is emitted -- no redundant
            duplicate of the project filter).

    Returns:
        The Weaviate filter to send.
    """
    from weaviate.classes.query import Filter  # noqa: PLC0415 (transport dependency)

    project_clause = Filter.by_property("project_id").equal(project_id)
    if predicate is None:
        return project_clause
    return Filter.all_of([project_clause, predicate])


def _scoped_delete_condition(
    batch: Sequence[str], *, project_id: str, source_file: str, predicate: Any
) -> Any:
    """Build the filter for a scoped, conditional delete (AC4/N48).

    EVERY delete carries project isolation, not only the ones a finding happened to
    name: the ids come from a project-filtered read, but a delete must not depend on
    the caller having read correctly. ``project_id`` AND ``source_file`` are therefore
    part of the condition the store evaluates, next to the id set and the
    operation-specific ``predicate``.

    Args:
        batch: The candidate object ids of this batch.
        project_id: Authoritative bound project.
        source_file: The claimed source the ids belong to.
        predicate: The operation's own condition (ordering or IS-NULL).

    Returns:
        The combined Weaviate filter.
    """
    from weaviate.classes.query import Filter  # noqa: PLC0415 (transport dependency)

    return Filter.all_of(
        [
            Filter.by_id().contains_any(list(batch)),
            Filter.by_property("project_id").equal(project_id),
            Filter.by_property("source_file").equal(source_file),
            predicate,
        ]
    )


def _exact_count(value: Any, *, field_name: str, context: str) -> int:
    """Return a delete counter as an EXACT non-negative int (AC10/R12, N44).

    No coercion and no default: a MISSING field, a numeric STRING, a BOOLEAN or a
    negative value is a fault, not a zero. Reporting ``successful="1"`` with ``failed``
    absent as "one confirmed delete" is precisely the false-success path R12 closed,
    so a new transport call inherits that strictness instead of starting permissive.

    Args:
        value: The raw counter as the client reported it.
        field_name: Counter name, for the message.
        context: What was attempted, for the message.

    Returns:
        The counter value.

    Raises:
        VectorDbWriteError: When the counter is absent, non-integer or negative.
    """
    if value is _MISSING_COUNT:
        raise VectorDbWriteError(
            f"{context}: the store reported no {field_name!r} count; an unreported "
            "count is never a zero (fail-closed, AC10/R12)."
        )
    if isinstance(value, bool) or not isinstance(value, int):
        raise VectorDbWriteError(
            f"{context}: {field_name} is {value!r} ({type(value).__name__}), not an "
            "integer; no coercion (fail-closed, AC10/R12)."
        )
    exact: int = value
    if exact < 0:
        raise VectorDbWriteError(
            f"{context}: {field_name} is negative ({exact}); fail-closed (AC10/R12)."
        )
    return exact


def _conditional_delete_counts(
    result: Any, *, prop: str, limit: int, requested: int
) -> int:
    """Validate one conditional-delete result and return the CONFIRMED count (N44).

    Both counters must exist as exact integers, they must be internally consistent
    (nothing may be reported beyond what was requested), and any reported failure is
    fail-closed. Only ``successful`` is returned -- the caller compares it against what
    it asked for and decides what a short count means.

    Args:
        result: The client's ``delete_many`` return value.
        prop: Property the condition ordered against, for the message.
        limit: Exclusive bound of the condition, for the message.
        requested: Number of ids sent in this batch.

    Returns:
        The confirmed number of deleted objects.

    Raises:
        VectorDbWriteError: On a missing/invalid counter, a reported failure or a
            count that exceeds the request.
    """
    predicate = prop if prop.endswith("IS NULL") else f"{prop} < {limit}"
    context = f"conditional delete of {requested} object(s) with {predicate}"
    failed = _exact_count(
        getattr(result, "failed", _MISSING_COUNT), field_name="failed", context=context
    )
    successful = _exact_count(
        getattr(result, "successful", _MISSING_COUNT),
        field_name="successful",
        context=context,
    )
    if failed:
        raise VectorDbWriteError(
            f"{context}: {failed} object(s) failed; fail-closed (R12 partial delete)."
        )
    if successful > requested or successful + failed > requested:
        raise VectorDbWriteError(
            f"{context}: the store reported {successful} deleted and {failed} failed "
            f"for {requested} requested object(s); an impossible count is never a "
            "success (fail-closed, AC10/R12)."
        )
    return successful


def configured_vector_source_properties(config: Any) -> tuple[str, ...] | None:
    """Return the named-vector ``source_properties`` of an existing collection (N35).

    ``_NamedVectorizerConfig`` has exactly three behaviour-defining fields in the
    pinned client -- ``vectorizer``, ``model`` and ``source_properties``. The model
    check alone let a collection that vectorises only ``title`` pass as long as
    pooling and ``vectorizeClassName`` matched, so the SOURCE PROPERTIES are read
    back and compared too.

    Args:
        config: A read-back collection configuration.

    Returns:
        The EXPLICITLY configured source properties in their configured order, or
        ``None`` when no named vector declares a selection. ``None`` is not drift:
        the client reports ``source_properties=None`` when the server derives the
        set from the per-property ``skip_vectorization`` flags, and those are
        already verified property by property. An EXPLICIT selection, however, can
        contradict the schema and is compared.
    """
    names: list[str] = []
    explicit = False
    for entry in _vector_config_entries(config):
        inner = getattr(entry, "vectorizer", None)
        raw = getattr(inner, "source_properties", None)
        if raw is None:
            continue
        explicit = True
        names.extend(str(name) for name in raw)
    return tuple(names) if explicit else None


def _vector_config_entries(config: Any) -> list[Any]:
    """Return the named-vector config entries of a read-back collection config."""
    vector_config = getattr(config, "vector_config", None)
    if isinstance(vector_config, dict):
        return list(vector_config.values())
    if vector_config:
        return list(vector_config)
    return []


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
    "configured_vector_source_properties",
    "configured_vectorizer_model",
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
