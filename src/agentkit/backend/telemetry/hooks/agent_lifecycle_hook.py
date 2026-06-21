"""AgentLifecycleHook: emit ``agent_start`` / ``agent_end`` per worker spawn.

FK-68 §68.2.2 (Worker-Lifecycle) / §68.3.1: a harness hook observes worker-agent
spawn (PreToolUse / PostToolUse for the ``Agent`` tool) and session end
(PostSession) and emits exactly one ``agent_start`` and one ``agent_end`` per run.

Mandatory payload fields (AG3-036 AC2): ``worker_id``, ``principal``,
``story_id``, ``run_id``, ``started_at`` / ``ended_at``, ``outcome``.
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


class AgentLifecycleHook(EmittingHook):
    """Emits ``agent_start`` on spawn and ``agent_end`` on session end."""

    name = "agent_lifecycle_hook"

    def __init__(self, emitter: EventEmitter) -> None:
        """Initialise with the canonical event emitter.

        Args:
            emitter: Telemetry emitter for persistence (FK-68 §68.3.4).
        """
        super().__init__(emitter)

    def evaluate(self, context: HookContext) -> HookResult:
        """Emit ``agent_start`` on agent spawn and ``agent_end`` on session end.

        Trigger conditions (FK-68 §68.2.2):
        - ``PRE_TOOL_USE`` with ``tool == "Agent"`` -> ``agent_start``.
        - ``POST_SESSION`` -> ``agent_end``.

        Args:
            context: The harness-neutral observation.

        Returns:
            A :class:`HookResult` carrying the lifecycle event, or a skipped
            result when the trigger condition does not match.
        """
        if context.trigger is HookTrigger.PRE_TOOL_USE and context.tool == "Agent":
            return HookResult.emitting((self._agent_start_event(context),))
        if context.trigger is HookTrigger.POST_SESSION:
            return HookResult.emitting((self._agent_end_event(context),))
        return HookResult.skipped()

    def _agent_start_event(self, context: HookContext) -> Event:
        payload: dict[str, object] = {
            "worker_id": context.worker_id or "",
            "principal": context.principal,
            "story_id": context.story_id,
            "run_id": context.run_id,
            "started_at": _timestamp_iso(context, "started_at"),
        }
        if context.subagent_type is not None:
            payload["subagent_type"] = context.subagent_type
        return Event(
            story_id=context.story_id,
            event_type=EventType.AGENT_START,
            project_key=context.project_key,
            run_id=context.run_id,
            phase=context.phase,
            source_component=self.name,
            payload=payload,
        )

    def _agent_end_event(self, context: HookContext) -> Event:
        payload: dict[str, object] = {
            "worker_id": context.worker_id or "",
            "principal": context.principal,
            "story_id": context.story_id,
            "run_id": context.run_id,
            "ended_at": _timestamp_iso(context, "ended_at"),
            "outcome": context.outcome or "success",
        }
        if context.subagent_type is not None:
            payload["subagent_type"] = context.subagent_type
        return Event(
            story_id=context.story_id,
            event_type=EventType.AGENT_END,
            project_key=context.project_key,
            run_id=context.run_id,
            phase=context.phase,
            source_component=self.name,
            payload=payload,
        )


def _timestamp_iso(context: HookContext, key: str) -> str:
    """Return the ISO timestamp from the context payload, falling back to now.

    Args:
        context: The observation whose payload may carry the timestamp.
        key: Payload key to read (``started_at`` / ``ended_at``).

    Returns:
        The ISO-8601 timestamp string.
    """
    value = context.payload.get(key)
    if isinstance(value, str) and value:
        return value
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


__all__ = ["AgentLifecycleHook"]
