"""Unit tests for the guard system."""

from __future__ import annotations

import pytest

from agentkit.pipeline.workflow.guards import (
    GuardResult,
    exploration_gate_approved,
    guard,
    mode_is_exploration,
    preflight_passed,
    verify_completed,
)
from agentkit.story_context_manager.models import PhaseState, PhaseStatus, StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType


class TestGuardResult:
    """Tests for GuardResult value object."""

    def test_pass(self) -> None:
        result = GuardResult.PASS()
        assert result.passed is True
        assert result.reason is None

    def test_fail_with_reason(self) -> None:
        result = GuardResult.FAIL(reason="not ready")
        assert result.passed is False
        assert result.reason == "not ready"

    def test_frozen(self) -> None:
        result = GuardResult.PASS()
        with pytest.raises(AttributeError):
            result.passed = False  # type: ignore[misc]

    def test_equality(self) -> None:
        a = GuardResult.PASS()
        b = GuardResult.PASS()
        assert a == b

        c = GuardResult.FAIL(reason="x")
        d = GuardResult.FAIL(reason="x")
        assert c == d
        assert a != c

    def test_fail_reason_present(self) -> None:
        result = GuardResult.FAIL(reason="setup incomplete")
        assert "setup incomplete" in (result.reason or "")


class TestGuardDecorator:
    """Tests for the @guard decorator."""

    def test_attaches_name(self) -> None:
        @guard("test_guard")
        def my_guard(ctx: StoryContext, state: PhaseState) -> GuardResult:
            return GuardResult.PASS()

        assert my_guard.guard_name == "test_guard"  # type: ignore[attr-defined]

    def test_attaches_description(self) -> None:
        @guard("test_guard", description="Does testing")
        def my_guard(ctx: StoryContext, state: PhaseState) -> GuardResult:
            return GuardResult.PASS()

        assert my_guard.guard_description == "Does testing"  # type: ignore[attr-defined]

    def test_attaches_reads(self) -> None:
        @guard("test_guard", reads=frozenset({"phase", "status"}))
        def my_guard(ctx: StoryContext, state: PhaseState) -> GuardResult:
            return GuardResult.PASS()

        assert my_guard.guard_reads == frozenset({"phase", "status"})  # type: ignore[attr-defined]

    def test_defaults_reads_to_empty_frozenset(self) -> None:
        @guard("test_guard")
        def my_guard(ctx: StoryContext, state: PhaseState) -> GuardResult:
            return GuardResult.PASS()

        assert my_guard.guard_reads == frozenset()  # type: ignore[attr-defined]

    def test_preserves_callable_behavior(
        self, minimal_story_context: StoryContext, minimal_phase_state: PhaseState,
    ) -> None:
        @guard("test_guard")
        def my_guard(ctx: StoryContext, state: PhaseState) -> GuardResult:
            return GuardResult.PASS()

        result = my_guard(minimal_story_context, minimal_phase_state)
        assert result.passed is True


class TestPreflightPassed:
    """Tests for the preflight_passed guard."""

    def test_passes_when_setup_completed(
        self,
        minimal_story_context: StoryContext,
        completed_setup_state: PhaseState,
    ) -> None:
        result = preflight_passed(minimal_story_context, completed_setup_state)
        assert result.passed is True

    def test_fails_when_setup_pending(
        self,
        minimal_story_context: StoryContext,
        minimal_phase_state: PhaseState,
    ) -> None:
        result = preflight_passed(minimal_story_context, minimal_phase_state)
        assert result.passed is False
        assert result.reason is not None
        assert "not completed" in result.reason

    def test_fails_when_different_phase_completed(
        self,
        minimal_story_context: StoryContext,
        completed_verify_state: PhaseState,
    ) -> None:
        result = preflight_passed(minimal_story_context, completed_verify_state)
        assert result.passed is False

    def test_has_guard_metadata(self) -> None:
        assert preflight_passed.guard_name == "preflight_passed"  # type: ignore[attr-defined]
        assert preflight_passed.guard_reads == frozenset({"phase", "status"})  # type: ignore[attr-defined]


class TestExplorationGateApproved:
    """Tests for the exploration_gate_approved guard."""

    def test_passes_when_exploration_completed(
        self,
        minimal_story_context: StoryContext,
        completed_exploration_state: PhaseState,
    ) -> None:
        result = exploration_gate_approved(
            minimal_story_context, completed_exploration_state,
        )
        assert result.passed is True

    def test_fails_when_exploration_pending(
        self, minimal_story_context: StoryContext,
    ) -> None:
        state = PhaseState(
            story_id="TEST-001",
            phase="exploration",
            status=PhaseStatus.PENDING,
        )
        result = exploration_gate_approved(minimal_story_context, state)
        assert result.passed is False
        assert result.reason is not None

    def test_fails_when_different_phase(
        self,
        minimal_story_context: StoryContext,
        completed_setup_state: PhaseState,
    ) -> None:
        result = exploration_gate_approved(
            minimal_story_context, completed_setup_state,
        )
        assert result.passed is False

    def test_has_guard_metadata(self) -> None:
        assert exploration_gate_approved.guard_name == "exploration_gate_approved"  # type: ignore[attr-defined]


