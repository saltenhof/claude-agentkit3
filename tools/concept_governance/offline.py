"""Explicit fixed-evaluation adapter for deterministic CLI tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from concept_governance.evaluator import EvaluationParseError
from concept_governance.models import PROMPT_VERSION, AuthorityProseResponse, ChunkClassification
from concept_governance.prompt import render_prompt

if TYPE_CHECKING:
    from pathlib import Path

    from concept_ingester.discovery import ConceptChunk


class OfflineEvaluations(BaseModel):
    """Versioned fixed classifications keyed by stable chunk UUID."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    model: str
    classifications: dict[str, AuthorityProseResponse]


class OfflineAuthorityProseEvaluator:
    """Return injected fixed classifications only at the LLM boundary."""

    def __init__(self, source: OfflineEvaluations) -> None:
        """Initialize from a validated offline document."""
        self._source = source

    @classmethod
    def from_path(cls, path: Path) -> OfflineAuthorityProseEvaluator:
        """Load strict fixed evaluations from JSON."""
        return cls(OfflineEvaluations.model_validate_json(path.read_text(encoding="utf-8")))

    @property
    def model(self) -> str:
        """Return the injected model identity."""
        return self._source.model

    def evaluate(self, chunk: ConceptChunk, vocabulary: tuple[str, ...]) -> ChunkClassification:
        """Return the classification for this stable chunk ID."""
        response = self._source.classifications.get(chunk.chunk_id)
        if response is None:
            raise EvaluationParseError(f"no offline classification for chunk {chunk.chunk_id}")
        _, prompt_sha256 = render_prompt(chunk, vocabulary)
        return ChunkClassification(
            has_normative_statements=response.has_normative_statements,
            assertions=response.assertions,
            prompt_version=PROMPT_VERSION,
            prompt_sha256=prompt_sha256,
            model=self.model,
        )
