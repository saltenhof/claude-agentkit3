"""Lifecycle operations for project_management."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agentkit.project_management.entities import Project, ProjectConfiguration
from agentkit.project_management.errors import (
    ProjectAlreadyArchivedError,
    ProjectImmutableFieldError,
)

if TYPE_CHECKING:
    from datetime import datetime

_IMMUTABLE_FIELDS = frozenset({"key", "story_id_prefix"})


def create_project(
    key: str,
    name: str,
    story_id_prefix: str,
    configuration: ProjectConfiguration,
) -> Project:
    """Create a new non-archived project entity."""

    return Project(
        key=key,
        name=name,
        story_id_prefix=story_id_prefix,
        configuration=configuration,
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
