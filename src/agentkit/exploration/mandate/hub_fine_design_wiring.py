"""Productive collaborators for the hub fine-design evaluator (AG3-097).

:class:`~agentkit.exploration.mandate.hub_fine_design.HubFineDesignEvaluator` is
the concrete multi-LLM-hub :class:`FineDesignEvaluator`, but it deliberately keeps
the LLM-SEMANTIC verdict (did the discussion converge? which decisions?) and the
per-round prompt OUT of the deterministic transport adapter -- they are injected
ports (``RoundConvergenceJudge`` / ``FineDesignPromptBuilder``). This module
supplies the PRODUCTIVE implementations of those two ports so the canonical
composition root (``build_exploration_phase_handler``) can wire the REAL
hub-backed evaluator instead of the fail-closed
``_UnavailableFineDesignEvaluator`` stand-in:

* :class:`ChangeFrameFineDesignPromptBuilder` -- a deterministic A-core that
  renders the change-frame's open points + prior round responses into the round
  prompt sent to every advisor. No LLM call, no I/O.
* :class:`LlmConvergenceJudge` -- delegates the convergence verdict to an injected
  :class:`~agentkit.verify_system.llm_evaluator.llm_client.LlmClient` (the SAME
  fail-closed default the rest of the pipeline uses until the FK-11 LLM-pool
  selection is wired). It NEVER fabricates a convergence verdict: a transport
  failure / unparseable verdict surfaces as
  :class:`~agentkit.exploration.mandate.fine_design.FineDesignEvaluatorUnavailableError`,
  so the hub path is REALLY driven (advisors acquired + sent over the hub) and the
  only fail-closed point is the verdict itself -> D4 bounded-retry-then-FAILED, NOT
  a fabricated APPROVED/freeze (ZERO DEBT / FAIL-CLOSED). This mirrors the Layer-2
  ``FailClosedLlmClient`` wiring (AG3-043 E6 / AG3-065): the evaluation REALLY runs
  and fails closed at the LLM boundary rather than silently passing.

Once the productive LLM-judge backend exists (FK-11 follow-up) the caller injects
a real ``LlmClient`` here and the convergence verdict becomes live WITHOUT any
change to the transport adapter or this builder.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, ValidationError

from agentkit.exploration.mandate.fine_design import (
    FineDesignDecision,
    FineDesignEvaluatorUnavailableError,
    FineDesignRoundOutcome,
)
from agentkit.verify_system.llm_evaluator.llm_client import LlmClientError

if TYPE_CHECKING:
    from agentkit.exploration.change_frame import ChangeFrame
    from agentkit.multi_llm_hub.entities import HubBackendName
    from agentkit.verify_system.llm_evaluator.llm_client import LlmClient

#: The reviewer-role wire-string the convergence judge routes through the
#: ``LlmClient`` (FK-11 §11.5.1 ``llm_roles``); a distinct role keeps the
#: fine-design verdict separable from the verify-system reviewer roles.
_CONVERGENCE_ROLE = "fine_design_convergence"


class ChangeFrameFineDesignPromptBuilder:
    """Deterministic per-round prompt builder for the hub advisors (FK-25 §25.5).

    Renders the change-frame's still-open fine-design questions (the
    ``open_points`` that need approval / are mere assumptions, plus any prior
    round responses) into the prompt broadcast to every advisor. Pure A-core: no
    LLM call, no I/O, no hidden state.
    """

    def build(
        self,
        change_frame: ChangeFrame,
        *,
        round_number: int,
        previous_responses: dict[HubBackendName, str],
    ) -> str:
        """Build the round prompt sent to every advising LLM.

        Args:
            change_frame: The change-frame being refined.
            round_number: The 1-based round number.
            previous_responses: The previous round's per-backend responses (empty
                on round 1).

        Returns:
            The deterministic prompt text.
        """
        open_points = change_frame.open_points
        lines = [
            "You are advising a class-2 fine-design discussion (FK-25 §25.5).",
            f"Story: {change_frame.story_id}. Round: {round_number}.",
            "",
            "Goal/scope (what changes):",
            f"  {change_frame.goal_and_scope.changes}",
            "",
            "Solution direction:",
            f"  pattern: {change_frame.solution_direction.pattern}",
            f"  anchoring: {change_frame.solution_direction.anchoring}",
            "",
            "Open points still needing a fine-design decision:",
        ]
        lines.extend(f"  - assumption: {point}" for point in open_points.assumptions)
        lines.extend(
            f"  - approval-needed: {point}" for point in open_points.approval_needed
        )
        if previous_responses:
            lines.append("")
            lines.append("Previous round positions:")
            lines.extend(
                f"  - {backend}: {text}"
                for backend, text in sorted(previous_responses.items())
            )
        lines.append("")
        lines.append(
            "Give your position on the open fine-design questions and state "
            "whether the discussion has converged on a single best decision."
        )
        return "\n".join(lines)


class _DecisionVerdict(BaseModel):
    """One decision entry of the strict convergence-verdict JSON contract."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: str
    question: str
    decision: str
    rationale: str
    normative_basis: tuple[str, ...]


