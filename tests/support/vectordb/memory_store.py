"""In-process StoryContext store implementing the VectorDB port for tests.

This is a real port implementation at the adapter boundary (not a mock of
business logic). Used for integration gates without a live Weaviate.
"""

from __future__ import annotations

import math
import re
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


class MemoryStoreError(Exception):
    """Raised on invalid store operations (fail-closed)."""


@dataclass
class _Object:
    uuid: str
    properties: dict[str, Any]


@dataclass
class MemoryVectorStore:
    """Minimal multi-collection object store with project filters."""

    collections: dict[str, dict[str, _Object]] = field(default_factory=dict)

    def ensure_collection(self, name: str) -> None:
        self.collections.setdefault(name, {})

    def collection_exists(self, name: str) -> bool:
        return name in self.collections

    def upsert(
        self,
        *,
        collection: str,
        objects: Sequence[Mapping[str, object]],
        uuids: Sequence[str] | None = None,
    ) -> int:
        self.ensure_collection(collection)
        bucket = self.collections[collection]
        written = 0
        for i, obj in enumerate(objects):
            props = dict(obj)
            uid = uuids[i] if uuids is not None and i < len(uuids) else str(props.get("chunk_uuid") or uuid.uuid4())
            if not isinstance(uid, str) or not uid:
                raise MemoryStoreError("upsert requires a non-empty uuid")
            bucket[uid] = _Object(uuid=uid, properties=props)
            written += 1
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
        if collection not in self.collections:
            return 0
        bucket = self.collections[collection]
        to_delete: list[str] = []
        for uid, obj in bucket.items():
            props = obj.properties
            if props.get("project_id") != project_id:
                continue
            if source_types is not None and props.get("source_type") not in source_types:
                continue
            if source_file is not None and props.get("source_file") != source_file:
                continue
            if generation_id_not is not None and props.get("generation_id") == generation_id_not:
                continue
            if generation_id_not is not None and props.get("generation_id") == generation_id_not:
                continue
            # When generation_id_not is set, delete objects whose generation differs.
            if generation_id_not is not None and props.get("generation_id") == generation_id_not:
                continue
            to_delete.append(uid)
        for uid in to_delete:
            del bucket[uid]
        return len(to_delete)

    def delete_by_ids(
        self,
        *,
        collection: str,
        uuids: Sequence[str],
        project_id: str | None = None,
        source_types: Sequence[str] | None = None,
    ) -> dict[str, int]:
        if collection not in self.collections:
            return {"matches": 0, "successful": 0, "failed": 0}
        bucket = self.collections[collection]
        matches = 0
        successful = 0
        failed = 0
        for uid in uuids:
            obj = bucket.get(uid)
            if obj is None:
                continue
            props = obj.properties
            if project_id is not None and props.get("project_id") != project_id:
                failed += 1
                continue
            if source_types is not None and props.get("source_type") not in source_types:
                failed += 1
                continue
            matches += 1
            del bucket[uid]
            successful += 1
        return {"matches": matches, "successful": successful, "failed": failed}

    # Note: also used via MemoryWeaviateClient.delete_by_ids

    def fetch(
        self,
        *,
        collection: str,
        project_id: str,
        source_types: Sequence[str] | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> list[dict[str, Any]]:
        if collection not in self.collections:
            return []
        out: list[dict[str, Any]] = []
        for obj in self.collections[collection].values():
            props = obj.properties
            if props.get("project_id") != project_id:
                continue
            if source_types is not None and props.get("source_type") not in source_types:
                continue
            if filters:
                ok = True
                for key, expected in filters.items():
                    if props.get(key) != expected:
                        ok = False
                        break
                if not ok:
                    continue
            row = dict(props)
            row["_uuid"] = obj.uuid
            out.append(row)
        return out

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
    ) -> list[dict[str, Any]]:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
            raise MemoryStoreError(f"limit must be a positive int, got {limit!r}")
        if search_mode not in {"hybrid", "vector", "keyword"}:
            raise MemoryStoreError(f"invalid search_mode: {search_mode!r}")
        candidates = self.fetch(
            collection=collection,
            project_id=project_id,
            source_types=source_types,
            filters=filters,
        )
        scored: list[dict[str, Any]] = []
        q = query.lower()
        q_tokens = set(re.findall(r"[a-z0-9_]+", q))
        for row in candidates:
            content = str(row.get("content", "")).lower()
            title = str(row.get("title", "")).lower()
            heading = str(row.get("section_heading", "")).lower()
            blob = f"{title} {heading} {content}"
            if search_mode == "keyword":
                score = _keyword_score(q_tokens, blob)
            elif search_mode == "vector":
                score = _vector_score(q, blob)
            else:
                score = 0.5 * _keyword_score(q_tokens, blob) + 0.5 * _vector_score(q, blob)
            if score <= 0.0:
                continue
            if not math.isfinite(score):
                raise MemoryStoreError(f"non-finite score for {row.get('chunk_uuid')!r}")
            hit = dict(row)
            hit["score"] = float(score)
            hit["snippet"] = str(row.get("content", ""))[:240]
            scored.append(hit)
        scored.sort(key=lambda h: float(h["score"]), reverse=True)
        return scored[:limit]


