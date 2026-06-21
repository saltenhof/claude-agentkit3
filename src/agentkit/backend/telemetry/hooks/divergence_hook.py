"""DivergenceHook: emit FK-34 ``review_divergence`` facts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.telemetry.divergence import (
    ReviewPairDivergence,
    apply_quorum,
    check_divergence,
    normalize_verdict,
)
from agentkit.backend.telemetry.events import Event, EventType
from agentkit.backend.telemetry.hooks.base import (
    EmittingHook,
    HookContext,
    HookResult,
    HookTrigger,
)

if TYPE_CHECKING:
    from agentkit.backend.telemetry.emitters import EventEmitter


class DivergenceHook(EmittingHook):
    """Emit review-pair divergence facts without LLM calls."""

    name = "divergence_hook"

    def __init__(self, emitter: EventEmitter) -> None:
        """Initialise with the canonical event emitter.

        Args:
            emitter: Telemetry emitter for persistence and querying review
                responses (FK-68 §68.3.4 / §68.3.5).
        """
        super().__init__(emitter)

    def evaluate(self, context: HookContext) -> HookResult:
        """Emit ``review_divergence`` for a completed review pair.

        The hook reads existing ``review_response`` events for the current round
        and combines them with the current observation. The first two reviewers
        form the review pair. Matching verdicts still emit a non-divergence
        fact; diverging verdicts apply quorum only when a third verdict is
        already present.

        Args:
            context: The harness-neutral observation.

        Returns:
            A :class:`HookResult` carrying the divergence fact, or a skipped
            result when the trigger does not match or fewer than two verdicts
            are available.
        """
        if not self._is_review_response(context):
            return HookResult.skipped()

        review_round = _coerce_round(context.payload.get("review_round"))
        verdicts = self._round_verdicts(context, review_round)
        fact = _review_pair_divergence(verdicts)
        if fact is None:
            return HookResult.skipped()

        event = Event(
            story_id=context.story_id,
            event_type=EventType.REVIEW_DIVERGENCE,
            project_key=context.project_key,
            run_id=context.run_id,
            phase=context.phase,
            source_component=self.name,
            severity="warning" if fact.divergent else "info",
            payload={
                "story_id": context.story_id,
                "reviewer_a": fact.reviewer_a,
                "reviewer_b": fact.reviewer_b,
                "divergent": fact.divergent,
                "quorum_triggered": fact.quorum_triggered,
                "final_verdict": fact.final_verdict,
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


def _review_pair_divergence(
    verdicts: list[tuple[str, str]],
) -> ReviewPairDivergence | None:
    """Build the review-pair divergence fact for the first two reviewers."""
    if len(verdicts) < 2:
        return None
    (reviewer_a, raw_verdict_a), (reviewer_b, raw_verdict_b) = verdicts[:2]
    verdict_a = normalize_verdict(raw_verdict_a)
    verdict_b = normalize_verdict(raw_verdict_b)
    divergent = check_divergence(raw_verdict_a, raw_verdict_b)
    final_verdict = None
    quorum_triggered = False
    if divergent and len(verdicts) >= 3:
        quorum_triggered = True
        final_verdict = apply_quorum(
            raw_verdict_a,
            raw_verdict_b,
            verdicts[2][1],
        )
    return ReviewPairDivergence(
        reviewer_a=reviewer_a,
        reviewer_b=reviewer_b,
        verdict_a=verdict_a,
        verdict_b=verdict_b,
        divergent=divergent,
        quorum_triggered=quorum_triggered,
        final_verdict=final_verdict,
    )


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


__all__ = ["DivergenceHook"]