class TestVerifyCompleted:
    """Tests for the verify_completed guard."""

    def test_passes_when_verify_completed(
        self,
        minimal_story_context: StoryContext,
        completed_verify_state: PhaseState,
    ) -> None:
        result = verify_completed(minimal_story_context, completed_verify_state)
        assert result.passed is True

    def test_fails_when_verify_in_progress(
        self, minimal_story_context: StoryContext,
    ) -> None:
        state = PhaseState(
            story_id="TEST-001",
            phase="verify",
            status=PhaseStatus.IN_PROGRESS,
        )
        result = verify_completed(minimal_story_context, state)
        assert result.passed is False

    def test_fails_when_different_phase(
        self,
        minimal_story_context: StoryContext,
        completed_setup_state: PhaseState,
    ) -> None:
        result = verify_completed(minimal_story_context, completed_setup_state)
        assert result.passed is False

    def test_has_guard_metadata(self) -> None:
        assert verify_completed.guard_name == "verify_completed"  # type: ignore[attr-defined]


class TestModeIsExploration:
    """Tests for the mode_is_exploration guard."""

    def test_passes_when_exploration_mode(
        self,
        minimal_story_context: StoryContext,
        minimal_phase_state: PhaseState,
    ) -> None:
        # minimal_story_context has mode=EXPLORATION
        result = mode_is_exploration(minimal_story_context, minimal_phase_state)
        assert result.passed is True

    def test_fails_when_execution_mode(
        self,
        execution_story_context: StoryContext,
        minimal_phase_state: PhaseState,
    ) -> None:
        result = mode_is_exploration(execution_story_context, minimal_phase_state)
        assert result.passed is False
        assert result.reason is not None
        assert "EXPLORATION" in result.reason

    def test_fails_when_not_applicable_mode(
        self, minimal_phase_state: PhaseState,
    ) -> None:
        ctx = StoryContext(
            story_id="TEST-003",
            story_type=StoryType.CONCEPT,
            mode=StoryMode.NOT_APPLICABLE,
        )
        result = mode_is_exploration(ctx, minimal_phase_state)
        assert result.passed is False

    def test_has_guard_metadata(self) -> None:
        assert mode_is_exploration.guard_name == "mode_is_exploration"  # type: ignore[attr-defined]
        assert mode_is_exploration.guard_reads == frozenset({"mode"})  # type: ignore[attr-defined]


class TestGuardSideEffectFreedom:
    """Verify that guards do not modify their inputs."""

    def test_preflight_passed_no_side_effects(
        self,
        minimal_story_context: StoryContext,
        completed_setup_state: PhaseState,
    ) -> None:
        ctx_before = minimal_story_context.model_dump()
        state_before = completed_setup_state.model_dump()
        preflight_passed(minimal_story_context, completed_setup_state)
        assert minimal_story_context.model_dump() == ctx_before
        assert completed_setup_state.model_dump() == state_before

    def test_mode_is_exploration_no_side_effects(
        self,
        minimal_story_context: StoryContext,
        minimal_phase_state: PhaseState,
    ) -> None:
        ctx_before = minimal_story_context.model_dump()
        state_before = minimal_phase_state.model_dump()
        mode_is_exploration(minimal_story_context, minimal_phase_state)
        assert minimal_story_context.model_dump() == ctx_before
        assert minimal_phase_state.model_dump() == state_before

    def test_verify_completed_no_side_effects(
        self,
        minimal_story_context: StoryContext,
        completed_verify_state: PhaseState,
    ) -> None:
        ctx_before = minimal_story_context.model_dump()
        state_before = completed_verify_state.model_dump()
        verify_completed(minimal_story_context, completed_verify_state)
        assert minimal_story_context.model_dump() == ctx_before
        assert completed_verify_state.model_dump() == state_before

    def test_exploration_gate_approved_no_side_effects(
        self,
        minimal_story_context: StoryContext,
        completed_exploration_state: PhaseState,
    ) -> None:
        ctx_before = minimal_story_context.model_dump()
        state_before = completed_exploration_state.model_dump()
        exploration_gate_approved(
            minimal_story_context, completed_exploration_state,
        )
        assert minimal_story_context.model_dump() == ctx_before
        assert completed_exploration_state.model_dump() == state_before
