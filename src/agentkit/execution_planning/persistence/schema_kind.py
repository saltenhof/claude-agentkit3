"""Planning projection schema-kind enum (BC14, FK-70 §70.10.2).

This is the BC14 pendant to the FK-69 ``telemetry.ProjectionKind``. It is a
SEPARATE, owner-distinct enum: the FK-69 ``ProjectionKind`` is pinned by
contract test to exactly seven FK-69 read-models and MUST NOT be widened with
planning tables. The ten BC14 planning schema families are NOT FK-69
read-models; they live here under the execution-planning (BC14) schema owner and
are persisted through the dedicated BC-9-hosted planning projection write path
(``PlanningProjectionAccessor``), not the FK-69 ``ProjectionAccessor``.

Sources:
- FK-70 §70.10.2 -- ten planning schema families, schema owner BC14, DB owner BC9
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["PlanningSchemaKind"]


class PlanningSchemaKind(StrEnum):
    """Canonical enum of the ten BC14 planning schema families (FK-70 §70.10.2).

    Each value is the wire/table name (ARCH-55, English-only) of one planning
    projection family owned by execution-planning (BC14). The planning write
    path is pinned to exactly these ten families by a dedicated contract test
    (the pendant to ``test_projection_kind_has_exactly_seven_values``).
    """

    PLANNED_STORY = "planned_story"
    DEPENDENCY_EDGE = "dependency_edge"
    BLOCKING_CONDITION = "blocking_condition"
    GATE = "gate"
    SCHEDULING_BUDGET = "scheduling_budget"
    SCHEDULING_POLICY = "scheduling_policy"
    RULEBOOK_REVISION = "rulebook_revision"
    RULEBOOK_COMPILE_RESULT = "rulebook_compile_result"
    EXECUTION_PLAN = "execution_plan"
    EXECUTION_WAVE = "execution_wave"
