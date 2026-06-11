"""Unit tests for the WeaviateStoryIndex shim (AG3-068 / FK-21 §21.11.4)."""

from __future__ import annotations

import pytest

from agentkit.integrations.vectordb import VectorDbWriteError
from agentkit.story_creation.weaviate_index import WeaviateStoryIndex


class _FakeAdapter:
    def __init__(self, *, raise_write: bool = False) -> None:
        self._raise = raise_write
        self.synced: list[object] = []

    def story_sync(self, *, objects: object) -> int:
        if self._raise:
            raise VectorDbWriteError("rejected")
        self.synced.append(objects)
        return 3


def test_index_story_forwards_to_story_sync() -> None:
    adapter = _FakeAdapter()
    index = WeaviateStoryIndex(adapter)  # type: ignore[arg-type]
    written = index.index_story(story_id="AK3-1", objects=[{"story_id": "AK3-1"}])
    assert written == 3
    assert adapter.synced == [[{"story_id": "AK3-1"}]]


def test_index_story_propagates_write_error_fail_closed() -> None:
    adapter = _FakeAdapter(raise_write=True)
    index = WeaviateStoryIndex(adapter)  # type: ignore[arg-type]
    with pytest.raises(VectorDbWriteError):
        index.index_story(story_id="AK3-1", objects=[{"story_id": "AK3-1"}])
