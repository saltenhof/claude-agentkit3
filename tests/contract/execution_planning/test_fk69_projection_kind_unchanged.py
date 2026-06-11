"""Contract test: AG3-099 does NOT widen the FK-69 ProjectionKind contract.

FK-70 §70.10.2 architecture precision: the ten BC14 planning families are NOT
FK-69 read-models. AG3-099 builds a separate, owner-distinct planning write path
and must leave the FK-69 ``ProjectionKind`` pinned at exactly seven values
(FK-69 §69.3). This test guards against an accidental cross-contract leak.
"""

from __future__ import annotations

from agentkit.execution_planning.persistence.schema_kind import PlanningSchemaKind
from agentkit.telemetry.projection_accessor import ProjectionKind


def test_fk69_projection_kind_still_has_seven_values() -> None:
    """The FK-69 ProjectionKind contract is untouched by AG3-099 (seven values)."""
    assert len({kind.value for kind in ProjectionKind}) == 7


def test_planning_families_are_not_fk69_projection_kinds() -> None:
    """No BC14 planning family leaked into the FK-69 ProjectionKind enum."""
    fk69_values = {kind.value for kind in ProjectionKind}
    planning_values = {kind.value for kind in PlanningSchemaKind}
    assert fk69_values.isdisjoint(planning_values), (
        "BC14 planning families must NOT appear in FK-69 ProjectionKind "
        f"(overlap: {sorted(fk69_values & planning_values)})"
    )
