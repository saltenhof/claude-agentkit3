"""Unit tests for :class:`WebCallBudgetGuard` (AG3-086 AC1 / AC1c / AC5b).

The guard is the SINGLE blocking owner of the research web-call budget (FK-30
§30.5.1a). It reads the existing web-call counter, decides fail-closed, writes NO
``web_call`` counter event, and emits an ``integrity_violation`` block audit on a
block (``guard="web_call_budget_guard"``, NO ``stage``).
"""

from __future__ import annotations

from agentkit.backend.governance.guard_system import (
    BudgetSeverity,
    WebCallBudgetGuard,
    WebCallBudgetObservation,
)
from agentkit.backend.telemetry.emitters import MemoryEmitter
from agentkit.backend.telemetry.events import Event, EventType, validate_event_payload


def _obs(
    story_type: str,
    *,
    tool: str = "WebFetch",
    story_type_resolved: bool = True,
) -> WebCallBudgetObservation:
    return WebCallBudgetObservation(
        story_id="AG3-001",
        run_id="run-1",
        project_key="demo",
        tool=tool,
        story_type=story_type,
        story_type_resolved=story_type_resolved,
    )


def _seed(emitter: MemoryEmitter, n: int) -> None:
    for i in range(n):
        emitter.emit(
            Event(
                story_id="AG3-001",
                event_type=EventType.WEB_CALL,
                run_id="run-1",
                payload={"web_call_count": i + 1},
            )
        )


def test_under_limit_allows_no_audit() -> None:
    emitter = MemoryEmitter()
    guard = WebCallBudgetGuard(emitter, web_call_limit=200, web_call_warning=180)
    decision = guard.evaluate_and_emit(_obs("research"))

    assert decision.verdict.allowed is True
    assert decision.severity is BudgetSeverity.PASS
    # The guard writes NO web_call counter event (telemetry owns that).
    assert emitter.query("AG3-001", EventType.WEB_CALL) == []
    # No integrity_violation on an allow.
    assert emitter.query("AG3-001", EventType.INTEGRITY_VIOLATION) == []


def test_warning_threshold_allows_with_warning_severity() -> None:
    emitter = MemoryEmitter()
    _seed(emitter, 180)  # current attempt is the 181st -> >= warning 180
    guard = WebCallBudgetGuard(emitter, web_call_limit=200, web_call_warning=180)
    decision = guard.evaluate_and_emit(_obs("research"))

    assert decision.verdict.allowed is True
    assert decision.severity is BudgetSeverity.WARNING
    assert emitter.query("AG3-001", EventType.INTEGRITY_VIOLATION) == []


def test_at_hard_limit_blocks_and_emits_integrity_violation() -> None:
    emitter = MemoryEmitter()
    _seed(emitter, 199)  # current attempt is the 200th -> >= limit 200
    guard = WebCallBudgetGuard(emitter, web_call_limit=200, web_call_warning=180)
    decision = guard.evaluate_and_emit(_obs("research"))

    assert decision.verdict.allowed is False
    assert decision.severity is BudgetSeverity.ERROR
    assert "web_call_budget_exceeded" in (decision.verdict.message or "")

    violations = emitter.query("AG3-001", EventType.INTEGRITY_VIOLATION)
    assert len(violations) == 1
    payload = violations[0].payload
    assert payload["guard"] == "web_call_budget_guard"
    assert "detail" in payload
    assert "stage" not in payload  # prompt-integrity-specific only
    # Validates green under the conditional contract (AC5b / AC0).
    validate_event_payload(EventType.INTEGRITY_VIOLATION, payload)


def test_non_research_story_allows() -> None:
    emitter = MemoryEmitter()
    _seed(emitter, 500)  # way over — but non-research is never budget-blocked
    guard = WebCallBudgetGuard(emitter, web_call_limit=200, web_call_warning=180)
    decision = guard.evaluate_and_emit(_obs("implementation"))

    assert decision.verdict.allowed is True
    assert decision.severity is BudgetSeverity.PASS
    assert emitter.query("AG3-001", EventType.INTEGRITY_VIOLATION) == []


def test_non_web_tool_allows() -> None:
    guard = WebCallBudgetGuard(MemoryEmitter())
    decision = guard.evaluate(_obs("research", tool="Bash"))
    assert decision.verdict.allowed is True
    assert decision.severity is BudgetSeverity.PASS


def test_unresolved_story_type_blocks_fail_closed_and_emits_audit() -> None:
    # AC1c: an UNRESOLVED story type on a web call is a fail-closed BLOCK from the
    # governance owner (no downgrade to non-research / allow).
    emitter = MemoryEmitter()
    guard = WebCallBudgetGuard(emitter)
    decision = guard.evaluate_and_emit(_obs("", story_type_resolved=False))

    assert decision.verdict.allowed is False
    assert decision.severity is BudgetSeverity.ERROR
    assert "story_type_unresolved" in (decision.verdict.message or "")

    violations = emitter.query("AG3-001", EventType.INTEGRITY_VIOLATION)
    assert len(violations) == 1
    assert violations[0].payload["guard"] == "web_call_budget_guard"
    validate_event_payload(EventType.INTEGRITY_VIOLATION, violations[0].payload)


def test_unresolved_non_web_tool_allows() -> None:
    guard = WebCallBudgetGuard(MemoryEmitter())
    decision = guard.evaluate(_obs("", tool="Bash", story_type_resolved=False))
    assert decision.verdict.allowed is True
