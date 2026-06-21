"""Contract test: the three typed exploration gate stages (AC6; FK-23 §23.5).

Pins the ``ExplorationGateStage`` StrEnum (exactly three members + wire values)
and the typed ``ExplorationGateStageSpec`` contract, plus the binding of the two
workflow-DSL yield-points to their typed stages (exploration-and-design.B3).
"""

from __future__ import annotations

from agentkit.backend.process.language.definitions import IMPLEMENTATION_WORKFLOW
from agentkit.backend.process.language.gates import (
    ExplorationGateStage,
    ExplorationGateStageSpec,
)


def test_three_gate_stages_pinned() -> None:
    """AC6: exactly three typed stages with the canonical wire values."""
    assert [s.value for s in ExplorationGateStage] == [
        "doc_fidelity",
        "design_review",
        "design_challenge",
    ]


def test_stage_spec_is_frozen_and_strict() -> None:
    spec = ExplorationGateStageSpec(
        stage_id=ExplorationGateStage.DESIGN_REVIEW,
        yield_point="design_review",
        required=True,
        rollback_on_fail=True,
    )
    assert spec.model_config["frozen"] is True
    assert spec.model_config["extra"] == "forbid"


def test_implementation_workflow_yield_points_are_typed() -> None:
    """The exploration yield-points carry their typed gate stages."""
    exploration = next(
        node
        for node in IMPLEMENTATION_WORKFLOW.nodes
        if node.name == "exploration"
    )
    stages = {
        yp.gate_stage.stage_id: yp.gate_stage
        for yp in exploration.yield_points
        if yp.gate_stage is not None
    }
    assert ExplorationGateStage.DESIGN_REVIEW in stages
    assert ExplorationGateStage.DESIGN_CHALLENGE in stages
    # Stage 2a is required + rolls back; Stage 2b is optional.
    assert stages[ExplorationGateStage.DESIGN_REVIEW].required is True
    assert stages[ExplorationGateStage.DESIGN_REVIEW].rollback_on_fail is True
    assert stages[ExplorationGateStage.DESIGN_CHALLENGE].required is False


def test_design_challenge_stage_value_matches_persistence() -> None:
    """The persistence stage wire-id matches the typed DESIGN_CHALLENGE value."""
    from agentkit.backend.exploration.review import design_challenge

    persistence_stage = design_challenge._DESIGN_CHALLENGE_STAGE  # noqa: SLF001
    assert persistence_stage == ExplorationGateStage.DESIGN_CHALLENGE.value
