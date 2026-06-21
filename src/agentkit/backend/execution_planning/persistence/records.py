"""Typed planning projection records, one per BC14 schema family (FK-70 §70.10.2).

These are the persisted row shapes for the ten planning schema families. They are
the BC14 pendant to the FK-69 ``ProjectionRecord`` union -- owner-distinct and
NOT part of the FK-69 union (which stays pinned to its seven read-models). Each
record is keyed by ``project_key`` (mandant isolation) plus a per-family
identity, carries a ``revision`` for revision-binding/idempotency (FK-70 §70.11
#8) and serializes deterministically.

The ``PlanningProjectionRecord`` union and ``planning_kind_to_record_type``
mapping drive the fail-closed type check in the planning write path (the pendant
to ``ProjectionRecordTypeMismatchError``).

Sources:
- FK-70 §70.10.2 -- ten schema families, schema owner BC14
- FK-70 §70.11 #8 -- idempotency / revision binding (no competing truths)
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from agentkit.backend.execution_planning.persistence.schema_kind import PlanningSchemaKind

__all__ = [
    "BlockingConditionRecord",
    "DependencyEdgeRecord",
    "ExecutionPlanRecord",
    "ExecutionWaveRecord",
    "GateRecord",
    "PlannedStoryRecord",
    "PlanningProjectionRecord",
    "RulebookCompileResultRecord",
    "RulebookRevisionRecord",
    "SchedulingBudgetRecord",
    "SchedulingPolicyRecord",
    "planning_kind_to_record_type",
]


class _PlanningRecordBase(BaseModel):
    """Common base for planning projection records (frozen, extra-forbid)."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class PlannedStoryRecord(_PlanningRecordBase):
    """``planned_story`` family: a planned story and its planning metadata."""

    project_key: str
    story_id: str
    story_type: str = "unknown"
    story_size: str = "unknown"
    participating_repos: tuple[str, ...] = Field(default_factory=tuple)
    planning_status: str
    is_hard_truth: bool = False
    revision: int = Field(ge=1, default=1)


class DependencyEdgeRecord(_PlanningRecordBase):
    """``dependency_edge`` family: one directed dependency edge."""

    project_key: str
    story_id: str
    depends_on_story_id: str
    kind: str
    rationale: str | None = None
    is_hard_truth: bool = False
    created_at: str
    revision: int = Field(ge=1, default=1)


class BlockingConditionRecord(_PlanningRecordBase):
    """``blocking_condition`` family: one typed blocker."""

    project_key: str
    story_id: str
    blocker_id: str
    kind: str
    provenance: str
    reason_code: str
    source_story_id: str | None = None
    source_gate_id: str | None = None
    detail: str | None = None
    is_hard_truth: bool = False
    revision: int = Field(ge=1, default=1)


class GateRecord(_PlanningRecordBase):
    """``gate`` family: one human/external gate."""

    project_key: str
    story_id: str
    gate_id: str
    gate_kind: str
    state: str
    reason_code: str
    is_blocking: bool = True
    revision: int = Field(ge=1, default=1)


class SchedulingBudgetRecord(_PlanningRecordBase):
    """``scheduling_budget`` family: capacity/risk budget dimensions."""

    project_key: str
    budget_id: str
    repo_parallel_cap: int = Field(ge=0)
    merge_risk_cap: int = Field(ge=0)
    api_rate_limit_cap: int = Field(ge=0)
    llm_pool_cap: int = Field(ge=0)
    ci_capacity_cap: int = Field(ge=0)
    revision: int = Field(ge=1, default=1)


class SchedulingPolicyRecord(_PlanningRecordBase):
    """``scheduling_policy`` family: a scheduling-policy decision snapshot."""

    project_key: str
    policy_id: str
    may_parallelize_now: bool
    budget_id: str
    recommended_batch_limit: int | None = None
    reason_code: str = "no_project_hint"
    revision: int = Field(ge=1, default=1)


class RulebookRevisionRecord(_PlanningRecordBase):
    """``rulebook_revision`` family: one versioned rulebook revision."""

    project_key: str
    rulebook_id: str
    revision: int = Field(ge=1)
    raw_syntax: str
    updated_by_principal: str
    created_at: str


class RulebookCompileResultRecord(_PlanningRecordBase):
    """``rulebook_compile_result`` family: outcome of a rulebook compile step."""

    project_key: str
    rulebook_id: str
    revision: int = Field(ge=1)
    status: str
    compiled_rules_json: str
    errors_json: str
    triggers_replan: bool = False
    compiled_at: str


class ExecutionPlanRecord(_PlanningRecordBase):
    """``execution_plan`` family: a computed plan snapshot (AK3 derivation)."""

    project_key: str
    plan_id: str
    graph_revision: int = Field(ge=0)
    readiness_revision: int = Field(ge=0)
    scheduling_revision: int = Field(ge=0)
    rulebook_revision: int = Field(ge=0)
    critical_path_story_ids: tuple[str, ...] = Field(default_factory=tuple)
    recommended_batch_story_ids: tuple[str, ...] = Field(default_factory=tuple)
    max_allowed_batch_story_ids: tuple[str, ...] = Field(default_factory=tuple)
    revision: int = Field(ge=1, default=1)


class ExecutionWaveRecord(_PlanningRecordBase):
    """``execution_wave`` family: one computed execution wave."""

    project_key: str
    plan_id: str
    wave_id: str
    wave_order: int = Field(ge=0)
    wave_state: str
    candidate_story_ids: tuple[str, ...] = Field(default_factory=tuple)
    revision: int = Field(ge=1, default=1)


# Discriminated union over all ten BC14 planning projection records. Used for
# type annotation AND runtime ``isinstance`` in the planning write path.
PlanningProjectionRecord = (
    PlannedStoryRecord
    | DependencyEdgeRecord
    | BlockingConditionRecord
    | GateRecord
    | SchedulingBudgetRecord
    | SchedulingPolicyRecord
    | RulebookRevisionRecord
    | RulebookCompileResultRecord
    | ExecutionPlanRecord
    | ExecutionWaveRecord
)


def planning_kind_to_record_type() -> dict[PlanningSchemaKind, type[_PlanningRecordBase]]:
    """Return the canonical ``PlanningSchemaKind`` -> record-type mapping.

    Drives the fail-closed type check at the planning write boundary (the
    pendant to FK-69 ``_KIND_TO_RECORD_TYPE``). Covers all ten families
    exhaustively.

    Returns:
        Mapping from each planning schema kind to its allowed record type.
    """

    return {
        PlanningSchemaKind.PLANNED_STORY: PlannedStoryRecord,
        PlanningSchemaKind.DEPENDENCY_EDGE: DependencyEdgeRecord,
        PlanningSchemaKind.BLOCKING_CONDITION: BlockingConditionRecord,
        PlanningSchemaKind.GATE: GateRecord,
        PlanningSchemaKind.SCHEDULING_BUDGET: SchedulingBudgetRecord,
        PlanningSchemaKind.SCHEDULING_POLICY: SchedulingPolicyRecord,
        PlanningSchemaKind.RULEBOOK_REVISION: RulebookRevisionRecord,
        PlanningSchemaKind.RULEBOOK_COMPILE_RESULT: RulebookCompileResultRecord,
        PlanningSchemaKind.EXECUTION_PLAN: ExecutionPlanRecord,
        PlanningSchemaKind.EXECUTION_WAVE: ExecutionWaveRecord,
    }
