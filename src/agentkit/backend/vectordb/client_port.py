"""Transport contract required by the VectorDB domain services."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


@runtime_checkable
class CorpusClientPort(Protocol):
    """Declare the thin-adapter corpus surface required by the backend."""

    def fetch_by_property(
        self,
        *,
        collection: str,
        project_id: str,
        prop: str,
        value: str,
        return_props: Sequence[str],
    ) -> Sequence[tuple[str, dict[str, object]]]: ...

    def fetch_by_property_any(
        self,
        *,
        collection: str,
        project_id: str,
        prop: str,
        values: Sequence[str],
        return_props: Sequence[str],
    ) -> Sequence[tuple[str, dict[str, object]]]: ...

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
    ) -> Sequence[tuple[str, dict[str, object], float]]: ...

    def upsert(self, *, collection: str, objects: Sequence[Mapping[str, object]]) -> int: ...

    def insert_object(self, *, collection: str, uuid: str, properties: Mapping[str, object]) -> bool: ...

    def delete_by_ids(self, *, collection: str, uuids: Sequence[str]) -> int: ...

    def delete_by_ids_if_property_below(
        self,
        *,
        collection: str,
        uuids: Sequence[str],
        prop: str,
        limit: int,
        project_id: str,
        source_file: str,
    ) -> int: ...

    def delete_by_ids_if_property_absent(
        self,
        *,
        collection: str,
        uuids: Sequence[str],
        prop: str,
        project_id: str,
        source_file: str,
    ) -> int: ...

    def ensure_collection(
        self,
        *,
        collection: str,
        property_specs: Sequence[Mapping[str, object]],
        vectorizer: str = ...,
        vectorizer_model: Mapping[str, object] | None = ...,
        vector_source_properties: Sequence[str] | None = ...,
    ) -> None: ...


__all__ = ["CorpusClientPort"]
