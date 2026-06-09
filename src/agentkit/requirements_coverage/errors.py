"""Domain exceptions for requirements_coverage."""

from __future__ import annotations

from agentkit.exceptions import AgentKitError


class StoryAreLinkError(AgentKitError):
    """Base error for StoryAreLink operations."""


class StoryAreLinkConflictError(StoryAreLinkError):
    """Raised when a StoryAreLink edge conflicts with existing state."""


class StoryAreLinkNotFoundError(StoryAreLinkError):
    """Raised when a StoryAreLink edge cannot be resolved."""


class AreConfigurationError(AgentKitError):
    """Raised when ARE is enabled (features.are=True) but no AreClient is provided.

    This indicates a configuration mismatch: the pipeline is configured
    to use ARE integration but the runtime was not given a client instance.
    """


class AreClientError(AgentKitError):
    """Base error for ARE REST client failures."""


class AreClientHttpError(AreClientError):
    """Raised when the ARE HTTP transport returns or raises an HTTP error."""


class AreClientDecodeError(AreClientError):
    """Raised when an ARE response cannot be decoded as valid JSON."""


class AreClientResponseError(AreClientError):
    """Raised when an ARE response has an unexpected contract shape."""
