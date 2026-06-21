"""Story-creation app layer (FK-21).

Deterministic application-layer components for the story-creation pipeline:
the two-stage VectorDB reconciliation (FK-21 §21.4), repo-affinity resolution
(FK-21 §21.9) and the deterministic ``story.md`` export (FK-21 §21.11). These
are business logic -- they live here, never in ``integrations/`` (which stays a
thin Weaviate transport adapter).
"""

from __future__ import annotations

__all__: list[str] = []
