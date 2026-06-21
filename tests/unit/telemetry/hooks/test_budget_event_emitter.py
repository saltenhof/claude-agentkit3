"""Unit tests for the OBSERVATIONAL :class:`BudgetEventEmitter` (AG3-086).

AG3-086 migration: the emitter is purely observational again (FK-68 §68.6.0).
The blocking double role was moved to
:class:`agentkit.backend.governance.guard_system.WebCallBudgetGuard`. The emitter now
NEVER returns a ``GuardVerdict`` — it only emits the ``web_call`` counter for a
RESOLVED research web call.
"""

from __future__ import annotations

from agentkit.backend.telemetry.emitters import MemoryEmitter
from agentkit.backend.telemetry.events import Event, EventType
from agentkit.backend.telemetry.hooks.base import HookContext, HookTrigger
from agentkit.backend.telemetry.hooks.budget_event_emitter import BudgetEventEmitter


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


def test_research_web_call_emits_event_and_never_returns_a_verdict() -> None:
    emitter = MemoryEmitter()
    hook = BudgetEventEmitter(emitter, web_call_limit=200)

    result = hook.evaluate(_context("research"))
    hook.emit(result)

    assert result.triggered is True
    assert result.events[0].event_type is EventType.WEB_CALL
    assert result.events[0].payload["over_budget"] is False
    # AG3-086: observational only — NO verdict (the block is the guard's).
    assert result.verdict is None
    assert emitter.all_events[0].event_type is EventType.WEB_CALL


def test_non_research_story_is_skipped() -> None:
    hook = BudgetEventEmitter(MemoryEmitter(), web_call_limit=200)
    result = hook.evaluate(_context("implementation"))
    assert result.triggered is False
    assert result.events == ()
    assert result.verdict is None


def test_research_over_budget_emits_but_does_not_block() -> None:
    emitter = MemoryEmitter()
    for event in _web_call(2):
        emitter.emit(event)
    hook = BudgetEventEmitter(emitter, web_call_limit=2)

    result = hook.evaluate(_context("research"))

    # Third call is at/over the limit of 2 — the observational payload flags it,
    # but the emitter NEVER blocks (no verdict). The block is the guard's job.
    assert result.events[0].payload["over_budget"] is True
    assert result.verdict is None


def test_non_web_tool_is_skipped() -> None:
    hook = BudgetEventEmitter(MemoryEmitter())
    result = hook.evaluate(_context("research", tool="Bash"))
    assert result.triggered is False


def test_unresolved_story_type_is_skipped_no_verdict() -> None:
    # AG3-086 migration: the emitter no longer fail-closes on an unresolved story
    # type — that block moved to WebCallBudgetGuard. The emitter stays silent.
    hook = BudgetEventEmitter(MemoryEmitter())
    result = hook.evaluate(_context("", story_type_resolved=False))
    assert result.triggered is False
    assert result.verdict is None
    assert result.events == ()


def test_unresolved_non_web_tool_is_skipped() -> None:
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
    assert result.verdict is None
