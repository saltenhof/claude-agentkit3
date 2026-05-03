"""Story creation application service."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from agentkit.story_context_manager.errors import (
    StoryIdentityConflictError,
    StoryProjectArchivedError,
    StoryProjectNotFoundError,
)
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.sizing import StorySize

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime
    from pathlib import Path

    from agentkit.project_management.repository import ProjectRepository
    from agentkit.story_context_manager.repository import StoryContextRepository
    from agentkit.story_context_manager.types import (
        ImplementationContract,
        StoryMode,
        StoryType,
    )


def create_story(
    *,
    project_key: str,
    story_type: StoryType,
    execution_route: StoryMode,
    project_repository: ProjectRepository,
    story_repository: StoryContextRepository,
    implementation_contract: ImplementationContract | None = None,
    issue_nr: int | None = None,
    title: str = "",
    story_size: StorySize = StorySize.SMALL,
    project_root: Path | None = None,
    participating_repos: Sequence[str] = (),
    labels: Sequence[str] = (),
    created_at: datetime | None = None,
) -> StoryContext:
    """Create and persist a story through the canonical allocation path."""

    project = project_repository.get(project_key)
    if project is None:
        raise StoryProjectNotFoundError(f"Project {project_key!r} does not exist")
    if project.archived_at is not None:
        raise StoryProjectArchivedError(f"Project {project_key!r} is archived")

    story_number = story_repository.allocate_next_story_number(project_key)
    story_id = f"{project.story_id_prefix}-{story_number:03d}"
    if story_repository.get_by_story_number(project_key, story_number) is not None:
        raise StoryIdentityConflictError(
            "Story number already belongs to this project",
        )

    story = StoryContext(
        story_uuid=uuid4(),
        project_key=project_key,
        story_number=story_number,
        story_id=story_id,
        story_type=story_type,
        execution_route=execution_route,
        implementation_contract=implementation_contract,
        issue_nr=issue_nr,
        title=title,
        story_size=story_size,
        project_root=project_root,
        participating_repos=list(participating_repos),
        labels=list(labels),
        created_at=created_at,
    )
    if story_repository.get_by_story_uuid(story.story_uuid) is not None:
        raise StoryIdentityConflictError("Story UUID already exists")
    story_repository.save(story)
    return story
