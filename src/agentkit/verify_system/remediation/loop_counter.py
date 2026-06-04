"""Remediation-loop counter and escalation decision (FK-38 / FK-27 §27.6a.2).

The subflow-internal remediation loop is bounded: after at most
``max_feedback_rounds`` failed QA-subflow rounds the story escalates instead of
looping forever (FK-27 §27.2.2 ``max_rounds_exceeded`` -> ``escalated``;
FK-38 remediation-loop; FK-03 §3.4.2 default 3). The loop never spins inline
(``while True``): :class:`RemediationLoopController` is a pure decision function
the orchestrating phase consumes once per round.

State-machine mapping (FK-27 §27.2.2):

* verdict PASS                         -> ``CONTINUE_TO_CLOSURE`` (``pass``)
* verdict FAIL, round <  max           -> ``CONTINUE_REMEDIATION``
  (``awaiting_remediation``)
* verdict FAIL, round >= max           -> ``ESCALATE`` (``escalated`` via
  ``max_rounds_exceeded``)

``max_feedback_rounds`` is configurable but NEVER bypassable: a FAIL at the
ceiling always escalates (NO ERROR BYPASSING).

Quelle:
  - FK-38 -- Remediation-Loop
  - FK-27 §27.2.2 / §27.6a.2 -- max_rounds_exceeded -> escalated
  - FK-03 §3.4.2 -- max_feedback_rounds Default 3
  - AG3-041 §2.1.4 -- RemediationLoopController, RemediationDecision
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from agentkit.core_types import PolicyVerdict

if TYPE_CHECKING:
    from agentkit.verify_system.qa_cycle.lifecycle import QaCycleState

#: FK-03 §3.4.2 default ceiling for subflow-internal remediation rounds.
DEFAULT_MAX_FEEDBACK_ROUNDS = 3


class RemediationDecision(StrEnum):
    """Outcome of one remediation-loop evaluation (FK-27 §27.2.2).

    Attributes:
        CONTINUE_TO_CLOSURE: QA passed; the story may proceed to closure.
        CONTINUE_REMEDIATION: QA failed but the round budget is not exhausted;
            run another remediation round (``advance_qa_cycle``).
        ESCALATE: QA failed and the round budget is exhausted; escalate
            (``max_rounds_exceeded`` -> ``escalated``). Hard, no retry.
    """

    CONTINUE_TO_CLOSURE = "continue_to_closure"
    CONTINUE_REMEDIATION = "continue_remediation"
    ESCALATE = "escalate"


@dataclass(frozen=True)
class RemediationLoopController:
    """Bounded remediation-loop decision function (FK-38).

    Attributes:
        max_feedback_rounds: Ceiling on remediation rounds before escalation
            (FK-03 §3.4.2 default 3). Must be >= 1.
    """

    max_feedback_rounds: int = DEFAULT_MAX_FEEDBACK_ROUNDS

    def __post_init__(self) -> None:
        """Validate the round ceiling (fail-closed).

        Raises:
            ValueError: If ``max_feedback_rounds`` is below 1 (a zero/negative
                ceiling would make every FAIL escalate immediately, which is a
                misconfiguration, not a valid loop).
        """
        if self.max_feedback_rounds < 1:
            msg = (
                "max_feedback_rounds must be >= 1 (FK-03 §3.4.2); "
                f"got {self.max_feedback_rounds!r}"
            )
            raise ValueError(msg)

    def check_and_advance(
        self,
        qa_cycle_state: QaCycleState,
        verdict: PolicyVerdict,
    ) -> RemediationDecision:
        """Decide the loop outcome from the verdict and the current round.

        Args:
            qa_cycle_state: The just-completed cycle's identity snapshot;
                ``round`` is the 1-based round counter.
            verdict: The policy-engine verdict of the just-completed round.

        Returns:
            ``CONTINUE_TO_CLOSURE`` on PASS; ``CONTINUE_REMEDIATION`` on FAIL
            while ``round < max_feedback_rounds``; ``ESCALATE`` on FAIL once
            ``round >= max_feedback_rounds`` (hard, never bypassable).
        """
        if verdict is PolicyVerdict.PASS:
            return RemediationDecision.CONTINUE_TO_CLOSURE
        if qa_cycle_state.round < self.max_feedback_rounds:
            return RemediationDecision.CONTINUE_REMEDIATION
        return RemediationDecision.ESCALATE


__all__ = [
    "DEFAULT_MAX_FEEDBACK_ROUNDS",
    "RemediationDecision",
    "RemediationLoopController",
]
