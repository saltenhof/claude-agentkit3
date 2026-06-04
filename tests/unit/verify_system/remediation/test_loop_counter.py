"""Unit tests for RemediationLoopController (FK-38, AG3-041 AC4)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agentkit.core_types import PolicyVerdict
from agentkit.verify_system.qa_cycle.lifecycle import QaCycleState
from agentkit.verify_system.remediation.loop_counter import (
    DEFAULT_MAX_FEEDBACK_ROUNDS,
    RemediationDecision,
    RemediationLoopController,
)


def _state(round_nr: int) -> QaCycleState:
    return QaCycleState(
        qa_cycle_id="a" * 12,
        round=round_nr,
        epoch=round_nr,
        evidence_epoch=datetime(2026, 5, 19, tzinfo=UTC),
        evidence_fingerprint="f" * 64,
    )


class TestCheckAndAdvance:
    def test_pass_continues_to_closure(self) -> None:
        controller = RemediationLoopController()
        decision = controller.check_and_advance(_state(1), PolicyVerdict.PASS)
        assert decision is RemediationDecision.CONTINUE_TO_CLOSURE

    def test_pass_continues_even_at_max_round(self) -> None:
        controller = RemediationLoopController(max_feedback_rounds=3)
        decision = controller.check_and_advance(_state(3), PolicyVerdict.PASS)
        assert decision is RemediationDecision.CONTINUE_TO_CLOSURE

    def test_fail_below_max_continues_remediation(self) -> None:
        controller = RemediationLoopController(max_feedback_rounds=3)
        decision = controller.check_and_advance(_state(1), PolicyVerdict.FAIL)
        assert decision is RemediationDecision.CONTINUE_REMEDIATION

    def test_fail_at_max_escalates(self) -> None:
        controller = RemediationLoopController(max_feedback_rounds=3)
        decision = controller.check_and_advance(_state(3), PolicyVerdict.FAIL)
        assert decision is RemediationDecision.ESCALATE

    def test_fail_above_max_escalates(self) -> None:
        controller = RemediationLoopController(max_feedback_rounds=3)
        decision = controller.check_and_advance(_state(5), PolicyVerdict.FAIL)
        assert decision is RemediationDecision.ESCALATE


class TestConfig:
    def test_default_ceiling_is_three(self) -> None:
        assert DEFAULT_MAX_FEEDBACK_ROUNDS == 3  # noqa: PLR2004
        assert RemediationLoopController().max_feedback_rounds == 3  # noqa: PLR2004

    def test_zero_ceiling_rejected(self) -> None:
        with pytest.raises(ValueError, match="max_feedback_rounds"):
            RemediationLoopController(max_feedback_rounds=0)

    def test_custom_ceiling_respected(self) -> None:
        controller = RemediationLoopController(max_feedback_rounds=1)
        assert (
            controller.check_and_advance(_state(1), PolicyVerdict.FAIL)
            is RemediationDecision.ESCALATE
        )