class _ConvergenceVerdict(BaseModel):
    """The strict JSON shape the convergence judge expects from the LLM.

    A strict, ``extra="forbid"`` contract so an unparseable / wrong-shaped verdict
    is a hard fail-closed signal (FK-34 §34.5.1 semantics applied to fine-design),
    never a silently-accepted fabricated convergence.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    converged: bool
    decisions: tuple[_DecisionVerdict, ...]


class LlmConvergenceJudge:
    """Convergence judge delegating the verdict to an injected ``LlmClient``.

    The deterministic transport adapter sends + records the per-advisor exchange;
    this judge asks the LLM for the convergence verdict over those responses and
    parses it against the strict :class:`_ConvergenceVerdict` contract. It NEVER
    fabricates a verdict: a transport failure (pool unreachable, e.g. the
    fail-closed default until FK-11 wires a pool) OR an unparseable response
    raises :class:`FineDesignEvaluatorUnavailableError`, which the caller edge maps
    to the D4 bounded-retry-then-FAILED outcome (no fabricated APPROVED/freeze).
    """

    def __init__(self, llm_client: LlmClient) -> None:
        """Initialise the judge.

        Args:
            llm_client: The LLM transport for the convergence verdict (the
                fail-closed default until the FK-11 pool selection is wired).
        """
        self._llm_client = llm_client

    def judge(
        self,
        change_frame: ChangeFrame,
        *,
        round_number: int,
        responses: dict[HubBackendName, str],
    ) -> FineDesignRoundOutcome:
        """Decide the round outcome from the recorded per-advisor responses.

        Args:
            change_frame: The change-frame being refined.
            round_number: The 1-based round number.
            responses: The per-backend response text exchanged this round.

        Returns:
            The :class:`FineDesignRoundOutcome` (converged + decisions).

        Raises:
            FineDesignEvaluatorUnavailableError: If the verdict LLM transport
                fails (pool unreachable -- the fail-closed default) or the verdict
                is unparseable. Never a fabricated convergence (D4 -> FAILED).
        """
        prompt = self._verdict_prompt(
            change_frame, round_number=round_number, responses=responses
        )
        try:
            raw = self._llm_client.complete(role=_CONVERGENCE_ROLE, prompt=prompt)
        except LlmClientError as exc:
            msg = (
                "fine-design convergence verdict unavailable: the LLM judge "
                "transport failed (FK-25 §25.5.4 non-reachability / FK-11 pool "
                f"selection is a follow-up): {exc}"
            )
            raise FineDesignEvaluatorUnavailableError(msg) from exc
        verdict = self._parse_verdict(raw)
        decisions = tuple(
            FineDesignDecision(
                decision_id=entry.decision_id,
                question=entry.question,
                decision=entry.decision,
                rationale=entry.rationale,
                normative_basis=entry.normative_basis,
                llm_responses=tuple(
                    f"{backend}: {text}" for backend, text in sorted(responses.items())
                ),
            )
            for entry in verdict.decisions
        )
        return FineDesignRoundOutcome(
            converged=verdict.converged, decisions=decisions
        )

    def _parse_verdict(self, raw: str) -> _ConvergenceVerdict:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            msg = (
                "fine-design convergence verdict is not valid JSON (FK-25 "
                f"§25.5.4 fail-closed, no fabricated convergence): {exc}"
            )
            raise FineDesignEvaluatorUnavailableError(msg) from exc
        try:
            return _ConvergenceVerdict.model_validate(payload)
        except ValidationError as exc:
            msg = (
                "fine-design convergence verdict has an invalid shape (FK-25 "
                f"§25.5.4 fail-closed, no fabricated convergence): {exc}"
            )
            raise FineDesignEvaluatorUnavailableError(msg) from exc

    @staticmethod
    def _verdict_prompt(
        change_frame: ChangeFrame,
        *,
        round_number: int,
        responses: dict[HubBackendName, str],
    ) -> str:
        positions = "\n".join(
            f"  - {backend}: {text}" for backend, text in sorted(responses.items())
        )
        return (
            "You are the deterministic convergence judge for a class-2 "
            "fine-design discussion (FK-25 §25.5). Given the per-advisor "
            f"positions of round {round_number} for story "
            f"{change_frame.story_id}, decide whether the discussion has "
            "converged on a single best decision.\n\n"
            f"Advisor positions:\n{positions}\n\n"
            "Respond with ONLY a JSON object of the exact shape "
            '{"converged": bool, "decisions": [{"decision_id": str, '
            '"question": str, "decision": str, "rationale": str, '
            '"normative_basis": [str]}]}.'
        )


__all__ = [
    "ChangeFrameFineDesignPromptBuilder",
    "LlmConvergenceJudge",
]
