"""Unit tests for :class:`AgentLifecycleHook` (AG3-036 AC2)."""

from __future__ import annotations

from agentkit.telemetry.emitters import MemoryEmitter
from agentkit.telemetry.events import EventType
from agentkit.telemetry.hooks.agent_lifecycle_hook import AgentLifecycleHook
from agentkit.telemetry.hooks.base import HookContext, HookTrigger


def _context(**overrides: object) -> HookContext:
    base: dict[str, object] = {
        "trigger": HookTrigger.PRE_TOOL_USE,
        "story_id": "AG3-001",
        "run_id": "run-1",
        "project_key": "demo",
        "worker_id": "worker-1",
        "tool": "Agent",
    }
    base.update(overrides)
    return HookContext(**base)  # type: ignore[arg-type]


def test_agent_start_emitted_on_agent_spawn() -> None:
    emitter = MemoryEmitter()
    hook = AgentLifecycleHook(emitter)

    result = hook.evaluate(_context(subagent_type="code"))
    hook.emit(result)

    assert result.triggered is True
    assert len(result.events) == 1
    event = result.events[0]
    assert event.event_type is EventType.AGENT_START
    assert event.source_component == "agent_lifecycle_hook"
    # Mandatory fields (AC2).
    assert event.payload["worker_id"] == "worker-1"
    assert event.payload["principal"] == "worker"
    assert event.payload["story_id"] == "AG3-001"
    assert event.payload["run_id"] == "run-1"
    assert "started_at" in event.payload
    assert event.payload["subagent_type"] == "code"
    assert emitter.all_events[0].event_type is EventType.AGENT_START


def test_agent_end_emitted_on_post_session() -> None:
    emitter = MemoryEmitter()
    hook = AgentLifecycleHook(emitter)

    result = hook.evaluate(
        _context(trigger=HookTrigger.POST_SESSION, tool="", outcome="success")
    )

    assert result.triggered is True
    event = result.events[0]
    assert event.event_type is EventType.AGENT_END
    assert event.payload["ended_at"]
    assert event.payload["outcome"] == "success"


def test_non_agent_pre_tool_use_is_skipped() -> None:
    hook = AgentLifecycleHook(MemoryEmitter())
    result = hook.evaluate(_context(tool="Bash"))
    assert result.triggered is False
    assert result.events == ()


def test_started_at_taken_from_payload_when_present() -> None:
    hook = AgentLifecycleHook(MemoryEmitter())
    result = hook.evaluate(
        _context(payload={"started_at": "2026-01-01T00:00:00+00:00"})
    )
    assert result.events[0].payload["started_at"] == "2026-01-01T00:00:00+00:00"
