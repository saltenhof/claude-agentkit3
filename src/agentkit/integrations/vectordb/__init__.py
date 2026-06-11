"""Weaviate story-knowledge-base runtime integration (FK-13 §13.2).

Thin transport adapter only -- the two-stage reconciliation, readiness decision
and export indexing policy are app-layer concerns (``story_creation`` /
``agentkit.vectordb``). ``weaviate-client`` is an OPTIONAL dependency; the
adapter fails closed with a typed error when it is absent or Weaviate is
unreachable, never a silent empty result.
"""

from __future__ import annotations

from agentkit.integrations.vectordb.errors import (
    VectorDbError,
    VectorDbUnavailableError,
    VectorDbWriteError,
)
from agentkit.integrations.vectordb.weaviate_adapter import (
    DEFAULT_SEARCH_LIMIT,
    DEFAULT_SEARCH_MODE,
    STORY_COLLECTION,
    StorySearchHit,
    WeaviateClientPort,
    WeaviateStoryAdapter,
)

__all__ = [
    "DEFAULT_SEARCH_LIMIT",
    "DEFAULT_SEARCH_MODE",
    "STORY_COLLECTION",
    "StorySearchHit",
    "VectorDbError",
    "VectorDbUnavailableError",
    "VectorDbWriteError",
    "WeaviateClientPort",
    "WeaviateStoryAdapter",
]
