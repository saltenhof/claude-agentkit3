"""Unit tests for :class:`DivergenceHook` (AG3-036 AC8)."""

from __future__ import annotations

from agentkit.telemetry.emitters import MemoryEmitter
from agentkit.telemetry.events import Event, EventType
from agentkit.telemetry.hooks.base import HookContext, HookTrigger
from agentkit.telemetry.hooks.divergence_hook import DivergenceHook


def _response_context(reviewer_role: str, verdict: str) -> HookContext:
    return HookContext(
        trigger=HookTrigger.POST_TOOL_USE,
        story_id="AG3-001",
        run_id="run-1",
        project_key="demo",
        tool="gemini_send",
        payload={
            "review_stage": "response",
            "reviewer_role": reviewer_role,
            "review_round": 1,
            "verdict": verdict,
        },
    )


def _response_event(reviewer_role: str, verdict: str) -> Event:
    return Event(
        story_id="AG3-001",
        event_type=EventType.REVIEW_RESPONSE,
        run_id="run-1",
        payload={
            "reviewer_role": reviewer_role,
            "review_round": 1,
            "verdict": verdict,
        },
    )


def test_divergence_emitted_when_reviewers_disagree() -> None:
    emitter = MemoryEmitter()
    emitter.emit(_response_event("qa", "PASS"))
    hook = DivergenceHook(emitter)

    # The current observation is the failing reviewer.
    result = hook.evaluate(_response_context("security", "FAIL"))
    hook.emit(result)

    assert result.triggered is True
    event = result.events[0]
    assert event.event_type is EventType.REVIEW_DIVERGENCE
    assert {event.payload["reviewer_a"], event.payload["reviewer_b"]} == {
        "qa",
        "security",
    }
    assert event.payload["score"] == "HIGH"
    assert emitter.all_events[-1].event_type is EventType.REVIEW_DIVERGENCE


def test_no_divergence_when_reviewers_agree() -> None:
    emitter = MemoryEmitter()
    emitter.emit(_response_event("qa", "PASS"))
    hook = DivergenceHook(emitter)

    result = hook.evaluate(_response_context("security", "PASS"))

    assert result.triggered is False
    assert result.events == ()


def test_non_response_observation_is_skipped() -> None:
    hook = DivergenceHook(MemoryEmitter())
    ctx = HookContext(
        trigger=HookTrigger.POST_TOOL_USE,
        story_id="AG3-001",
        run_id="run-1",
        project_key="demo",
        tool="gemini_send",
        payload={"review_stage": "request", "reviewer_role": "qa"},
    )
    result = hook.evaluate(ctx)
    assert result.triggered is False
