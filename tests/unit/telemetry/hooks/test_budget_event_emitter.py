"""Unit tests for :class:`BudgetEventEmitter` (AG3-036 AC6)."""

from __future__ import annotations

from agentkit.telemetry.emitters import MemoryEmitter
from agentkit.telemetry.events import Event, EventType
from agentkit.telemetry.hooks.base import HookContext, HookTrigger
from agentkit.telemetry.hooks.budget_event_emitter import BudgetEventEmitter


def _context(
    story_type: str, tool: str = "WebFetch", *, story_type_resolved: bool = True
) -> HookContext:
    return HookContext(
        trigger=HookTrigger.POST_TOOL_USE,
        story_id="AG3-001",
        run_id="run-1",
        project_key="demo",
        tool=tool,
        story_type=story_type,
        story_type_resolved=story_type_resolved,
    )


def _web_call(n: int) -> list[Event]:
    return [
        Event(
            story_id="AG3-001",
            event_type=EventType.WEB_CALL,
            run_id="run-1",
            payload={"web_call_count": i + 1},
        )
        for i in range(n)
    ]


def test_research_web_call_emits_event_and_allows_below_limit() -> None:
    emitter = MemoryEmitter()
    hook = BudgetEventEmitter(emitter, web_call_limit=200)

    result = hook.evaluate(_context("research"))
    hook.emit(result)

    assert result.triggered is True
    assert result.events[0].event_type is EventType.WEB_CALL
    assert result.events[0].payload["over_budget"] is False
    assert result.verdict is not None
    assert result.verdict.allowed is True
    assert emitter.all_events[0].event_type is EventType.WEB_CALL


def test_non_research_story_is_skipped() -> None:
    hook = BudgetEventEmitter(MemoryEmitter(), web_call_limit=200)
    result = hook.evaluate(_context("implementation"))
    assert result.triggered is False
    assert result.events == ()
    assert result.verdict is None


def test_research_budget_overrun_denies() -> None:
    emitter = MemoryEmitter()
    for event in _web_call(2):
        emitter.emit(event)
    hook = BudgetEventEmitter(emitter, web_call_limit=2)

    result = hook.evaluate(_context("research"))

    # Third call exceeds the limit of 2.
    assert result.events[0].payload["over_budget"] is True
    assert result.verdict is not None
    assert result.verdict.allowed is False
    assert "web_call_budget_exceeded" in (result.verdict.message or "")


def test_non_web_tool_is_skipped() -> None:
    hook = BudgetEventEmitter(MemoryEmitter())
    result = hook.evaluate(_context("research", tool="Bash"))
    assert result.triggered is False


def test_unresolved_story_type_fails_closed_deny() -> None:
    # FIX-B: an UNRESOLVED story type on a web call must DENY, NOT downgrade to
    # "not research" (no silent allow).
    hook = BudgetEventEmitter(MemoryEmitter())
    result = hook.evaluate(_context("", story_type_resolved=False))
    assert result.triggered is True
    assert result.verdict is not None
    assert result.verdict.allowed is False
    assert "story_type_unresolved" in (result.verdict.message or "")
    # No web_call event is emitted for an unresolved state.
    assert result.events == ()


def test_unresolved_non_web_tool_is_skipped() -> None:
    # The unresolved fail-closed only fires for an actual web call.
    hook = BudgetEventEmitter(MemoryEmitter())
    result = hook.evaluate(
        _context("", tool="Bash", story_type_resolved=False)
    )
    assert result.triggered is False
    assert result.verdict is None


def test_websearch_tool_triggers() -> None:
    hook = BudgetEventEmitter(MemoryEmitter())
    result = hook.evaluate(_context("research", tool="WebSearch"))
    assert result.triggered is True
    assert result.events[0].payload["tool"] == "WebSearch"
