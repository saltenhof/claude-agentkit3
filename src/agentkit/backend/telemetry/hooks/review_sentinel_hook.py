"""ReviewSentinelHook: emit ``review_request`` / ``review_response`` / ``review_compliant``.

FK-68 §68.2.2 (Worker-Reviews) / §68.3.1: a harness hook observes pool-send
calls carrying a review template sentinel and emits the three review event types.

Mandatory payload fields (AG3-036 AC4): ``reviewer_role``, ``review_round``,
``template_name``, plus ``verdict`` on ``review_response``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.telemetry.events import Event, EventType
from agentkit.backend.telemetry.hooks.base import (
    EmittingHook,
    HookContext,
    HookResult,
    HookTrigger,
)

if TYPE_CHECKING:
    from agentkit.backend.telemetry.emitters import EventEmitter

#: Payload key naming the review lifecycle stage observed in the pool-send.
_REVIEW_STAGE_KEY = "review_stage"

#: The three review lifecycle stages (FK-68 §68.2.2 Worker-Reviews).
_STAGE_TO_EVENT: dict[str, EventType] = {
    "request": EventType.REVIEW_REQUEST,
    "response": EventType.REVIEW_RESPONSE,
    "compliant": EventType.REVIEW_COMPLIANT,
}

#: Pre-send observations carry the request stage; post-send the response /
#: compliance stages (FK-68 §68.2.2: review_request is PreToolUse, the others
#: PostToolUse). A stage already named in the payload wins over the default.
_TRIGGER_DEFAULT_STAGE: dict[HookTrigger, str] = {
    HookTrigger.PRE_TOOL_USE: "request",
    HookTrigger.POST_TOOL_USE: "response",
}


class ReviewSentinelHook(EmittingHook):
    """Emits the three worker-review event types (FK-68 §68.2.2)."""

    name = "review_sentinel_hook"

    def __init__(self, emitter: EventEmitter) -> None:
        """Initialise with the canonical event emitter.

        Args:
            emitter: Telemetry emitter for persistence (FK-68 §68.3.4).
        """
        super().__init__(emitter)

    def evaluate(self, context: HookContext) -> HookResult:
        """Emit a review event when a review-template sentinel is observed.

        Trigger (FK-68 §68.2.2): a pool-send (``tool`` ending in ``_send``)
        carrying a recognised ``template_name`` sentinel. The lifecycle stage is
        taken from the payload ``review_stage`` (``request`` / ``response`` /
        ``compliant``), defaulting to the trigger-phase default.

        Args:
            context: The harness-neutral observation.

        Returns:
            A :class:`HookResult` carrying one review event, or a skipped result
            when no review sentinel is present.
        """
        if not self._is_review_send(context):
            return HookResult.skipped()
        stage = self._resolve_stage(context)
        event_type = _STAGE_TO_EVENT.get(stage)
        if event_type is None:
            return HookResult.skipped()

        payload: dict[str, object] = {
            "reviewer_role": str(context.payload.get("reviewer_role", "")),
            "review_round": _coerce_round(context.payload.get("review_round")),
            "template_name": str(context.payload.get("template_name", "")),
        }
        if event_type is EventType.REVIEW_RESPONSE:
            payload["verdict"] = str(context.payload.get("verdict", ""))

        event = Event(
            story_id=context.story_id,
            event_type=event_type,
            project_key=context.project_key,
            run_id=context.run_id,
            phase=context.phase,
            source_component=self.name,
            payload=payload,
        )
        return HookResult.emitting((event,))

    @staticmethod
    def _is_review_send(context: HookContext) -> bool:
        return (
            context.tool.endswith("_send")
            and bool(context.payload.get("template_name"))
        )

    @staticmethod
    def _resolve_stage(context: HookContext) -> str:
        explicit = context.payload.get(_REVIEW_STAGE_KEY)
        if isinstance(explicit, str) and explicit in _STAGE_TO_EVENT:
            return explicit
        return _TRIGGER_DEFAULT_STAGE.get(context.trigger, "response")


def _coerce_round(value: object) -> int:
    """Coerce a payload ``review_round`` value to a positive int (default 1).

    Args:
        value: Raw payload value.

    Returns:
        The review round number, defaulting to ``1`` when not derivable.
    """
    if isinstance(value, bool):
        return 1
    if isinstance(value, int) and value >= 1:
        return value
    if isinstance(value, str) and value.isdigit() and int(value) >= 1:
        return int(value)
    return 1


__all__ = ["ReviewSentinelHook"]
