"""Domain entities for execution planning.

``StoryDependencyKind`` has been imported from ``agentkit.backend.core_types``
since AG3-021 and uses the FK-70 §70.4.2-normative 8-value vocabulary.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agentkit.backend.core_types import StoryDependencyKind

__all__ = [
    "BlockingCondition",
    "BlockingConditionKind",
    "BlockingConditionProvenance",
    "ExecutionCapacityBudgets",
    "ExecutionFeasibility",
    "ExecutionSchedulingPolicy",
    "ExecutionWave",
    "ExecutionWaveLifecycle",
    "ExternalGate",
    "GateState",
    "HumanGate",
    "HumanGateKind",
    "ParallelizationConfig",
    "PlanDerivation",
    "PlannedStory",
    "PlanningStatus",
    "ReadinessAssessment",
    "RePlanChange",
    "RePlanChangeKind",
    "RePlanTrigger",
    "SchedulingHint",
    "StoryDependency",
    "StoryDependencyKind",
    "StoryRefForPlanning",
    "WaveStory",
    "blocking_condition_status",
    "classify_replan_trigger",
    "planning_status_from_blockers",
]


class PlanningStatus(StrEnum):
    """Planning-specific derived story status."""

    UNSTARTED = "UNSTARTED"
    READY = "READY"
    FLIGHT = "FLIGHT"
    DONE = "DONE"
    BLOCKED_EXTERNAL = "BLOCKED_EXTERNAL"
    BLOCKED_HUMAN = "BLOCKED_HUMAN"
    BLOCKED_CAPACITY = "BLOCKED_CAPACITY"
    BLOCKED_CONFLICT = "BLOCKED_CONFLICT"


class BlockingConditionKind(StrEnum):
    """Closed planning blocker vocabulary."""

    BLOCKED_INTERNAL_DEPENDENCY = "blocked_internal_dependency"
    BLOCKED_EXTERNAL = "blocked_external"
    BLOCKED_HUMAN = "blocked_human"
    BLOCKED_CAPACITY = "blocked_capacity"
    BLOCKED_CONFLICT = "blocked_conflict"
    BLOCKED_CONTRACT = "blocked_contract"


class BlockingConditionProvenance(StrEnum):
    """Where a blocker was derived from."""

    DEPENDENCY_GRAPH = "dependency_graph"
    HUMAN_GATE = "human_gate"
    EXTERNAL_GATE = "external_gate"
    SCHEDULING_POLICY = "scheduling_policy"
    CONFLICT_EVALUATION = "conflict_evaluation"
    CONTRACT_EVALUATION = "contract_evaluation"


class GateState(StrEnum):
    """Resolved state for planning gates."""

    OPEN = "open"
    RESOLVED = "resolved"


class HumanGateKind(StrEnum):
    """Human involvement categories relevant to readiness."""

    BLOCKING_GATE = "blocking_gate"
    OPTIONAL_REVIEW = "optional_review"


class ExecutionWaveLifecycle(StrEnum):
    """Lifecycle of one execution wave."""

    PLANNED = "planned"
    ACTIVE = "active"
    COMPLETED = "completed"
    COLLAPSED = "collapsed"


class RePlanTrigger(StrEnum):
    """Closed re-plan trigger classes."""

    STORY_DONE = "story_done"
    BLOCKER_OR_GATE_CHANGED = "blocker_or_gate_changed"
    CAPACITY_BUDGET_CHANGED = "capacity_budget_changed"
    RULEBOOK_OR_POLICY_CHANGED = "rulebook_or_policy_changed"
    CONFLICT_OR_CONTRACT_REEVALUATED = "conflict_or_contract_reevaluated"


class RePlanChangeKind(StrEnum):
    """Typed change descriptions consumed by re-plan classification."""

    STORY_DONE = "story_done"
    BLOCKER_CHANGED = "blocker_changed"
    GATE_CHANGED = "gate_changed"
    CAPACITY_BUDGET_CHANGED = "capacity_budget_changed"
    RULEBOOK_CHANGED = "rulebook_changed"
    SCHEDULING_POLICY_CHANGED = "scheduling_policy_changed"
    CONFLICT_REEVALUATED = "conflict_reevaluated"
    CONTRACT_REEVALUATED = "contract_reevaluated"


class StoryDependency(BaseModel):
    """Directed dependency edge between two stories in one project graph."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    story_id: str
    depends_on_story_id: str
    kind: StoryDependencyKind
    created_at: datetime

    @field_validator("depends_on_story_id")
    @classmethod
    def _validate_no_self_edge(cls, value: str, info: object) -> str:
        data = getattr(info, "data", {})
        if isinstance(data, dict) and data.get("story_id") == value:
            raise ValueError("story dependency must not point to itself")
        return value


