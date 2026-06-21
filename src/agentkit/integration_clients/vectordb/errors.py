"""Errors for the Weaviate story-knowledge-base runtime adapter (FK-13 §13.2).

The VectorDB is mandatory infrastructure (FK-13 §13.2 / FK-21 §21.4.3): a
Weaviate outage, a missing ``weaviate-client`` dependency or a failed write is a
hard ERROR that blocks the consuming flow fail-closed -- never a silent empty
result.
"""

from __future__ import annotations


class VectorDbError(Exception):
    """Base error for the Weaviate runtime adapter (fail-closed)."""


class VectorDbUnavailableError(VectorDbError):
    """Raised when Weaviate is unreachable or the client is unusable.

    Covers a missing ``weaviate-client`` dependency, a connection failure and a
    failed readiness probe. The consuming story-creation / export flow MUST
    treat this as a hard blocker (FK-21 §21.4.3 / §21.11.4) -- never continue
    with an empty similarity result or skip indexing.
    """


class VectorDbWriteError(VectorDbError):
    """Raised when a ``story_sync`` write/indexing operation fails.

    FK-21 §21.11.4: an indexing failure during ``story.md`` export is a hard
    blocker (fail-closed) -- no warning, no catch-up path.
    """


__all__ = [
    "VectorDbError",
    "VectorDbUnavailableError",
    "VectorDbWriteError",
]
