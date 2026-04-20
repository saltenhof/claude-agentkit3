"""Unit tests for the PipelineEngine.

Tests cover normal execution, guard/precondition evaluation,
pipeline robustness, and transition evaluation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.exceptions import PipelineError
from agentkit.phase_state_store import (
    OverrideRecord,
    load_flow_execution,
    load_node_execution_ledger,
    save_override_record,
)
from agentkit.pipeline.engine import (
    PipelineEngine,
    _can_enter_phase,
    _evaluate_transitions,
)
from agentkit.pipeline.lifecycle import (
    HandlerResult,
    NoOpHandler,
    PhaseHandlerRegistry,
)
from agentkit.pipeline.state import load_attempts, load_phase_state
from agentkit.process.language.builder import Workflow
from agentkit.process.language.guards import GuardResult, guard
from agentkit.process.language.model import ExecutionPolicy
from agentkit.state_backend import load_execution_events
from agentkit.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.state_backend.store import reset_backend_cache_for_tests
from agentkit.story_context_manager.models import PhaseState, PhaseStatus, StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType
from agentkit.telemetry.events import EventType

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Test helpers — real handler classes (no mocks)
# ---------------------------------------------------------------------------


class PausingHandler:
    """Handler that pauses with a given yield status."""

    def __init__(self, yield_status: str = "awaiting_review") -> None:
        self._yield_status = yield_status

    def on_enter(
        self, ctx: StoryContext, state: PhaseState,
    ) -> HandlerResult:
        return HandlerResult(
            status=PhaseStatus.PAUSED,
            yield_status=self._yield_status,
        )

    def on_exit(self, ctx: StoryContext, state: PhaseState) -> None:
        pass

    def on_resume(
        self, ctx: StoryContext, state: PhaseState, trigger: str,
    ) -> HandlerResult:
        return HandlerResult(status=PhaseStatus.COMPLETED)


class FailingHandler:
    """Handler that raises an exception on on_enter."""

    def __init__(self, message: str = "Something went wrong") -> None:
        self._message = message

    def on_enter(
        self, ctx: StoryContext, state: PhaseState,
    ) -> HandlerResult:
        raise RuntimeError(self._message)

    def on_exit(self, ctx: StoryContext, state: PhaseState) -> None:
        pass

    def on_resume(
        self, ctx: StoryContext, state: PhaseState, trigger: str,
    ) -> HandlerResult:
        raise RuntimeError(self._message)


class FailResultHandler:
    """Handler that returns FAILED status (not an exception)."""

    def __init__(self, errors: tuple[str, ...] = ("check failed",)) -> None:
        self._errors = errors

    def on_enter(
        self, ctx: StoryContext, state: PhaseState,
    ) -> HandlerResult:
        return HandlerResult(
            status=PhaseStatus.FAILED,
            errors=self._errors,
        )

    def on_exit(self, ctx: StoryContext, state: PhaseState) -> None:
        pass

    def on_resume(
        self, ctx: StoryContext, state: PhaseState, trigger: str,
    ) -> HandlerResult:
        return HandlerResult(
            status=PhaseStatus.FAILED,
            errors=self._errors,
        )


class TrackingHandler:
    """Handler that tracks calls for verification."""

    def __init__(self) -> None:
        self.on_enter_calls: list[tuple[StoryContext, PhaseState]] = []
        self.on_exit_calls: list[tuple[StoryContext, PhaseState]] = []
        self.on_resume_calls: list[
            tuple[StoryContext, PhaseState, str]
        ] = []

    def on_enter(
        self, ctx: StoryContext, state: PhaseState,
    ) -> HandlerResult:
        self.on_enter_calls.append((ctx, state))
        return HandlerResult(status=PhaseStatus.COMPLETED)

    def on_exit(self, ctx: StoryContext, state: PhaseState) -> None:
        self.on_exit_calls.append((ctx, state))

    def on_resume(
        self, ctx: StoryContext, state: PhaseState, trigger: str,
    ) -> HandlerResult:
        self.on_resume_calls.append((ctx, state, trigger))
        return HandlerResult(status=PhaseStatus.COMPLETED)


# ---------------------------------------------------------------------------
# Test guards — real functions (no mocks)
# ---------------------------------------------------------------------------


@guard("always_pass", description="Always passes")
def _always_pass(ctx: StoryContext, state: PhaseState) -> GuardResult:
    return GuardResult.PASS()


@guard("always_fail", description="Always fails")
def _always_fail(ctx: StoryContext, state: PhaseState) -> GuardResult:
    return GuardResult.FAIL(reason="Guard always fails")


@guard(
    "require_setup_done",
    description="Requires setup phase completed",
)
def _require_setup_done(
    ctx: StoryContext, state: PhaseState,
) -> GuardResult:
    if state.phase == "setup" and state.status == PhaseStatus.COMPLETED:
        return GuardResult.PASS()
    return GuardResult.FAIL(reason="Setup not completed")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def sqlite_backend_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


@pytest.fixture()
def story_ctx() -> StoryContext:
    """A minimal StoryContext for testing."""
    return StoryContext(
        project_key="test-project",
        story_id="TEST-001",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        title="Test Story",
    )


@pytest.fixture()
def story_dir(tmp_path: Path, story_ctx: StoryContext) -> Path:
    path = tmp_path / "stories" / story_ctx.story_id
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture()
def simple_workflow() -> object:
    """A simple two-phase workflow: setup -> closure."""
    return (
        Workflow("simple")
        .phase("setup")
        .phase("closure")
        .transition("setup", "closure")
        .build()
    )


@pytest.fixture()
def simple_registry() -> PhaseHandlerRegistry:
    """Registry with NoOpHandler for setup and closure."""
    registry = PhaseHandlerRegistry()
    registry.register("setup", NoOpHandler())
    registry.register("closure", NoOpHandler())
    return registry


# ---------------------------------------------------------------------------
# Normal execution tests
# ---------------------------------------------------------------------------


class TestRunPhaseNormal:
    """Tests for normal (happy-path) phase execution."""

    def test_noop_handler_completes(
        self,
        story_dir: Path,
        story_ctx: StoryContext,
        simple_workflow: object,
        simple_registry: PhaseHandlerRegistry,
    ) -> None:
        """run_phase with NoOpHandler returns phase_completed."""
        engine = PipelineEngine(simple_workflow, simple_registry, story_dir)  # type: ignore[arg-type]
        state = PhaseState(
            story_id="TEST-001", phase="setup",
            status=PhaseStatus.PENDING,
        )
        result = engine.run_phase(story_ctx, state)
        assert result.status == "phase_completed"
        assert result.phase == "setup"
        assert result.attempt_id is not None

    def test_attempt_record_created(
        self,
        story_dir: Path,
        story_ctx: StoryContext,
        simple_workflow: object,
        simple_registry: PhaseHandlerRegistry,
    ) -> None:
        """run_phase creates an AttemptRecord in phase-runs/ directory."""
        engine = PipelineEngine(simple_workflow, simple_registry, story_dir)  # type: ignore[arg-type]
        state = PhaseState(
            story_id="TEST-001", phase="setup",
            status=PhaseStatus.PENDING,
        )
        engine.run_phase(story_ctx, state)

        attempts = load_attempts(story_dir, "setup")
        assert len(attempts) == 1
        assert attempts[0].phase == "setup"
        assert attempts[0].outcome == "phase_completed"

    def test_phase_state_persisted(
        self,
        story_dir: Path,
        story_ctx: StoryContext,
        simple_workflow: object,
        simple_registry: PhaseHandlerRegistry,
    ) -> None:
        """run_phase saves PhaseState after execution."""
        engine = PipelineEngine(simple_workflow, simple_registry, story_dir)  # type: ignore[arg-type]
        state = PhaseState(
            story_id="TEST-001", phase="setup",
            status=PhaseStatus.PENDING,
        )
        engine.run_phase(story_ctx, state)

        loaded = load_phase_state(story_dir)
        assert loaded is not None
        assert loaded.phase == "setup"
        assert loaded.status == PhaseStatus.COMPLETED

        flow = load_flow_execution(story_dir)
        assert flow is not None
        assert flow.flow_id == "simple"
        assert flow.status == "COMPLETED"
        assert flow.current_node_id == "setup"

        ledger = load_node_execution_ledger(story_dir, "simple", "setup")
        assert ledger is not None
        assert ledger.execution_count == 1
        assert ledger.success_count == 1
        assert ledger.last_outcome == "PASS"

    def test_pausing_handler_yields(
        self,
        story_dir: Path,
        story_ctx: StoryContext,
    ) -> None:
        """run_phase with handler returning PAUSED yields correctly."""
        workflow = (
            Workflow("yield-test")
            .phase("exploration")
                .yield_to(
                    "review",
                    on="awaiting_review",
                    resume_triggers=["approved"],
                )
            .build()
        )
        registry = PhaseHandlerRegistry()
        registry.register(
            "exploration", PausingHandler("awaiting_review"),
        )
        engine = PipelineEngine(workflow, registry, story_dir)
        state = PhaseState(
            story_id="TEST-001", phase="exploration",
            status=PhaseStatus.PENDING,
        )
        result = engine.run_phase(story_ctx, state)

        assert result.status == "yielded"
        assert result.yield_status == "awaiting_review"
        assert result.phase == "exploration"

        flow = load_flow_execution(story_dir)
        assert flow is not None
        assert flow.flow_id == "yield-test"
        assert flow.status == "YIELDED"

        ledger = load_node_execution_ledger(story_dir, "yield-test", "exploration")
        assert ledger is not None
        assert ledger.last_outcome == "YIELD"
        assert ledger.success_count == 0

    def test_resume_after_yield(
        self,
        story_dir: Path,
        story_ctx: StoryContext,
    ) -> None:
        """resume_phase after yield calls handler.on_resume."""
        workflow = (
            Workflow("resume-test")
            .phase("exploration")
                .yield_to(
                    "review",
                    on="awaiting_review",
                    resume_triggers=["approved"],
                )
            .build()
        )
        tracking = TrackingHandler()

        class PauseThenCompleteHandler:
            """Pauses on enter, completes on resume."""

            def __init__(self, tracker: TrackingHandler) -> None:
                self._tracker = tracker

            def on_enter(
                self, ctx: StoryContext, state: PhaseState,
            ) -> HandlerResult:
                return HandlerResult(
                    status=PhaseStatus.PAUSED,
                    yield_status="awaiting_review",
                )

            def on_exit(
                self, ctx: StoryContext, state: PhaseState,
            ) -> None:
                pass

            def on_resume(
                self, ctx: StoryContext, state: PhaseState, trigger: str,
            ) -> HandlerResult:
                self._tracker.on_resume_calls.append(
                    (ctx, state, trigger),
                )
                return HandlerResult(status=PhaseStatus.COMPLETED)

        registry = PhaseHandlerRegistry()
        handler = PauseThenCompleteHandler(tracking)
        registry.register("exploration", handler)
        engine = PipelineEngine(workflow, registry, story_dir)

        # First: run phase to get PAUSED
        initial_state = PhaseState(
            story_id="TEST-001", phase="exploration",
            status=PhaseStatus.PENDING,
        )
        yield_result = engine.run_phase(story_ctx, initial_state)
        assert yield_result.status == "yielded"

        # Then: resume
        paused_state = PhaseState(
            story_id="TEST-001", phase="exploration",
            status=PhaseStatus.PAUSED,
            paused_reason="awaiting_review",
        )
        resume_result = engine.resume_phase(
            story_ctx, paused_state, "approved",
        )
        assert resume_result.status == "phase_completed"
        assert len(tracking.on_resume_calls) == 1
        assert tracking.on_resume_calls[0][2] == "approved"


# ---------------------------------------------------------------------------
# Guard / Precondition evaluation tests
# ---------------------------------------------------------------------------


class TestGuardAndPrecondition:
    """Tests for guard and precondition evaluation."""

    def test_precondition_satisfied_allows_entry(
        self,
        story_dir: Path,
        story_ctx: StoryContext,
    ) -> None:
        """run_phase proceeds when precondition passes."""
        workflow = (
            Workflow("precond-pass")
            .phase("setup")
            .phase("closure")
                .precondition(_always_pass)
            .transition("setup", "closure")
            .build()
        )
        registry = PhaseHandlerRegistry()
        registry.register("setup", NoOpHandler())
        registry.register("closure", NoOpHandler())
        engine = PipelineEngine(workflow, registry, story_dir)

        state = PhaseState(
            story_id="TEST-001", phase="closure",
            status=PhaseStatus.PENDING,
        )
        result = engine.run_phase(story_ctx, state)
        assert result.status == "phase_completed"

    def test_precondition_violated_blocks(
        self,
        story_dir: Path,
        story_ctx: StoryContext,
    ) -> None:
        """run_phase with violated precondition returns blocked."""
        workflow = (
            Workflow("precond-fail")
            .phase("setup")
            .phase("closure")
                .precondition(_always_fail)
            .transition("setup", "closure")
            .build()
        )
        registry = PhaseHandlerRegistry()
        registry.register("setup", NoOpHandler())
        registry.register("closure", NoOpHandler())
        engine = PipelineEngine(workflow, registry, story_dir)

        state = PhaseState(
            story_id="TEST-001", phase="closure",
            status=PhaseStatus.PENDING,
        )
        result = engine.run_phase(story_ctx, state)
        assert result.status == "blocked"


class TestExecutionPoliciesAndOverrides:
    """Tests for node execution policy, retry, and override semantics."""

    def test_once_per_run_skips_second_execution(
        self,
        story_dir: Path,
        story_ctx: StoryContext,
    ) -> None:
        tracking = TrackingHandler()
        workflow = (
            Workflow("once")
            .phase("setup")
            .execution_policy(ExecutionPolicy.ONCE_PER_RUN)
            .build()
        )
        registry = PhaseHandlerRegistry()
        registry.register("setup", tracking)
        engine = PipelineEngine(workflow, registry, story_dir)

        state = PhaseState(
            story_id="TEST-001",
            phase="setup",
            status=PhaseStatus.PENDING,
        )

        first = engine.run_phase(story_ctx, state)
        second = engine.run_phase(story_ctx, state)

        assert first.status == "phase_completed"
        assert second.status == "phase_completed"
        assert len(tracking.on_enter_calls) == 1

        attempts = load_attempts(story_dir, "setup")
        assert len(attempts) == 2
        assert attempts[-1].outcome == "skipped"

    def test_failed_node_backtracks_via_retry_policy(
        self,
        story_dir: Path,
        story_ctx: StoryContext,
    ) -> None:
        workflow = (
            Workflow("retry")
            .phase("implementation")
            .phase("verify")
                .retry_policy(max_attempts=3, backtrack_target="implementation")
            .transition("implementation", "verify")
            .transition("verify", "implementation")
            .build()
        )
        registry = PhaseHandlerRegistry()
        registry.register("implementation", NoOpHandler())
        registry.register("verify", FailResultHandler(("qa failed",)))
        engine = PipelineEngine(workflow, registry, story_dir)

        state = PhaseState(
            story_id="TEST-001",
            phase="verify",
            status=PhaseStatus.PENDING,
        )
        result = engine.run_phase(story_ctx, state)

        assert result.status == "phase_completed"
        assert result.next_phase == "implementation"

        attempts = load_attempts(story_dir, "verify")
        assert len(attempts) == 1
        assert attempts[0].outcome == "backtrack"

    def test_skip_override_bypasses_handler(
        self,
        story_dir: Path,
        story_ctx: StoryContext,
    ) -> None:
        tracking = TrackingHandler()
        workflow = (
            Workflow("override-skip")
            .phase("verify")
                .override_policy(allow_skip=True)
            .phase("closure")
            .transition("verify", "closure")
            .build()
        )
        registry = PhaseHandlerRegistry()
        registry.register("verify", tracking)
        registry.register("closure", NoOpHandler())
        engine = PipelineEngine(workflow, registry, story_dir)

        save_override_record(
            story_dir,
            OverrideRecord(
                override_id="ovr-1",
                project_key=story_ctx.project_key,
                story_id=story_ctx.story_id,
                run_id=engine._runtime.resolve_run_id(story_ctx),  # type: ignore[attr-defined]
                flow_id="override-skip",
                target_node_id="verify",
                override_type="skip_node",
                actor_type="human",
                actor_id="tester",
                reason="operator skip",
                created_at=datetime.now(tz=UTC),
            ),
        )

        state = PhaseState(
            story_id="TEST-001",
            phase="verify",
            status=PhaseStatus.PENDING,
        )
        result = engine.run_phase(story_ctx, state)

        assert result.status == "phase_completed"
        assert result.next_phase == "closure"
        assert tracking.on_enter_calls == []

    def test_jump_override_redirects_flow(
        self,
        story_dir: Path,
        story_ctx: StoryContext,
    ) -> None:
        tracking = TrackingHandler()
        workflow = (
            Workflow("override-jump")
            .phase("verify")
                .override_policy(allow_jump=True)
            .phase("closure")
            .transition("verify", "closure")
            .build()
        )
        registry = PhaseHandlerRegistry()
        registry.register("verify", tracking)
        registry.register("closure", NoOpHandler())
        engine = PipelineEngine(workflow, registry, story_dir)

        save_override_record(
            story_dir,
            OverrideRecord(
                override_id="ovr-2",
                project_key=story_ctx.project_key,
                story_id=story_ctx.story_id,
                run_id=engine._runtime.resolve_run_id(story_ctx),  # type: ignore[attr-defined]
                flow_id="override-jump",
                target_node_id="closure",
                override_type="jump_to",
                actor_type="human",
                actor_id="tester",
                reason="operator jump",
                created_at=datetime.now(tz=UTC),
            ),
        )

        state = PhaseState(
            story_id="TEST-001",
            phase="verify",
            status=PhaseStatus.PENDING,
        )
        result = engine.run_phase(story_ctx, state)

        assert result.status == "phase_completed"
        assert result.next_phase == "closure"
        assert tracking.on_enter_calls == []
        assert result.errors == ("operator jump",)

    def test_conditional_precondition_skipped_when_not_applicable(
        self,
        story_dir: Path,
    ) -> None:
        """Precondition with when=... that does not match is skipped."""
        ctx = StoryContext(
            project_key="test-project",
            story_id="TEST-001",
            story_type=StoryType.BUGFIX,
            execution_route=StoryMode.EXECUTION,
        )
        workflow = (
            Workflow("cond-precond")
            .phase("impl")
                .precondition(
                    _always_fail,
                    when=lambda c, s: c.execution_route == StoryMode.EXPLORATION,
                )
            .build()
        )
        registry = PhaseHandlerRegistry()
        registry.register("impl", NoOpHandler())
        engine = PipelineEngine(workflow, registry, story_dir)

        state = PhaseState(
            story_id="TEST-001", phase="impl",
            status=PhaseStatus.PENDING,
        )
        # Should NOT be blocked since mode is EXECUTION, not EXPLORATION
        result = engine.run_phase(ctx, state)
        assert result.status == "phase_completed"

    def test_transition_guard_pass_returns_transition(
        self,
        tmp_path: Path,
        story_ctx: StoryContext,
    ) -> None:
        """evaluate_transitions returns transition when guard passes."""
        workflow = (
            Workflow("trans-pass")
            .phase("setup")
            .phase("closure")
            .transition("setup", "closure", guard=_always_pass)
            .build()
        )
        state = PhaseState(
            story_id="TEST-001", phase="setup",
            status=PhaseStatus.COMPLETED,
        )
        transition = _evaluate_transitions(workflow, story_ctx, state)
        assert transition is not None
        assert transition.target == "closure"

    def test_transition_guard_fail_returns_none(
        self,
        tmp_path: Path,
        story_ctx: StoryContext,
    ) -> None:
        """evaluate_transitions returns None when all guards fail."""
        workflow = (
            Workflow("trans-fail")
            .phase("setup")
            .phase("closure")
            .transition("setup", "closure", guard=_always_fail)
            .build()
        )
        state = PhaseState(
            story_id="TEST-001", phase="setup",
            status=PhaseStatus.COMPLETED,
        )
        transition = _evaluate_transitions(workflow, story_ctx, state)
        assert transition is None

    def test_transition_multiple_first_fail_second_pass(
        self,
        tmp_path: Path,
        story_ctx: StoryContext,
    ) -> None:
        """First guard FAIL, second PASS: second transition wins."""
        workflow = (
            Workflow("trans-multi")
            .phase("setup")
            .phase("exploration")
            .phase("implementation")
            .transition("setup", "exploration", guard=_always_fail)
            .transition("setup", "implementation", guard=_always_pass)
            .build()
        )
        state = PhaseState(
            story_id="TEST-001", phase="setup",
            status=PhaseStatus.COMPLETED,
        )
        transition = _evaluate_transitions(workflow, story_ctx, state)
        assert transition is not None
        assert transition.target == "implementation"


# ---------------------------------------------------------------------------
# Pipeline robustness tests (CRITICAL)
# ---------------------------------------------------------------------------


class TestPipelineRobustness:
    """Robustness tests for error handling and edge cases."""

    def test_phase_not_in_workflow_raises(
        self,
        story_dir: Path,
        story_ctx: StoryContext,
    ) -> None:
        """run_phase on undefined phase raises PipelineError."""
        workflow = Workflow("minimal").phase("setup").build()
        registry = PhaseHandlerRegistry()
        registry.register("setup", NoOpHandler())
        engine = PipelineEngine(workflow, registry, story_dir)

        state = PhaseState(
            story_id="TEST-001", phase="nonexistent",
            status=PhaseStatus.PENDING,
        )
        with pytest.raises(PipelineError, match="not defined in workflow"):
            engine.run_phase(story_ctx, state)

    def test_no_handler_registered_raises(
        self,
        story_dir: Path,
        story_ctx: StoryContext,
    ) -> None:
        """run_phase on phase without handler raises PipelineError."""
        workflow = Workflow("minimal").phase("setup").build()
        registry = PhaseHandlerRegistry()
        # Deliberately NOT registering a handler
        engine = PipelineEngine(workflow, registry, story_dir)

        state = PhaseState(
            story_id="TEST-001", phase="setup",
            status=PhaseStatus.PENDING,
        )
        with pytest.raises(PipelineError, match="No handler registered"):
            engine.run_phase(story_ctx, state)

    def test_resume_when_not_paused_fails(
        self,
        story_dir: Path,
        story_ctx: StoryContext,
    ) -> None:
        """resume_phase when state is not PAUSED returns failed."""
        workflow = (
            Workflow("resume-not-paused")
            .phase("setup")
                .yield_to(
                    "wait", on="waiting",
                    resume_triggers=["go"],
                )
            .build()
        )
        registry = PhaseHandlerRegistry()
        registry.register("setup", NoOpHandler())
        engine = PipelineEngine(workflow, registry, story_dir)

        state = PhaseState(
            story_id="TEST-001", phase="setup",
            status=PhaseStatus.IN_PROGRESS,
        )
        result = engine.resume_phase(story_ctx, state, "go")
        assert result.status == "failed"
        assert "expected 'paused'" in result.errors[0]

    def test_resume_with_invalid_trigger_fails(
        self,
        story_dir: Path,
        story_ctx: StoryContext,
    ) -> None:
        """resume_phase with trigger not in yield point returns failed."""
        workflow = (
            Workflow("bad-trigger")
            .phase("exploration")
                .yield_to(
                    "review",
                    on="awaiting_review",
                    resume_triggers=["approved", "rejected"],
                )
            .build()
        )
        registry = PhaseHandlerRegistry()
        registry.register("exploration", PausingHandler("awaiting_review"))
        engine = PipelineEngine(workflow, registry, story_dir)

        paused_state = PhaseState(
            story_id="TEST-001", phase="exploration",
            status=PhaseStatus.PAUSED,
            paused_reason="awaiting_review",
        )
        result = engine.resume_phase(
            story_ctx, paused_state, "invalid_trigger",
        )
        assert result.status == "failed"
        assert "Invalid resume trigger" in result.errors[0]

    def test_handler_exception_returns_failed(
        self,
        story_dir: Path,
        story_ctx: StoryContext,
    ) -> None:
        """Handler raising exception returns failed with error details."""
        workflow = Workflow("exception").phase("setup").build()
        registry = PhaseHandlerRegistry()
        registry.register("setup", FailingHandler("Boom!"))
        engine = PipelineEngine(workflow, registry, story_dir)

        state = PhaseState(
            story_id="TEST-001", phase="setup",
            status=PhaseStatus.PENDING,
        )
        result = engine.run_phase(story_ctx, state)
        assert result.status == "failed"
        assert len(result.errors) > 0
        assert "Boom!" in result.errors[0]

        flow = load_flow_execution(story_dir)
        assert flow is not None
        assert flow.flow_id == "exception"
        assert flow.status == "FAILED"

        ledger = load_node_execution_ledger(story_dir, "exception", "setup")
        assert ledger is not None
        assert ledger.last_outcome == "FAIL"
        assert ledger.execution_count == 1

    def test_handler_exception_preserves_story_id(
        self,
        story_dir: Path,
        story_ctx: StoryContext,
    ) -> None:
        """When handler raises, persisted state has correct story_id, not 'unknown'."""
        workflow = Workflow("exc-id").phase("setup").build()
        registry = PhaseHandlerRegistry()
        registry.register("setup", FailingHandler("Kaboom!"))
        engine = PipelineEngine(workflow, registry, story_dir)

        state = PhaseState(
            story_id="TEST-001", phase="setup",
            status=PhaseStatus.PENDING,
        )
        result = engine.run_phase(story_ctx, state)
        assert result.status == "failed"

        # Load persisted state and verify story_id is preserved
        loaded = load_phase_state(story_dir)
        assert loaded is not None
        assert loaded.story_id == "TEST-001"
        assert loaded.story_id != "unknown"

    def test_handler_returning_failed_status(
        self,
        story_dir: Path,
        story_ctx: StoryContext,
    ) -> None:
        """Handler returning FAILED status produces failed EngineResult."""
        workflow = Workflow("fail-status").phase("verify").build()
        registry = PhaseHandlerRegistry()
        registry.register(
            "verify", FailResultHandler(("qa check failed",)),
        )
        engine = PipelineEngine(workflow, registry, story_dir)

        state = PhaseState(
            story_id="TEST-001", phase="verify",
            status=PhaseStatus.PENDING,
        )
        result = engine.run_phase(story_ctx, state)
        assert result.status == "failed"
        assert "qa check failed" in result.errors

    def test_can_enter_phase_no_preconditions(
        self,
        tmp_path: Path,
        story_ctx: StoryContext,
    ) -> None:
        """can_enter_phase on phase without preconditions returns True."""
        workflow = Workflow("no-precond").phase("setup").build()
        state = PhaseState(
            story_id="TEST-001", phase="setup",
            status=PhaseStatus.PENDING,
        )
        can_enter, reasons = _can_enter_phase(
            workflow,
            "setup",
            story_ctx,
            state,
        )
        assert can_enter is True
        assert reasons == []

    def test_can_enter_phase_with_violated_precondition(
        self,
        tmp_path: Path,
        story_ctx: StoryContext,
    ) -> None:
        """can_enter_phase returns False with reasons on violation."""
        workflow = (
            Workflow("precond-check")
            .phase("closure")
                .precondition(_always_fail)
            .build()
        )
        state = PhaseState(
            story_id="TEST-001", phase="closure",
            status=PhaseStatus.PENDING,
        )
        can_enter, reasons = _can_enter_phase(
            workflow,
            "closure",
            story_ctx,
            state,
        )
        assert can_enter is False
        assert len(reasons) == 1
        assert "Guard always fails" in reasons[0]


# ---------------------------------------------------------------------------
# Transition evaluation tests
# ---------------------------------------------------------------------------


class TestTransitionEvaluation:
    """Tests for transition resolution logic."""

    def test_valid_transition_sets_next_phase(
        self,
        story_dir: Path,
        story_ctx: StoryContext,
        simple_workflow: object,
        simple_registry: PhaseHandlerRegistry,
    ) -> None:
        """Phase with valid transition sets next_phase in result."""
        engine = PipelineEngine(simple_workflow, simple_registry, story_dir)  # type: ignore[arg-type]
        state = PhaseState(
            story_id="TEST-001", phase="setup",
            status=PhaseStatus.PENDING,
        )
        result = engine.run_phase(story_ctx, state)
        assert result.status == "phase_completed"
        assert result.next_phase == "closure"

    def test_terminal_phase_has_no_next_phase(
        self,
        story_dir: Path,
        story_ctx: StoryContext,
        simple_workflow: object,
        simple_registry: PhaseHandlerRegistry,
    ) -> None:
        """Terminal phase (no outgoing transitions) has next_phase=None."""
        engine = PipelineEngine(simple_workflow, simple_registry, story_dir)  # type: ignore[arg-type]
        state = PhaseState(
            story_id="TEST-001", phase="closure",
            status=PhaseStatus.PENDING,
        )
        result = engine.run_phase(story_ctx, state)
        assert result.status == "phase_completed"
        assert result.next_phase is None

    def test_transition_without_guard_always_passes(
        self,
        tmp_path: Path,
        story_ctx: StoryContext,
    ) -> None:
        """A transition without a guard always passes."""
        workflow = (
            Workflow("no-guard")
            .phase("a")
            .phase("b")
            .transition("a", "b")
            .build()
        )
        state = PhaseState(
            story_id="TEST-001", phase="a",
            status=PhaseStatus.COMPLETED,
        )
        transition = _evaluate_transitions(workflow, story_ctx, state)
        assert transition is not None
        assert transition.target == "b"

    def test_no_transitions_returns_none(
        self,
        tmp_path: Path,
        story_ctx: StoryContext,
    ) -> None:
        """Phase with no outgoing transitions evaluates to None."""
        workflow = (
            Workflow("terminal")
            .phase("end")
            .build()
        )
        state = PhaseState(
            story_id="TEST-001", phase="end",
            status=PhaseStatus.COMPLETED,
        )
        transition = _evaluate_transitions(workflow, story_ctx, state)
        assert transition is None

    def test_phase_snapshot_created_on_completion(
        self,
        story_dir: Path,
        story_ctx: StoryContext,
    ) -> None:
        """Completed phase creates a phase snapshot file."""
        workflow = Workflow("snapshot").phase("setup").build()
        registry = PhaseHandlerRegistry()
        registry.register("setup", NoOpHandler())
        engine = PipelineEngine(workflow, registry, story_dir)

        state = PhaseState(
            story_id="TEST-001", phase="setup",
            status=PhaseStatus.PENDING,
        )
        engine.run_phase(story_ctx, state)

        snapshot_file = story_dir / "phase-state-setup.json"
        assert snapshot_file.exists()

    def test_multiple_attempts_increment_id(
        self,
        story_dir: Path,
        story_ctx: StoryContext,
    ) -> None:
        """Running a phase multiple times increments attempt IDs."""
        workflow = Workflow("multi-attempt").phase("setup").build()
        registry = PhaseHandlerRegistry()
        registry.register("setup", NoOpHandler())
        engine = PipelineEngine(workflow, registry, story_dir)

        state = PhaseState(
            story_id="TEST-001", phase="setup",
            status=PhaseStatus.PENDING,
        )
        r1 = engine.run_phase(story_ctx, state)
        r2 = engine.run_phase(story_ctx, state)

        assert r1.attempt_id == "setup-001"
        assert r2.attempt_id == "setup-002"

        attempts = load_attempts(story_dir, "setup")
        assert len(attempts) == 2

    def test_guard_evaluations_recorded_in_attempt(
        self,
        story_dir: Path,
        story_ctx: StoryContext,
    ) -> None:
        """Exit-guard evaluations are recorded in the attempt record."""
        workflow = (
            Workflow("guard-audit")
            .phase("setup")
                .guard(_always_pass)
            .build()
        )
        registry = PhaseHandlerRegistry()
        registry.register("setup", NoOpHandler())
        engine = PipelineEngine(workflow, registry, story_dir)

        state = PhaseState(
            story_id="TEST-001", phase="setup",
            status=PhaseStatus.PENDING,
        )
        result = engine.run_phase(story_ctx, state)
        assert result.status == "phase_completed"

        attempts = load_attempts(story_dir, "setup")
        assert len(attempts) == 1
        assert len(attempts[0].guard_evaluations) == 1

    def test_guard_failure_after_completion_blocks_transition(
        self,
        story_dir: Path,
        story_ctx: StoryContext,
    ) -> None:
        """Handler completes but exit-guard FAIL -> EngineResult status='failed'."""
        workflow = (
            Workflow("guard-exit-fail")
            .phase("setup")
                .guard(_always_fail)
            .phase("closure")
            .transition("setup", "closure")
            .build()
        )
        registry = PhaseHandlerRegistry()
        registry.register("setup", NoOpHandler())
        registry.register("closure", NoOpHandler())
        engine = PipelineEngine(workflow, registry, story_dir)

        state = PhaseState(
            story_id="TEST-001", phase="setup",
            status=PhaseStatus.PENDING,
        )
        result = engine.run_phase(story_ctx, state)
        # Handler completed but guard blocked the transition
        assert result.status == "failed"
        assert result.phase == "setup"
        assert "Guard always fails" in result.errors[0]

        # Verify state persisted as FAILED
        loaded = load_phase_state(story_dir)
        assert loaded is not None
        assert loaded.status == PhaseStatus.FAILED

        # Guard evaluation should be recorded in attempt
        attempts = load_attempts(story_dir, "setup")
        assert len(attempts) == 1
        assert len(attempts[0].guard_evaluations) == 1
        assert attempts[0].guard_evaluations[0]["passed"] is False

    def test_can_enter_phase_unknown_phase(
        self,
        tmp_path: Path,
        story_ctx: StoryContext,
    ) -> None:
        """can_enter_phase on unknown phase returns (True, [])."""
        workflow = Workflow("minimal").phase("setup").build()
        state = PhaseState(
            story_id="TEST-001", phase="setup",
            status=PhaseStatus.PENDING,
        )
        can_enter, reasons = _can_enter_phase(
            workflow,
            "nonexistent",
            story_ctx,
            state,
        )
        assert can_enter is True
        assert reasons == []


class TestRuntimeTelemetry:
    """Tests for canonical engine telemetry emission."""

    def test_run_id_is_stable_per_engine_instance(
        self,
        story_dir: Path,
        story_ctx: StoryContext,
    ) -> None:
        workflow = Workflow("run-id").phase("setup").build()
        registry = PhaseHandlerRegistry()
        registry.register("setup", NoOpHandler())

        first_engine = PipelineEngine(workflow, registry, story_dir)
        first_run_id = first_engine._runtime.resolve_run_id(story_ctx)  # type: ignore[attr-defined]
        assert first_engine._runtime.resolve_run_id(story_ctx) == first_run_id  # type: ignore[attr-defined]

        second_engine = PipelineEngine(workflow, registry, story_dir)
        second_run_id = second_engine._runtime.resolve_run_id(story_ctx)  # type: ignore[attr-defined]
        assert second_run_id != first_run_id

    def test_terminal_phase_emits_flow_start_node_result_and_flow_end(
        self,
        story_dir: Path,
        story_ctx: StoryContext,
    ) -> None:
        workflow = Workflow("telemetry-terminal").phase("setup").build()
        registry = PhaseHandlerRegistry()
        registry.register("setup", NoOpHandler())
        engine = PipelineEngine(workflow, registry, story_dir)

        state = PhaseState(
            story_id="TEST-001",
            phase="setup",
            status=PhaseStatus.PENDING,
        )
        engine.run_phase(story_ctx, state)

        flow = load_flow_execution(story_dir)
        assert flow is not None
        events = load_execution_events(
            story_dir,
            project_key=story_ctx.project_key,
            story_id=story_ctx.story_id,
            run_id=flow.run_id,
        )

        assert [event.event_type for event in events] == [
            EventType.FLOW_START.value,
            EventType.NODE_RESULT.value,
            EventType.FLOW_END.value,
        ]
        assert all(event.project_key == story_ctx.project_key for event in events)
        assert all(event.run_id == flow.run_id for event in events)
        assert events[1].payload["outcome"] == "PASS"
        assert events[2].payload["status"] == "COMPLETED"

    def test_jump_override_emits_override_applied_once(
        self,
        story_dir: Path,
        story_ctx: StoryContext,
    ) -> None:
        workflow = (
            Workflow("telemetry-override")
            .phase("verify")
                .override_policy(allow_jump=True)
            .phase("closure")
            .transition("verify", "closure")
            .build()
        )
        registry = PhaseHandlerRegistry()
        registry.register("verify", NoOpHandler())
        registry.register("closure", NoOpHandler())
        engine = PipelineEngine(workflow, registry, story_dir)

        save_override_record(
            story_dir,
            OverrideRecord(
                override_id="ovr-telemetry",
                project_key=story_ctx.project_key,
                story_id=story_ctx.story_id,
                run_id=engine._runtime.resolve_run_id(story_ctx),  # type: ignore[attr-defined]
                flow_id="telemetry-override",
                target_node_id="closure",
                override_type="jump_to",
                actor_type="human",
                actor_id="tester",
                reason="jump to closure",
                created_at=datetime.now(tz=UTC),
            ),
        )

        state = PhaseState(
            story_id="TEST-001",
            phase="verify",
            status=PhaseStatus.PENDING,
        )
        engine.run_phase(story_ctx, state)

        flow = load_flow_execution(story_dir)
        assert flow is not None
        events = load_execution_events(
            story_dir,
            project_key=story_ctx.project_key,
            story_id=story_ctx.story_id,
            run_id=flow.run_id,
        )
        override_events = [
            event
            for event in events
            if event.event_type == EventType.OVERRIDE_APPLIED.value
        ]
        node_events = [
            event for event in events if event.event_type == EventType.NODE_RESULT.value
        ]

        assert len(override_events) == 1
        assert override_events[0].payload["override_type"] == "jump_to"
        assert override_events[0].payload["override_id"] == "ovr-telemetry"
        assert len(node_events) == 1
        assert node_events[0].payload["target_node_id"] == "closure"

    def test_retry_backtrack_emits_backtrack_node_result_without_flow_end(
        self,
        story_dir: Path,
        story_ctx: StoryContext,
    ) -> None:
        workflow = (
            Workflow("telemetry-backtrack")
            .phase("implementation")
            .phase("verify")
                .retry_policy(max_attempts=3, backtrack_target="implementation")
            .transition("implementation", "verify")
            .transition("verify", "implementation")
            .build()
        )
        registry = PhaseHandlerRegistry()
        registry.register("implementation", NoOpHandler())
        registry.register("verify", FailResultHandler(("qa failed",)))
        engine = PipelineEngine(workflow, registry, story_dir)

        state = PhaseState(
            story_id="TEST-001",
            phase="verify",
            status=PhaseStatus.PENDING,
        )
        result = engine.run_phase(story_ctx, state)
        assert result.status == "phase_completed"
        assert result.next_phase == "implementation"

        flow = load_flow_execution(story_dir)
        assert flow is not None
        events = load_execution_events(
            story_dir,
            project_key=story_ctx.project_key,
            story_id=story_ctx.story_id,
            run_id=flow.run_id,
        )

        assert [event.event_type for event in events] == [
            EventType.FLOW_START.value,
            EventType.NODE_RESULT.value,
        ]
        assert events[1].payload["outcome"] == "BACKTRACK"
        assert events[1].payload["target_node_id"] == "implementation"