def _keyword_score(q_tokens: set[str], blob: str) -> float:
    if not q_tokens:
        return 0.0
    b_tokens = set(re.findall(r"[a-z0-9_]+", blob))
    if not b_tokens:
        return 0.0
    inter = q_tokens & b_tokens
    return len(inter) / len(q_tokens)


def _vector_score(query: str, blob: str) -> float:
    """Cheap bag-of-chars proxy for vector similarity (deterministic)."""
    if not query or not blob:
        return 0.0
    # Character n-gram Jaccard.
    def grams(s: str) -> set[str]:
        s = re.sub(r"\s+", " ", s)
        return {s[i : i + 3] for i in range(max(0, len(s) - 2))}

    a, b = grams(query), grams(blob)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class MemoryWeaviateClient:
    """``WeaviateClientPort``-compatible client backed by :class:`MemoryVectorStore`."""

    def __init__(self, store: MemoryVectorStore | None = None) -> None:
        self.store = store or MemoryVectorStore()
        self._ready = True

    def is_ready(self) -> bool:
        return self._ready

    def close(self) -> None:
        self._ready = False

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
        return self.store.search(
            collection=collection,
            query=query,
            search_mode=search_mode,
            project_id=project_id,
            limit=limit,
            filters=filters,
            source_types=source_types,
        )

    def upsert(
        self,
        *,
        collection: str,
        objects: Sequence[Mapping[str, object]],
        uuids: Sequence[str] | None = None,
    ) -> int:
        return self.store.upsert(collection=collection, objects=objects, uuids=uuids)

    def delete_by_filter(
        self,
        *,
        collection: str,
        project_id: str,
        source_types: Sequence[str] | None = None,
        source_file: str | None = None,
        generation_id_not: str | None = None,
    ) -> int:
        return self.store.delete_by_filter(
            collection=collection,
            project_id=project_id,
            source_types=source_types,
            source_file=source_file,
            generation_id_not=generation_id_not,
        )

    def delete_by_ids(
        self,
        *,
        collection: str,
        uuids: Sequence[str],
        project_id: str | None = None,
        source_types: Sequence[str] | None = None,
    ) -> dict[str, int]:
        return self.store.delete_by_ids(
            collection=collection,
            uuids=uuids,
            project_id=project_id,
            source_types=source_types,
        )

    def fetch(
        self,
        *,
        collection: str,
        project_id: str,
        source_types: Sequence[str] | None = None,
        filters: Mapping[str, object] | None = None,
    ) -> Sequence[Mapping[str, object]]:
        return self.store.fetch(
            collection=collection,
            project_id=project_id,
            source_types=source_types,
            filters=filters,
        )


__all__ = [
    "MemoryStoreError",
    "MemoryVectorStore",
    "MemoryWeaviateClient",
]
