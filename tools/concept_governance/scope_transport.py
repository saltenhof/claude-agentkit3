"""W3 composition over the reused epoch-rotating Hub transport."""

from __future__ import annotations

import os
import uuid
from typing import TYPE_CHECKING

from agentkit.integration_clients.multi_llm_hub.client import HubClient, HubClientProtocol
from agentkit.integration_clients.multi_llm_hub.config import load_multi_llm_hub_config
from concept_governance.hub_batch import HubBatchSession
from concept_governance.hub_batch_client import HubBatchLlmClient
from concept_governance.scope_evaluator import LlmScopeConsistencyEvaluator

if TYPE_CHECKING:
    from agentkit.integration_clients.multi_llm_hub.entities import HubBackendName
    from concept_governance.scope_contracts import ScopeEvaluation
    from concept_governance.scope_models import ScopePartition

SCOPE_MODEL_ENV = "SCOPE_CONSISTENCY_MODEL"
SCOPE_DEFAULT_MODELS: tuple[HubBackendName, ...] = ("chatgpt", "gemini", "grok", "qwen")
_ALLOWED_MODELS = frozenset(SCOPE_DEFAULT_MODELS)


class RoutedScopeConsistencyEvaluator:
    """Route stable partitions while sharing one HubBatchSession lifecycle."""

    parallelism = 1

    def __init__(self, session: HubBatchSession, models: tuple[HubBackendName, ...]) -> None:
        """Initialize the deterministic backend route."""
        self._session = session
        self._models = models

    def __enter__(self) -> RoutedScopeConsistencyEvaluator:
        """Open the reused epoch lifecycle."""
        self._session.open()
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        """Close and fence the reused epoch lifecycle."""
        del exc_type, exc_value, traceback
        self._session.close()

    @property
    def model(self) -> str:
        """Return the run-level model identity."""
        return self._models[0] if len(self._models) == 1 else "governance-pool/v1"

    def evaluate(self, partition: ScopePartition) -> ScopeEvaluation:
        """Make exactly one routed LLM call for this partition."""
        index = uuid.UUID(partition.partition_id).int % len(self._models)
        model = self._models[index]
        evaluator = LlmScopeConsistencyEvaluator(HubBatchLlmClient(self._session, model), model)
        return evaluator.evaluate(partition)

    def checkpoint(self, partition_id: str) -> None:
        """Commit a fully policy-processed partition to the epoch."""
        self._session.checkpoint(partition_id)


def build_hub_scope_evaluator(
    hub: HubClientProtocol | None = None,
    *,
    epoch_partition_limit: int | None = None,
) -> RoutedScopeConsistencyEvaluator:
    """Build W3 over ChatGPT, Gemini, Grok, and Qwen, never Kimi."""
    configured = os.environ.get(SCOPE_MODEL_ENV)
    if configured is not None and configured not in _ALLOWED_MODELS:
        raise ValueError(f"{SCOPE_MODEL_ENV} must be one of {sorted(_ALLOWED_MODELS)}")
    models = (configured,) if configured is not None else SCOPE_DEFAULT_MODELS
    if hub is None:
        config = load_multi_llm_hub_config()
        hub = HubClient(config.base_url)
    session = HubBatchSession(
        hub,
        models,
        owner="concept-scope-consistency",
        description="concept scope consistency",
        epoch_chunk_limit=epoch_partition_limit,
    )
    return RoutedScopeConsistencyEvaluator(session, models)
