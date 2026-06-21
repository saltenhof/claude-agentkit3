"""Unit tests for the double-role :class:`ReviewGuard` (AG3-036 AC5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from agentkit.backend.governance.protocols import ViolationType
from agentkit.backend.telemetry.emitters import MemoryEmitter
from agentkit.backend.telemetry.events import Event, EventType
from agentkit.backend.telemetry.hooks.base import HookContext, HookTrigger
from agentkit.backend.telemetry.hooks.review_guard import ReviewGuard


def _commit_context() -> HookContext:
    return HookContext(
        trigger=HookTrigger.PRE_TOOL_USE,
        story_id="AG3-001",
        run_id="run-1",
        project_key="demo",
        tool="Bash",
        command="git commit -m 'inc'",
    )


def _compliant_event(role: str, ts: datetime) -> Event:
    return Event(
        story_id="AG3-001",
        event_type=EventType.REVIEW_COMPLIANT,
        timestamp=ts,
        run_id="run-1",
        payload={"reviewer_role": role},
    )


def test_deny_when_required_role_missing() -> None:
    emitter = MemoryEmitter()
    guard = ReviewGuard(emitter, required_roles=("qa", "security"))

    result = guard.evaluate(_commit_context())
    guard.emit(result)

    assert result.verdict is not None
    assert result.verdict.allowed is False
    assert result.verdict.violation_type is ViolationType.POLICY_VIOLATION
    assert result.verdict.message == "review_not_compliant: missing roles qa, security"
    # Intervention event emitted (double role).
    assert result.events[0].event_type is EventType.REVIEW_GUARD_INTERVENTION
    assert emitter.all_events[0].event_type is EventType.REVIEW_GUARD_INTERVENTION


def test_allow_when_all_roles_compliant_since_last_commit() -> None:
    emitter = MemoryEmitter()
    now = datetime.now(UTC)
    emitter.emit(_compliant_event("qa", now))
    emitter.emit(_compliant_event("security", now))
    guard = ReviewGuard(emitter, required_roles=("qa", "security"))

    result = guard.evaluate(_commit_context())

    assert result.verdict is not None
    assert result.verdict.allowed is True
    assert result.events == ()


def test_deny_when_compliance_predates_last_commit() -> None:
    emitter = MemoryEmitter()
    old = datetime.now(UTC) - timedelta(hours=1)
    emitter.emit(_compliant_event("qa", old))
    emitter.emit(
        Event(
            story_id="AG3-001",
            event_type=EventType.INCREMENT_COMMIT,
            timestamp=datetime.now(UTC),
            run_id="run-1",
            payload={"commit_sha": "abc"},
        )
    )
    guard = ReviewGuard(emitter, required_roles=("qa",))

    result = guard.evaluate(_commit_context())

    assert result.verdict is not None
    assert result.verdict.allowed is False
    assert "qa" in (result.verdict.message or "")


def test_empty_required_roles_allows() -> None:
    guard = ReviewGuard(MemoryEmitter(), required_roles=())
    result = guard.evaluate(_commit_context())
    assert result.verdict is not None
    assert result.verdict.allowed is True


def test_non_commit_is_skipped() -> None:
    guard = ReviewGuard(MemoryEmitter(), required_roles=("qa",))
    result = guard.evaluate(
        HookContext(
            trigger=HookTrigger.PRE_TOOL_USE,
            story_id="AG3-001",
            run_id="run-1",
            project_key="demo",
            tool="Bash",
            command="git status",
        )
    )
    assert result.triggered is False
    assert result.verdict is None
