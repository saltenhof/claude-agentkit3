"""Weaviate story-knowledge-base runtime integration (FK-13 §13.2).

Thin transport adapter only -- the two-stage reconciliation, readiness decision
and export indexing policy are app-layer concerns (``story_creation`` /
``agentkit.backend.vectordb``). ``weaviate-client`` is a hard dependency
(AG3-174 / FK-13 §13.2); the adapter still fails closed with a typed error when
it is absent or Weaviate is unreachable, never a silent empty result.
"""

from __future__ import annotations

from agentkit.integration_clients.vectordb.errors import (
    VectorDbError,
    VectorDbUnavailableError,
    VectorDbWriteError,
)
from agentkit.integration_clients.vectordb.weaviate_adapter import (
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
