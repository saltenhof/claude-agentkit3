"""Pure readiness calculations for execution planning."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.core_types import StoryDependencyKind
from agentkit.backend.execution_planning.dependency_graph import HARD_BLOCKING_DEPENDENCY_KINDS
from agentkit.backend.execution_planning.entities import (
    BlockingCondition,
    BlockingConditionKind,
    BlockingConditionProvenance,
    ExecutionCapacityBudgets,
    ExecutionFeasibility,
    ExecutionSchedulingPolicy,
    ExecutionWave,
    ExecutionWaveLifecycle,
    ExternalGate,
    HumanGate,
    PlanDerivation,
    ReadinessAssessment,
    SchedulingHint,
    WaveStory,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from agentkit.backend.execution_planning.dependency_graph import DependencyGraph
    from agentkit.backend.execution_planning.entities import (
        ParallelizationConfig,
        StoryRefForPlanning,
    )

_DONE_STATUSES = frozenset({"done", "completed", "pass", "pass_with_warnings"})
_NON_FEASIBILITY_BLOCKERS = frozenset({BlockingConditionKind.BLOCKED_CAPACITY})
_CONFLICT_BLOCKERS = frozenset(
    {
        BlockingConditionKind.BLOCKED_CONFLICT,
        BlockingConditionKind.BLOCKED_CONTRACT,
    },
)


def compute_readiness(
    graph: DependencyGraph,
    completed_story_ids: set[str],
    all_stories: Sequence[StoryRefForPlanning],
    parallel_config: ParallelizationConfig,
) -> ReadinessAssessment:
    """Compute deterministic next-ready and one-wave-after story sets."""

    budgets = _budgets_from_parallel_config(parallel_config)
    plan = derive_plan(
        graph=graph,
        completed_story_ids=completed_story_ids,
        all_stories=all_stories,
        project_key=parallel_config.project_key,
        budgets=budgets,
    )
    next_ready = list(plan.execution_wave.stories)
    completed_after_next_wave = completed_story_ids | {
        story.story_id for story in next_ready
    }
    following_plan = derive_plan(
        graph=graph,
        completed_story_ids=completed_after_next_wave,
        all_stories=all_stories,
        project_key=parallel_config.project_key,
        budgets=budgets,
    )
    next_ready_ids = {story.story_id for story in next_ready}
    next_wave_after = [
        story
        for story in following_plan.ready_set
        if story.story_id not in next_ready_ids
    ]
    return ReadinessAssessment(
        next_ready=next_ready,
        next_wave_after=next_wave_after,
        theoretical_parallelism=len(plan.ready_set),
        practical_parallelism=plan.recommended_batch,
        reason=_reason(
            len(plan.ready_set),
            plan.max_allowed_batch,
            plan.recommended_batch,
        ),
        feasibility=plan.feasibility,
        scheduling_policy=plan.scheduling_policy,
        plan_derivation=plan,
    )


def derive_plan(
    *,
    graph: DependencyGraph,
    completed_story_ids: set[str],
    all_stories: Sequence[StoryRefForPlanning],
    project_key: str,
    budgets: ExecutionCapacityBudgets,
    scheduling_hint: SchedulingHint | None = None,
    human_gates: Sequence[HumanGate] = (),
    external_gates: Sequence[ExternalGate] = (),
    blocking_conditions: Sequence[BlockingCondition] = (),
) -> PlanDerivation:
    """Derive the deterministic plan outputs for one project."""

    project_stories = [
        story for story in all_stories if story.project_key == project_key
    ]
    stories_by_id = {story.story_id: story for story in project_stories}
    active_stories = [
        story
        for story in project_stories
        if story.story_id not in completed_story_ids
        and story.lifecycle_status.lower() not in _DONE_STATUSES
    ]
    layer_by_story_id = _layer_index_by_story_id(graph, stories_by_id)
    ready_set, blocked_set = _derive_ready_and_blocked_sets(
        graph=graph,
        stories=active_stories,
        completed_story_ids=completed_story_ids,
        layer_by_story_id=layer_by_story_id,
        human_gates=human_gates,
        external_gates=external_gates,
        blocking_conditions=blocking_conditions,
        project_key=project_key,
    )
    hard_blockers = tuple(
        blocker
        for story in blocked_set
        for blocker in story.blocked_by
        if blocker.kind not in _NON_FEASIBILITY_BLOCKERS
    )
    feasibility = ExecutionFeasibility(
        project_key=project_key,
        can_parallelize=len(ready_set) > 1,
        feasible_story_ids=tuple(story.story_id for story in ready_set),
        blocked_conditions=_sorted_blockers(hard_blockers),
    )
    max_allowed_batch = min(len(ready_set), budgets.max_allowed_batch)
    recommended_batch = max_allowed_batch
    if scheduling_hint is not None and scheduling_hint.recommended_batch_limit is not None:
        recommended_batch = min(
            recommended_batch,
            scheduling_hint.recommended_batch_limit,
        )
    scheduling_policy = ExecutionSchedulingPolicy(
        project_key=project_key,
        may_parallelize_now=feasibility.can_parallelize and max_allowed_batch > 1,
        budgets=budgets,
        hint=scheduling_hint,
    )
    execution_stories = tuple(ready_set[:recommended_batch])
    return PlanDerivation(
        project_key=project_key,
        critical_path=_critical_path(graph, stories_by_id),
        ready_set=tuple(ready_set),
        blocked_set=tuple(blocked_set),
        execution_wave=ExecutionWave(
            project_key=project_key,
            wave_id=_wave_id(project_key, execution_stories),
            lifecycle=ExecutionWaveLifecycle.PLANNED,
            stories=execution_stories,
        ),
        recommended_batch=recommended_batch,
        max_allowed_batch=max_allowed_batch,
        feasibility=feasibility,
        scheduling_policy=scheduling_policy,
    )


def completed_story_ids_from_statuses(
    stories: Sequence[StoryRefForPlanning],
) -> set[str]:
    """Derive completed story ids from planning story statuses."""

    return {
        story.story_id
        for story in stories
        if story.lifecycle_status.lower() in _DONE_STATUSES
    }


def _derive_ready_and_blocked_sets(
    *,
    graph: DependencyGraph,
    stories: Sequence[StoryRefForPlanning],
    completed_story_ids: set[str],
    layer_by_story_id: dict[str, int],
    human_gates: Sequence[HumanGate],
    external_gates: Sequence[ExternalGate],
    blocking_conditions: Sequence[BlockingCondition],
    project_key: str,
) -> tuple[list[WaveStory], list[WaveStory]]:
    ready: list[WaveStory] = []
    blocked: list[WaveStory] = []
    for story in sorted(stories, key=lambda item: (item.story_number, item.story_id)):
        if story.story_id in completed_story_ids:
            continue
        blocked_by = _blocking_conditions_for_story(
            graph=graph,
            story=story,
            completed_story_ids=completed_story_ids,
            human_gates=human_gates,
            external_gates=external_gates,
            blocking_conditions=blocking_conditions,
            project_key=project_key,
        )
        is_ready = not any(
            blocker.kind not in _NON_FEASIBILITY_BLOCKERS for blocker in blocked_by
        )
        wave_story = WaveStory(
            story_id=story.story_id,
            story_number=story.story_number,
            title=story.title,
            wave=layer_by_story_id.get(story.story_id, 0),
            is_ready=is_ready,
            blocked_by=blocked_by,
        )
        if wave_story.is_ready:
            ready.append(wave_story)
        else:
            blocked.append(wave_story)
    return ready, blocked


def _blocking_conditions_for_story(
    *,
    graph: DependencyGraph,
    story: StoryRefForPlanning,
    completed_story_ids: set[str],
    human_gates: Sequence[HumanGate],
    external_gates: Sequence[ExternalGate],
    blocking_conditions: Sequence[BlockingCondition],
    project_key: str,
) -> tuple[BlockingCondition, ...]:
    blockers: list[BlockingCondition] = []
    for edge in graph.direct_predecessor_edges(story.story_id):
        if edge.kind not in HARD_BLOCKING_DEPENDENCY_KINDS:
            continue
        if edge.depends_on_story_id in completed_story_ids:
            continue
        blockers.append(_blocker_from_edge(edge.kind, story.story_id, edge.depends_on_story_id))
    blockers.extend(
        BlockingCondition(
            story_id=story.story_id,
            kind=BlockingConditionKind.BLOCKED_HUMAN,
            provenance=BlockingConditionProvenance.HUMAN_GATE,
            reason_code=gate.reason_code,
            source_gate_id=gate.gate_id,
        )
        for gate in human_gates
        if gate.project_key == project_key
        and gate.story_id == story.story_id
        and gate.is_blocking_open
    )
    blockers.extend(
        BlockingCondition(
            story_id=story.story_id,
            kind=BlockingConditionKind.BLOCKED_EXTERNAL,
            provenance=BlockingConditionProvenance.EXTERNAL_GATE,
            reason_code=gate.reason_code,
            source_gate_id=gate.gate_id,
        )
        for gate in external_gates
        if gate.project_key == project_key
        and gate.story_id == story.story_id
        and gate.is_blocking_open
    )
    blockers.extend(
        blocker
        for blocker in blocking_conditions
        if blocker.story_id == story.story_id
    )
    return _sorted_blockers(blockers)


def _blocker_from_edge(
    kind: StoryDependencyKind,
    story_id: str,
    depends_on_story_id: str,
) -> BlockingCondition:
    blocker_kind = _blocker_kind_from_edge_kind(kind)
    return BlockingCondition(
        story_id=story_id,
        kind=blocker_kind,
        provenance=_provenance_for_blocker_kind(blocker_kind),
        reason_code=kind.value,
        source_story_id=depends_on_story_id,
    )


def _blocker_kind_from_edge_kind(kind: StoryDependencyKind) -> BlockingConditionKind:
    if kind in {
        StoryDependencyKind.HARD_STORY_DEPENDENCY,
        StoryDependencyKind.SERIAL_EXECUTION_CONSTRAINT,
    }:
        return BlockingConditionKind.BLOCKED_INTERNAL_DEPENDENCY
    if kind is StoryDependencyKind.MUTEX_CONSTRAINT:
        return BlockingConditionKind.BLOCKED_CONFLICT
    if kind is StoryDependencyKind.SHARED_CONTRACT_DEPENDENCY:
        return BlockingConditionKind.BLOCKED_CONTRACT
    if kind is StoryDependencyKind.SHARED_FILE_CONFLICT:
        return BlockingConditionKind.BLOCKED_CONFLICT
    if kind is StoryDependencyKind.EXTERNAL_DEPENDENCY:
        return BlockingConditionKind.BLOCKED_EXTERNAL
    if kind is StoryDependencyKind.HUMAN_GATE_DEPENDENCY:
        return BlockingConditionKind.BLOCKED_HUMAN
    raise ValueError(f"Unsupported hard dependency kind: {kind!r}")


def _provenance_for_blocker_kind(
    kind: BlockingConditionKind,
) -> BlockingConditionProvenance:
    if kind is BlockingConditionKind.BLOCKED_EXTERNAL:
        return BlockingConditionProvenance.EXTERNAL_GATE
    if kind is BlockingConditionKind.BLOCKED_HUMAN:
        return BlockingConditionProvenance.HUMAN_GATE
    if kind in _CONFLICT_BLOCKERS:
        return (
            BlockingConditionProvenance.CONTRACT_EVALUATION
            if kind is BlockingConditionKind.BLOCKED_CONTRACT
            else BlockingConditionProvenance.CONFLICT_EVALUATION
        )
    return BlockingConditionProvenance.DEPENDENCY_GRAPH


def _layer_index_by_story_id(
    graph: DependencyGraph,
    stories_by_id: dict[str, StoryRefForPlanning],
) -> dict[str, int]:
    layers = graph.topological_layers()
    layer_by_story_id: dict[str, int] = {}
    for index, layer in enumerate(layers):
        for story_id in layer:
            layer_by_story_id[story_id] = index
    for story_id in stories_by_id:
        layer_by_story_id.setdefault(story_id, 0)
    return layer_by_story_id


def _critical_path(
    graph: DependencyGraph,
    stories_by_id: dict[str, StoryRefForPlanning],
) -> tuple[str, ...]:
    story_ids = sorted(stories_by_id)
    paths: dict[str, tuple[str, ...]] = {story_id: (story_id,) for story_id in story_ids}
    for layer in graph.topological_layers():
        for story_id in sorted(story for story in layer if story in stories_by_id):
            predecessors = sorted(
                predecessor
                for predecessor in graph.direct_hard_predecessors(story_id)
                if predecessor in stories_by_id
            )
            if not predecessors:
                paths[story_id] = (story_id,)
                continue
            candidate_paths = [
                (*paths.get(predecessor, (predecessor,)), story_id)
                for predecessor in predecessors
            ]
            paths[story_id] = max(candidate_paths, key=lambda path: (len(path), path))
    if not paths:
        return ()
    return max(paths.values(), key=lambda path: (len(path), path))


def derive_budgets(
    config: ParallelizationConfig,
) -> ExecutionCapacityBudgets:
    """Canonical derivation of ``ExecutionCapacityBudgets`` from a ``ParallelizationConfig``.

    This is the Single Source of Truth for all five-cap derivation sites.
    Call this function instead of duplicating the fan-out inline.

    Args:
        config: Active parallelization config.

    Returns:
        ``ExecutionCapacityBudgets`` with all five caps set.
    """
    repo_cap = config.max_parallel_stories_per_repo or config.max_parallel_stories
    return ExecutionCapacityBudgets(
        repo_parallel_cap=repo_cap,
        merge_risk_cap=config.max_parallel_stories,
        api_rate_limit_cap=config.max_parallel_stories,
        llm_pool_cap=config.max_parallel_stories,
        ci_capacity_cap=config.max_parallel_stories,
    )


# Keep the private alias so existing internal callers (if any) still compile.
_budgets_from_parallel_config = derive_budgets


def _sorted_blockers(
    blockers: Sequence[BlockingCondition],
) -> tuple[BlockingCondition, ...]:
    return tuple(
        sorted(
            blockers,
            key=lambda blocker: (
                blocker.story_id,
                blocker.kind.value,
                blocker.provenance.value,
                blocker.reason_code,
                blocker.source_story_id or "",
                blocker.source_gate_id or "",
            ),
        ),
    )


def _wave_id(project_key: str, stories: tuple[WaveStory, ...]) -> str:
    story_ids = ",".join(story.story_id for story in stories)
    return f"{project_key}:planned:{story_ids}" if story_ids else f"{project_key}:planned:empty"


def _reason(
    theoretical_parallelism: int,
    max_allowed_batch: int,
    recommended_batch: int,
) -> str:
    if theoretical_parallelism == recommended_batch:
        return f"{recommended_batch} ready stories selected"
    return (
        f"{recommended_batch} of {theoretical_parallelism} ready stories selected; "
        f"max_allowed_batch={max_allowed_batch}"
    )