class ParallelizationConfig(BaseModel):
    """Project-local practical parallelization limits."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str
    max_parallel_stories: int = Field(ge=1)
    max_parallel_stories_per_repo: int | None = Field(default=None, ge=1)


class BlockingCondition(BaseModel):
    """Typed blocker binding a reason to one story."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    story_id: str
    kind: BlockingConditionKind
    provenance: BlockingConditionProvenance
    reason_code: str
    source_story_id: str | None = None
    source_gate_id: str | None = None
    detail: str | None = None


class StoryRefForPlanning(BaseModel):
    """Minimal story read model consumed by planning calculations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str
    story_id: str
    story_number: int = Field(ge=1)
    title: str
    lifecycle_status: str
    repo: str | None = None
    story_type: str = "unknown"
    story_size: str = "unknown"
    participating_repos: tuple[str, ...] = Field(default_factory=tuple)
    human_touchpoints: tuple[str, ...] = Field(default_factory=tuple)
    external_prerequisites: tuple[str, ...] = Field(default_factory=tuple)
    planning_status: PlanningStatus = PlanningStatus.UNSTARTED


class PlannedStory(StoryRefForPlanning):
    """FK-70 planning read model for one story."""


class WaveStory(BaseModel):
    """Story projection inside a readiness wave."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    story_id: str
    story_number: int = Field(ge=1)
    title: str
    wave: int = Field(ge=0)
    is_ready: bool
    blocked_by: tuple[BlockingCondition, ...] = Field(default_factory=tuple)


class ExecutionCapacityBudgets(BaseModel):
    """Scheduling budget dimensions that cap ready work."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    repo_parallel_cap: int = Field(ge=0)
    merge_risk_cap: int = Field(ge=0)
    api_rate_limit_cap: int = Field(ge=0)
    llm_pool_cap: int = Field(ge=0)
    ci_capacity_cap: int = Field(ge=0)

    @property
    def max_allowed_batch(self) -> int:
        """Return the strictest central budget cap."""

        return min(
            self.repo_parallel_cap,
            self.merge_risk_cap,
            self.api_rate_limit_cap,
            self.llm_pool_cap,
            self.ci_capacity_cap,
        )


class SchedulingHint(BaseModel):
    """In-memory scheduling hint that may only narrow a batch."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    recommended_batch_limit: int | None = Field(default=None, ge=1)
    reason_code: str = "no_project_hint"


class ExecutionFeasibility(BaseModel):
    """Hard-rule execution feasibility result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str
    can_parallelize: bool
    feasible_story_ids: tuple[str, ...] = Field(default_factory=tuple)
    blocked_conditions: tuple[BlockingCondition, ...] = Field(default_factory=tuple)


class ExecutionSchedulingPolicy(BaseModel):
    """Budget-based scheduling result, separate from feasibility."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str
    may_parallelize_now: bool
    budgets: ExecutionCapacityBudgets
    hint: SchedulingHint | None = None


class HumanGate(BaseModel):
    """First-class human planning gate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str
    story_id: str
    gate_id: str
    kind: HumanGateKind
    state: GateState
    reason_code: str

    @property
    def is_blocking_open(self) -> bool:
        """Return whether this gate blocks readiness."""

        return self.kind is HumanGateKind.BLOCKING_GATE and self.state is GateState.OPEN


class ExternalGate(BaseModel):
    """First-class external planning gate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str
    story_id: str
    gate_id: str
    state: GateState
    reason_code: str

    @property
    def is_blocking_open(self) -> bool:
        """Return whether this gate blocks readiness."""

        return self.state is GateState.OPEN


class ExecutionWave(BaseModel):
    """Tenant-scoped wave of simultaneously released stories."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str
    wave_id: str
    lifecycle: ExecutionWaveLifecycle
    stories: tuple[WaveStory, ...] = Field(default_factory=tuple)


class PlanDerivation(BaseModel):
    """Pure planning derivation owned by execution planning."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str
    critical_path: tuple[str, ...] = Field(default_factory=tuple)
    ready_set: tuple[WaveStory, ...] = Field(default_factory=tuple)
    blocked_set: tuple[WaveStory, ...] = Field(default_factory=tuple)
    execution_wave: ExecutionWave
    recommended_batch: int = Field(ge=0)
    max_allowed_batch: int = Field(ge=0)
    feasibility: ExecutionFeasibility
    scheduling_policy: ExecutionSchedulingPolicy


