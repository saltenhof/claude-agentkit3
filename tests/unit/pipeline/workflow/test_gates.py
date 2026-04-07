"""Unit tests for gate contracts."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

import pytest

from agentkit.pipeline.workflow.gates import Gate, GateStage
from agentkit.pipeline.workflow.guards import GuardResult

if TYPE_CHECKING:
    from agentkit.story.models import PhaseState, StoryContext


class TestGateStage:
    """Tests for GateStage frozen dataclass."""

    def test_minimal_construction(self) -> None:
        gs = GateStage(name="structural", actor="system")
        assert gs.name == "structural"
        assert gs.actor == "system"
        assert gs.evidence == ()
        assert gs.outcomes == ("PASS", "FAIL")
        assert gs.condition is None
        assert gs.risk_triggers == ()

    def test_full_construction(self) -> None:
        def cond(ctx: StoryContext, state: PhaseState) -> GuardResult:
            return GuardResult.PASS()

        gs = GateStage(
            name="semantic",
            actor="qa_agent",
            evidence=("semantic-review.json",),
            outcomes=("PASS", "FAIL", "WARN"),
            condition=cond,
            risk_triggers=("coverage_below_threshold",),
        )
        assert gs.name == "semantic"
        assert gs.actor == "qa_agent"
        assert gs.evidence == ("semantic-review.json",)
        assert gs.outcomes == ("PASS", "FAIL", "WARN")
        assert gs.condition is cond
        assert gs.risk_triggers == ("coverage_below_threshold",)

    def test_frozen(self) -> None:
        gs = GateStage(name="test", actor="system")
        with pytest.raises(dataclasses.FrozenInstanceError):
            gs.name = "modified"  # type: ignore[misc]

    def test_default_outcomes(self) -> None:
        gs = GateStage(name="x", actor="y")
        assert "PASS" in gs.outcomes
        assert "FAIL" in gs.outcomes


class TestGate:
    """Tests for Gate frozen dataclass."""

    def test_minimal_construction(self) -> None:
        gate = Gate(id="verify_gate")
        assert gate.id == "verify_gate"
        assert gate.stages == ()
        assert gate.max_remediation_rounds == 2
        assert gate.on_max_exceeded == "escalate"
        assert gate.final_aggregation == "deterministic"

    def test_full_construction(self) -> None:
        stage1 = GateStage(name="structural", actor="system")
        stage2 = GateStage(name="semantic", actor="qa_agent")

        gate = Gate(
            id="full_gate",
            stages=(stage1, stage2),
            max_remediation_rounds=3,
            on_max_exceeded="fail_hard",
            final_aggregation="majority",
        )
        assert gate.id == "full_gate"
        assert len(gate.stages) == 2
        assert gate.stages[0].name == "structural"
        assert gate.stages[1].name == "semantic"
        assert gate.max_remediation_rounds == 3
        assert gate.on_max_exceeded == "fail_hard"
        assert gate.final_aggregation == "majority"

    def test_frozen(self) -> None:
        gate = Gate(id="test")
        with pytest.raises(dataclasses.FrozenInstanceError):
            gate.id = "modified"  # type: ignore[misc]

    def test_default_values(self) -> None:
        gate = Gate(id="defaults")
        assert gate.max_remediation_rounds == 2
        assert gate.on_max_exceeded == "escalate"
        assert gate.final_aggregation == "deterministic"

    def test_multi_stage_gate(self) -> None:
        stages = tuple(
            GateStage(name=f"stage_{i}", actor=f"actor_{i}") for i in range(4)
        )
        gate = Gate(id="multi", stages=stages)
        assert len(gate.stages) == 4
        for i, stage in enumerate(gate.stages):
            assert stage.name == f"stage_{i}"
            assert stage.actor == f"actor_{i}"
