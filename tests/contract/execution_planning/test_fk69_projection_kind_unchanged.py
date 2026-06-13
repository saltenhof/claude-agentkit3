"""Contract test: AG3-099 does NOT widen the FK-69 ProjectionKind contract.

FK-70 §70.10.2 architecture precision: the ten BC14 planning families are NOT
FK-69 read-models. AG3-099 builds a separate, owner-distinct planning write path
and must leave the FK-69 ``ProjectionKind`` distinct from planning kinds.

Note: AG3-108 (FK-69 §69.15 Codex-approved) added ``qa_check_outcomes`` as the
eighth FK-69 table; the count is now 8. This test guards against planning families
leaking into FK-69, not against legitimate FK-69 extensions.
"""

from __future__ import annotations

from agentkit.execution_planning.persistence.schema_kind import PlanningSchemaKind
from agentkit.telemetry.projection_accessor import ProjectionKind


def test_fk69_projection_kind_still_has_seven_values() -> None:
    """The FK-69 ProjectionKind contract is distinct from planning kinds.

    AG3-099 must not leak BC14 planning families into FK-69.
    AG3-108 (FK-69 §69.15 Codex-approved): qa_check_outcomes is the 8th
    FK-69 table (eight values total).
    """
    assert len({kind.value for kind in ProjectionKind}) == 8


def test_planning_families_are_not_fk69_projection_kinds() -> None:
    """No BC14 planning family leaked into the FK-69 ProjectionKind enum."""
    fk69_values = {kind.value for kind in ProjectionKind}
    planning_values = {kind.value for kind in PlanningSchemaKind}
    assert fk69_values.isdisjoint(planning_values), (
        "BC14 planning families must NOT appear in FK-69 ProjectionKind "
        f"(overlap: {sorted(fk69_values & planning_values)})"
    )
