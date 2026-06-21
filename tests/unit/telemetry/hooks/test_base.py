"""Unit tests for the telemetry-hook base surfaces (AG3-036 §2.1.1)."""

from __future__ import annotations

import pytest

from agentkit.backend.governance.protocols import GuardVerdict
from agentkit.backend.telemetry.emitters import MemoryEmitter
from agentkit.backend.telemetry.events import Event, EventType
from agentkit.backend.telemetry.hooks.base import (
    EmittingHook,
    HookContext,
    HookResult,
    HookTrigger,
    TelemetryHook,
)


def test_hook_context_is_frozen_and_forbids_extra() -> None:
    ctx = HookContext(
        trigger=HookTrigger.PRE_TOOL_USE,
        story_id="AG3-001",
        run_id="run-1",
        project_key="demo",
    )
    with pytest.raises(Exception):  # noqa: B017, PT011 -- pydantic frozen error
        ctx.story_id = "AG3-002"  # type: ignore[misc]
    with pytest.raises(Exception):  # noqa: B017, PT011 -- extra='forbid'
        HookContext(  # type: ignore[call-arg]
            trigger=HookTrigger.PRE_TOOL_USE,
            story_id="AG3-001",
            run_id="run-1",
            project_key="demo",
            unknown_field="x",
        )


def test_hook_result_skipped_and_emitting() -> None:
    skipped = HookResult.skipped()
    assert skipped.triggered is False
    assert skipped.events == ()
    assert skipped.verdict is None

    event = Event(story_id="AG3-001", event_type=EventType.AGENT_START)
    verdict = GuardVerdict.allow("review_guard")
    emitting = HookResult.emitting((event,), verdict=verdict)
    assert emitting.triggered is True
    assert emitting.events == (event,)
    assert emitting.verdict is verdict


def test_emitting_hook_persists_each_event() -> None:
    emitter = MemoryEmitter()

    class _Hook(EmittingHook):
        name = "test_hook"

        def evaluate(self, context: HookContext) -> HookResult:
            return HookResult.skipped()

    hook = _Hook(emitter)
    e1 = Event(story_id="AG3-001", event_type=EventType.AGENT_START)
    e2 = Event(story_id="AG3-001", event_type=EventType.AGENT_END)
    hook.emit(HookResult.emitting((e1, e2)))

    assert emitter.all_events == [e1, e2]


def test_concrete_hooks_satisfy_protocol() -> None:
    from agentkit.backend.telemetry.hooks.agent_lifecycle_hook import AgentLifecycleHook

    hook = AgentLifecycleHook(MemoryEmitter())
    assert isinstance(hook, TelemetryHook)
