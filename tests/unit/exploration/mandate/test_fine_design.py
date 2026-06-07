"""Unit tests for FineDesignSubprocess (FK-25 §25.5 skeleton, AG3-047 AC5).

Exercises both terminating paths (converged + max_rounds_exceeded) and the
fail-closed evaluator-unavailable propagation, against real in-test
:class:`FineDesignEvaluator` implementations (first-class implementations of the
injected port, NOT mocks).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
from tests.exploration_change_frame_fixture import example_change_frame

from agentkit.exploration.mandate.fine_design import (
    FineDesignDecision,
    FineDesignEvaluatorUnavailableError,
    FineDesignRoundOutcome,
    FineDesignSubprocess,
)

if TYPE_CHECKING:
    from agentkit.exploration.change_frame import ChangeFrame


@dataclass
class _ConvergeAfter:
    """Evaluator that converges on round ``converge_on`` (records calls)."""

    converge_on: int
    calls: list[int] = field(default_factory=list)

    def run_round(
        self, change_frame: ChangeFrame, *, round_number: int
    ) -> FineDesignRoundOutcome:
        del change_frame
        self.calls.append(round_number)
        decision = FineDesignDecision(
            decision_id=f"FD-{round_number:03d}",
            question="how to resolve the broker streaming contract?",
            decision="single run_status key on terminal_fail",
            rationale="consistent with existing state-management pattern",
            normative_basis=("FK-39", "FK-26 §26.2"),
            llm_responses=(f"round {round_number} position",),
        )
        return FineDesignRoundOutcome(
            converged=round_number >= self.converge_on,
            decisions=(decision,),
        )


def test_converges_within_limit() -> None:
    """An evaluator converging on round 2 -> status=converged, rounds=2."""
    evaluator = _ConvergeAfter(converge_on=2)
    subprocess = FineDesignSubprocess(evaluator)

    result = subprocess.run(example_change_frame(), max_rounds=10)

    assert result.status == "converged"
    assert result.rounds == 2
    assert evaluator.calls == [1, 2]
    assert len(result.final_design_decisions) == 1


def test_max_rounds_exceeded() -> None:
    """An evaluator that never converges -> status=max_rounds_exceeded."""
    evaluator = _ConvergeAfter(converge_on=999)
    subprocess = FineDesignSubprocess(evaluator)

    result = subprocess.run(example_change_frame(), max_rounds=3)

    assert result.status == "max_rounds_exceeded"
    assert result.rounds == 3
    assert evaluator.calls == [1, 2, 3]
    # The last round's decisions are carried (FK-25 §25.5.1).
    assert result.final_design_decisions[0].decision_id == "FD-003"


def test_default_max_rounds_is_ten() -> None:
    """The default ceiling is 10 rounds (FK-25 §25.5.1)."""
    evaluator = _ConvergeAfter(converge_on=999)

    result = FineDesignSubprocess(evaluator).run(example_change_frame())

    assert result.rounds == 10
    assert len(evaluator.calls) == 10


def test_invalid_max_rounds_fails_closed() -> None:
    """A non-positive round ceiling is a fail-closed programming error."""
    with pytest.raises(ValueError, match="max_rounds must be >= 1"):
        FineDesignSubprocess(_ConvergeAfter(converge_on=1)).run(
            example_change_frame(), max_rounds=0
        )


@dataclass
class _Unavailable:
    """Evaluator whose backend is not reachable (FK-25 §25.5.4)."""

    def run_round(
        self, change_frame: ChangeFrame, *, round_number: int
    ) -> FineDesignRoundOutcome:
        del change_frame, round_number
        msg = "no advising LLM reachable"
        raise FineDesignEvaluatorUnavailableError(msg)


def test_evaluator_unavailable_propagates_not_swallowed() -> None:
    """An unavailable evaluator propagates -- the shell never fakes an outcome.

    FK-25 §25.5.4 / ERROR-1 fix: the bounded subprocess must NOT swallow the
    non-reachability signal into a converged or max_rounds_exceeded result; it
    propagates so the phase handler escalates fail-closed.
    """
    with pytest.raises(FineDesignEvaluatorUnavailableError):
        FineDesignSubprocess(_Unavailable()).run(example_change_frame())
