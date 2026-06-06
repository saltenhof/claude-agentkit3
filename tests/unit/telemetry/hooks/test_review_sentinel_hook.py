"""Unit tests for :class:`ReviewSentinelHook` (AG3-036 AC4)."""

from __future__ import annotations

from agentkit.telemetry.emitters import MemoryEmitter
from agentkit.telemetry.events import EventType
from agentkit.telemetry.hooks.base import HookContext, HookTrigger
from agentkit.telemetry.hooks.review_sentinel_hook import ReviewSentinelHook


def _context(**overrides: object) -> HookContext:
    base: dict[str, object] = {
        "trigger": HookTrigger.PRE_TOOL_USE,
        "story_id": "AG3-001",
        "run_id": "run-1",
        "project_key": "demo",
        "tool": "chatgpt_send",
        "payload": {
            "reviewer_role": "qa",
            "review_round": 1,
            "template_name": "qa-review-v1",
        },
    }
    base.update(overrides)
    return HookContext(**base)  # type: ignore[arg-type]


def test_review_request_emitted_pre_send() -> None:
    hook = ReviewSentinelHook(MemoryEmitter())
    result = hook.evaluate(_context())
    assert result.events[0].event_type is EventType.REVIEW_REQUEST
    payload = result.events[0].payload
    assert payload["reviewer_role"] == "qa"
    assert payload["review_round"] == 1
    assert payload["template_name"] == "qa-review-v1"


def test_review_response_emitted_post_send_with_verdict() -> None:
    hook = ReviewSentinelHook(MemoryEmitter())
    result = hook.evaluate(
        _context(
            trigger=HookTrigger.POST_TOOL_USE,
            payload={
                "reviewer_role": "qa",
                "review_round": 2,
                "template_name": "qa-review-v1",
                "verdict": "PASS",
            },
        )
    )
    event = result.events[0]
    assert event.event_type is EventType.REVIEW_RESPONSE
    assert event.payload["verdict"] == "PASS"
    assert event.payload["review_round"] == 2


def test_review_compliant_emitted_when_stage_compliant() -> None:
    hook = ReviewSentinelHook(MemoryEmitter())
    result = hook.evaluate(
        _context(
            trigger=HookTrigger.POST_TOOL_USE,
            payload={
                "reviewer_role": "qa",
                "review_round": 1,
                "template_name": "qa-review-v1",
                "review_stage": "compliant",
            },
        )
    )
    assert result.events[0].event_type is EventType.REVIEW_COMPLIANT


def test_send_without_template_is_skipped() -> None:
    hook = ReviewSentinelHook(MemoryEmitter())
    result = hook.evaluate(_context(payload={"reviewer_role": "qa"}))
    assert result.triggered is False


def test_non_send_tool_is_skipped() -> None:
    hook = ReviewSentinelHook(MemoryEmitter())
    result = hook.evaluate(_context(tool="Bash"))
    assert result.triggered is False
