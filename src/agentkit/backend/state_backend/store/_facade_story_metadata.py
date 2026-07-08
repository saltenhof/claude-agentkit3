"""Story metadata facade operations and static BC-store compatibility exports."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.state_backend.execution_planning_store import (
    delete_story_dependency as delete_story_dependency,
)
from agentkit.backend.state_backend.execution_planning_store import (
    load_parallelization_config as load_parallelization_config,
)
from agentkit.backend.state_backend.execution_planning_store import (
    load_story_dependencies as load_story_dependencies,
)
from agentkit.backend.state_backend.execution_planning_store import (
    load_story_dependency_rows_for_story as load_story_dependency_rows_for_story,
)
from agentkit.backend.state_backend.execution_planning_store import (
    save_parallelization_config as save_parallelization_config,
)
from agentkit.backend.state_backend.execution_planning_store import (
    save_story_dependency as save_story_dependency,
)
from agentkit.backend.state_backend.project_store import (
    load_project as load_project,
)
from agentkit.backend.state_backend.project_store import (
    load_project_api_token as load_project_api_token,
)
from agentkit.backend.state_backend.project_store import (
    load_project_api_token_by_hash as load_project_api_token_by_hash,
)
from agentkit.backend.state_backend.project_store import (
    load_project_api_tokens_for_project as load_project_api_tokens_for_project,
)
from agentkit.backend.state_backend.project_store import (
    load_project_by_story_id_prefix as load_project_by_story_id_prefix,
)
from agentkit.backend.state_backend.project_store import (
    load_projects as load_projects,
)
from agentkit.backend.state_backend.project_store import (
    save_project as save_project,
)
from agentkit.backend.state_backend.project_store import (
    save_project_api_token as save_project_api_token,
)
from agentkit.backend.state_backend.requirements_coverage_store import (
    delete_story_are_link as delete_story_are_link,
)
from agentkit.backend.state_backend.requirements_coverage_store import (
    load_story_are_links as load_story_are_links,
)
from agentkit.backend.state_backend.requirements_coverage_store import (
    save_story_are_link as save_story_are_link,
)
from agentkit.backend.state_backend.requirements_coverage_store import (
    update_story_are_link_kind as update_story_are_link_kind,
)
from agentkit.backend.state_backend.store import mappers
from agentkit.backend.state_backend.store._facade_backend import _backend_module

if TYPE_CHECKING:
    from pathlib import Path
    from uuid import UUID

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