class RePlanChange(BaseModel):
    """Typed input for pure re-plan trigger classification."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_key: str
    change_kind: RePlanChangeKind
    story_id: str | None = None
    reason_code: str


class ReadinessAssessment(BaseModel):
    """Deterministic answer for the next-ready planning question."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    next_ready: list[WaveStory]
    next_wave_after: list[WaveStory]
    theoretical_parallelism: int = Field(ge=0)
    practical_parallelism: int = Field(ge=0)
    reason: str
    feasibility: ExecutionFeasibility | None = None
    scheduling_policy: ExecutionSchedulingPolicy | None = None
    plan_derivation: PlanDerivation | None = None


def blocking_condition_status(kind: BlockingConditionKind) -> PlanningStatus:
    """Map one blocker class to its derived planning status."""

    if kind is BlockingConditionKind.BLOCKED_INTERNAL_DEPENDENCY:
        return PlanningStatus.UNSTARTED
    if kind is BlockingConditionKind.BLOCKED_EXTERNAL:
        return PlanningStatus.BLOCKED_EXTERNAL
    if kind is BlockingConditionKind.BLOCKED_HUMAN:
        return PlanningStatus.BLOCKED_HUMAN
    if kind is BlockingConditionKind.BLOCKED_CAPACITY:
        return PlanningStatus.BLOCKED_CAPACITY
    if kind in {
        BlockingConditionKind.BLOCKED_CONFLICT,
        BlockingConditionKind.BLOCKED_CONTRACT,
    }:
        return PlanningStatus.BLOCKED_CONFLICT
    raise ValueError(f"Unsupported blocking condition kind: {kind!r}")


def planning_status_from_blockers(
    blockers: tuple[BlockingCondition, ...] | list[BlockingCondition],
) -> PlanningStatus:
    """Derive a deterministic planning status from blocker priority."""

    blocker_kinds = {blocker.kind for blocker in blockers}
    if BlockingConditionKind.BLOCKED_HUMAN in blocker_kinds:
        return PlanningStatus.BLOCKED_HUMAN
    if BlockingConditionKind.BLOCKED_EXTERNAL in blocker_kinds:
        return PlanningStatus.BLOCKED_EXTERNAL
    if (
        BlockingConditionKind.BLOCKED_CONFLICT in blocker_kinds
        or BlockingConditionKind.BLOCKED_CONTRACT in blocker_kinds
    ):
        return PlanningStatus.BLOCKED_CONFLICT
    if BlockingConditionKind.BLOCKED_CAPACITY in blocker_kinds:
        return PlanningStatus.BLOCKED_CAPACITY
    if BlockingConditionKind.BLOCKED_INTERNAL_DEPENDENCY in blocker_kinds:
        return PlanningStatus.UNSTARTED
    return PlanningStatus.READY


def classify_replan_trigger(change: RePlanChange) -> RePlanTrigger:
    """Classify one typed change description into a re-plan trigger."""

    if change.change_kind is RePlanChangeKind.STORY_DONE:
        return RePlanTrigger.STORY_DONE
    if change.change_kind in {
        RePlanChangeKind.BLOCKER_CHANGED,
        RePlanChangeKind.GATE_CHANGED,
    }:
        return RePlanTrigger.BLOCKER_OR_GATE_CHANGED
    if change.change_kind is RePlanChangeKind.CAPACITY_BUDGET_CHANGED:
        return RePlanTrigger.CAPACITY_BUDGET_CHANGED
    if change.change_kind in {
        RePlanChangeKind.RULEBOOK_CHANGED,
        RePlanChangeKind.SCHEDULING_POLICY_CHANGED,
    }:
        return RePlanTrigger.RULEBOOK_OR_POLICY_CHANGED
    if change.change_kind in {
        RePlanChangeKind.CONFLICT_REEVALUATED,
        RePlanChangeKind.CONTRACT_REEVALUATED,
    }:
        return RePlanTrigger.CONFLICT_OR_CONTRACT_REEVALUATED
    raise ValueError(f"Unsupported re-plan change kind: {change.change_kind!r}")
