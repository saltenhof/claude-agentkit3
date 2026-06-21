"""Lifecycle operations for project_management."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agentkit.backend.project_management.entities import Project, ProjectConfiguration
from agentkit.backend.project_management.errors import (
    ProjectAlreadyArchivedError,
    ProjectImmutableFieldError,
    ProjectRepositoriesInvalidError,
)

if TYPE_CHECKING:
    from datetime import datetime

_IMMUTABLE_FIELDS = frozenset({"key", "story_id_prefix"})


def _validate_repositories_for_write(repositories: list[str]) -> None:
    """Enforce min-1-entry constraint at write time.

    The Pydantic schema allows ``repositories=[]`` for forward-compat
    reads of legacy DB records.  This function enforces the stricter
    write-time contract: at least one repo must be present.

    Args:
        repositories: The repositories list to validate.

    Raises:
        ``ProjectRepositoriesInvalidError`` if the list is empty.
    """
    if not repositories:
        raise ProjectRepositoriesInvalidError(
            "repositories must contain at least one entry"
        )


def create_project(
    key: str,
    name: str,
    story_id_prefix: str,
    configuration: ProjectConfiguration,
    repositories: list[str],
) -> Project:
    """Create a new non-archived project entity.

    AG3-020 §2.1.3 mandates ``repositories`` as a dedicated explicit
    parameter rather than only living inside ``configuration``.  When the
    caller passes a list here it overrides ``configuration.repositories``;
    the two layers stay aligned via a re-validation of the effective
    configuration.

    Args:
        key: Unique project key (lower-case slugs).
        name: Human-readable project name.
        story_id_prefix: Prefix for generated story display-IDs (e.g. ``"AK3"``).
        configuration: Full project configuration including ``repositories``.
        repositories: Authoritative repositories list for the new project.
            The list overrides ``configuration.repositories`` so that the
            field is unambiguous at the call site.  Must contain at least
            one entry (enforced by the strict ``ProjectConfiguration``
            schema; ``_validate_repositories_for_write`` provides a clearer
            error message on the same condition).

    Returns:
        A new, non-archived ``Project`` entity.

    Raises:
        ``ProjectRepositoriesInvalidError`` if ``repositories`` is empty.
        ``pydantic.ValidationError`` if the effective configuration is
        otherwise invalid (e.g. duplicate entries, ``repo_url`` not member
        of the list, etc.).
    """
    _validate_repositories_for_write(repositories)
    payload: dict[str, Any] = configuration.model_dump(mode="python")
    payload["repositories"] = repositories
    effective_configuration = ProjectConfiguration.model_validate(payload)

    return Project(
        key=key,
        name=name,
        story_id_prefix=story_id_prefix,
        configuration=effective_configuration,
        archived_at=None,
    )


def update_configuration(
    project: Project,
    *,
    name: str | None = None,
    configuration_updates: dict[str, object] | None = None,
) -> Project:
    """Update mutable project attributes."""

    updates = configuration_updates or {}
    immutable_attempts = _IMMUTABLE_FIELDS.intersection(updates)
    if immutable_attempts:
        attempted = ", ".join(sorted(immutable_attempts))
        raise ProjectImmutableFieldError(f"Immutable project field update: {attempted}")

    configuration = project.configuration
    if updates:
        configuration_payload: dict[str, Any] = configuration.model_dump(mode="python")
        configuration_payload.update(updates)
        configuration = ProjectConfiguration.model_validate(configuration_payload)
        # Enforce min-1 when repositories are explicitly updated.
        if "repositories" in updates:
            _validate_repositories_for_write(configuration.repositories)

    return project.model_copy(
        update={
            "name": project.name if name is None else name,
            "configuration": configuration,
        },
    )


def archive_project(project: Project, *, archived_at: datetime) -> Project:
    """Archive a project exactly once."""

    if project.archived_at is not None:
        raise ProjectAlreadyArchivedError(f"Project {project.key!r} is archived")
    return project.model_copy(update={"archived_at": archived_at})
