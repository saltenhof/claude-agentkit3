"""Thin governance composition over the existing Hub LLM transport."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from agentkit.integration_clients.multi_llm_hub.client import HubClient, HubClientProtocol
from agentkit.integration_clients.multi_llm_hub.config import load_multi_llm_hub_config
from concept_governance.evaluator import LlmAuthorityProseEvaluator
from concept_governance.evaluator_pool import RoutedAuthorityProseEvaluator
from concept_governance.hub_batch import HubBatchSession
from concept_governance.hub_batch_client import HubBatchLlmClient

if TYPE_CHECKING:
    from agentkit.integration_clients.multi_llm_hub.entities import HubBackendName
    from concept_governance.port import AuthorityProseEvaluator

MODEL_ENV = "AUTHORITY_PROSE_MODEL"
DEFAULT_MODELS: tuple[HubBackendName, ...] = ("chatgpt", "gemini", "grok", "qwen")
_ALLOWED_MODELS = frozenset(DEFAULT_MODELS)


def build_hub_evaluator(hub: HubClientProtocol | None = None) -> RoutedAuthorityProseEvaluator:
    """Build W2 with one shared lease over the configured healthy backends."""
    configured = os.environ.get(MODEL_ENV)
    if configured is not None and configured not in _ALLOWED_MODELS:
        raise ValueError(f"{MODEL_ENV} must be one of {sorted(_ALLOWED_MODELS)}")
    models = (configured,) if configured is not None else DEFAULT_MODELS
    if hub is None:
        config = load_multi_llm_hub_config()
        hub = HubClient(config.base_url)
    session = HubBatchSession(hub, models, owner="concept-authority-prose")
    evaluators: dict[str, tuple[AuthorityProseEvaluator, ...]] = {
        model: (
            LlmAuthorityProseEvaluator(
                HubBatchLlmClient(session, model),
                model,
            ),
        )
        for model in models
    }
    return RoutedAuthorityProseEvaluator(evaluators, models, lifecycle=session)
