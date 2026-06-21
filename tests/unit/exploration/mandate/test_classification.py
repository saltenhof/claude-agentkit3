"""Unit tests for MandateClassification (FK-25 §25.4.1, AG3-047 AC1).

Covers all four class paths plus the FK-25 §25.4.1 check ORDER (3 -> 4 -> 2,
first hit wins). Real detector + checker (pure logic, no mocks).
"""

from __future__ import annotations

from tests.exploration_change_frame_fixture import example_change_frame

from agentkit.backend.exploration.change_frame import (
    AffectedBuildingBlocks,
    ContractChanges,
    OpenPoints,
)
from agentkit.backend.exploration.mandate.classification import (
    MandateClass,
    MandateClassification,
)
from agentkit.backend.exploration.mandate.impact_checker import ImpactExceedanceChecker
from agentkit.backend.exploration.mandate.scope_detector import ScopeExplosionDetector
from agentkit.backend.story_context_manager.story_model import ChangeImpact


def _classifier() -> MandateClassification:
    return MandateClassification(
        scope_detector=ScopeExplosionDetector(),
        impact_checker=ImpactExceedanceChecker(),
    )


def _exploding_frame() -> object:
    """A frame that fires >= 2 HIGH scope indicators (and large impact)."""
    return example_change_frame().model_copy(
        update={
            "affected_building_blocks": AffectedBuildingBlocks(
                affected=[f"m{i}" for i in range(8)],
            ),
            "contract_changes": ContractChanges(
                interfaces=["a", "b"],
                data_model=["c", "d"],
                events=["e"],
                external_integrations=["f"],
            ),
        }
    )


def test_trivial_path_no_signal() -> None:
    """No scope/impact/fine-design signal -> TRIVIAL (straight to review)."""
    frame = example_change_frame().model_copy(
        update={
            "affected_building_blocks": AffectedBuildingBlocks(affected=["one"]),
            "open_points": OpenPoints(
                decided=["x"], assumptions=["y"], approval_needed=[]
            ),
        }
    )

    result = _classifier().classify(frame, ChangeImpact.ARCHITECTURE_IMPACT)

    assert result.mandate_class is MandateClass.TRIVIAL
    assert result.run_design_challenge is False


def test_scope_explosion_path() -> None:
    """>= 2 HIGH indicators -> SCOPE_EXPLOSION (Klasse 3)."""
    result = _classifier().classify(
        _exploding_frame(), ChangeImpact.ARCHITECTURE_IMPACT
    )

    assert result.mandate_class is MandateClass.SCOPE_EXPLOSION
    assert result.scope_explosion.triggered is True
    assert result.run_design_challenge is True


def test_impact_escalation_path() -> None:
    """Impact exceeds declared (no scope explosion) -> IMPACT_ESCALATION."""
    frame = example_change_frame().model_copy(
        update={
            "affected_building_blocks": AffectedBuildingBlocks(
                affected=["m1", "m2", "m3", "m4"],
            ),
            "contract_changes": ContractChanges(
                interfaces=["a", "b"], data_model=["c"], events=["d"]
            ),
        }
    )

    result = _classifier().classify(frame, ChangeImpact.LOCAL)

    assert result.scope_explosion.triggered is False
    assert result.impact_exceedance.exceeded is True
    assert result.mandate_class is MandateClass.IMPACT_ESCALATION


def test_fine_design_path() -> None:
    """No scope/impact signal but an approval_needed open point -> FINE_DESIGN."""
    frame = example_change_frame().model_copy(
        update={
            "affected_building_blocks": AffectedBuildingBlocks(affected=["one"]),
            "open_points": OpenPoints(
                decided=[],
                assumptions=[],
                approval_needed=["broker API streaming semantics unresolved"],
            ),
        }
    )

    result = _classifier().classify(frame, ChangeImpact.ARCHITECTURE_IMPACT)

    assert result.mandate_class is MandateClass.FINE_DESIGN
    assert result.run_design_challenge is True


def test_check_order_scope_wins_over_impact() -> None:
    """A frame that triggers BOTH scope (3) and impact (4) -> SCOPE_EXPLOSION.

    FK-25 §25.4.1 order is 3 before 4: the more restrictive scope-explosion
    class must win even though the impact check ALSO fires (both sub-results are
    carried for telemetry).
    """
    # The exploding frame derives ARCHITECTURE_IMPACT; declare LOCAL so impact
    # ALSO exceeds. Scope (3) must still win.
    result = _classifier().classify(_exploding_frame(), ChangeImpact.LOCAL)

    assert result.scope_explosion.triggered is True
    assert result.impact_exceedance.exceeded is True
    assert result.mandate_class is MandateClass.SCOPE_EXPLOSION


def test_check_order_impact_wins_over_fine_design() -> None:
    """Impact (4) wins over fine-design (2) when both signals are present.

    A frame with an approval_needed open point (fine-design signal) AND an
    impact exceedance must classify as IMPACT_ESCALATION (4 before 2).
    """
    frame = example_change_frame().model_copy(
        update={
            "affected_building_blocks": AffectedBuildingBlocks(
                affected=["m1", "m2", "m3", "m4"],
            ),
            "contract_changes": ContractChanges(
                interfaces=["a", "b"], data_model=["c"], events=["d"]
            ),
            "open_points": OpenPoints(
                decided=[], assumptions=[], approval_needed=["unresolved detail"]
            ),
        }
    )

    result = _classifier().classify(frame, ChangeImpact.LOCAL)

    assert result.impact_exceedance.exceeded is True
    assert result.mandate_class is MandateClass.IMPACT_ESCALATION
