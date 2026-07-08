"""Project-management persistence store."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.state_backend.state_backend_connection_manager import (
    _backend_module,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.auth.entities import ProjectApiToken
    from agentkit.backend.project_management.entities import Project


def save_project(project: Project, store_dir: Path | None = None) -> None:
    """Persist one project record."""
    from agentkit.backend.state_backend.store import mappers

    row = mappers.project_to_row(project)
    _backend_module().save_project_row(store_dir, row)


def load_project(key: str, store_dir: Path | None = None) -> Project | None:
    """Load one project record by project key."""
    from agentkit.backend.state_backend.store import mappers

    row = _backend_module().load_project_row(store_dir, key)
    if row is None:
        return None
    return mappers.project_row_to_entity(row)


def load_projects(
    store_dir: Path | None = None,
    *,
    include_archived: bool = False,
) -> list[Project]:
    """Load project records."""
    from agentkit.backend.state_backend.store import mappers

    rows = _backend_module().load_project_rows(
        store_dir,
        include_archived=include_archived,
    )
    return [mappers.project_row_to_entity(row) for row in rows]


def load_project_by_story_id_prefix(
    story_id_prefix: str,
    store_dir: Path | None = None,
) -> Project | None:
    """Load the project owning a story-id prefix."""
    from agentkit.backend.state_backend.store import mappers

    row = _backend_module().load_project_row_by_story_id_prefix(
        store_dir,
        story_id_prefix,
    )
    if row is None:
        return None
    return mappers.project_row_to_entity(row)


def save_project_api_token(
    token: ProjectApiToken,
    store_dir: Path | None = None,
) -> None:
    """Persist one opaque project API token record."""
    from agentkit.backend.state_backend.store import mappers

    row = mappers.project_api_token_to_row(token)
    _backend_module().save_project_api_token_row(store_dir, row)


def load_project_api_token(
    token_id: str,
    store_dir: Path | None = None,
) -> ProjectApiToken | None:
    """Load one project API token by token id."""
    from agentkit.backend.state_backend.store import mappers

    row = _backend_module().load_project_api_token_row(store_dir, token_id)
    if row is None:
        return None
    return mappers.project_api_token_row_to_entity(row)


def load_project_api_token_by_hash(
    token_hash: str,
    store_dir: Path | None = None,
) -> ProjectApiToken | None:
    """Load one project API token by bearer-token hash."""
    from agentkit.backend.state_backend.store import mappers

    row = _backend_module().load_project_api_token_row_by_hash(store_dir, token_hash)
    if row is None:
        return None
    return mappers.project_api_token_row_to_entity(row)


def load_project_api_tokens_for_project(
    project_key: str,
    store_dir: Path | None = None,
) -> list[ProjectApiToken]:
    """Load project API tokens scoped to one project."""
    from agentkit.backend.state_backend.store import mappers

    rows = _backend_module().load_project_api_token_rows_for_project(
        store_dir,
        project_key,
    )
    return [mappers.project_api_token_row_to_entity(row) for row in rows]


__all__ = [
    "save_project",
    "load_project",
    "load_projects",
    "load_project_by_story_id_prefix",
    "save_project_api_token",
    "load_project_api_token",
    "load_project_api_token_by_hash",
    "load_project_api_tokens_for_project",
]
