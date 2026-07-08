"""Persistence round-trip tests for all ten BC14 planning schema families.

AC6: each of the ten planning schema families has a write->read->same-data
round-trip test over the BC-9 planning projection write path -- the nine new
families plus the ``dependency_edge`` family migrated onto the planning write
path. Exactly ten round-trip tests, one of which (``dependency_edge``) proves the
migration. Idempotency / revision binding is proven (FK-70 §70.11 #8).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentkit.backend.bootstrap.composition_root import build_planning_projection_accessor
from agentkit.backend.execution_planning.persistence.errors import (
    PlanningProjectionRecordTypeMismatchError,
)
from agentkit.backend.execution_planning.persistence.filter import PlanningProjectionFilter
from agentkit.backend.execution_planning.persistence.records import (
    BlockingConditionRecord,
    DependencyEdgeRecord,
    ExecutionPlanRecord,
    ExecutionWaveRecord,
    GateRecord,
    PlannedStoryRecord,
    RulebookCompileResultRecord,
    RulebookRevisionRecord,
    SchedulingBudgetRecord,
    SchedulingPolicyRecord,
)
from agentkit.backend.execution_planning.persistence.schema_kind import PlanningSchemaKind
from agentkit.backend.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.backend.state_backend.persistence_test_support import reset_backend_cache_for_tests

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from agentkit.backend.execution_planning.persistence.accessor import (
        PlanningProjectionAccessor,
    )

_PROJECT = "PROJ-TEST"


@pytest.fixture(autouse=True)
def sqlite_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


@pytest.fixture()
def accessor(tmp_path: Path) -> PlanningProjectionAccessor:
    story_dir = tmp_path / "stories" / "AG3-099"
    story_dir.mkdir(parents=True, exist_ok=True)
    return build_planning_projection_accessor(story_dir)


def _filter(**kwargs: object) -> PlanningProjectionFilter:
    return PlanningProjectionFilter(project_key=_PROJECT, **kwargs)  # type: ignore[arg-type]


def test_roundtrip_planned_story(accessor: PlanningProjectionAccessor) -> None:
    record = PlannedStoryRecord(
        project_key=_PROJECT,
        story_id="S1",
        story_type="implementation",
        story_size="M",
        participating_repos=("repo-a", "repo-b"),
        planning_status="READY",
        is_hard_truth=True,
        revision=1,
    )
    accessor.write_projection(PlanningSchemaKind.PLANNED_STORY, record)
    result = accessor.read_projection(
        PlanningSchemaKind.PLANNED_STORY, _filter(story_id="S1")
    )
    assert result == [record]


def test_roundtrip_dependency_edge_migrated(
    accessor: PlanningProjectionAccessor,
) -> None:
    """``dependency_edge`` round-trip over the MIGRATED planning write path."""
    record = DependencyEdgeRecord(
        project_key=_PROJECT,
        story_id="S2",
        depends_on_story_id="S1",
        kind="hard_story_dependency",
        rationale="S2 builds on S1",
        is_hard_truth=True,
        created_at="2026-06-11T00:00:00+00:00",
        revision=1,
    )
    accessor.write_projection(PlanningSchemaKind.DEPENDENCY_EDGE, record)
    result = accessor.read_projection(
        PlanningSchemaKind.DEPENDENCY_EDGE, _filter(story_id="S2")
    )
    assert result == [record]


def test_roundtrip_blocking_condition(accessor: PlanningProjectionAccessor) -> None:
    record = BlockingConditionRecord(
        project_key=_PROJECT,
        blocker_id="BLK-1",
        story_id="S1",
        kind="blocked_external",
        provenance="external_gate",
        reason_code="api_unavailable",
        detail="waiting for partner API",
        is_hard_truth=False,
        revision=1,
    )
    accessor.write_projection(PlanningSchemaKind.BLOCKING_CONDITION, record)
    result = accessor.read_projection(
        PlanningSchemaKind.BLOCKING_CONDITION, _filter(story_id="S1")
    )
    assert result == [record]


def test_roundtrip_gate(accessor: PlanningProjectionAccessor) -> None:
    record = GateRecord(
        project_key=_PROJECT,
        gate_id="GATE-1",
        story_id="S1",
        gate_kind="human",
        state="open",
        reason_code="uat_pending",
        is_blocking=True,
        revision=1,
    )
    accessor.write_projection(PlanningSchemaKind.GATE, record)
    result = accessor.read_projection(PlanningSchemaKind.GATE, _filter(story_id="S1"))
    assert result == [record]


def test_roundtrip_scheduling_budget(accessor: PlanningProjectionAccessor) -> None:
    record = SchedulingBudgetRecord(
        project_key=_PROJECT,
        budget_id="BUD-1",
        repo_parallel_cap=3,
        merge_risk_cap=2,
        api_rate_limit_cap=5,
        llm_pool_cap=4,
        ci_capacity_cap=6,
        revision=1,
    )
    accessor.write_projection(PlanningSchemaKind.SCHEDULING_BUDGET, record)
    result = accessor.read_projection(
        PlanningSchemaKind.SCHEDULING_BUDGET, _filter()
    )
    assert result == [record]


def test_roundtrip_scheduling_policy(accessor: PlanningProjectionAccessor) -> None:
    record = SchedulingPolicyRecord(
        project_key=_PROJECT,
        policy_id="POL-1",
        may_parallelize_now=True,
        budget_id="BUD-1",
        recommended_batch_limit=2,
        reason_code="project_hint",
        revision=1,
    )
    accessor.write_projection(PlanningSchemaKind.SCHEDULING_POLICY, record)
    result = accessor.read_projection(
        PlanningSchemaKind.SCHEDULING_POLICY, _filter()
    )
    assert result == [record]


def test_scheduling_budget_revision_filtered_read(
    accessor: PlanningProjectionAccessor,
) -> None:
    """A ``revision``-scoped read of ``scheduling_budget`` honours the filter column.

    The ``scheduling_budget`` adapter only exposes ``revision`` as a filterable
    column; a read filtered by ``revision`` must return the matching revision and
    exclude a different one (proves the adapter's ``_has_column`` revision branch).
    """
    rev1 = SchedulingBudgetRecord(
        project_key=_PROJECT, budget_id="BUD-1", repo_parallel_cap=3,
        merge_risk_cap=2, api_rate_limit_cap=5, llm_pool_cap=4, ci_capacity_cap=6,
        revision=1,
    )
    rev2 = SchedulingBudgetRecord(
        project_key=_PROJECT, budget_id="BUD-2", repo_parallel_cap=7,
        merge_risk_cap=2, api_rate_limit_cap=5, llm_pool_cap=4, ci_capacity_cap=6,
        revision=2,
    )
    accessor.write_projection(PlanningSchemaKind.SCHEDULING_BUDGET, rev1)
    accessor.write_projection(PlanningSchemaKind.SCHEDULING_BUDGET, rev2)
    result = accessor.read_projection(
        PlanningSchemaKind.SCHEDULING_BUDGET, _filter(revision=2)
    )
    assert result == [rev2]


def test_scheduling_policy_revision_filtered_read(
    accessor: PlanningProjectionAccessor,
) -> None:
    """A ``revision``-scoped read of ``scheduling_policy`` honours the filter column."""
    rev1 = SchedulingPolicyRecord(
        project_key=_PROJECT, policy_id="POL-1", may_parallelize_now=True,
        budget_id="BUD-1", revision=1,
    )
    rev2 = SchedulingPolicyRecord(
        project_key=_PROJECT, policy_id="POL-2", may_parallelize_now=False,
        budget_id="BUD-1", revision=2,
    )
    accessor.write_projection(PlanningSchemaKind.SCHEDULING_POLICY, rev1)
    accessor.write_projection(PlanningSchemaKind.SCHEDULING_POLICY, rev2)
    result = accessor.read_projection(
        PlanningSchemaKind.SCHEDULING_POLICY, _filter(revision=1)
    )
    assert result == [rev1]


def test_roundtrip_rulebook_revision(accessor: PlanningProjectionAccessor) -> None:
    record = RulebookRevisionRecord(
        project_key=_PROJECT,
        rulebook_id="RB-1",
        revision=1,
        raw_syntax="parallelize S1 S2",
        updated_by_principal="admin:alice",
        created_at="2026-06-11T00:00:00+00:00",
    )
    accessor.write_projection(PlanningSchemaKind.RULEBOOK_REVISION, record)
    result = accessor.read_projection(
        PlanningSchemaKind.RULEBOOK_REVISION, _filter(rulebook_id="RB-1")
    )
    assert result == [record]


def test_roundtrip_rulebook_compile_result(
    accessor: PlanningProjectionAccessor,
) -> None:
    record = RulebookCompileResultRecord(
        project_key=_PROJECT,
        rulebook_id="RB-1",
        revision=1,
        status="compiled",
        compiled_rules_json='[{"rule_kind": "parallelize"}]',
        errors_json="[]",
        triggers_replan=True,
        compiled_at="2026-06-11T00:00:00+00:00",
    )
    accessor.write_projection(PlanningSchemaKind.RULEBOOK_COMPILE_RESULT, record)
    result = accessor.read_projection(
        PlanningSchemaKind.RULEBOOK_COMPILE_RESULT, _filter(rulebook_id="RB-1")
    )
    assert result == [record]


def test_roundtrip_execution_plan(accessor: PlanningProjectionAccessor) -> None:
    record = ExecutionPlanRecord(
        project_key=_PROJECT,
        plan_id="PLAN-1",
        graph_revision=2,
        readiness_revision=3,
        scheduling_revision=1,
        rulebook_revision=1,
        critical_path_story_ids=("S1", "S2"),
        recommended_batch_story_ids=("S1",),
        max_allowed_batch_story_ids=("S1", "S2"),
        revision=1,
    )
    accessor.write_projection(PlanningSchemaKind.EXECUTION_PLAN, record)
    result = accessor.read_projection(
        PlanningSchemaKind.EXECUTION_PLAN, _filter(plan_id="PLAN-1")
    )
    assert result == [record]


def test_roundtrip_execution_wave(accessor: PlanningProjectionAccessor) -> None:
    record = ExecutionWaveRecord(
        project_key=_PROJECT,
        plan_id="PLAN-1",
        wave_id="WAVE-1",
        wave_order=0,
        wave_state="planned",
        candidate_story_ids=("S1", "S2"),
        revision=1,
    )
    accessor.write_projection(PlanningSchemaKind.EXECUTION_WAVE, record)
    result = accessor.read_projection(
        PlanningSchemaKind.EXECUTION_WAVE, _filter(plan_id="PLAN-1")
    )
    assert result == [record]


def test_idempotency_and_revision_binding(
    accessor: PlanningProjectionAccessor,
) -> None:
    """FK-70 §70.11 #8: same identity -> one row; a new revision replaces it."""
    base = PlannedStoryRecord(
        project_key=_PROJECT, story_id="S1", planning_status="UNSTARTED", revision=1
    )
    accessor.write_projection(PlanningSchemaKind.PLANNED_STORY, base)
    accessor.write_projection(PlanningSchemaKind.PLANNED_STORY, base)
    rows = accessor.read_projection(
        PlanningSchemaKind.PLANNED_STORY, _filter(story_id="S1")
    )
    assert len(rows) == 1, "duplicate write of same identity must not duplicate rows"

    revised = base.model_copy(update={"planning_status": "READY", "revision": 2})
    accessor.write_projection(PlanningSchemaKind.PLANNED_STORY, revised)
    rows = accessor.read_projection(
        PlanningSchemaKind.PLANNED_STORY, _filter(story_id="S1")
    )
    assert rows == [revised], "a new revision binds and replaces the prior truth"


def test_write_type_mismatch_fails_closed(
    accessor: PlanningProjectionAccessor,
) -> None:
    """A record type that does not match the schema kind is rejected (FAIL-CLOSED)."""
    wrong = GateRecord(
        project_key=_PROJECT,
        gate_id="G",
        story_id="S1",
        gate_kind="human",
        state="open",
        reason_code="x",
    )
    with pytest.raises(PlanningProjectionRecordTypeMismatchError):
        accessor.write_projection(PlanningSchemaKind.PLANNED_STORY, wrong)
