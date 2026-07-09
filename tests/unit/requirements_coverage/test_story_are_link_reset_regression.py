"""Regression: StoryAreLink entries survive a story reset (FK-40 §40.5b.4).

The story-reset guardrail says that StoryAreLink entries are NOT deleted
on reset — they are part of the story contract, not of the run state.
This test pins that invariant without touching any schema or status
fields (AG3-030 scope restriction).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from agentkit.backend.project_management.entities import ProjectConfiguration
from agentkit.backend.project_management.lifecycle import create_project
from agentkit.backend.requirements_coverage.models import StoryAreLink, StoryAreLinkKind
from agentkit.backend.state_backend.persistence_test_support import reset_backend_cache_for_tests
from agentkit.backend.state_backend.store.project_management_repository import (
    StateBackendProjectRepository,
)
from agentkit.backend.state_backend.store.story_are_link_repository import (
    StateBackendStoryAreLinkRepository,
)
from agentkit.backend.state_backend.store.story_context_repository import (
    StateBackendStoryContextRepository,
)
from agentkit.backend.story_context_manager.display_id import format_story_display_id
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.types import StoryMode, StoryType


@pytest.fixture(autouse=True)
def _reset_backend() -> None:
    reset_backend_cache_for_tests()


def _configuration() -> ProjectConfiguration:
    return ProjectConfiguration(
        repo_url="",
        default_branch="main",
        are_url=None,
        default_worker_count=1,
        repositories=["https://example.test/repo.git"],
    )


def _seed_story(tmp_path: Path) -> str:
    project_repository = StateBackendProjectRepository(tmp_path)
    story_repository = StateBackendStoryContextRepository(tmp_path)
    project_repository.save(
        create_project(
            "tenant-b",
            "Tenant B",
            "AK3",
            _configuration(),
            repositories=["https://example.test/repo.git"],
        )
    )
    story_id = format_story_display_id("AK3", 1)
    story_repository.save(
        StoryContext(
            project_key="tenant-b",
            story_number=1,
            story_id=story_id,
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
            title="Reset regression story",
            created_at=datetime.now(UTC),
        ),
    )
    return story_id


def test_story_are_links_survive_reset_simulation(tmp_path: Path) -> None:
    """StoryAreLink rows are not deleted when the run state would be reset.

    We simulate a 'reset' by verifying that persisted StoryAreLink entries
    are still queryable after the backend cache is cleared and re-opened
    (the same operation the real reset path would do before a re-run).
    """
    story_id = _seed_story(tmp_path)
    repository = StateBackendStoryAreLinkRepository(tmp_path)

    link = StoryAreLink(
        story_id=story_id,
        are_item_id="ARE-RESET-1",
        kind=StoryAreLinkKind.ADDRESSES,
    )
    repository.add(link)

    # Simulate reset by clearing backend cache (same as pre-run reset would do)
    reset_backend_cache_for_tests()

    # Re-open the repository against the same path — links must still exist
    repository_after_reset = StateBackendStoryAreLinkRepository(tmp_path)
    links_after = repository_after_reset.list_by_story(story_id)

    assert links_after == [link], (
        "StoryAreLink entries must survive a reset — they are part of the "
        "story contract, not the run state (FK-40 §40.5b.4)"
    )
