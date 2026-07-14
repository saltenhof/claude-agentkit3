"""Thin governance composition over the existing Hub LLM transport."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, cast

from agentkit.backend.verify_system.llm_evaluator.llm_client import HubLlmClient
from agentkit.integration_clients.multi_llm_hub.client import HubClient
from agentkit.integration_clients.multi_llm_hub.config import load_multi_llm_hub_config
from concept_governance.evaluator import LlmAuthorityProseEvaluator
from concept_governance.evaluator_pool import RoutedAuthorityProseEvaluator

if TYPE_CHECKING:
    from agentkit.integration_clients.multi_llm_hub.entities import HubBackendName
    from concept_governance.port import AuthorityProseEvaluator

MODEL_ENV = "AUTHORITY_PROSE_MODEL"
DEFAULT_MODELS: tuple[HubBackendName, ...] = ("chatgpt",)
_ALLOWED_MODELS = frozenset({"chatgpt", "grok", "qwen", "kimi"})
_MODEL_SLOTS = {"chatgpt": 1, "grok": 3, "qwen": 3, "kimi": 2}


class _GovernanceResolver:
    def __init__(self, model: HubBackendName) -> None:
        self._model = model

    def resolve(self, role: str) -> HubBackendName:
        if role != "concept_authority_prose":
            raise ValueError(f"unsupported governance role: {role}")
        return self._model


def build_hub_evaluator() -> RoutedAuthorityProseEvaluator:
    """Build W2 on HubLlmClient, excluding login-required Gemini."""
    configured = os.environ.get(MODEL_ENV)
    if configured is not None and configured not in _ALLOWED_MODELS:
        raise ValueError(f"{MODEL_ENV} must be one of {sorted(_ALLOWED_MODELS)}")
    models = (cast("HubBackendName", configured),) if configured is not None else DEFAULT_MODELS
    config = load_multi_llm_hub_config()
    evaluators: dict[str, tuple[AuthorityProseEvaluator, ...]] = {
        model: tuple(
            LlmAuthorityProseEvaluator(
                HubLlmClient(
                    HubClient(config.base_url),
                    _GovernanceResolver(model),
                    owner=f"concept-authority-prose-{model}-{index}",
                ),
                model,
            )
            for index in range(_MODEL_SLOTS[model])
        )
        for model in models
    }
    routes = tuple(model for model in models for _ in range(_MODEL_SLOTS[model]))
    return RoutedAuthorityProseEvaluator(evaluators, routes)
