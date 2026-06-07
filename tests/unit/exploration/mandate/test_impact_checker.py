"""Unit tests for ImpactExceedanceChecker (FK-25 §25.7, AG3-047 AC4).

``exceeded`` is ``rank(actual) > rank(declared)`` over the total order
LOCAL < COMPONENT < CROSS_COMPONENT < ARCHITECTURE_IMPACT. Real change-frames
(no mocks; pure logic).
"""

from __future__ import annotations

from tests.exploration_change_frame_fixture import example_change_frame

from agentkit.exploration.change_frame import (
    AffectedBuildingBlocks,
    ContractChanges,
)
from agentkit.exploration.mandate.impact_checker import (
    IMPACT_ORDER,
    ImpactExceedanceChecker,
    impact_rank,
)
from agentkit.story_context_manager.story_model import ChangeImpact


def _architecture_frame() -> object:
    """Build a frame whose derived impact is ARCHITECTURE_IMPACT."""
    return example_change_frame().model_copy(
        update={
            "affected_building_blocks": AffectedBuildingBlocks(
                affected=["m1", "m2", "m3", "m4"],
            ),
            "contract_changes": ContractChanges(
                interfaces=["a", "b"],
                data_model=["c"],
                events=["d"],
            ),
        }
    )


def test_local_declared_vs_architecture_actual_exceeds() -> None:
    """LOCAL declared but ARCHITECTURE_IMPACT derived -> exceeded=True (Klasse 4)."""
    checker = ImpactExceedanceChecker()

    result = checker.check(_architecture_frame(), ChangeImpact.LOCAL)

    assert result.declared is ChangeImpact.LOCAL
    assert result.actual is ChangeImpact.ARCHITECTURE_IMPACT
    assert result.exceeded is True


def test_architecture_declared_covers_any_actual() -> None:
    """ARCHITECTURE_IMPACT declared covers any derived impact -> not exceeded."""
    checker = ImpactExceedanceChecker()

    result = checker.check(
        _architecture_frame(), ChangeImpact.ARCHITECTURE_IMPACT
    )

    assert result.exceeded is False


def test_local_frame_local_declared_not_exceeded() -> None:
    """A single-block frame derives LOCAL; LOCAL declared -> not exceeded."""
    frame = example_change_frame().model_copy(
        update={
            "affected_building_blocks": AffectedBuildingBlocks(affected=["only"]),
        }
    )
    checker = ImpactExceedanceChecker()

    result = checker.check(frame, ChangeImpact.LOCAL)

    assert result.actual is ChangeImpact.LOCAL
    assert result.exceeded is False


def test_impact_order_is_total_and_ascending() -> None:
    """The ChangeImpact ordering is LOCAL < COMPONENT < CROSS < ARCHITECTURE."""
    assert IMPACT_ORDER == (
        ChangeImpact.LOCAL,
        ChangeImpact.COMPONENT,
        ChangeImpact.CROSS_COMPONENT,
        ChangeImpact.ARCHITECTURE_IMPACT,
    )
    ranks = [impact_rank(i) for i in IMPACT_ORDER]
    assert ranks == sorted(ranks)
    assert ranks == [0, 1, 2, 3]
