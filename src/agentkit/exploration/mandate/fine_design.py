"""FineDesignSubprocess -- the Klasse-2 fine-design skeleton (FK-25 §25.5).

FK-25 §25.5 (Schritt J) resolves a Klasse-2 finding (a technical fine-design
decision within the normative frame) through an ITERATIVE multi-LLM discussion
led by the harness agent (ChatGPT mandatory, Qwen preferred), bounded at 10
rounds, converging to a documented decision.

SKELETON ONLY (story AG3-047 §2.1.4 / FK-25 §25.5):
-----------------------------------------------------
The FULL multi-LLM discussion (ChatGPT-mandatory acquire/send/release over the
LLM hub, ``llm_session_stats`` post-hoc verification, hook-based round
enforcement, the non-reachability escalation ``infra_unavailable``) is a
deliberate FOLLOW-UP story (AG3-047 §2.2 out-of-scope). This class provides the
deterministic GERUEST:

* a bounded loop of at most ``max_rounds`` rounds (default 10, FK-25 §25.5.1);
* ONE injected :class:`FineDesignEvaluator` call per round (the single-LLM
  stand-in for the future multi-LLM exchange -- NO secret multi-LLM invention);
* termination as ``converged`` (an evaluator round reports convergence) or
  ``max_rounds_exceeded`` (the round ceiling was hit without convergence,
  FK-25 §25.5.1 "Nach Runde 10 terminiert der Agent").

The evaluator is an injected boundary port so the bloodgroup-A core performs no
LLM transport itself; the productive multi-LLM adapter replaces the single-call
stand-in in the follow-up story without changing this orchestration shell.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from agentkit.exploration.change_frame import ChangeFrame

#: Default round ceiling (FK-25 §25.5.1: "Maximal 10 Runden").
DEFAULT_MAX_ROUNDS: Final[int] = 10


class FineDesignEvaluatorUnavailableError(RuntimeError):
    """The fine-design evaluator cannot run a round at all (FK-25 §25.5.4).

    Raised by a :class:`FineDesignEvaluator` whose advising-LLM backend is not
    reachable / not yet wired, i.e. the FK-25 §25.5.4 non-reachability case
    ("steht kein zweites LLM zur Verfuegung ... Abbruch, Eskalation an den
    Menschen"). This is NOT a failure to converge (that is a real, completed
    discussion that hit the round limit); it is the honest signal that no real
    fine-design discussion could be held at all. The bounded subprocess shell
    deliberately does NOT swallow this error -- it propagates so the caller
    (the exploration phase handler) escalates fail-closed instead of fabricating
    a converged or max-rounds-exceeded outcome (ZERO DEBT / FAIL-CLOSED).
    """


class FineDesignDecision(BaseModel):
    """One documented fine-design decision (FK-25 §25.5.5 schema, English keys).

    Mirrors the FK-25 §25.5.5 ``feindesign_entscheidungen`` entry (the German
    concept keys ``frage``/``entscheidung``/``begruendung`` are rendered in
    English per ARCH-55). Carries the fields the ``fine_design_decision``
    telemetry event pins (FK-25 §25.8 / ``MANDATORY_PAYLOAD_FIELDS``).

    Attributes:
        decision_id: Stable decision id (e.g. ``FD-001``).
        question: The fine-design question being resolved.
        decision: The decision taken.
        rationale: Why this decision is the best fitting one.
        normative_basis: The normative sources backing the decision (FK-*/DK-*).
        llm_responses: The per-LLM positions exchanged this decision (the
            single-LLM stand-in records one entry; the multi-LLM follow-up
            records the full exchange). The ``fine_design_decision`` telemetry
            event carries this verbatim.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: str
    question: str
    decision: str
    rationale: str
    normative_basis: tuple[str, ...]
    llm_responses: tuple[str, ...]


