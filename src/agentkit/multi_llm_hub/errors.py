"""Exceptions raised by the Multi-LLM Hub adapter."""

from __future__ import annotations

from agentkit.exceptions import AgentKitError


class MultiLlmHubError(AgentKitError):
    """Base error for external Hub adapter failures."""


class HubUnavailableError(MultiLlmHubError):
    """Raised when the external Hub is unreachable or returns 5xx."""


class HubSessionNotFoundError(MultiLlmHubError):
    """Raised when the external Hub cannot resolve a session (404/410)."""


class HubAcquireQueuedError(MultiLlmHubError):
    """Raised when the Hub returns a queued-acquire response (no slot granted yet).

    FK-11 §11.2.3 Zeile 187: acquire -> queued means no session_id/token was
    granted; the caller must re-acquire with the same owner after a short wait.
    The optional ``estimated_wait_seconds`` field carries the Hub hint when
    present in the wire payload.

    Attributes:
        estimated_wait_seconds: Optional estimated wait time from the Hub.
    """

    def __init__(
        self,
        message: str,
        *,
        estimated_wait_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.estimated_wait_seconds: float | None = estimated_wait_seconds


class HubLoginRequiredError(MultiLlmHubError):
    """Raised when the Hub returns a login-required error (HTTP 500, login code).

    FK-11 §11.2.3 Zeile 191: distinct from generic HubUnavailableError. Indicates
    that a human operator must log in to the hub before the session can proceed.
    Distinct from transient 5xx (hub down) — this requires operator action.
    """
