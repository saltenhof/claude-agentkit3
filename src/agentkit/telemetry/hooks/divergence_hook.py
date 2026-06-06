"""DivergenceHook: emit ``review_divergence`` on diverging reviewer verdicts.

FK-68 §68.2.2 (Review-Divergenz) / §68.3.1: emitted after a review pair when the
divergence-score computer (Kap. 28) measures a divergence between two reviewers.
Payload fields: ``reviewer_a``, ``reviewer_b``, ``score`` (LOW / MEDIUM / HIGH),
``routing``.

This hook (AG3-036 §2.1.8 / AC8) only emits the event. The follow-up action (a
third reviewer) is THEME-009 (verify-system.A9) and out of scope. Trigger: after
Layer-2 ``review_response`` observations -- it inspects the response verdicts of
the current review round and emits when at least two reviewers disagree.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.telemetry.events import Event, EventType
from agentkit.telemetry.hooks.base import (
    EmittingHook,
    HookContext,
    HookResult,
    HookTrigger,
)

if TYPE_CHECKING:
    from agentkit.telemetry.emitters import EventEmitter

#: Divergence score buckets (FK-68 §68.2.2).
_SCORE_LOW = "LOW"
_SCORE_HIGH = "HIGH"

#: Verdicts treated as a passing review for divergence detection.
_PASS_VERDICTS = frozenset({"PASS", "pass", "APPROVE", "approve"})


class DivergenceHook(EmittingHook):
    """Emits ``review_divergence`` on diverging reviewer verdicts (FK-68 §68.2.2)."""

    name = "divergence_hook"

    def __init__(self, emitter: EventEmitter) -> None:
        """Initialise with the canonical event emitter.

        Args:
            emitter: Telemetry emitter for persistence and querying review
                responses (FK-68 §68.3.4 / §68.3.5).
        """
        super().__init__(emitter)

    def evaluate(self, context: HookContext) -> HookResult:
        """Emit ``review_divergence`` when reviewers of a round disagree.

        Trigger (FK-68 §68.2.2): a ``review_response`` observation (PostToolUse
        pool-send carrying ``review_stage == "response"``). The hook reads all
        ``review_response`` events of the current review round and, when at least
        two reviewers produced opposing verdicts, emits one ``review_divergence``
        event for the diverging pair.

        Args:
            context: The harness-neutral observation.

        Returns:
            A :class:`HookResult` carrying the divergence event, or a skipped
            result when there is no divergence (or the trigger does not match).
        """
        if not self._is_review_response(context):
            return HookResult.skipped()

        review_round = _coerce_round(context.payload.get("review_round"))
        verdicts = self._round_verdicts(context, review_round)
        pair = _find_diverging_pair(verdicts)
        if pair is None:
            return HookResult.skipped()

        reviewer_a, verdict_a, reviewer_b, verdict_b = pair
        event = Event(
            story_id=context.story_id,
            event_type=EventType.REVIEW_DIVERGENCE,
            project_key=context.project_key,
            run_id=context.run_id,
            phase=context.phase,
            source_component=self.name,
            severity="warning",
            payload={
                "story_id": context.story_id,
                "run_id": context.run_id,
                "review_round": review_round,
                "reviewer_a": reviewer_a,
                "reviewer_b": reviewer_b,
                "verdict_a": verdict_a,
                "verdict_b": verdict_b,
                "score": _SCORE_HIGH,
                "routing": "third_reviewer",
            },
        )
        return HookResult.emitting((event,))

    @staticmethod
    def _is_review_response(context: HookContext) -> bool:
        return (
            context.trigger is HookTrigger.POST_TOOL_USE
            and context.tool.endswith("_send")
            and context.payload.get("review_stage") == "response"
        )

    def _round_verdicts(
        self, context: HookContext, review_round: int
    ) -> list[tuple[str, str]]:
        """Return ``(reviewer_role, verdict)`` pairs for the current round.

        Combines the persisted ``review_response`` events with the current
        in-flight observation (which may not be persisted yet).

        Args:
            context: The current observation.
            review_round: The review round to filter on.

        Returns:
            A list of ``(reviewer_role, verdict)`` tuples for the round.
        """
        verdicts: dict[str, str] = {}
        for event in self._emitter.query(
            context.story_id, EventType.REVIEW_RESPONSE
        ):
            if _coerce_round(event.payload.get("review_round")) != review_round:
                continue
            role = event.payload.get("reviewer_role")
            verdict = event.payload.get("verdict")
            if isinstance(role, str) and role and isinstance(verdict, str):
                verdicts[role] = verdict
        current_role = context.payload.get("reviewer_role")
        current_verdict = context.payload.get("verdict")
        if (
            isinstance(current_role, str)
            and current_role
            and isinstance(current_verdict, str)
        ):
            verdicts[current_role] = current_verdict
        return list(verdicts.items())


def _is_pass(verdict: str) -> bool:
    return verdict in _PASS_VERDICTS


def _find_diverging_pair(
    verdicts: list[tuple[str, str]],
) -> tuple[str, str, str, str] | None:
    """Find a diverging ``(reviewer_a, verdict_a, reviewer_b, verdict_b)`` pair.

    Two reviewers diverge when one passes and the other does not.

    Args:
        verdicts: ``(reviewer_role, verdict)`` pairs of one review round.

    Returns:
        The first diverging pair, or ``None`` when all reviewers agree.
    """
    passing = [(r, v) for r, v in verdicts if _is_pass(v)]
    failing = [(r, v) for r, v in verdicts if not _is_pass(v)]
    if passing and failing:
        reviewer_a, verdict_a = passing[0]
        reviewer_b, verdict_b = failing[0]
        return reviewer_a, verdict_a, reviewer_b, verdict_b
    return None


def _coerce_round(value: object) -> int:
    """Coerce a ``review_round`` value to a positive int (default 1).

    Args:
        value: Raw payload value.

    Returns:
        The review round, defaulting to ``1``.
    """
    if isinstance(value, bool):
        return 1
    if isinstance(value, int) and value >= 1:
        return value
    if isinstance(value, str) and value.isdigit() and int(value) >= 1:
        return int(value)
    return 1


__all__ = ["DivergenceHook", "_SCORE_HIGH", "_SCORE_LOW"]
