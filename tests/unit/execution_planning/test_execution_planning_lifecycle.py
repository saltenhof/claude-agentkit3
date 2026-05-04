from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from agentkit.execution_planning.entities import (
    ParallelizationConfig,
    StoryDependency,
    StoryDependencyKind,
    StoryRefForPlanning,
)
from agentkit.execution_planning.errors import (
    StoryDependencyConflictError,
    StoryDependencyCycleError,
    StoryDependencyNotFoundError,
)
from agentkit.execution_planning.lifecycle import (
    add_dependency,
    assess_readiness,
    remove_dependency,
)


@dataclass
class _StoryRepo:
    stories: dict[tuple[str, str], StoryRefForPlanning]

    def get(self, project_key: str, story_id: str) -> StoryRefForPlanning | None:
        return self.stories.get((project_key, story_id))

    def list_for_project(self, project_key: str) -> list[StoryRefForPlanning]:
        return [
            story
            for (stored_project_key, _), story in self.stories.items()
            if stored_project_key == project_key
        ]


@dataclass
class _DepRepo:
    edges: list[StoryDependency] = field(default_factory=list)

    def list_for_project(self, project_key: str) -> list[StoryDependency]:
        del project_key
        return list(self.edges)

    def list_for_story(self, story_id: str) -> list[StoryDependency]:
        return [edge for edge in self.edges if edge.story_id == story_id]

    def add(self, edge: StoryDependency, *, project_key: str) -> None:
        del project_key
        if edge in self.edges:
            raise StoryDependencyConflictError("duplicate")
        self.edges.append(edge)

    def remove(
        self,
        story_id: str,
        depends_on_story_id: str,
        kind: StoryDependencyKind,
    ) -> None:
        before = len(self.edges)
        self.edges = [
            edge
            for edge in self.edges
            if not (
                edge.story_id == story_id
                and edge.depends_on_story_id == depends_on_story_id
                and edge.kind == kind
            )
        ]
        if len(self.edges) == before:
            raise StoryDependencyNotFoundError("missing")


@dataclass
class _ConfigRepo:
    config: ParallelizationConfig | None = None

    def get(self, project_key: str) -> ParallelizationConfig | None:
        del project_key
        return self.config

    def upsert(self, config: ParallelizationConfig) -> None:
        self.config = config


def _story(project_key: str, number: int, *, status: str = "defined") -> StoryRefForPlanning:
    return StoryRefForPlanning(
        project_key=project_key,
        story_id=f"AK3-{number:03d}",
        story_number=number,
        title=f"Story {number}",
        lifecycle_status=status,
    )


def test_add_and_remove_dependency() -> None:
    story_repo = _StoryRepo(
        {
            ("tenant-a", "AK3-001"): _story("tenant-a", 1),
            ("tenant-a", "AK3-002"): _story("tenant-a", 2),
        },
    )
    dep_repo = _DepRepo()

    edge = add_dependency(
        story_id="AK3-002",
        depends_on_story_id="AK3-001",
        kind=StoryDependencyKind.BLOCKS,
        project_key="tenant-a",
        story_repo=story_repo,
        dep_repo=dep_repo,
    )

    assert dep_repo.edges == [edge]
    remove_dependency(
        story_id="AK3-002",
        depends_on_story_id="AK3-001",
        kind=StoryDependencyKind.BLOCKS,
        dep_repo=dep_repo,
    )
    assert dep_repo.edges == []


def test_add_dependency_rejects_cycle_without_persisting() -> None:
    story_repo = _StoryRepo(
        {
            ("tenant-a", "AK3-001"): _story("tenant-a", 1),
            ("tenant-a", "AK3-002"): _story("tenant-a", 2),
        },
    )
    dep_repo = _DepRepo(
        [
            StoryDependency(
                story_id="AK3-002",
                depends_on_story_id="AK3-001",
                kind=StoryDependencyKind.BLOCKS,
                created_at=datetime.now(UTC),
            ),
        ],
    )

    with pytest.raises(StoryDependencyCycleError):
        add_dependency(
            story_id="AK3-001",
            depends_on_story_id="AK3-002",
            kind=StoryDependencyKind.BLOCKS,
            project_key="tenant-a",
            story_repo=story_repo,
            dep_repo=dep_repo,
        )

    assert len(dep_repo.edges) == 1


def test_add_dependency_rejects_self_cross_project_and_missing_story() -> None:
    story_repo = _StoryRepo(
        {
            ("tenant-a", "AK3-001"): _story("tenant-a", 1),
            ("tenant-a", "AK3-002"): _story("tenant-b", 2),
        },
    )

    with pytest.raises(StoryDependencyConflictError):
        add_dependency(
            story_id="AK3-001",
            depends_on_story_id="AK3-001",
            kind=StoryDependencyKind.BLOCKS,
            project_key="tenant-a",
            story_repo=story_repo,
            dep_repo=_DepRepo(),
        )
    with pytest.raises(StoryDependencyNotFoundError):
        add_dependency(
            story_id="AK3-002",
            depends_on_story_id="AK3-001",
            kind=StoryDependencyKind.BLOCKS,
            project_key="tenant-a",
            story_repo=story_repo,
            dep_repo=_DepRepo(),
        )
    with pytest.raises(StoryDependencyNotFoundError):
        add_dependency(
            story_id="missing",
            depends_on_story_id="AK3-001",
            kind=StoryDependencyKind.BLOCKS,
            project_key="tenant-a",
            story_repo=story_repo,
            dep_repo=_DepRepo(),
        )


def test_assess_readiness_uses_default_parallel_config() -> None:
    story_repo = _StoryRepo(
        {
            ("tenant-a", "AK3-001"): _story("tenant-a", 1, status="done"),
            ("tenant-a", "AK3-002"): _story("tenant-a", 2),
        },
    )
    dep_repo = _DepRepo(
        [
            StoryDependency(
                story_id="AK3-002",
                depends_on_story_id="AK3-001",
                kind=StoryDependencyKind.BLOCKS,
                created_at=datetime.now(UTC),
            ),
        ],
    )

    result = assess_readiness(
        project_key="tenant-a",
        story_repo=story_repo,
        dep_repo=dep_repo,
        config_repo=_ConfigRepo(),
    )

    assert [story.story_id for story in result.next_ready] == ["AK3-002"]
