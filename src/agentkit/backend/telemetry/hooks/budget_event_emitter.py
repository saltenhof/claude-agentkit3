"""BudgetEventEmitter: observational web-call telemetry for research stories.

FK-68 §68.6 / §68.6.0 (Budget-Tracking): the ``BudgetEventEmitter`` tracks web
calls (WebSearch / WebFetch) ONLY for research stories and writes the
``web_call`` counter event (FK-68 §68.2.2 governance table). It is PURELY
OBSERVATIONAL — the blocking decision is Governance's responsibility
(:class:`agentkit.backend.governance.guard_system.WebCallBudgetGuard`, FK-30 §30.5.1a).

AG3-086 migration: the previous double role (emit + DENY on over-budget /
unresolved story type) is REMOVED. ``BudgetEventEmitter`` now NEVER returns a
``GuardVerdict``; the budget block — including the fail-closed branch for an
unresolved story type — lives exclusively in ``WebCallBudgetGuard`` (single
block owner, no double blockade, no wrong owner). The observational ``web_call``
counter event the guard reads stays here (FK-68 §68.6.0: telemetry hooks are
purely observational).

Behaviour (observational only):
- Non-web tool -> no event (skipped).
- UNRESOLVED story type on a web call -> no event (the guard owns the
  fail-closed block; the emitter cannot classify the call and stays silent).
- RESOLVED non-research story -> no event (the budget applies only to research).
- RESOLVED research web call -> emit one ``web_call`` event (no verdict).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.telemetry.events import Event, EventType
from agentkit.backend.telemetry.hooks.base import (
    EmittingHook,
    HookContext,
    HookResult,
)

if TYPE_CHECKING:
    from agentkit.backend.telemetry.emitters import EventEmitter

#: Story type that activates the web-call budget (FK-68 §68.6.1).
_RESEARCH_STORY_TYPE = "research"

#: Default hard limit for research web calls (FK-68 §68.6.1 ``telemetry.web_call_limit``).
#: Carried only to enrich the observational payload; the blocking decision is the
#: guard's (``WebCallBudgetGuard``), not the emitter's.
_DEFAULT_WEB_CALL_LIMIT = 200

#: Tool names that count as a web call (FK-68 §68.6.1).
_WEB_TOOLS = frozenset({"WebFetch", "WebSearch"})


class BudgetEventEmitter(EmittingHook):
    """Observational web-call telemetry for research stories (FK-68 §68.6.0).

    Writes the ``web_call`` counter event for research web calls and returns NO
    guard verdict (the blocking decision is ``WebCallBudgetGuard``'s, FK-30
    §30.5.1a). AG3-086 removed the previous block double role.
    """

    name = "budget_event_emitter"

    def __init__(
        self,
        emitter: EventEmitter,
        *,
        web_call_limit: int = _DEFAULT_WEB_CALL_LIMIT,
    ) -> None:
        """Initialise with the emitter and the research web-call hard limit.

        Args:
            emitter: Telemetry emitter for persistence and counting prior web
                calls (FK-68 §68.3.4 / §68.3.5).
            web_call_limit: Hard limit enriching the observational payload
                (``telemetry.web_call_limit``, default 200). Injected as a value
                to honour the AC10 import boundary. NOT used for any blocking
                decision here — that is the guard's responsibility.
        """
        super().__init__(emitter)
        self._web_call_limit = web_call_limit

    def evaluate(self, context: HookContext) -> HookResult:
        """Emit ``web_call`` for research web calls (observational, no verdict).

        Trigger (FK-68 §68.6.1): a WebFetch / WebSearch tool call for a story
        whose ``story_type == "research"``. Non-research stories and unresolved
        story types are skipped (the guard owns the fail-closed block).

        Args:
            context: The harness-neutral observation.

        Returns:
            A :class:`HookResult`. For a research web call it emits one
            ``web_call`` event and carries NO verdict; any other context is
            skipped.
        """
        if context.tool not in _WEB_TOOLS:
            return HookResult.skipped()
        if not context.story_type_resolved:
            # The guard owns the fail-closed block for an unresolved story type
            # (AG3-086 migration). The observational emitter cannot classify the
            # call and stays silent — it never blocks and never emits a verdict.
            return HookResult.skipped()
        if context.story_type != _RESEARCH_STORY_TYPE:
            # FK-68 §68.6.1: the budget applies ONLY to RESOLVED research stories.
            return HookResult.skipped()

        prior_calls = len(
            self._emitter.query(context.story_id, EventType.WEB_CALL)
        )
        # The current attempt is the (prior_calls + 1)-th web call.
        current_count = prior_calls + 1
        over_budget = current_count >= self._web_call_limit

        event = Event(
            story_id=context.story_id,
            event_type=EventType.WEB_CALL,
            project_key=context.project_key,
            run_id=context.run_id,
            phase=context.phase,
            source_component=self.name,
            severity="error" if over_budget else "info",
            payload={
                "story_id": context.story_id,
                "run_id": context.run_id,
                "tool": context.tool,
                "web_call_count": current_count,
                "web_call_limit": self._web_call_limit,
                "over_budget": over_budget,
            },
        )
        return HookResult.emitting((event,))


__all__ = ["BudgetEventEmitter"]
