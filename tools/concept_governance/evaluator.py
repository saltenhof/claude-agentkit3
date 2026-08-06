"""Productive W2 evaluator with transport-only bounded retry."""

from __future__ import annotations

from typing import TYPE_CHECKING

from concept_governance.models import PROMPT_VERSION, ChunkClassification
from concept_governance.parser import ResponseContractError, ResponseParseError, parse_response
from concept_governance.prompt import render_prompt
from concept_governance.transport_retry import complete_with_transport_retry

if TYPE_CHECKING:
    from concept_ingester.discovery import ConceptChunk

    from agentkit.backend.verify_system.llm_evaluator.llm_client import LlmClient


class EvaluationParseError(ValueError):
    """Raised when the evaluator returned one unparseable final response."""


class LlmAuthorityProseEvaluator:
    """Classify chunks through an injected text LLM client."""

    def __init__(self, llm_client: LlmClient, model: str) -> None:
        """Initialize with the existing transport port and resolved model."""
        self._llm_client = llm_client
        self._model = model

    @property
    def model(self) -> str:
        """Return the resolved backend identity."""
        return self._model

    def evaluate(self, chunk: ConceptChunk, vocabulary: tuple[str, ...]) -> ChunkClassification:
        """Ask once; retry only while transport produced no response."""
        prompt, prompt_sha256 = render_prompt(chunk, vocabulary)
        response = complete_with_transport_retry(
            self._llm_client,
            role="concept_authority_prose",
            prompt=prompt,
            backend=self._model,
            item_kind="chunk",
            item_id=chunk.chunk_id,
        )
        try:
            parsed = parse_response(response)
        except ResponseContractError:
            raise
        except ResponseParseError as exc:
            raise EvaluationParseError(
                f"completed evaluation response is unparseable: {exc}"
            ) from exc
        return ChunkClassification(
            has_normative_statements=parsed.has_normative_statements,
            assertions=parsed.assertions,
            prompt_version=PROMPT_VERSION,
            prompt_sha256=prompt_sha256,
            model=self._model,
        )
