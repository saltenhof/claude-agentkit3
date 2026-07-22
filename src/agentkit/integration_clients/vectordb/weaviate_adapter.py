"""Thin Weaviate runtime adapter for the story knowledge base (FK-13 §13.2).

Transport only — no business rules. Fail-closed on outage and on malformed
responses. No silent empty results, no score defaults, no ignored search_mode.
``weaviate-client`` is a hard dependency (AG3-174 / FK-13 §13.2); the import
is still guarded so absence surfaces as a typed error.
"""

from __future__ import annotations

import contextlib
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Protocol, runtime_checkable

from agentkit.integration_clients.vectordb.errors import (
    VectorDbUnavailableError,
    VectorDbWriteError,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

DEFAULT_SEARCH_LIMIT: Final[int] = 20
DEFAULT_SEARCH_MODE: Final[str] = "hybrid"
STORY_COLLECTION: Final[str] = "StoryContext"
_VALID_SEARCH_MODES: Final[frozenset[str]] = frozenset({"hybrid", "vector", "keyword"})


@dataclass(frozen=True)
class StorySearchHit:
    """One similarity hit from ``story_search`` (transport-level record)."""

    story_id: str
    title: str
    score: float
    snippet: str
    source_type: str = ""
    section_heading: str = ""
    concept_id: str = ""
    project_id: str = ""
    raw: Mapping[str, object] | None = None


@runtime_checkable
class WeaviateClientPort(Protocol):
    """Minimal transport surface the adapter needs from a Weaviate client."""

    def is_ready(self) -> bool: ...

    def close(self) -> None: ...

    def search(
        self,
        *,
        collection: str,
        query: str,
        search_mode: str,
        project_id: str,
        limit: int,
        filters: Mapping[str, object] | None = None,
        source_types: Sequence[str] | None = None,
    ) -> Sequence[Mapping[str, object]]: ...

    def upsert(
        self,
        *,
        collection: str,
        objects: Sequence[Mapping[str, object]],
        uuids: Sequence[str] | None = None,
    ) -> int: ...

    def delete_by_filter(
        self,
        *,
        collection: str,
        project_id: str,
        source_types: Sequence[str] | None = None,
        source_file: str | None = None,
        generation_id_not: str | None = None,
    ) -> int: ...

    def fetch(
        self,
        *,
        collection: str,
        project_id: str,
        source_types: Sequence[str] | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> Sequence[Mapping[str, object]]: ...


def _require_str_field(raw: Mapping[str, object], key: str) -> str:
    """Require a non-empty string field (no empty-string repair defaults, R07)."""
    if key not in raw:
        raise VectorDbUnavailableError(
            f"Weaviate hit missing required field {key!r}; fail-closed (R07)."
        )
    value = raw[key]
    if not isinstance(value, str):
        raise VectorDbUnavailableError(
            f"Weaviate hit field {key!r} must be str, got {type(value).__name__}; "
            "fail-closed (R07)."
        )
    if value == "":
        raise VectorDbUnavailableError(
            f"Weaviate hit field {key!r} must be non-empty; fail-closed (R07)."
        )
    return value


def normalize_hit_mapping(
    raw: Mapping[str, object],
    *,
    expected_project_id: str | None = None,
    expected_source_types: Sequence[str] | None = None,
) -> dict[str, object]:
    """Strict response normalisation used by every search path (R07).

    Rejects foreign project_id and unexpected source_type. No repair defaults.
    """
    story_id = raw.get("story_id")
    concept_id = raw.get("concept_id")
    if story_id is not None and not isinstance(story_id, str):
        raise VectorDbUnavailableError(
            f"Weaviate hit has non-string 'story_id' ({story_id!r}); fail-closed."
        )
    if concept_id is not None and not isinstance(concept_id, str):
        raise VectorDbUnavailableError(
            f"Weaviate hit has non-string 'concept_id' ({concept_id!r}); fail-closed."
        )
    has_story = isinstance(story_id, str) and story_id != ""
    has_concept = isinstance(concept_id, str) and concept_id != ""
    if not has_story and not has_concept:
        raise VectorDbUnavailableError(
            "Weaviate hit is missing both story_id and concept_id; fail-closed."
        )

    score = raw.get("score")
    if score is None or not isinstance(score, (int, float)) or isinstance(score, bool):
        raise VectorDbUnavailableError(
            f"Weaviate hit has non-numeric 'score' ({score!r}); fail-closed."
        )
    score_f = float(score)
    if not math.isfinite(score_f):
        raise VectorDbUnavailableError(
            f"Weaviate hit has non-finite score ({score!r}); fail-closed."
        )

    title = _require_str_field(raw, "title")
    project_id = _require_str_field(raw, "project_id")
    source_type = _require_str_field(raw, "source_type")
    if expected_project_id is not None and project_id != expected_project_id:
        raise VectorDbUnavailableError(
            f"Weaviate hit project_id {project_id!r} != expected "
            f"{expected_project_id!r}; fail-closed (R07)."
        )
    if expected_source_types is not None and source_type not in expected_source_types:
        raise VectorDbUnavailableError(
            f"Weaviate hit source_type {source_type!r} not in "
            f"{list(expected_source_types)!r}; fail-closed (R07)."
        )

    snippet = raw.get("snippet")
    if snippet is None:
        content = raw.get("content")
        if not isinstance(content, str) or content == "":
            raise VectorDbUnavailableError(
                "Weaviate hit missing snippet/content; fail-closed (R07)."
            )
        snippet = content[:240]
    elif not isinstance(snippet, str) or snippet == "":
        raise VectorDbUnavailableError(
            f"Weaviate hit has invalid 'snippet' ({snippet!r}); fail-closed."
        )

    section_heading = raw.get("section_heading")
    if section_heading is not None and not isinstance(section_heading, str):
        raise VectorDbUnavailableError(
            f"Weaviate hit has non-string section_heading ({section_heading!r})."
        )
    if section_heading is None:
        raise VectorDbUnavailableError(
            "Weaviate hit missing section_heading; fail-closed (R07)."
        )

    out = dict(raw)
    out.update(
        {
            "story_id": story_id if has_story else "",
            "concept_id": concept_id if has_concept else "",
            "title": title,
            "score": score_f,
            "snippet": snippet,
            "source_type": source_type,
            "section_heading": section_heading,
            "project_id": project_id,
        }
    )
    return out


def _coerce_hit(
    raw: Mapping[str, object],
    *,
    expected_project_id: str | None = None,
    expected_source_types: Sequence[str] | None = None,
) -> StorySearchHit:
    """Map a raw transport mapping into a typed hit (strict, fail-closed)."""
    norm = normalize_hit_mapping(
        raw,
        expected_project_id=expected_project_id,
        expected_source_types=expected_source_types,
    )
    return StorySearchHit(
        story_id=str(norm["story_id"]),
        title=str(norm["title"]),
        score=float(norm["score"]),  # type: ignore[arg-type]
        snippet=str(norm["snippet"]),
        source_type=str(norm["source_type"]),
        section_heading=str(norm["section_heading"]),
        concept_id=str(norm["concept_id"]),
        project_id=str(norm["project_id"]),
        raw=norm,
    )


class WeaviateStoryAdapter:
    """Thin transport adapter to the Weaviate story knowledge base."""

    def __init__(self, client: WeaviateClientPort) -> None:
        self._client = client

    @property
    def raw_client(self) -> WeaviateClientPort:
        """Expose the underlying client port (schema ensure / advanced ops)."""
        return self._client

    @classmethod
    def connect(
        cls,
        *,
        host: str,
        port: int,
        grpc_port: int | None = None,
    ) -> WeaviateStoryAdapter:
        client = _build_real_client(host=host, port=port, grpc_port=grpc_port)
        return cls(client)

    def is_ready(self) -> bool:
        try:
            return bool(self._client.is_ready())
        except VectorDbUnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001
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
        filters: Mapping[str, object] | None = None,
        source_types: Sequence[str] | None = None,
    ) -> list[StorySearchHit]:
        if search_mode not in _VALID_SEARCH_MODES:
            raise VectorDbUnavailableError(
                f"invalid search_mode {search_mode!r}; fail-closed."
            )
        try:
            raw_hits = self._client.search(
                collection=STORY_COLLECTION,
                query=query,
                search_mode=search_mode,
                project_id=project_id,
                limit=limit,
                filters=filters,
                source_types=source_types,
            )
        except VectorDbUnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise VectorDbUnavailableError(
                f"Weaviate story_search failed for project_id={project_id!r}: "
                f"{exc} (fail-closed: no silent empty result, FK-21 §21.4.3)."
            ) from exc
        return [
            _coerce_hit(
                hit,
                expected_project_id=project_id,
                expected_source_types=source_types,
            )
            for hit in raw_hits
        ]

    def search(
        self,
        *,
        collection: str,
        query: str,
        search_mode: str,
        project_id: str,
        limit: int,
        filters: Mapping[str, object] | None = None,
        source_types: Sequence[str] | None = None,
    ) -> Sequence[Mapping[str, object]]:
        """Port-compatible search used by MCP tools / ingest engine.

        Always runs the same strict hit normalisation as ``story_search`` (R07).
        """
        if search_mode not in _VALID_SEARCH_MODES:
            raise VectorDbUnavailableError(
                f"invalid search_mode {search_mode!r}; fail-closed."
            )
        try:
            raw_hits = self._client.search(
                collection=collection,
                query=query,
                search_mode=search_mode,
                project_id=project_id,
                limit=limit,
                filters=filters,
                source_types=source_types,
            )
        except VectorDbUnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise VectorDbUnavailableError(
                f"Weaviate search failed: {exc} (fail-closed)."
            ) from exc
        return [
            normalize_hit_mapping(
                hit,
                expected_project_id=project_id,
                expected_source_types=source_types,
            )
            for hit in raw_hits
        ]

    def delete_by_ids(
        self,
        *,
        collection: str,
        uuids: Sequence[str],
        project_id: str,
        source_types: Sequence[str] | None = None,
    ) -> dict[str, int]:
        """Project-/source-scoped UUID delete with structured counters (R07/R12)."""
        from agentkit.integration_clients.vectordb.strict_counters import (
            parse_delete_counters,
        )

        deleter = getattr(self._client, "delete_by_ids", None)
        if not callable(deleter):
            raise VectorDbWriteError(
                "Weaviate client lacks delete_by_ids; fail-closed (R12)."
            )
        try:
            result = deleter(
                collection=collection,
                uuids=uuids,
                project_id=project_id,
                source_types=source_types,
            )
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, VectorDbWriteError):
                raise
            raise VectorDbWriteError(
                f"Weaviate delete_by_ids failed: {exc} (fail-closed)."
            ) from exc
        return parse_delete_counters(result)

    def story_sync(
        self,
        *,
        objects: Sequence[Mapping[str, object]],
        uuids: Sequence[str] | None = None,
    ) -> int:
        from agentkit.integration_clients.vectordb.strict_counters import (
            require_strict_int,
        )

        try:
            raw = self._client.upsert(
                collection=STORY_COLLECTION, objects=objects, uuids=uuids
            )
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, VectorDbWriteError):
                raise
            raise VectorDbWriteError(
                f"Weaviate story_sync indexing failed for {len(objects)} object(s): "
                f"{exc} (fail-closed: indexing failure blocks export, FK-21 §21.11.4)."
            ) from exc
        return require_strict_int(raw, field="story_sync.written")

    def upsert(
        self,
        *,
        collection: str,
        objects: Sequence[Mapping[str, object]],
        uuids: Sequence[str] | None = None,
    ) -> int:
        from agentkit.integration_clients.vectordb.strict_counters import (
            require_strict_int,
        )

        try:
            raw = self._client.upsert(
                collection=collection, objects=objects, uuids=uuids
            )
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, VectorDbWriteError):
                raise
            raise VectorDbWriteError(
                f"Weaviate upsert failed: {exc} (fail-closed)."
            ) from exc
        return require_strict_int(raw, field="upsert.written")

    def delete_by_filter(
        self,
        *,
        collection: str,
        project_id: str,
        source_types: Sequence[str] | None = None,
        source_file: str | None = None,
        generation_id_not: str | None = None,
    ) -> int:
        from agentkit.integration_clients.vectordb.strict_counters import (
            require_strict_int,
        )

        try:
            raw = self._client.delete_by_filter(
                collection=collection,
                project_id=project_id,
                source_types=source_types,
                source_file=source_file,
                generation_id_not=generation_id_not,
            )
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, VectorDbWriteError):
                raise
            raise VectorDbWriteError(
                f"Weaviate delete_by_filter failed: {exc} (fail-closed)."
            ) from exc
        return require_strict_int(raw, field="delete_by_filter.deleted")

    def fetch(
        self,
        *,
        collection: str,
        project_id: str,
        source_types: Sequence[str] | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> Sequence[Mapping[str, object]]:
        try:
            return self._client.fetch(
                collection=collection,
                project_id=project_id,
                source_types=source_types,
                filters=filters,
            )
        except Exception as exc:  # noqa: BLE001
            raise VectorDbUnavailableError(
                f"Weaviate fetch failed: {exc} (fail-closed)."
            ) from exc

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._client.close()


def _build_real_client(
    *, host: str, port: int, grpc_port: int | None
) -> WeaviateClientPort:
    try:
        import weaviate  # noqa: PLC0415
    except ImportError as exc:
        raise VectorDbUnavailableError(
            "weaviate-client is not installed; the VectorDB is mandatory "
            "infrastructure (FK-13 §13.2). Install weaviate-client>=4.9,<5.0 "
            "-- fail-closed, no silent skip."
        ) from exc

    try:
        if grpc_port is not None:
            connection = weaviate.connect_to_local(
                host=host, port=port, grpc_port=grpc_port
            )
        else:
            connection = weaviate.connect_to_local(host=host, port=port)
    except Exception as exc:  # noqa: BLE001
        raise VectorDbUnavailableError(
            f"Could not connect to Weaviate at {host}:{port}: {exc} "
            "(fail-closed, FK-13 §13.2)."
        ) from exc
    return _RealWeaviateClient(connection)


class _RealWeaviateClient:
    """Adapts the concrete ``weaviate-client`` API to :class:`WeaviateClientPort`."""

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
        filters: Mapping[str, object] | None = None,
        source_types: Sequence[str] | None = None,
    ) -> Sequence[Mapping[str, object]]:
        if search_mode not in _VALID_SEARCH_MODES:
            raise VectorDbUnavailableError(f"invalid search_mode {search_mode!r}")
        coll = self._connection.collections.get(collection)  # type: ignore[attr-defined]
        combined = _build_filters(project_id, filters=filters, source_types=source_types)
        if search_mode == "hybrid":
            response = coll.query.hybrid(
                query=query,
                limit=limit,
                filters=combined,
                return_metadata=["score"],
            )
        elif search_mode == "vector":
            response = coll.query.near_text(
                query=query,
                limit=limit,
                filters=combined,
                return_metadata=["score"],
            )
        else:  # keyword / BM25
            response = coll.query.bm25(
                query=query,
                limit=limit,
                filters=combined,
                return_metadata=["score"],
            )
        hits: list[Mapping[str, object]] = []
        for obj in response.objects:
            props = dict(obj.properties)
            score = getattr(obj.metadata, "score", None)
            if score is None:
                raise VectorDbUnavailableError(
                    "Weaviate hit is missing metadata.score; fail-closed "
                    "(no default 0.0)."
                )
            if not isinstance(score, (int, float)) or isinstance(score, bool):
                raise VectorDbUnavailableError(
                    f"Weaviate hit has non-numeric score {score!r}; fail-closed."
                )
            if not math.isfinite(float(score)):
                raise VectorDbUnavailableError(
                    f"Weaviate hit has non-finite score {score!r}; fail-closed."
                )
            row: dict[str, object] = dict(props)
            row["score"] = float(score)
            if "snippet" not in row or row.get("snippet") in (None, ""):
                content = row.get("content")
                if not isinstance(content, str) or not content:
                    raise VectorDbUnavailableError(
                        "Weaviate hit missing content for snippet; fail-closed (R07)."
                    )
                row["snippet"] = content[:240]
            hits.append(row)
        return hits

    def upsert(
        self,
        *,
        collection: str,
        objects: Sequence[Mapping[str, object]],
        uuids: Sequence[str] | None = None,
    ) -> int:
        coll = self._connection.collections.get(collection)  # type: ignore[attr-defined]
        written = 0
        with coll.batch.dynamic() as batch:
            for i, obj in enumerate(objects):
                props = dict(obj)
                uid = None
                if uuids is not None and i < len(uuids):
                    uid = uuids[i]
                elif "chunk_uuid" in props:
                    uid = str(props["chunk_uuid"])
                if uid:
                    batch.add_object(properties=props, uuid=uid)
                else:
                    batch.add_object(properties=props)
                written += 1
        failed = getattr(coll.batch, "failed_objects", None) or []
        if failed:
            raise VectorDbWriteError(
                f"Weaviate batch upsert had {len(failed)} failure(s); fail-closed."
            )
        return written

    def delete_by_filter(
        self,
        *,
        collection: str,
        project_id: str,
        source_types: Sequence[str] | None = None,
        source_file: str | None = None,
        generation_id_not: str | None = None,
    ) -> int:
        from weaviate.classes.query import Filter  # noqa: PLC0415

        coll = self._connection.collections.get(collection)  # type: ignore[attr-defined]
        where = Filter.by_property("project_id").equal(project_id)
        if source_types:
            type_filters = [
                Filter.by_property("source_type").equal(st) for st in source_types
            ]
            combined_types = type_filters[0]
            for extra in type_filters[1:]:
                combined_types = combined_types | extra
            where = where & combined_types
        if source_file is not None:
            where = where & Filter.by_property("source_file").equal(source_file)
        if generation_id_not is not None:
            where = where & Filter.by_property("generation_id").not_equal(
                generation_id_not
            )
        result = coll.data.delete_many(where=where)
        from agentkit.integration_clients.vectordb.strict_counters import (
            parse_delete_counters,
        )

        counters = parse_delete_counters(result)
        # Filter-delete expected count is not known a priori; require
        # matches==successful and failed==0 only.
        if counters["failed"] != 0 or counters["matches"] != counters["successful"]:
            raise VectorDbWriteError(
                f"partial delete: matches={counters['matches']}, "
                f"successful={counters['successful']}, failed={counters['failed']}; "
                "fail-closed (R04/R07)."
            )
        return counters["successful"]

    def delete_by_ids(
        self,
        *,
        collection: str,
        uuids: Sequence[str],
        project_id: str,
        source_types: Sequence[str] | None = None,
    ) -> dict[str, int]:
        """Delete by UUID with mandatory project (and optional source) scope."""
        from weaviate.classes.query import Filter  # noqa: PLC0415

        from agentkit.integration_clients.vectordb.strict_counters import (
            parse_delete_counters,
        )

        if not uuids:
            return {"matches": 0, "successful": 0, "failed": 0}
        coll = self._connection.collections.get(collection)  # type: ignore[attr-defined]
        # Scope filter: project_id AND optional source_types, AND uuid list.
        where: Any = Filter.by_property("project_id").equal(project_id)
        if source_types:
            type_filters = [
                Filter.by_property("source_type").equal(st) for st in source_types
            ]
            combined = type_filters[0]
            for extra in type_filters[1:]:
                combined = combined | extra
            where = where & combined
        id_filters = [Filter.by_id().equal(uid) for uid in uuids]
        id_clause = id_filters[0]
        for extra in id_filters[1:]:
            id_clause = id_clause | extra
        where = where & id_clause
        result = coll.data.delete_many(where=where)
        # Full shape required — missing failed is not repaired to 0 (R07).
        return parse_delete_counters(result)

    def fetch(
        self,
        *,
        collection: str,
        project_id: str,
        source_types: Sequence[str] | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> Sequence[Mapping[str, object]]:
        """Fetch with server-side project filter on every page (R07)."""
        coll = self._connection.collections.get(collection)  # type: ignore[attr-defined]
        combined = _build_filters(project_id, filters=filters, source_types=source_types)
        rows: list[Mapping[str, object]] = []
        page_limit = 1000
        offset = 0
        while True:
            response = coll.query.fetch_objects(
                filters=combined,
                limit=page_limit,
                offset=offset,
            )
            batch = list(response.objects)
            for obj in batch:
                props = dict(obj.properties)
                if props.get("project_id") != project_id:
                    raise VectorDbUnavailableError(
                        "fetch returned object outside project filter; fail-closed (R07)."
                    )
                rows.append(props)
            if len(batch) < page_limit:
                break
            offset += page_limit
            if offset > 1_000_000:
                raise VectorDbUnavailableError(
                    "fetch pagination exceeded safety bound; fail-closed (R07)."
                )
        return rows


def _build_filters(
    project_id: str,
    *,
    filters: Mapping[str, object] | None,
    source_types: Sequence[str] | None,
) -> Any:
    from weaviate.classes.query import Filter  # noqa: PLC0415

    clause: Any = Filter.by_property("project_id").equal(project_id)
    if source_types:
        type_filters = [Filter.by_property("source_type").equal(st) for st in source_types]
        combined: Any = type_filters[0]
        for extra in type_filters[1:]:
            combined = combined | extra
        clause = clause & combined
    if filters:
        for key, value in filters.items():
            if not isinstance(value, (str, int, float, bool)):
                raise VectorDbUnavailableError(
                    f"filter value for {key!r} has unsupported type "
                    f"{type(value).__name__}"
                )
            clause = clause & Filter.by_property(key).equal(value)
    return clause


def _project_filter(project_id: str) -> object:
    """Build a project-scope filter (kept for back-compat imports)."""
    return _build_filters(project_id, filters=None, source_types=None)


__all__ = [
    "DEFAULT_SEARCH_LIMIT",
    "DEFAULT_SEARCH_MODE",
    "STORY_COLLECTION",
    "StorySearchHit",
    "WeaviateClientPort",
    "WeaviateStoryAdapter",
]
