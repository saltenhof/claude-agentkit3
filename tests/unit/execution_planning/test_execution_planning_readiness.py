from __future__ import annotations

from datetime import UTC, datetime

from agentkit.execution_planning.dependency_graph import DependencyGraph
from agentkit.execution_planning.entities import (
    BlockingConditionKind,
    ExecutionCapacityBudgets,
    ExternalGate,
    GateState,
    HumanGate,
    HumanGateKind,
    ParallelizationConfig,
    SchedulingHint,
    StoryDependency,
    StoryDependencyKind,
    StoryRefForPlanning,
)
from agentkit.execution_planning.readiness import compute_readiness, derive_plan


def _story(number: int, *, status: str = "defined") -> StoryRefForPlanning:
    return StoryRefForPlanning(
        project_key="tenant-a",
        story_id=f"AK3-{number:03d}",
        story_number=number,
        title=f"Story {number}",
        lifecycle_status=status,
    )


def _edge(
    story_id: str,
    depends_on: str,
    *,
    kind: StoryDependencyKind = StoryDependencyKind.HARD_STORY_DEPENDENCY,
) -> StoryDependency:
    return StoryDependency(
        story_id=story_id,
        depends_on_story_id=depends_on,
        kind=kind,
        created_at=datetime.now(UTC),
    )


def _budgets(limit: int) -> ExecutionCapacityBudgets:
    return ExecutionCapacityBudgets(
        repo_parallel_cap=limit,
        merge_risk_cap=limit,
        api_rate_limit_cap=limit,
        llm_pool_cap=limit,
        ci_capacity_cap=limit,
    )


def test_linear_chain_readiness() -> None:
    stories = [_story(1, status="done"), _story(2), _story(3)]
    graph = DependencyGraph([_edge("AK3-002", "AK3-001"), _edge("AK3-003", "AK3-002")])

    result = compute_readiness(
        graph,
        {"AK3-001"},
        stories,
        ParallelizationConfig(project_key="tenant-a", max_parallel_stories=2),
    )

    assert [story.story_id for story in result.next_ready] == ["AK3-002"]
    assert [story.story_id for story in result.next_wave_after] == ["AK3-003"]
    assert result.reason


def test_practical_parallelism_caps_ready_stories() -> None:
    stories = [_story(1), _story(2), _story(3)]

    result = compute_readiness(
        DependencyGraph([]),
        set(),
        stories,
        ParallelizationConfig(project_key="tenant-a", max_parallel_stories=2),
    )

    assert result.theoretical_parallelism == 3
    assert result.practical_parallelism == 2
    assert [story.story_number for story in result.next_ready] == [1, 2]
    assert result.feasibility is not None
    assert result.scheduling_policy is not None
    assert result.feasibility.can_parallelize
    assert result.scheduling_policy.may_parallelize_now


def test_diamond_next_wave_after() -> None:
    stories = [_story(1, status="done"), _story(2), _story(3), _story(4)]
    graph = DependencyGraph(
        [
            _edge("AK3-002", "AK3-001"),
            _edge("AK3-003", "AK3-001"),
            _edge("AK3-004", "AK3-002"),
            _edge("AK3-004", "AK3-003"),
        ],
    )

    result = compute_readiness(
        graph,
        {"AK3-001"},
        stories,
        ParallelizationConfig(project_key="tenant-a", max_parallel_stories=2),
    )

    assert [story.story_id for story in result.next_ready] == ["AK3-002", "AK3-003"]
    assert [story.story_id for story in result.next_wave_after] == ["AK3-004"]


def test_feasibility_and_scheduling_are_separate_results() -> None:
    stories = [_story(1), _story(2), _story(3)]

    plan = derive_plan(
        graph=DependencyGraph([]),
        completed_story_ids=set(),
        all_stories=stories,
        project_key="tenant-a",
        budgets=_budgets(1),
    )

    assert plan.feasibility.can_parallelize
    assert not plan.scheduling_policy.may_parallelize_now
    assert plan.max_allowed_batch == 1
    assert plan.recommended_batch == 1


def test_scheduling_hint_only_narrows_and_never_heals_hard_blockers() -> None:
    stories = [_story(1), _story(2)]
    graph = DependencyGraph([_edge("AK3-002", "AK3-001")])

    blocked_plan = derive_plan(
        graph=graph,
        completed_story_ids=set(),
        all_stories=stories,
        project_key="tenant-a",
        budgets=_budgets(4),
        scheduling_hint=SchedulingHint(recommended_batch_limit=4),
    )
    narrowed_plan = derive_plan(
        graph=DependencyGraph([]),
        completed_story_ids=set(),
        all_stories=stories,
        project_key="tenant-a",
        budgets=_budgets(4),
        scheduling_hint=SchedulingHint(recommended_batch_limit=1),
    )

    assert [story.story_id for story in blocked_plan.ready_set] == ["AK3-001"]
    assert "AK3-002" in {story.story_id for story in blocked_plan.blocked_set}
    assert blocked_plan.recommended_batch == 1
    assert [story.story_id for story in narrowed_plan.ready_set] == [
        "AK3-001",
        "AK3-002",
    ]
    assert narrowed_plan.max_allowed_batch == 2
    assert narrowed_plan.recommended_batch == 1


