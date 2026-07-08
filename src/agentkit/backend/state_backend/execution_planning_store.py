"""Execution-planning persistence store."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.state_backend.state_backend_connection_manager import (
    _backend_module,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.execution_planning.entities import (
        ParallelizationConfig,
        StoryDependency,
        StoryDependencyKind,
    )


def save_story_dependency(
    project_key: str,
    edge: StoryDependency,
    store_dir: Path | None = None,
) -> None:
    """Persist one story dependency edge."""
    from agentkit.backend.state_backend.store import mappers

    row = mappers.story_dependency_to_row(edge, project_key=project_key)
    _backend_module().save_story_dependency_row(store_dir, row)


def load_story_dependencies(
    project_key: str,
    store_dir: Path | None = None,
) -> list[StoryDependency]:
    """Load all story dependency edges for one project."""
    from agentkit.backend.state_backend.store import mappers

    rows = _backend_module().load_story_dependency_rows(store_dir, project_key)
    return [mappers.story_dependency_row_to_entity(row) for row in rows]


def load_story_dependency_rows_for_story(
    story_id: str,
    store_dir: Path | None = None,
) -> list[StoryDependency]:
    """Load story dependency edges for one story."""
    from agentkit.backend.state_backend.store import mappers

    rows = _backend_module().load_story_dependency_rows_for_story(store_dir, story_id)
    return [mappers.story_dependency_row_to_entity(row) for row in rows]


def delete_story_dependency(
    story_id: str,
    depends_on_story_id: str,
    kind: StoryDependencyKind,
    store_dir: Path | None = None,
) -> int:
    """Delete one story dependency edge."""
    return int(
        _backend_module().delete_story_dependency_row(
            store_dir,
            story_id,
            depends_on_story_id,
            kind.value,
        ),
    )


def load_parallelization_config(
    project_key: str,
    store_dir: Path | None = None,
) -> ParallelizationConfig | None:
    """Load the parallelization config for one project."""
    from agentkit.backend.state_backend.store import mappers

    row = _backend_module().load_parallelization_config_row(store_dir, project_key)
    if row is None:
        return None
    return mappers.parallelization_config_row_to_entity(row)


def save_parallelization_config(
    config: ParallelizationConfig,
    store_dir: Path | None = None,
) -> None:
    """Persist one parallelization config."""
    from agentkit.backend.state_backend.store import mappers

    row = mappers.parallelization_config_to_row(config)
    _backend_module().save_parallelization_config_row(store_dir, row)


__all__ = [
    "save_story_dependency",
    "load_story_dependencies",
    "load_story_dependency_rows_for_story",
    "delete_story_dependency",
    "load_parallelization_config",
    "save_parallelization_config",
]
