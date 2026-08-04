"""Domain exceptions for project_management."""

from __future__ import annotations

from agentkit.backend.exceptions import AgentKitError


class ProjectImmutableFieldError(AgentKitError):
    """Raised when an immutable project field is changed after creation."""


class ProjectAlreadyArchivedError(AgentKitError):
    """Raised when an archived project is archived again."""


class ProjectNotFoundError(AgentKitError):
    """Raised when a project lookup cannot resolve a key."""


class ProjectStoryIdPrefixConflictError(AgentKitError):
    """Raised when another project already owns a story-id prefix."""


class ProjectRepositoriesInvalidError(AgentKitError):
    """Raised when the ``repositories`` list is invalid (empty, duplicates, blanks)."""


class ProjectRepoStillInUseError(AgentKitError):
    """Raised when removing a repo that is still referenced by an active story."""