class FineDesignRoundOutcome(BaseModel):
    """The outcome of one fine-design round (injected evaluator return value).

    Attributes:
        converged: ``True`` iff the discussion converged this round (the loop
            stops and the decisions are returned).
        decisions: The decisions reached / refined this round.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    converged: bool
    decisions: tuple[FineDesignDecision, ...]


@runtime_checkable
class FineDesignEvaluator(Protocol):
    """Injected single-round evaluator port (the multi-LLM stand-in).

    FK-25 §25.5: one round = one exchange with the advising LLM(s). The skeleton
    invokes this port exactly once per round; the bloodgroup-A core performs no
    LLM transport itself. The productive multi-LLM adapter implements this port
    in the follow-up story (AG3-047 §2.2).
    """

    def run_round(
        self, change_frame: ChangeFrame, *, round_number: int
    ) -> FineDesignRoundOutcome:
        """Run one fine-design round.

        Args:
            change_frame: The change-frame being refined.
            round_number: The 1-based round number (<= ``max_rounds``).

        Returns:
            The :class:`FineDesignRoundOutcome` for this round.
        """
        ...


class FineDesignResult(BaseModel):
    """Result of the fine-design subprocess (FK-25 §25.5).

    Attributes:
        status: ``converged`` (a round reported convergence) or
            ``max_rounds_exceeded`` (the ceiling was hit first, FK-25 §25.5.1).
        rounds: The number of rounds actually run (1 .. ``max_rounds``).
        final_design_decisions: The decisions from the terminating round.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["converged", "max_rounds_exceeded"]
    rounds: int
    final_design_decisions: tuple[FineDesignDecision, ...]


class FineDesignSubprocess:
    """The Klasse-2 fine-design skeleton (FK-25 §25.5; single-LLM-per-round)."""

    def __init__(self, evaluator: FineDesignEvaluator) -> None:
        """Initialise the subprocess.

        Args:
            evaluator: The injected single-round evaluator (multi-LLM stand-in;
                FK-25 §25.5 -- one call per round, no direct LLM transport in the
                bloodgroup-A core).
        """
        self._evaluator = evaluator

    def run(
        self, change_frame: ChangeFrame, max_rounds: int = DEFAULT_MAX_ROUNDS
    ) -> FineDesignResult:
        """Run the bounded fine-design loop (FK-25 §25.5.1, skeleton).

        Runs at most ``max_rounds`` rounds, ONE evaluator call each. The loop
        stops as soon as a round reports convergence (``status=converged``); if
        the ceiling is reached without convergence the result is
        ``max_rounds_exceeded`` carrying the last round's decisions (FK-25
        §25.5.1: the agent terminates and documents the reached state).

        Args:
            change_frame: The change-frame being refined.
            max_rounds: The round ceiling (default 10, FK-25 §25.5.1).

        Returns:
            The :class:`FineDesignResult`.

        Raises:
            ValueError: If ``max_rounds`` is not >= 1 (a zero/negative ceiling
                is a programming error; fail-closed, ZERO DEBT).
        """
        if max_rounds < 1:
            msg = f"max_rounds must be >= 1 (FK-25 §25.5.1); got {max_rounds}"
            raise ValueError(msg)

        last_decisions: tuple[FineDesignDecision, ...] = ()
        for round_number in range(1, max_rounds + 1):
            outcome = self._evaluator.run_round(
                change_frame, round_number=round_number
            )
            last_decisions = outcome.decisions
            if outcome.converged:
                return FineDesignResult(
                    status="converged",
                    rounds=round_number,
                    final_design_decisions=last_decisions,
                )
        return FineDesignResult(
            status="max_rounds_exceeded",
            rounds=max_rounds,
            final_design_decisions=last_decisions,
        )


__all__ = [
    "DEFAULT_MAX_ROUNDS",
    "FineDesignDecision",
    "FineDesignEvaluator",
    "FineDesignEvaluatorUnavailableError",
    "FineDesignResult",
    "FineDesignRoundOutcome",
    "FineDesignSubprocess",
]
