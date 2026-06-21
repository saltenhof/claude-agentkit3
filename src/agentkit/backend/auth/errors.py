"""Errors raised by the authentication boundary."""

from __future__ import annotations

from agentkit.backend.exceptions import AgentKitError


class AuthError(AgentKitError):
    """Base class for authentication failures."""


class AuthFailedError(AuthError):
    """Credentials, session, or token validation failed."""


class TokenNotFoundError(AuthError):
    """Requested project API token does not exist."""


class ProjectMismatchError(AuthError):
    """A token was used for a different project than its owner project."""
