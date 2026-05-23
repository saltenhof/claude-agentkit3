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


class AreCapabilityNotImplementedError(AgentKitError):
    """Raised when an ARE dock-point is called but not yet implemented.

    This is a contract-slot sentinel for AG3-030. When ARE is enabled
    and an ``AreClient`` is present, the full dock-point body has not
    been wired up yet (follow-up stories, THEME-009). No pipeline path
    should call a dock-point with ARE enabled in production until the
    corresponding follow-up story has replaced this exception with real
    logic.
    """
