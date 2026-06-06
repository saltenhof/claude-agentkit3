"""BudgetEventEmitter: web-call telemetry + budget denial for research stories.

FK-68 §68.6 (Budget-Tracking): the ``BudgetEventEmitter`` tracks web calls
(WebSearch / WebFetch) ONLY for research stories. It writes a ``web_call`` event
(FK-68 §68.2.2 governance table) and -- per AG3-036 §2.1.6 / AC6 -- denies the
operation when the hard budget is exceeded.

Concept note: FK-68 §68.6.0 splits the responsibility (observational emission in
telemetry, blocking in governance.WebCallBudgetGuard). AG3-036 §2.1.6 mandates
the double role here (emit + DENY), analogous to ReviewGuard (§2.1.5). The
canonical event type is ``web_call`` (FK-68 §68.2.2 / §68.6); the AC6 wording
"web_call_attempted" is the descriptive name of the same emitted fact.

Behaviour (FAIL-CLOSED, AG3-036 AC6 / FIX-B):
- Non-web tool -> no event, no verdict (skipped).
- UNRESOLVED story type (``context.story_type_resolved is False``) on a web call
  -> fail-closed DENY (``story_type_unresolved``). An active binding whose story
  type is unresolvable is an inconsistent state; it must NOT be downgraded to
  "not research".
- RESOLVED non-research story -> no event, no verdict (skipped). The hard limit
  applies only to research stories (FK-68 §68.6.1).
- RESOLVED research story, count below the hard limit -> ``web_call`` event + allow.
- RESOLVED research story, count at/above the hard limit -> ``web_call`` event + DENY.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.governance.protocols import GuardVerdict, ViolationType
from agentkit.telemetry.events import Event, EventType
from agentkit.telemetry.hooks.base import (
    EmittingHook,
    HookContext,
    HookResult,
)

if TYPE_CHECKING:
    from agentkit.telemetry.emitters import EventEmitter

#: Story type that activates the web-call budget (FK-68 §68.6.1).
_RESEARCH_STORY_TYPE = "research"

#: Default hard limit for research web calls (FK-68 §68.6.1 ``telemetry.web_call_limit``).
_DEFAULT_WEB_CALL_LIMIT = 200

#: Tool names that count as a web call (FK-68 §68.6.1).
_WEB_TOOLS = frozenset({"WebFetch", "WebSearch"})


class BudgetEventEmitter(EmittingHook):
    """Tracks research web calls and denies on budget overrun (FK-68 §68.6)."""

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
            web_call_limit: Hard limit for research web calls
                (``telemetry.web_call_limit``, default 200). Injected as a value
                to honour the AC10 import boundary.
        """
        super().__init__(emitter)
        self._web_call_limit = web_call_limit

    def evaluate(self, context: HookContext) -> HookResult:
        """Emit ``web_call`` for research web calls and deny on budget overrun.

        Trigger (FK-68 §68.6.1): a WebFetch / WebSearch tool call for a story
        whose ``story_type == "research"``. Non-research stories are skipped.

        Args:
            context: The harness-neutral observation.

        Returns:
            A :class:`HookResult`. For research web calls it always emits a
            ``web_call`` event and carries an allow or DENY verdict; for any
            other context it is skipped.
        """
        if context.tool not in _WEB_TOOLS:
            return HookResult.skipped()
        if not context.story_type_resolved:
            # FIX-B fail-closed: an UNRESOLVED story type (backend fault OR missing
            # record) on an active web call is an inconsistent state. We cannot
            # confirm the story is non-research or within budget, so we DENY rather
            # than downgrade an empty ``story_type`` to "not research".
            verdict = GuardVerdict.block(
                self.name,
                ViolationType.POLICY_VIOLATION,
                "story_type_unresolved: cannot confirm the active story is "
                "non-research or within budget",
                detail={"story_id": context.story_id, "tool": context.tool},
            )
            return HookResult(triggered=True, verdict=verdict)
        if context.story_type != _RESEARCH_STORY_TYPE:
            # FK-68 §68.6.1: the hard limit applies ONLY to RESOLVED research stories.
            return HookResult.skipped()

        prior_calls = len(
            self._emitter.query(context.story_id, EventType.WEB_CALL)
        )
        # The current attempt is the (prior_calls + 1)-th web call.
        current_count = prior_calls + 1
        over_budget = current_count > self._web_call_limit

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

        if over_budget:
            verdict = GuardVerdict.block(
                self.name,
                ViolationType.POLICY_VIOLATION,
                (
                    f"web_call_budget_exceeded: {current_count} > "
                    f"{self._web_call_limit}"
                ),
                detail={
                    "story_id": context.story_id,
                    "web_call_count": current_count,
                    "web_call_limit": self._web_call_limit,
                },
            )
        else:
            verdict = GuardVerdict.allow(self.name)

        return HookResult.emitting((event,), verdict=verdict)


__all__ = ["BudgetEventEmitter"]
