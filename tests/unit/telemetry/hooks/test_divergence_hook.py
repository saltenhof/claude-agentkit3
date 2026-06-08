"""Unit tests for :class:`DivergenceHook` (AG3-066)."""

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


_DIVERGENCE_PAYLOAD_KEYS = {
    "story_id",
    "reviewer_a",
    "reviewer_b",
    "divergent",
    "quorum_triggered",
    "final_verdict",
}


def test_divergence_event_emitted_when_reviewers_disagree_without_third_verdict() -> None:
    emitter = MemoryEmitter()
    emitter.emit(_response_event("qa", "PASS"))
    hook = DivergenceHook(emitter)

    # The current observation is the second reviewer; no third verdict exists yet.
    result = hook.evaluate(_response_context("security", "FAIL"))
    hook.emit(result)

    assert result.triggered is True
    event = result.events[0]
    assert event.event_type is EventType.REVIEW_DIVERGENCE
    assert set(event.payload) == _DIVERGENCE_PAYLOAD_KEYS
    assert event.payload == {
        "story_id": "AG3-001",
        "reviewer_a": "qa",
        "reviewer_b": "security",
        "divergent": True,
        "quorum_triggered": False,
        "final_verdict": None,
    }
    assert emitter.all_events[-1].event_type is EventType.REVIEW_DIVERGENCE


def test_non_divergence_still_emits_event_without_quorum() -> None:
    emitter = MemoryEmitter()
    emitter.emit(_response_event("qa", "PASS"))
    hook = DivergenceHook(emitter)

    result = hook.evaluate(_response_context("security", "PASS"))

    assert result.triggered is True
    event = result.events[0]
    assert event.event_type is EventType.REVIEW_DIVERGENCE
    assert set(event.payload) == _DIVERGENCE_PAYLOAD_KEYS
    assert event.payload == {
        "story_id": "AG3-001",
        "reviewer_a": "qa",
        "reviewer_b": "security",
        "divergent": False,
        "quorum_triggered": False,
        "final_verdict": None,
    }


def test_divergence_with_third_verdict_emits_quorum_majority() -> None:
    emitter = MemoryEmitter()
    emitter.emit(_response_event("qa", "PASS"))
    emitter.emit(_response_event("security", "FAIL"))
    hook = DivergenceHook(emitter)

    result = hook.evaluate(_response_context("architecture", "PASS"))

    assert result.triggered is True
    event = result.events[0]
    assert event.event_type is EventType.REVIEW_DIVERGENCE
    assert set(event.payload) == _DIVERGENCE_PAYLOAD_KEYS
    assert event.payload == {
        "story_id": "AG3-001",
        "reviewer_a": "qa",
        "reviewer_b": "security",
        "divergent": True,
        "quorum_triggered": True,
        "final_verdict": "PASS",
    }


def test_divergence_with_three_distinct_verdicts_fails_closed() -> None:
    emitter = MemoryEmitter()
    emitter.emit(_response_event("qa", "PASS"))
    emitter.emit(_response_event("security", "PASS_WITH_CONCERNS"))
    hook = DivergenceHook(emitter)

    result = hook.evaluate(_response_context("architecture", "FAIL"))

    assert result.triggered is True
    event = result.events[0]
    assert event.payload == {
        "story_id": "AG3-001",
        "reviewer_a": "qa",
        "reviewer_b": "security",
        "divergent": True,
        "quorum_triggered": True,
        "final_verdict": "FAIL",
    }


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
