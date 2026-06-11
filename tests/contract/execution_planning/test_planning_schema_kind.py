"""Contract test: the planning write path pins exactly the ten BC14 families.

Pendant to ``tests/contract/telemetry/test_projection_accessor.py``
(``test_projection_kind_has_exactly_seven_values``). This is the fachliche
contract between the BC-9-hosted planning projection write path and FK-70
§70.10.2. Changes to ``PlanningSchemaKind`` MUST be cross-checked against FK-70
§70.10.2.

The owner-distinct FK-69 ``ProjectionKind`` (seven values) stays untouched; that
contract test must remain green independently (see
``tests/contract/execution_planning/test_fk69_projection_kind_unchanged.py``).
"""

from __future__ import annotations

from agentkit.execution_planning.persistence.records import (
    planning_kind_to_record_type,
)
from agentkit.execution_planning.persistence.schema_kind import PlanningSchemaKind

_BC14_EXPECTED_FAMILIES = {
    "planned_story",
    "dependency_edge",
    "blocking_condition",
    "gate",
    "scheduling_budget",
    "scheduling_policy",
    "rulebook_revision",
    "rulebook_compile_result",
    "execution_plan",
    "execution_wave",
}


def test_planning_schema_kind_has_exactly_ten_values() -> None:
    """FK-70 §70.10.2 normalizes exactly ten planning schema families."""
    actual = {kind.value for kind in PlanningSchemaKind}
    assert len(actual) == 10, (
        f"PlanningSchemaKind should have exactly 10 values (FK-70 §70.10.2). "
        f"Found: {sorted(actual)}"
    )


def test_planning_schema_kind_values_match_fk70() -> None:
    """PlanningSchemaKind values match exactly the FK-70 §70.10.2 family names."""
    actual = {kind.value for kind in PlanningSchemaKind}
    assert actual == _BC14_EXPECTED_FAMILIES, (
        f"PlanningSchemaKind diverges from FK-70 §70.10.2.\n"
        f"Expected: {sorted(_BC14_EXPECTED_FAMILIES)}\n"
        f"Found: {sorted(actual)}"
    )


def test_planning_record_mapping_covers_all_ten_families() -> None:
    """Every planning schema kind has a registered record type (fail-closed map)."""
    mapping = planning_kind_to_record_type()
    assert set(mapping.keys()) == set(PlanningSchemaKind)
    assert len(mapping) == 10
