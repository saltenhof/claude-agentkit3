"""Story, project, planning, and requirements coverage facade operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.state_backend.store import mappers
from agentkit.backend.state_backend.store._facade_backend import _backend_module

if TYPE_CHECKING:
    from pathlib import Path
    from uuid import UUID

    from agentkit.backend.auth.entities import ProjectApiToken
    from agentkit.backend.execution_planning.entities import (
        ParallelizationConfig,
        StoryDependency,
        StoryDependencyKind,
    )
    from agentkit.backend.project_management.entities import Project
    from agentkit.backend.requirements_coverage.models import (
        StoryAreLink,
        StoryAreLinkKind,
    )
    from agentkit.backend.story_context_manager.models import StoryContext


def save_story_context(story_dir: Path, ctx: StoryContext) -> None:
    row = mappers.story_context_to_row(ctx)
    _backend_module().save_story_context_row(story_dir, row)


def save_story_context_global(store_dir: Path | None, ctx: StoryContext) -> None:
    row = mappers.story_context_to_row(ctx)
    _backend_module().save_story_context_global_row(store_dir, row)


def load_story_context(story_dir: Path) -> StoryContext | None:
    row = _backend_module().load_story_context_row(story_dir)
    if row is None:
        return None
    return mappers.story_context_payload_to_record(
        str(row["payload_json"]),
        db_label=str(story_dir),
    )


def load_story_context_global(
    project_key: str,
    story_id: str,
    store_dir: Path | None = None,
) -> StoryContext | None:
    backend = _backend_module()
    if not hasattr(backend, "load_story_context_global_row"):
        raise RuntimeError(
            "Global story-context reads are unsupported by the active backend",
        )
    row = backend.load_story_context_global_row(store_dir, project_key, story_id)
    if row is None:
        return None
    return mappers.story_context_payload_to_record(
        str(row["payload_json"]),
        db_label="postgres",
    )


def load_story_context_by_story_number_global(
    store_dir: Path | None,
    project_key: str,
    story_number: int,
) -> StoryContext | None:
    row = _backend_module().load_story_context_by_story_number_row(
        store_dir,
        project_key,
        story_number,
    )
    if row is None:
        return None
    return mappers.story_context_payload_to_record(
        str(row["payload_json"]),
        db_label="story_contexts",
    )


def load_story_context_by_uuid_global(
    store_dir: Path | None,
    story_uuid: UUID,
) -> StoryContext | None:
    row = _backend_module().load_story_context_by_uuid_row(
        store_dir,
        str(story_uuid),
    )
    if row is None:
        return None
    return mappers.story_context_payload_to_record(
        str(row["payload_json"]),
        db_label="story_contexts",
    )


def load_story_contexts_global(
    project_key: str,
    store_dir: Path | None = None,
) -> list[StoryContext]:
    backend = _backend_module()
    if not hasattr(backend, "load_story_context_rows_global"):
        raise RuntimeError(
            "Global story-context reads are unsupported by the active backend",
        )
    rows = backend.load_story_context_rows_global(store_dir, project_key)
    result: list[StoryContext] = []
    for row in rows:
        result.append(
            mappers.story_context_payload_to_record(
                str(row["payload_json"]),
                db_label="postgres",
            )
        )
    return result


def read_story_context_record(story_dir: Path) -> StoryContext | None:
    return load_story_context(story_dir)


def save_project(project: Project, store_dir: Path | None = None) -> None:
    row = mappers.project_to_row(project)
    _backend_module().save_project_row(store_dir, row)


def load_project(key: str, store_dir: Path | None = None) -> Project | None:
    row = _backend_module().load_project_row(store_dir, key)
    if row is None:
        return None
    return mappers.project_row_to_entity(row)


def load_projects(
    store_dir: Path | None = None,
    *,
    include_archived: bool = False,
) -> list[Project]:
    rows = _backend_module().load_project_rows(
        store_dir,
        include_archived=include_archived,
    )
    return [mappers.project_row_to_entity(row) for row in rows]


def load_project_by_story_id_prefix(
    story_id_prefix: str,
    store_dir: Path | None = None,
) -> Project | None:
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
    row = mappers.project_api_token_to_row(token)
    _backend_module().save_project_api_token_row(store_dir, row)


def load_project_api_token(
    token_id: str,
    store_dir: Path | None = None,
) -> ProjectApiToken | None:
    row = _backend_module().load_project_api_token_row(store_dir, token_id)
    if row is None:
        return None
    return mappers.project_api_token_row_to_entity(row)


def load_project_api_token_by_hash(
    token_hash: str,
    store_dir: Path | None = None,
) -> ProjectApiToken | None:
    row = _backend_module().load_project_api_token_row_by_hash(store_dir, token_hash)
    if row is None:
        return None
    return mappers.project_api_token_row_to_entity(row)


def load_project_api_tokens_for_project(
    project_key: str,
    store_dir: Path | None = None,
) -> list[ProjectApiToken]:
    rows = _backend_module().load_project_api_token_rows_for_project(
        store_dir,
        project_key,
    )
    return [mappers.project_api_token_row_to_entity(row) for row in rows]


def save_story_dependency(
    project_key: str,
    edge: StoryDependency,
    store_dir: Path | None = None,
) -> None:
    row = mappers.story_dependency_to_row(edge, project_key=project_key)
    _backend_module().save_story_dependency_row(store_dir, row)


def load_story_dependencies(
    project_key: str,
    store_dir: Path | None = None,
) -> list[StoryDependency]:
    rows = _backend_module().load_story_dependency_rows(store_dir, project_key)
    return [mappers.story_dependency_row_to_entity(row) for row in rows]


def load_story_dependency_rows_for_story(
    story_id: str,
    store_dir: Path | None = None,
) -> list[StoryDependency]:
    rows = _backend_module().load_story_dependency_rows_for_story(store_dir, story_id)
    return [mappers.story_dependency_row_to_entity(row) for row in rows]


def delete_story_dependency(
    story_id: str,
    depends_on_story_id: str,
    kind: StoryDependencyKind,
    store_dir: Path | None = None,
) -> int:
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
    row = _backend_module().load_parallelization_config_row(store_dir, project_key)
    if row is None:
        return None
    return mappers.parallelization_config_row_to_entity(row)


def save_parallelization_config(
    config: ParallelizationConfig,
    store_dir: Path | None = None,
) -> None:
    row = mappers.parallelization_config_to_row(config)
    _backend_module().save_parallelization_config_row(store_dir, row)


def save_story_are_link(
    link: StoryAreLink,
    store_dir: Path | None = None,
) -> None:
    row = mappers.story_are_link_to_row(link)
    _backend_module().save_story_are_link_row(store_dir, row)


def load_story_are_links(
    story_id: str,
    store_dir: Path | None = None,
) -> list[StoryAreLink]:
    rows = _backend_module().load_story_are_link_rows(store_dir, story_id)
    return [mappers.story_are_link_row_to_entity(row) for row in rows]


def update_story_are_link_kind(
    store_dir: Path | None,
    story_id: str,
    are_item_id: str,
    old_kind: StoryAreLinkKind,
    new_kind: StoryAreLinkKind,
) -> StoryAreLink | None:
    row = _backend_module().update_story_are_link_kind_row(
        store_dir,
        story_id,
        are_item_id,
        old_kind.value,
        new_kind.value,
    )
    if row is None:
        return None
    return mappers.story_are_link_row_to_entity(row)


def delete_story_are_link(
    store_dir: Path | None,
    story_id: str,
    are_item_id: str,
    kind: StoryAreLinkKind,
) -> int:
    return int(
        _backend_module().delete_story_are_link_row(
            store_dir,
            story_id,
            are_item_id,
            kind.value,
        ),
    )


__all__ = [
    "save_story_context",
    "save_story_context_global",
    "load_story_context",
    "load_story_context_global",
    "load_story_context_by_story_number_global",
    "load_story_context_by_uuid_global",
    "load_story_contexts_global",
    "read_story_context_record",
    "save_project",
    "load_project",
    "load_projects",
    "load_project_by_story_id_prefix",
    "save_project_api_token",
    "load_project_api_token",
    "load_project_api_token_by_hash",
    "load_project_api_tokens_for_project",
    "save_story_dependency",
    "load_story_dependencies",
    "load_story_dependency_rows_for_story",
    "delete_story_dependency",
    "load_parallelization_config",
    "save_parallelization_config",
    "save_story_are_link",
    "load_story_are_links",
    "update_story_are_link_kind",
    "delete_story_are_link",
]
