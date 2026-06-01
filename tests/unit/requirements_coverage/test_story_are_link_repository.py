from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.project_management.entities import ProjectConfiguration
from agentkit.project_management.lifecycle import create_project
from agentkit.requirements_coverage.errors import (
    StoryAreLinkConflictError,
    StoryAreLinkNotFoundError,
)
from agentkit.requirements_coverage.models import StoryAreLink, StoryAreLinkKind
from agentkit.state_backend.store import facade
from agentkit.state_backend.store.project_management_repository import (
    StateBackendProjectRepository,
)
from agentkit.state_backend.store.story_are_link_repository import (
    StateBackendStoryAreLinkRepository,
)
from agentkit.state_backend.store.story_context_repository import (
    StateBackendStoryContextRepository,
)
from agentkit.story_context_manager.display_id import format_story_display_id
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _reset_backend() -> None:
    facade.reset_backend_cache_for_tests()


def _configuration() -> ProjectConfiguration:
    return ProjectConfiguration(
        repo_url="",
        default_branch="main",
        are_url=None,
        default_worker_count=1,
        repositories=["https://example.test/repo.git"],
    )


def _seed_story(tmp_path: Path) -> str:
    """Seed a story_contexts row (AG3-050).

    The ``story_are_links`` FK references ``story_contexts(story_id)``, so the
    runtime projection row is what must exist. The display-ID is materialized
    through the single canonical formatter (FK-02 §2.11.2).
    """
    project_repository = StateBackendProjectRepository(tmp_path)
    story_repository = StateBackendStoryContextRepository(tmp_path)
    project_repository.save(create_project("tenant-a", "Tenant A", "AK3", _configuration(), repositories=["https://example.test/repo.git"]))
    story_id = format_story_display_id("AK3", 1)
    story_repository.save(
        StoryContext(
            project_key="tenant-a",
            story_number=1,
            story_id=story_id,
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
            title="Coverage story",
            created_at=datetime.now(UTC),
        ),
    )
    return story_id


def test_story_are_link_repository_insert_update_delete(tmp_path: Path) -> None:
    story_id = _seed_story(tmp_path)
    repository = StateBackendStoryAreLinkRepository(tmp_path)
    link = StoryAreLink(
        story_id=story_id,
        are_item_id="ARE-1",
        kind=StoryAreLinkKind.ADDRESSES,
    )

    repository.add(link)
    updated = repository.update_kind(
        story_id,
        "ARE-1",
        StoryAreLinkKind.ADDRESSES,
        StoryAreLinkKind.PARTIAL,
    )

    assert updated == StoryAreLink(
        story_id=story_id,
        are_item_id="ARE-1",
        kind=StoryAreLinkKind.PARTIAL,
    )
    assert repository.list_by_story(story_id) == [updated]

    repository.remove(story_id, "ARE-1", StoryAreLinkKind.PARTIAL)

    assert repository.list_by_story(story_id) == []


def test_story_are_link_repository_rejects_duplicates(tmp_path: Path) -> None:
    story_id = _seed_story(tmp_path)
    repository = StateBackendStoryAreLinkRepository(tmp_path)
    link = StoryAreLink(
        story_id=story_id,
        are_item_id="ARE-1",
        kind=StoryAreLinkKind.ADDRESSES,
    )

    repository.add(link)

    with pytest.raises(StoryAreLinkConflictError):
        repository.add(link)
    with pytest.raises(sqlite3.IntegrityError):
        facade.save_story_are_link(link, tmp_path)


def test_story_are_link_repository_allows_multiple_kinds(tmp_path: Path) -> None:
    story_id = _seed_story(tmp_path)
    repository = StateBackendStoryAreLinkRepository(tmp_path)

    repository.add(
        StoryAreLink(
            story_id=story_id,
            are_item_id="ARE-1",
            kind=StoryAreLinkKind.ADDRESSES,
        )
    )
    repository.add(
        StoryAreLink(
            story_id=story_id,
            are_item_id="ARE-1",
            kind=StoryAreLinkKind.DERIVES_FROM,
        )
    )

    assert repository.list_by_story(story_id) == [
        StoryAreLink(
            story_id=story_id,
            are_item_id="ARE-1",
            kind=StoryAreLinkKind.ADDRESSES,
        ),
        StoryAreLink(
            story_id=story_id,
            are_item_id="ARE-1",
            kind=StoryAreLinkKind.DERIVES_FROM,
        ),
    ]


def test_story_are_link_repository_lists_by_story_deterministically(
    tmp_path: Path,
) -> None:
    story_id = _seed_story(tmp_path)
    repository = StateBackendStoryAreLinkRepository(tmp_path)
    repository.add(
        StoryAreLink(
            story_id=story_id,
            are_item_id="ARE-2",
            kind=StoryAreLinkKind.RECURRING,
        )
    )
    repository.add(
        StoryAreLink(
            story_id=story_id,
            are_item_id="ARE-1",
            kind=StoryAreLinkKind.PARTIAL,
        )
    )
    repository.add(
        StoryAreLink(
            story_id=story_id,
            are_item_id="ARE-1",
            kind=StoryAreLinkKind.ADDRESSES,
        )
    )

    assert repository.list_by_story(story_id) == [
        StoryAreLink(
            story_id=story_id,
            are_item_id="ARE-1",
            kind=StoryAreLinkKind.ADDRESSES,
        ),
        StoryAreLink(
            story_id=story_id,
            are_item_id="ARE-1",
            kind=StoryAreLinkKind.PARTIAL,
        ),
        StoryAreLink(
            story_id=story_id,
            are_item_id="ARE-2",
            kind=StoryAreLinkKind.RECURRING,
        ),
    ]


def test_story_are_link_repository_reports_missing_rows(tmp_path: Path) -> None:
    story_id = _seed_story(tmp_path)
    repository = StateBackendStoryAreLinkRepository(tmp_path)

    with pytest.raises(StoryAreLinkNotFoundError):
        repository.update_kind(
            story_id,
            "ARE-1",
            StoryAreLinkKind.ADDRESSES,
            StoryAreLinkKind.PARTIAL,
        )
    with pytest.raises(StoryAreLinkNotFoundError):
        repository.remove(story_id, "ARE-1", StoryAreLinkKind.ADDRESSES)
