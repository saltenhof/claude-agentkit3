"""Unit tests for ScopeExplosionDetector (FK-25 §25.6, AG3-047 AC3).

The detector triggers Klasse 3 iff >= 2 HIGH indicators fire. These tests build
real :class:`ChangeFrame` instances (via the static FK-23 fixture + immutable
``model_copy``) -- no mocks (the detector is pure logic).
"""

from __future__ import annotations

from tests.exploration_change_frame_fixture import example_change_frame

from agentkit.exploration.change_frame import (
    AffectedBuildingBlocks,
    ContractChanges,
)
from agentkit.exploration.mandate.scope_detector import (
    ScopeExplosionDetector,
    ScopeIndicatorWeight,
)


def test_no_explosion_for_small_frame() -> None:
    """A small change-frame fires < 2 HIGH indicators -> not triggered."""
    detector = ScopeExplosionDetector()

    result = detector.detect(example_change_frame())

    assert result.triggered is False
    assert result.high_indicators_count < 2


def test_explosion_triggers_on_two_high_indicators() -> None:
    """Many affected blocks + broad contracts fire >= 2 HIGH -> triggered."""
    frame = example_change_frame().model_copy(
        update={
            "affected_building_blocks": AffectedBuildingBlocks(
                affected=[f"module-{i}" for i in range(8)],
            ),
            "contract_changes": ContractChanges(
                interfaces=["a", "b"],
                data_model=["c", "d"],
                events=["e"],
                external_integrations=["f"],
            ),
        }
    )
    detector = ScopeExplosionDetector()

    result = detector.detect(frame)

    assert result.triggered is True
    assert result.high_indicators_count >= 2
    high = {
        ind.name
        for ind in result.indicators
        if ind.weight is ScopeIndicatorWeight.HIGH
    }
    # affected_building_blocks (8 > 5), unplanned_contracts (6 > 4) and
    # cross_module_contract (4 dims, 8 blocks) all fire HIGH here.
    assert "affected_building_blocks" in high
    assert "unplanned_contracts" in high


def test_single_high_indicator_does_not_trigger() -> None:
    """A single HIGH indicator (one dimension only) does NOT trigger Klasse 3."""
    frame = example_change_frame().model_copy(
        update={
            "affected_building_blocks": AffectedBuildingBlocks(
                affected=[f"module-{i}" for i in range(8)],
            ),
            # A single contract dimension, below the unplanned threshold -> only
            # the affected-blocks HIGH indicator fires (1 < 2).
            "contract_changes": ContractChanges(interfaces=["only-one"]),
        }
    )
    detector = ScopeExplosionDetector()

    result = detector.detect(frame)

    assert result.high_indicators_count == 1
    assert result.triggered is False