def test_mixed_hard_and_soft_edges_only_hard_edges_block_readiness() -> None:
    stories = [_story(1), _story(2), _story(3)]
    graph = DependencyGraph(
        [
            _edge(
                "AK3-002",
                "AK3-001",
                kind=StoryDependencyKind.SOFT_STORY_DEPENDENCY,
            ),
            _edge(
                "AK3-003",
                "AK3-001",
                kind=StoryDependencyKind.HARD_STORY_DEPENDENCY,
            ),
        ],
    )

    plan = derive_plan(
        graph=graph,
        completed_story_ids=set(),
        all_stories=stories,
        project_key="tenant-a",
        budgets=_budgets(3),
    )

    assert [story.story_id for story in plan.ready_set] == ["AK3-001", "AK3-002"]
    blocked_by_kind = {
        blocker.kind
        for story in plan.blocked_set
        for blocker in story.blocked_by
    }
    assert blocked_by_kind == {BlockingConditionKind.BLOCKED_INTERNAL_DEPENDENCY}


def test_human_gate_blocking_vs_optional_review_and_external_gate() -> None:
    stories = [_story(1), _story(2), _story(3)]

    plan = derive_plan(
        graph=DependencyGraph([]),
        completed_story_ids=set(),
        all_stories=stories,
        project_key="tenant-a",
        budgets=_budgets(3),
        human_gates=[
            HumanGate(
                project_key="tenant-a",
                story_id="AK3-001",
                gate_id="approval",
                kind=HumanGateKind.BLOCKING_GATE,
                state=GateState.OPEN,
                reason_code="approval_missing",
            ),
            HumanGate(
                project_key="tenant-a",
                story_id="AK3-002",
                gate_id="review",
                kind=HumanGateKind.OPTIONAL_REVIEW,
                state=GateState.OPEN,
                reason_code="review_requested",
            ),
        ],
        external_gates=[
            ExternalGate(
                project_key="tenant-a",
                story_id="AK3-003",
                gate_id="api",
                state=GateState.OPEN,
                reason_code="api_unavailable",
            ),
        ],
    )

    assert [story.story_id for story in plan.ready_set] == ["AK3-002"]
    blockers = {
        story.story_id: {blocker.kind for blocker in story.blocked_by}
        for story in plan.blocked_set
    }
    assert blockers == {
        "AK3-001": {BlockingConditionKind.BLOCKED_HUMAN},
        "AK3-003": {BlockingConditionKind.BLOCKED_EXTERNAL},
    }


def test_readiness_rule_matrix_for_dependency_kinds() -> None:
    stories = [_story(number) for number in range(1, 8)]
    graph = DependencyGraph(
        [
            _edge("AK3-002", "AK3-001", kind=StoryDependencyKind.HARD_STORY_DEPENDENCY),
            _edge(
                "AK3-003",
                "AK3-001",
                kind=StoryDependencyKind.SERIAL_EXECUTION_CONSTRAINT,
            ),
            _edge("AK3-004", "AK3-001", kind=StoryDependencyKind.MUTEX_CONSTRAINT),
            _edge(
                "AK3-005",
                "AK3-001",
                kind=StoryDependencyKind.SHARED_CONTRACT_DEPENDENCY,
            ),
            _edge(
                "AK3-006",
                "AK3-001",
                kind=StoryDependencyKind.SHARED_FILE_CONFLICT,
            ),
            _edge("AK3-007", "AK3-001", kind=StoryDependencyKind.EXTERNAL_DEPENDENCY),
        ],
    )

    blocked_plan = derive_plan(
        graph=graph,
        completed_story_ids=set(),
        all_stories=stories,
        project_key="tenant-a",
        budgets=_budgets(7),
    )
    ready_plan = derive_plan(
        graph=graph,
        completed_story_ids={"AK3-001"},
        all_stories=stories,
        project_key="tenant-a",
        budgets=_budgets(7),
    )

    assert [story.story_id for story in blocked_plan.ready_set] == ["AK3-001"]
    assert [story.story_id for story in ready_plan.ready_set] == [
        "AK3-002",
        "AK3-003",
        "AK3-004",
        "AK3-005",
        "AK3-006",
        "AK3-007",
    ]


def test_plan_derivation_is_tenant_scoped_and_deterministic() -> None:
    stories = [
        _story(1),
        _story(2),
        StoryRefForPlanning(
            project_key="tenant-b",
            story_id="AK3-003",
            story_number=3,
            title="Story 3",
            lifecycle_status="defined",
        ),
    ]
    kwargs = {
        "graph": DependencyGraph([]),
        "completed_story_ids": set(),
        "all_stories": stories,
        "project_key": "tenant-a",
        "budgets": _budgets(3),
    }

    first = derive_plan(**kwargs)
    second = derive_plan(**kwargs)

    assert [story.story_id for story in first.ready_set] == ["AK3-001", "AK3-002"]
    assert first.execution_wave.project_key == "tenant-a"
    assert first == second
    assert first.critical_path in {("AK3-001",), ("AK3-002",)}
