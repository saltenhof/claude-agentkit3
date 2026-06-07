"""Contract test: the four mandate classes + the FK-25 §25.4.1 check order.

Pins the stable English class catalogue (ARCH-55) and the check-order contract
(3 -> 4 -> 2, first hit wins) so a drift in either is caught.
"""

from __future__ import annotations

from tests.exploration_change_frame_fixture import example_change_frame

from agentkit.exploration.change_frame import (
    AffectedBuildingBlocks,
    ContractChanges,
    OpenPoints,
)
from agentkit.exploration.mandate.classification import (
    MandateClass,
    MandateClassification,
)
from agentkit.exploration.mandate.impact_checker import ImpactExceedanceChecker
from agentkit.exploration.mandate.scope_detector import ScopeExplosionDetector
from agentkit.story_context_manager.story_model import ChangeImpact


def test_mandate_class_catalogue_is_english() -> None:
    """The four classes carry English names AND values (ARCH-55)."""
    assert {c.value for c in MandateClass} == {
        "trivial",
        "fine_design",
        "scope_explosion",
        "impact_escalation",
    }
    # English member names (no German klasse_1..4).
    assert {c.name for c in MandateClass} == {
        "TRIVIAL",
        "FINE_DESIGN",
        "SCOPE_EXPLOSION",
        "IMPACT_ESCALATION",
    }


def _classifier() -> MandateClassification:
    return MandateClassification(
        scope_detector=ScopeExplosionDetector(),
        impact_checker=ImpactExceedanceChecker(),
    )


def _exploding_frame() -> object:
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


def test_all_four_class_paths() -> None:
    """Each of the four classes is reachable by a distinct frame/declared pair."""
    clf = _classifier()

    trivial = example_change_frame().model_copy(
        update={
            "affected_building_blocks": AffectedBuildingBlocks(affected=["one"]),
            "open_points": OpenPoints(
                decided=["x"], assumptions=[], approval_needed=[]
            ),
        }
    )
    fine_design = example_change_frame().model_copy(
        update={
            "affected_building_blocks": AffectedBuildingBlocks(affected=["one"]),
            "open_points": OpenPoints(
                decided=[], assumptions=[], approval_needed=["open detail"]
            ),
        }
    )
    impact = example_change_frame().model_copy(
        update={
            "affected_building_blocks": AffectedBuildingBlocks(
                affected=["m1", "m2", "m3", "m4"],
            ),
            "contract_changes": ContractChanges(
                interfaces=["a", "b"], data_model=["c"], events=["d"]
            ),
        }
    )

    assert (
        clf.classify(trivial, ChangeImpact.ARCHITECTURE_IMPACT).mandate_class
        is MandateClass.TRIVIAL
    )
    assert (
        clf.classify(fine_design, ChangeImpact.ARCHITECTURE_IMPACT).mandate_class
        is MandateClass.FINE_DESIGN
    )
    assert (
        clf.classify(impact, ChangeImpact.LOCAL).mandate_class
        is MandateClass.IMPACT_ESCALATION
    )
    assert (
        clf.classify(_exploding_frame(), ChangeImpact.LOCAL).mandate_class
        is MandateClass.SCOPE_EXPLOSION
    )


def test_check_order_3_before_4_before_2() -> None:
    """First-hit-wins in FK-25 order: scope (3) > impact (4) > fine-design (2)."""
    clf = _classifier()

    # scope + impact + fine-design all fire -> scope (3) wins.
    all_signals = _exploding_frame().model_copy(
        update={
            "open_points": OpenPoints(
                decided=[], assumptions=[], approval_needed=["open"]
            ),
        }
    )
    res_all = clf.classify(all_signals, ChangeImpact.LOCAL)
    assert res_all.scope_explosion.triggered is True
    assert res_all.impact_exceedance.exceeded is True
    assert res_all.mandate_class is MandateClass.SCOPE_EXPLOSION

    # impact + fine-design fire (no scope) -> impact (4) wins over fine-design.
    impact_and_fine = example_change_frame().model_copy(
        update={
            "affected_building_blocks": AffectedBuildingBlocks(
                affected=["m1", "m2", "m3", "m4"],
            ),
            "contract_changes": ContractChanges(
                interfaces=["a", "b"], data_model=["c"], events=["d"]
            ),
            "open_points": OpenPoints(
                decided=[], assumptions=[], approval_needed=["open"]
            ),
        }
    )
    res_impact = clf.classify(impact_and_fine, ChangeImpact.LOCAL)
    assert res_impact.impact_exceedance.exceeded is True
    assert res_impact.mandate_class is MandateClass.IMPACT_ESCALATION
