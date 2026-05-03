"""Domain errors for story_context_manager."""

from __future__ import annotations

from agentkit.exceptions import StoryError


class StoryProjectNotFoundError(StoryError):
    """Raised when a story is created for an unknown project."""


class StoryProjectArchivedError(StoryError):
    """Raised when a story is created for an archived project."""


class StoryIdentityConflictError(StoryError):
    """Raised when story identity uniqueness is violated."""
