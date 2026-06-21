"""Domain exceptions for project_management."""

from __future__ import annotations

from importlib import import_module
from typing import cast

_BaseProjectError = Exception
try:
    _shared_exceptions = import_module("agentkit.shared.exceptions")
except ImportError:
    pass
else:  # pragma: no cover - exercised only when shared BC exists
    _BaseProjectError = cast(
        "type[Exception]",
        _shared_exceptions.AgentKitError,
    )


class ProjectImmutableFieldError(_BaseProjectError):
    """Raised when an immutable project field is changed after creation."""


class ProjectAlreadyArchivedError(_BaseProjectError):
    """Raised when an archived project is archived again."""


class ProjectNotFoundError(_BaseProjectError):
    """Raised when a project lookup cannot resolve a key."""


class ProjectStoryIdPrefixConflictError(_BaseProjectError):
    """Raised when another project already owns a story-id prefix."""


class ProjectRepositoriesInvalidError(_BaseProjectError):
    """Raised when the ``repositories`` list is invalid (empty, duplicates, blanks)."""


class ProjectRepoStillInUseError(_BaseProjectError):
    """Raised when removing a repo that is still referenced by an active story."""
