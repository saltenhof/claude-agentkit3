from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agentkit.execution_planning.entities import (
    BlockingCondition,
    BlockingConditionKind,
    BlockingConditionProvenance,
    ExecutionCapacityBudgets,
    HumanGate,
    HumanGateKind,
    ParallelizationConfig,
    PlannedStory,
    PlanningStatus,
    RePlanChange,
    RePlanChangeKind,
    RePlanTrigger,
    StoryDependency,
    StoryDependencyKind,
    StoryRefForPlanning,
    blocking_condition_status,
    classify_replan_trigger,
    planning_status_from_blockers,
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


def test_planned_story_field_set_and_story_ref_defaults_keep_callers_compatible() -> None:
    ref = StoryRefForPlanning(
        project_key="tenant-a",
        story_id="AK3-001",
        story_number=1,
        title="Story 1",
        lifecycle_status="defined",
    )

    assert isinstance(
        PlannedStory(
            project_key="tenant-a",
            story_id="AK3-002",
            story_number=2,
            title="Story 2",
            lifecycle_status="defined",
            story_type="implementation",
            story_size="m",
            participating_repos=("repo-a",),
            human_touchpoints=("uat",),
            external_prerequisites=("api-token",),
            planning_status=PlanningStatus.UNSTARTED,
        ),
        StoryRefForPlanning,
    )
    assert ref.story_type == "unknown"
    assert ref.story_size == "unknown"
    assert ref.participating_repos == ()
    assert ref.human_touchpoints == ()
    assert ref.external_prerequisites == ()
    assert ref.planning_status is PlanningStatus.UNSTARTED


def test_blocking_condition_closed_classes_and_typed_binding() -> None:
    assert {kind.value for kind in BlockingConditionKind} == {
        "blocked_internal_dependency",
        "blocked_external",
        "blocked_human",
        "blocked_capacity",
        "blocked_conflict",
        "blocked_contract",
    }
    blocker = BlockingCondition(
        story_id="AK3-002",
        kind=BlockingConditionKind.BLOCKED_INTERNAL_DEPENDENCY,
        provenance=BlockingConditionProvenance.DEPENDENCY_GRAPH,
        reason_code="hard_story_dependency",
        source_story_id="AK3-001",
    )

    assert blocker.source_story_id == "AK3-001"


@pytest.mark.parametrize(
    ("kind", "status"),
    [
        (BlockingConditionKind.BLOCKED_INTERNAL_DEPENDENCY, PlanningStatus.UNSTARTED),
        (BlockingConditionKind.BLOCKED_EXTERNAL, PlanningStatus.BLOCKED_EXTERNAL),
        (BlockingConditionKind.BLOCKED_HUMAN, PlanningStatus.BLOCKED_HUMAN),
        (BlockingConditionKind.BLOCKED_CAPACITY, PlanningStatus.BLOCKED_CAPACITY),
        (BlockingConditionKind.BLOCKED_CONFLICT, PlanningStatus.BLOCKED_CONFLICT),
        (BlockingConditionKind.BLOCKED_CONTRACT, PlanningStatus.BLOCKED_CONFLICT),
    ],
)
def test_blocker_kind_maps_to_planning_status(
    kind: BlockingConditionKind,
    status: PlanningStatus,
) -> None:
    assert blocking_condition_status(kind) is status


def test_multi_blocker_status_priority() -> None:
    blockers = [
        BlockingCondition(
            story_id="AK3-002",
            kind=kind,
            provenance=BlockingConditionProvenance.DEPENDENCY_GRAPH,
            reason_code=kind.value,
        )
        for kind in (
            BlockingConditionKind.BLOCKED_CAPACITY,
            BlockingConditionKind.BLOCKED_CONTRACT,
            BlockingConditionKind.BLOCKED_EXTERNAL,
            BlockingConditionKind.BLOCKED_HUMAN,
            BlockingConditionKind.BLOCKED_INTERNAL_DEPENDENCY,
        )
    ]

    assert planning_status_from_blockers(blockers) is PlanningStatus.BLOCKED_HUMAN


def test_planning_status_has_exact_fk70_values() -> None:
    assert [status.value for status in PlanningStatus] == [
        "UNSTARTED",
        "READY",
        "FLIGHT",
        "DONE",
        "BLOCKED_EXTERNAL",
        "BLOCKED_HUMAN",
        "BLOCKED_CAPACITY",
        "BLOCKED_CONFLICT",
    ]


def test_budget_dimensions_are_typed_and_closed() -> None:
    budgets = ExecutionCapacityBudgets(
        repo_parallel_cap=3,
        merge_risk_cap=2,
        api_rate_limit_cap=4,
        llm_pool_cap=5,
        ci_capacity_cap=6,
    )

    assert budgets.max_allowed_batch == 2


def test_human_gate_models_optional_review_separately() -> None:
    blocking = HumanGate(
        project_key="tenant-a",
        story_id="AK3-001",
        gate_id="uat",
        kind=HumanGateKind.BLOCKING_GATE,
        state="open",
        reason_code="uat_missing",
    )
    optional = HumanGate(
        project_key="tenant-a",
        story_id="AK3-001",
        gate_id="review",
        kind=HumanGateKind.OPTIONAL_REVIEW,
        state="open",
        reason_code="review_requested",
    )

    assert blocking.is_blocking_open
    assert not optional.is_blocking_open


@pytest.mark.parametrize(
    ("change_kind", "trigger"),
    [
        (RePlanChangeKind.STORY_DONE, RePlanTrigger.STORY_DONE),
        (
            RePlanChangeKind.BLOCKER_CHANGED,
            RePlanTrigger.BLOCKER_OR_GATE_CHANGED,
        ),
        (
            RePlanChangeKind.GATE_CHANGED,
            RePlanTrigger.BLOCKER_OR_GATE_CHANGED,
        ),
        (
            RePlanChangeKind.CAPACITY_BUDGET_CHANGED,
            RePlanTrigger.CAPACITY_BUDGET_CHANGED,
        ),
        (
            RePlanChangeKind.RULEBOOK_CHANGED,
            RePlanTrigger.RULEBOOK_OR_POLICY_CHANGED,
        ),
        (
            RePlanChangeKind.SCHEDULING_POLICY_CHANGED,
            RePlanTrigger.RULEBOOK_OR_POLICY_CHANGED,
        ),
        (
            RePlanChangeKind.CONFLICT_REEVALUATED,
            RePlanTrigger.CONFLICT_OR_CONTRACT_REEVALUATED,
        ),
        (
            RePlanChangeKind.CONTRACT_REEVALUATED,
            RePlanTrigger.CONFLICT_OR_CONTRACT_REEVALUATED,
        ),
    ],
)
def test_replan_trigger_classification(
    change_kind: RePlanChangeKind,
    trigger: RePlanTrigger,
) -> None:
    assert (
        classify_replan_trigger(
            RePlanChange(
                project_key="tenant-a",
                change_kind=change_kind,
                reason_code=change_kind.value,
            ),
        )
        is trigger
    )
