"""Exceptions raised by the Multi-LLM Hub adapter."""

from __future__ import annotations

from agentkit.exceptions import AgentKitError


class MultiLlmHubError(AgentKitError):
    """Base error for external Hub adapter failures."""


class HubUnavailableError(MultiLlmHubError):
    """Raised when the external Hub is unreachable or returns 5xx."""


class HubSessionNotFoundError(MultiLlmHubError):
    """Raised when the external Hub cannot resolve a session."""
