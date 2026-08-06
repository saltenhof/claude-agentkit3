"""Single-call productive evaluator for each W3 scope partition."""

from __future__ import annotations

from typing import TYPE_CHECKING

from concept_governance.scope_contracts import ScopeEvaluation
from concept_governance.scope_models import SCOPE_PROMPT_VERSION, ScopePartition
from concept_governance.scope_parser import parse_scope_response
from concept_governance.scope_prompt import render_scope_prompt
from concept_governance.transport_retry import complete_with_transport_retry

if TYPE_CHECKING:
    from agentkit.backend.verify_system.llm_evaluator.llm_client import LlmClient


class LlmScopeConsistencyEvaluator:
    """Evaluate one complete partition with exactly one LLM call."""

    def __init__(self, llm_client: LlmClient, model: str) -> None:
        """Initialize with the shared Hub-backed text client."""
        self._llm_client = llm_client
        self._model = model

    @property
    def model(self) -> str:
        """Return the resolved backend identity."""
        return self._model

    def evaluate(self, partition: ScopePartition) -> ScopeEvaluation:
        """Render once, retry unanswered transport, and parse one final response."""
        prompt, prompt_sha256 = render_scope_prompt(partition)
        raw = complete_with_transport_retry(
            self._llm_client,
            role="concept_scope_consistency",
            prompt=prompt,
            backend=self._model,
            item_kind="partition",
            item_id=partition.partition_id,
        )
        return ScopeEvaluation(
            response=parse_scope_response(raw),
            prompt_version=SCOPE_PROMPT_VERSION,
            prompt_sha256=prompt_sha256,
            model=self._model,
        )
