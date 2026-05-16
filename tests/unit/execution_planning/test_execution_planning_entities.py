from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agentkit.execution_planning.entities import (
    ParallelizationConfig,
    StoryDependency,
    StoryDependencyKind,
)


def test_story_dependency_rejects_self_edge() -> None:
    with pytest.raises(ValidationError):
        StoryDependency(
            story_id="AK3-001",
            depends_on_story_id="AK3-001",
            kind=StoryDependencyKind.HARD_STORY_DEPENDENCY,
            created_at=datetime.now(UTC),
        )


def test_story_dependency_accepts_declared_kinds() -> None:
    edge = StoryDependency(
        story_id="AK3-002",
        depends_on_story_id="AK3-001",
        kind=StoryDependencyKind.SHARED_CONTRACT_DEPENDENCY,
        created_at=datetime.now(UTC),
    )

    assert edge.kind is StoryDependencyKind.SHARED_CONTRACT_DEPENDENCY


def test_parallelization_config_rejects_zero_limits() -> None:
    with pytest.raises(ValidationError):
        ParallelizationConfig(project_key="tenant-a", max_parallel_stories=0)
    with pytest.raises(ValidationError):
        ParallelizationConfig(
            project_key="tenant-a",
            max_parallel_stories=1,
            max_parallel_stories_per_repo=0,
        )
