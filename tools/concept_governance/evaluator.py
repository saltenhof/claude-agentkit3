"""Productive bounded-retry W2 evaluator over the existing LLM port."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from agentkit.backend.verify_system.llm_evaluator.llm_client import LlmClientError
from concept_governance.models import PROMPT_VERSION, ChunkClassification
from concept_governance.parser import ResponseParseError, parse_response
from concept_governance.prompt import render_prompt

TRANSPORT_RETRY_DELAY_SECONDS = 5.0

if TYPE_CHECKING:
    from concept_ingester.discovery import ConceptChunk

    from agentkit.backend.verify_system.llm_evaluator.llm_client import LlmClient

class EvaluationParseError(ValueError):
    """Raised after both bounded parse attempts fail."""


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
        """Ask the two fixed questions and parse with one bounded retry."""
        last_error: ResponseParseError | None = None
        for attempt in range(2):
            prompt, prompt_sha256 = render_prompt(chunk, vocabulary, retry=attempt == 1)
            response = _complete_with_retry(self._llm_client, prompt)
            try:
                parsed = parse_response(response)
            except ResponseParseError as exc:
                last_error = exc
                continue
            return ChunkClassification(
                has_normative_statements=parsed.has_normative_statements,
                assertions=parsed.assertions,
                prompt_version=PROMPT_VERSION,
                prompt_sha256=prompt_sha256,
                model=self._model,
            )
        raise EvaluationParseError(f"response unparseable after 2 attempts: {last_error}") from last_error


def _complete_with_retry(llm_client: LlmClient, prompt: str) -> str:
    """Retry one transient transport failure, then preserve fail-closed error."""
    try:
        return llm_client.complete(role="concept_authority_prose", prompt=prompt)
    except LlmClientError:
        time.sleep(TRANSPORT_RETRY_DELAY_SECONDS)
        return llm_client.complete(role="concept_authority_prose", prompt=prompt)
