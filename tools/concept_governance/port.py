"""Evaluator port separating LLM classification from W2 policy."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from concept_ingester.discovery import ConceptChunk

    from concept_governance.models import ChunkClassification


class AuthorityProseEvaluator(Protocol):
    """Classify one deterministic concept chunk without deciding policy."""

    @property
    def model(self) -> str:
        """Return the resolved model/backend identity."""
        ...

    def evaluate(self, chunk: ConceptChunk, vocabulary: tuple[str, ...]) -> ChunkClassification:
        """Return a typed classification for one chunk."""
        ...
