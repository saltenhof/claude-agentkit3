"""Unit tests for :class:`SkillUsageCheckGuard` (AG3-086 AC2 / AC2b).

F-43-030 / FK-43 §43.6.2: block ad-hoc methodology when a matching skill EXISTS
and its precondition is met; allow otherwise. Each block emits an
``integrity_violation`` (``guard="skill_usage_check"``, NO ``stage``).
"""

from __future__ import annotations

from agentkit.governance.guard_system import (
    SkillPrecondition,
    SkillUsageCheckGuard,
    SkillUsageObservation,
)
from agentkit.telemetry.emitters import MemoryEmitter
from agentkit.telemetry.events import EventType, validate_event_payload


class _FakeBindingLookup:
    """First-class in-memory ``SkillBindingLookup`` (not a mock — a real port)."""

    def __init__(self, bound: set[str]) -> None:
        self._bound = bound

    def is_bound(self, project_key: str, skill_name: str) -> bool:
        _ = project_key
        return skill_name in self._bound


def _obs(
    *,
    tool: str = "Bash",
    command: str = "",
    cli_args: tuple[str, ...] = (),
    feature_are: bool = False,
) -> SkillUsageObservation:
    return SkillUsageObservation(
        story_id="AG3-001",
        run_id="run-1",
        project_key="demo",
        tool=tool,
        command=command,
        cli_args=cli_args,
        feature_are=feature_are,
    )


def test_blocks_ad_hoc_when_skill_exists_and_precondition_met() -> None:
    emitter = MemoryEmitter()
    guard = SkillUsageCheckGuard(_FakeBindingLookup({"semantic-review"}), emitter)

    decision = guard.evaluate_and_emit(
        _obs(command="agentkit semantic-review --file src/x.py")
    )

    assert decision.verdict.allowed is False
    assert decision.matched_skill == "semantic-review"
    # AC2b: exactly one integrity_violation, guard=skill_usage_check, NO stage.
    violations = emitter.query("AG3-001", EventType.INTEGRITY_VIOLATION)
    assert len(violations) == 1
    payload = violations[0].payload
    assert payload["guard"] == "skill_usage_check"
    assert "stage" not in payload
    validate_event_payload(EventType.INTEGRITY_VIOLATION, payload)


def test_allows_when_no_matching_skill_bound() -> None:
    # The same ad-hoc signal, but the skill is NOT bound -> cannot force usage.
    emitter = MemoryEmitter()
    guard = SkillUsageCheckGuard(_FakeBindingLookup(set()), emitter)

    decision = guard.evaluate_and_emit(
        _obs(command="agentkit semantic-review --file src/x.py")
    )

    assert decision.verdict.allowed is True
    # AC2b: allow -> NO event.
    assert emitter.query("AG3-001", EventType.INTEGRITY_VIOLATION) == []


def test_allows_when_skill_marker_present() -> None:
    # The agent invoked the skill (structural marker) -> not ad-hoc.
    emitter = MemoryEmitter()
    guard = SkillUsageCheckGuard(_FakeBindingLookup({"semantic-review"}), emitter)

    decision = guard.evaluate_and_emit(
        _obs(
            command="agentkit semantic-review --file src/x.py",
            cli_args=("--via-skill=semantic-review",),
        )
    )

    assert decision.verdict.allowed is True
    assert emitter.query("AG3-001", EventType.INTEGRITY_VIOLATION) == []


def test_allows_unrelated_tool_call() -> None:
    emitter = MemoryEmitter()
    guard = SkillUsageCheckGuard(_FakeBindingLookup({"semantic-review"}), emitter)
    decision = guard.evaluate_and_emit(_obs(command="ls -la"))
    assert decision.verdict.allowed is True


def test_feature_are_precondition_gates_the_block() -> None:
    # The ARE skill rule applies only when features.are is enabled.
    emitter = MemoryEmitter()
    guard = SkillUsageCheckGuard(_FakeBindingLookup({"manage-requirements"}), emitter)

    # features.are disabled -> precondition NOT met -> allow even though bound.
    allowed = guard.evaluate_and_emit(
        _obs(command="agentkit requirements link", feature_are=False)
    )
    assert allowed.verdict.allowed is True
    assert emitter.query("AG3-001", EventType.INTEGRITY_VIOLATION) == []

    # features.are enabled + bound -> block.
    blocked = guard.evaluate_and_emit(
        _obs(command="agentkit requirements link", feature_are=True)
    )
    assert blocked.verdict.allowed is False
    assert blocked.matched_skill == "manage-requirements"


def test_precondition_enum_values() -> None:
    assert SkillPrecondition.ALWAYS.value == "always"
    assert SkillPrecondition.FEATURE_ARE.value == "feature_are"
