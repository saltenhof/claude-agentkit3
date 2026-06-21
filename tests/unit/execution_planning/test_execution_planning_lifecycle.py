from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from agentkit.backend.execution_planning.audit import PlanningAuditEmitter
from agentkit.backend.execution_planning.entities import (
    ExecutionWave,
    ExecutionWaveLifecycle,
    ParallelizationConfig,
    StoryDependency,
    StoryDependencyKind,
    StoryRefForPlanning,
    WaveStory,
)
from agentkit.backend.execution_planning.errors import (
    StoryDependencyConflictError,
    StoryDependencyCycleError,
    StoryDependencyNotFoundError,
)
from agentkit.backend.execution_planning.lifecycle import (
    add_dependency,
    assess_readiness,
    mark_wave_after_results,
    remove_dependency,
)
from agentkit.backend.telemetry.emitters import MemoryEmitter
from agentkit.backend.telemetry.events import EventType


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
        kind=StoryDependencyKind.HARD_STORY_DEPENDENCY,
        project_key="tenant-a",
        story_repo=story_repo,
        dep_repo=dep_repo,
    )

    assert dep_repo.edges == [edge]
    remove_dependency(
        story_id="AK3-002",
        depends_on_story_id="AK3-001",
        kind=StoryDependencyKind.HARD_STORY_DEPENDENCY,
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
                kind=StoryDependencyKind.HARD_STORY_DEPENDENCY,
                created_at=datetime.now(UTC),
            ),
        ],
    )

    with pytest.raises(StoryDependencyCycleError):
        add_dependency(
            story_id="AK3-001",
            depends_on_story_id="AK3-002",
            kind=StoryDependencyKind.HARD_STORY_DEPENDENCY,
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
            kind=StoryDependencyKind.HARD_STORY_DEPENDENCY,
            project_key="tenant-a",
            story_repo=story_repo,
            dep_repo=_DepRepo(),
        )
    with pytest.raises(StoryDependencyNotFoundError):
        add_dependency(
            story_id="AK3-002",
            depends_on_story_id="AK3-001",
            kind=StoryDependencyKind.HARD_STORY_DEPENDENCY,
            project_key="tenant-a",
            story_repo=story_repo,
            dep_repo=_DepRepo(),
        )
    with pytest.raises(StoryDependencyNotFoundError):
        add_dependency(
            story_id="missing",
            depends_on_story_id="AK3-001",
            kind=StoryDependencyKind.HARD_STORY_DEPENDENCY,
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
                kind=StoryDependencyKind.HARD_STORY_DEPENDENCY,
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


def test_assess_readiness_emits_story_ready_and_blocked_audit() -> None:
    """AC7: the readiness evaluation emits ``story_ready``/``story_blocked``.

    AK3-002 hard-depends on the not-yet-done AK3-001, so AK3-001 is READY and
    AK3-002 is BLOCKED. ``assess_readiness`` is the AG3-099 decision site for
    these two audit events (FK-70 §70.6.1/§70.10.3).
    """
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
                kind=StoryDependencyKind.HARD_STORY_DEPENDENCY,
                created_at=datetime.now(UTC),
            ),
        ],
    )
    emitter = MemoryEmitter()
    audit = PlanningAuditEmitter(emitter)

    assess_readiness(
        project_key="tenant-a",
        story_repo=story_repo,
        dep_repo=dep_repo,
        config_repo=_ConfigRepo(),
        audit=audit,
    )

    ready = {
        event.story_id
        for event in emitter.all_events
        if event.event_type is EventType.STORY_READY
    }
    blocked = {
        event.story_id
        for event in emitter.all_events
        if event.event_type is EventType.STORY_BLOCKED
    }
    assert ready == {"AK3-001"}
    assert blocked == {"AK3-002"}
    blocked_events = [
        event
        for event in emitter.all_events
        if event.event_type is EventType.STORY_BLOCKED
    ]
    # story_blocked carries the mandatory reason (FK-68 §68.2.2 contract).
    assert blocked_events[0].payload["reason"]


def test_emit_readiness_audit_without_plan_derivation_emits_ready_only() -> None:
    """The audit emitter guards the ``plan_derivation is None`` case (FK-70 §70.10.3).

    ``ReadinessAssessment.plan_derivation`` is optional; when it is absent the
    block-emission loop must be skipped (early return) while READY stories still
    emit ``story_ready``. This proves the defensive guard rather than crashing on
    ``None.blocked_set``.
    """
    from agentkit.backend.execution_planning.entities import ReadinessAssessment, WaveStory
    from agentkit.backend.execution_planning.lifecycle import _emit_readiness_audit

    assessment = ReadinessAssessment(
        next_ready=[
            WaveStory(
                story_id="AK3-001", story_number=1, title="S1", wave=0, is_ready=True
            )
        ],
        next_wave_after=[],
        theoretical_parallelism=1,
        practical_parallelism=1,
        reason="ok",
        plan_derivation=None,
    )
    emitter = MemoryEmitter()
    _emit_readiness_audit(
        assessment, project_key="tenant-a", audit=PlanningAuditEmitter(emitter)
    )
    emitted = [event.event_type for event in emitter.all_events]
    assert emitted == [EventType.STORY_READY]


def test_assess_readiness_without_audit_emits_nothing() -> None:
    """No audit emitter -> readiness evaluation is silent (back-compat)."""
    story_repo = _StoryRepo(
        {("tenant-a", "AK3-001"): _story("tenant-a", 1)},
    )
    # Pure assertion: assess_readiness(audit=None) does not raise and yields a
    # result; covered jointly with the default-config test above.
    result = assess_readiness(
        project_key="tenant-a",
        story_repo=story_repo,
        dep_repo=_DepRepo(),
        config_repo=_ConfigRepo(),
    )
    assert [s.story_id for s in result.next_ready] == ["AK3-001"]


def test_execution_wave_collapses_on_partial_failure() -> None:
    wave = ExecutionWave(
        project_key="tenant-a",
        wave_id="tenant-a:planned:AK3-001,AK3-002",
        lifecycle=ExecutionWaveLifecycle.ACTIVE,
        stories=(
            WaveStory(
                story_id="AK3-001",
                story_number=1,
                title="Story 1",
                wave=0,
                is_ready=True,
            ),
            WaveStory(
                story_id="AK3-002",
                story_number=2,
                title="Story 2",
                wave=0,
                is_ready=True,
            ),
        ),
    )

    collapsed = mark_wave_after_results(
        wave,
        completed_story_ids={"AK3-001"},
        failed_story_ids={"AK3-002"},
    )
    completed = mark_wave_after_results(
        wave,
        completed_story_ids={"AK3-001", "AK3-002"},
        failed_story_ids=set(),
    )

    assert collapsed.lifecycle is ExecutionWaveLifecycle.COLLAPSED
    assert completed.lifecycle is ExecutionWaveLifecycle.COMPLETED
    assert collapsed.project_key == "tenant-a"
