"""Domain exceptions for requirements_coverage."""

from __future__ import annotations

from agentkit.exceptions import AgentKitError


class StoryAreLinkError(AgentKitError):
    """Base error for StoryAreLink operations."""


class StoryAreLinkConflictError(StoryAreLinkError):
    """Raised when a StoryAreLink edge conflicts with existing state."""


class StoryAreLinkNotFoundError(StoryAreLinkError):
    """Raised when a StoryAreLink edge cannot be resolved."""
