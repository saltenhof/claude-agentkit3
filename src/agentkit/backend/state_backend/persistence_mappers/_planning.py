"""Execution-planning and requirements-coverage row mappers."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from ._common import dump_json

if TYPE_CHECKING:
    from agentkit.backend.execution_planning.entities import ParallelizationConfig, StoryDependency
    from agentkit.backend.requirements_coverage.models import StoryAreLink



def story_dependency_to_row(
    edge: StoryDependency,
    *,
    project_key: str,
) -> dict[str, Any]:
    """Convert a story dependency edge to a DB row."""

    return {
        "project_key": project_key,
        "story_id": edge.story_id,
        "depends_on_story_id": edge.depends_on_story_id,
        "kind": edge.kind.value,
        "created_at": edge.created_at.isoformat(),
    }



def story_dependency_row_to_entity(row: dict[str, Any]) -> StoryDependency:
    """Convert a DB row to a story dependency edge."""

    from agentkit.backend.execution_planning.entities import (
        StoryDependency as _StoryDependency,
    )
    from agentkit.backend.execution_planning.entities import (
        StoryDependencyKind as _StoryDependencyKind,
    )

    created_at_raw = row["created_at"]
    created_at = (
        datetime.fromisoformat(created_at_raw)
        if isinstance(created_at_raw, str)
        else created_at_raw
    )
    return _StoryDependency(
        story_id=str(row["story_id"]),
        depends_on_story_id=str(row["depends_on_story_id"]),
        kind=_StoryDependencyKind(str(row["kind"])),
        created_at=created_at,
    )



def parallelization_config_to_row(config: ParallelizationConfig) -> dict[str, Any]:
    """Convert a parallelization config to a DB row."""

    return {
        "project_key": config.project_key,
        "max_parallel_stories": config.max_parallel_stories,
        "max_parallel_stories_per_repo": config.max_parallel_stories_per_repo,
        "extra_config_json": dump_json({}),
    }



def parallelization_config_row_to_entity(
    row: dict[str, Any],
) -> ParallelizationConfig:
    """Convert a DB row to a parallelization config."""

    from agentkit.backend.execution_planning.entities import (
        ParallelizationConfig as _ParallelizationConfig,
    )

    max_parallel_stories_per_repo = row.get("max_parallel_stories_per_repo")
    return _ParallelizationConfig(
        project_key=str(row["project_key"]),
        max_parallel_stories=int(row["max_parallel_stories"]),
        max_parallel_stories_per_repo=(
            int(max_parallel_stories_per_repo)
            if max_parallel_stories_per_repo is not None
            else None
        ),
    )



def story_are_link_to_row(link: StoryAreLink) -> dict[str, Any]:
    """Convert a StoryAreLink edge to a DB row."""

    return {
        "story_id": link.story_id,
        "are_item_id": link.are_item_id,
        "kind": link.kind.value,
    }



def story_are_link_row_to_entity(row: dict[str, Any]) -> StoryAreLink:
    """Convert a DB row to a StoryAreLink edge."""

    from agentkit.backend.requirements_coverage.models import (
        StoryAreLink as _StoryAreLink,
    )
    from agentkit.backend.requirements_coverage.models import (
        StoryAreLinkKind as _StoryAreLinkKind,
    )

    return _StoryAreLink(
        story_id=str(row["story_id"]),
        are_item_id=str(row["are_item_id"]),
        kind=_StoryAreLinkKind(str(row["kind"])),
    )
