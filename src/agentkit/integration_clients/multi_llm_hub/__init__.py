"""Adapter surface for the external Multi-LLM Hub."""

from __future__ import annotations

from agentkit.integration_clients.multi_llm_hub.client import HubClient
from agentkit.integration_clients.multi_llm_hub.config import (
    DEFAULT_LLM_HUB_URL,
    LLM_HUB_URL_ENV,
    MultiLlmHubConfig,
    load_multi_llm_hub_config,
)
from agentkit.integration_clients.multi_llm_hub.entities import (
    HubBackendMetric,
    HubBackendName,
    HubHealth,
    HubHolder,
    HubMessage,
    HubSession,
    HubSessionLease,
)
from agentkit.integration_clients.multi_llm_hub.errors import (
    HubSessionNotFoundError,
    HubUnavailableError,
    MultiLlmHubError,
)

__all__ = [
    "DEFAULT_LLM_HUB_URL",
    "LLM_HUB_URL_ENV",
    "HubBackendMetric",
    "HubBackendName",
    "HubClient",
    "HubHealth",
    "HubHolder",
    "HubMessage",
    "HubSession",
    "HubSessionLease",
    "HubSessionNotFoundError",
    "HubUnavailableError",
    "MultiLlmHubConfig",
    "MultiLlmHubError",
    "load_multi_llm_hub_config",
]
