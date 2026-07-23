"""AC10 Weaviate-axis tests: malformed responses are hard errors, never repairs.

Fakes live ONLY at the WeaviateClientPort (the external boundary). Proves NO
empty-string substitution, NO ``0.0`` score repair, NaN/Infinity rejected,
unsupported search_mode rejected, missing mandatory field rejected.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.integration_clients.vectordb.errors import VectorDbUnavailableError
from agentkit.integration_clients.vectordb.weaviate_adapter import (
    SEARCH_MODES,
    WeaviateStoryAdapter,
    _coerce_hit,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


class _FakeClient:
    def __init__(self, hits: Sequence[Mapping[str, object]]) -> None:
        self._hits = hits

    def is_ready(self) -> bool:
        return True

    def close(self) -> None:
        pass

    def search(
        self,
        *,
        collection: str,
        query: str,
        search_mode: str,
        project_id: str,
        limit: int,
    ) -> Sequence[Mapping[str, object]]:
        return self._hits

    def upsert(self, *, collection: str, objects: Sequence[Mapping[str, object]]) -> int:
        return len(objects)


def _adapter(hits: Sequence[Mapping[str, object]]) -> WeaviateStoryAdapter:
    return WeaviateStoryAdapter(_FakeClient(hits))


def test_three_search_modes_are_effective() -> None:
    assert set(SEARCH_MODES) == {"hybrid", "vector", "keyword"}


def test_good_hit_coerces() -> None:
    hit = _coerce_hit({"story_id": "S1", "title": "T", "snippet": "snip", "score": 0.9})
    assert hit.story_id == "S1"
    assert hit.score == 0.9


@pytest.mark.parametrize(
    "raw,match",
    [
        ({"story_id": "", "title": "t", "snippet": "s", "score": 0.1}, "story_id"),
        ({"story_id": "S1", "title": 5, "snippet": "s", "score": 0.1}, "title"),
        ({"story_id": "S1", "title": "t", "snippet": None, "score": 0.1}, "snippet"),
        ({"story_id": "S1", "title": "t", "snippet": "s", "score": None}, "score"),
        ({"story_id": "S1", "title": "t", "snippet": "s", "score": float("nan")}, "non-finite"),
        ({"story_id": "S1", "title": "t", "snippet": "s", "score": float("inf")}, "non-finite"),
        ({"story_id": "S1", "title": "t", "snippet": "s", "score": True}, "non-numeric"),
    ],
)
def test_malformed_hit_is_hard_error_no_repair(raw: dict[str, object], match: str) -> None:
    with pytest.raises(VectorDbUnavailableError, match=match):
        _coerce_hit(raw)


def test_missing_title_no_empty_string_repair() -> None:
    adapter = _adapter([{"story_id": "S1", "title": "", "snippet": "s", "score": 0.5}])
    with pytest.raises(VectorDbUnavailableError, match="title"):
        adapter.story_search("q", project_id="p")


def test_missing_score_no_zero_repair() -> None:
    adapter = _adapter([{"story_id": "S1", "title": "t", "snippet": "s", "score": None}])
    with pytest.raises(VectorDbUnavailableError, match="non-numeric"):
        adapter.story_search("q", project_id="p")


def test_unsupported_search_mode_rejected() -> None:
    adapter = _adapter([])
    with pytest.raises(VectorDbUnavailableError, match="unsupported search_mode"):
        adapter.story_search("q", search_mode="fuzzy", project_id="p")
