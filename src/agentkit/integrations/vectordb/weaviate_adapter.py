"""Thin Weaviate runtime adapter for the story knowledge base (FK-13 §13.2).

This is an ``integrations/`` *adapter*: it owns ONLY the transport to Weaviate
via the optional ``weaviate-client`` dependency. It carries no business rule --
the two-stage reconciliation, the threshold filter, the readiness *decision* and
the export indexing policy live in the app layer (``story_creation`` /
``agentkit.vectordb``). The adapter never returns a silent empty result on an
outage: every transport failure raises a typed
:class:`~agentkit.integrations.vectordb.errors.VectorDbError` so the caller can
fail closed (FK-21 §21.4.3 / §21.11.4).

``weaviate-client`` is an OPTIONAL dependency (``pip install
'agentkit[weaviate]'``). The import is guarded; when the package is absent any
operation raises :class:`VectorDbUnavailableError` rather than crashing at import
time, so the fail-closed path stays testable without the package installed.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable

from agentkit.integrations.vectordb.errors import (
    VectorDbUnavailableError,
    VectorDbWriteError,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

#: Fixed pre-filter search limit (FK-13 §13.5.2: "fest im Code").
DEFAULT_SEARCH_LIMIT: Final[int] = 20

#: Fixed search mode (FK-13 §13.5.2: "fest im Code").
DEFAULT_SEARCH_MODE: Final[str] = "hybrid"

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

    Fail-closed: a malformed hit (missing/typed-wrong ``story_id`` or ``score``)
    raises :class:`VectorDbUnavailableError` rather than degrading the result
    set silently (FK-21 §21.4.3).
    """
    story_id = raw.get("story_id")
    score = raw.get("score")
    if not isinstance(story_id, str) or not story_id:
        raise VectorDbUnavailableError(
            f"Weaviate hit is missing a string 'story_id' (got {story_id!r}); "
            "fail-closed (FK-21 §21.4.3)."
        )
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        raise VectorDbUnavailableError(
            f"Weaviate hit {story_id!r} has a non-numeric 'score' ({score!r}); "
            "fail-closed (FK-21 §21.4.3)."
        )
    title = raw.get("title")
    snippet = raw.get("snippet")
    return StorySearchHit(
        story_id=story_id,
        title=title if isinstance(title, str) else "",
        score=float(score),
        snippet=snippet if isinstance(snippet, str) else "",
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
            search_mode: Search mode; fixed ``"hybrid"`` per FK-13 §13.5.2.
            project_id: Project-prefix scope for the search (FK-21 §21.4.1).
            limit: Pre-filter result cap; fixed ``20`` per FK-13 §13.5.2.

        Returns:
            The transport-level hits (unfiltered; the threshold filter is an
            app-layer concern).

        Raises:
            VectorDbUnavailableError: On any transport failure -- the caller
                MUST treat this as a hard blocker, never an empty result
                (FK-21 §21.4.3).
        """
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
        del search_mode  # required by the WeaviateClientPort Protocol; unused by the real hybrid query (S1172)
        coll = self._connection.collections.get(collection)  # type: ignore[attr-defined]
        response = coll.query.hybrid(
            query=query,
            limit=limit,
            filters=_project_filter(project_id),
            return_metadata=["score"],
        )
        hits: list[Mapping[str, object]] = []
        for obj in response.objects:
            props = dict(obj.properties)
            score = getattr(obj.metadata, "score", None)
            hits.append(
                {
                    "story_id": props.get("story_id", ""),
                    "title": props.get("title", ""),
                    "score": score if score is not None else 0.0,
                    "snippet": props.get("snippet", ""),
                }
            )
        return hits

    def upsert(
        self,
        *,
        collection: str,
        objects: Sequence[Mapping[str, object]],
    ) -> int:
        coll = self._connection.collections.get(collection)  # type: ignore[attr-defined]
        written = 0
        with coll.batch.dynamic() as batch:
            for obj in objects:
                batch.add_object(properties=dict(obj))
                written += 1
        return written


def _project_filter(project_id: str) -> object:
    """Build a project-scope filter for the Weaviate hybrid query."""
    from weaviate.classes.query import Filter  # noqa: PLC0415 (optional dependency)

    return Filter.by_property("project_id").equal(project_id)


__all__ = [
    "DEFAULT_SEARCH_LIMIT",
    "DEFAULT_SEARCH_MODE",
    "STORY_COLLECTION",
    "StorySearchHit",
    "WeaviateClientPort",
    "WeaviateStoryAdapter",
]
