"""Write-ordering tests for PipelineEngine handlers (AG3-025 §2.1.2).

Verifiziert: save_attempt wird VOR save_phase_state aufgerufen (FK-39 §39.4.4).
Nutzt echte Recording-Test-Doubles statt MagicMock (Story §2.1.2.2).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from tests.phase_state_factory import make_phase_state

from agentkit.core_types.attempt import AttemptOutcome, FailureCause
from agentkit.pipeline_engine.engine import PipelineEngine
from agentkit.pipeline_engine.lifecycle import HandlerResult, PhaseHandlerRegistry
from agentkit.pipeline_engine.phase_envelope.store import PhaseEnvelopeStore
from agentkit.pipeline_engine.phase_executor import PhaseState, PhaseStatus
from agentkit.process.language.builder import Workflow
from agentkit.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.state_backend.store import reset_backend_cache_for_tests
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from agentkit.pipeline_engine.phase_executor.records import AttemptRecord


# ---------------------------------------------------------------------------
# Recording Test-Doubles (Story §2.1.2.2 — keine MagicMock)
# ---------------------------------------------------------------------------


class RecordingAttemptRepo:
    """Records all save() calls with their argument, raising optional exception."""

    def __init__(
        self,
        log: list[tuple[str, Any]],
        raise_after: bool = False,
    ) -> None:
        self.log = log
        self.raise_after = raise_after

    def save(self, record: AttemptRecord) -> None:
        self.log.append(("save_attempt", record))
        if self.raise_after:
            raise RuntimeError("Simulated crash between saves")


class RecordingPhaseRepo:
    """Records all save() calls with their argument."""

    def __init__(self, log: list[tuple[str, Any]]) -> None:
        self.log = log

    def save(self, state: PhaseState) -> None:
        self.log.append(("save_phase_state", state))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def sqlite_backend_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


@pytest.fixture()
def story_ctx() -> StoryContext:
    return StoryContext(
        project_key="test-project",
        story_id="WO-001",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        title="Write-Ordering Test",
    )


@pytest.fixture()
def story_dir(tmp_path: Path, story_ctx: StoryContext) -> Path:
    path = tmp_path / "stories" / story_ctx.story_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _make_envelope(state: PhaseState) -> object:
    return PhaseEnvelopeStore.make_fresh_envelope(state)


# ---------------------------------------------------------------------------
# Handler helpers
# ---------------------------------------------------------------------------


class CompletingHandler:
    def on_enter(self, ctx: StoryContext, envelope: object) -> HandlerResult:
        return HandlerResult(status=PhaseStatus.COMPLETED)

    def on_exit(self, ctx: StoryContext, envelope: object) -> None:
        pass

    def on_resume(self, ctx: StoryContext, envelope: object, trigger: str) -> HandlerResult:
        return HandlerResult(status=PhaseStatus.COMPLETED)


class FailingHandler:
    def on_enter(self, ctx: StoryContext, envelope: object) -> HandlerResult:
        return HandlerResult(status=PhaseStatus.FAILED, errors=("handler failed",))

    def on_exit(self, ctx: StoryContext, envelope: object) -> None:
        pass

    def on_resume(self, ctx: StoryContext, envelope: object, trigger: str) -> HandlerResult:
        return HandlerResult(status=PhaseStatus.FAILED, errors=("handler failed",))


class PausingHandler:
    def on_enter(self, ctx: StoryContext, envelope: object) -> HandlerResult:
        return HandlerResult(
            status=PhaseStatus.PAUSED,
            yield_status="awaiting_design_review",
        )

    def on_exit(self, ctx: StoryContext, envelope: object) -> None:
        pass

    def on_resume(self, ctx: StoryContext, envelope: object, trigger: str) -> HandlerResult:
        return HandlerResult(status=PhaseStatus.COMPLETED)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def _instrument_engine(
    engine: PipelineEngine,
    monkeypatch: pytest.MonkeyPatch,
    log: list[tuple[str, Any]],
    crash_on_save_attempt: bool = False,
) -> tuple[RecordingAttemptRepo, RecordingPhaseRepo]:
    """Instrument the engine to record save_attempt and save_phase_state calls.

    Patches the store-module functions directly (the save_phase_completion helper
    imports them at call time, so patching the canonical source is sufficient).
    Also patches the engine module's own imports for any direct calls outside the
    helper.
    """
    attempt_repo = RecordingAttemptRepo(log, raise_after=crash_on_save_attempt)
    phase_repo = RecordingPhaseRepo(log)

    import agentkit.state_backend.store as _store

    def _fake_save_attempt(story_dir: object, record: AttemptRecord) -> None:
        attempt_repo.save(record)

    def _fake_save_phase_state(story_dir: object, state: PhaseState) -> None:
        phase_repo.save(state)

    # Patch the canonical store module (source of truth)
    monkeypatch.setattr(_store, "save_attempt", _fake_save_attempt)
    monkeypatch.setattr(_store, "save_phase_state", _fake_save_phase_state)

    # Patch save_phase_completion module — it holds its own bound references
    # (module-level imports from agentkit.state_backend.store)
    import agentkit.pipeline_engine.phase_executor.save_phase_completion as _spc
    monkeypatch.setattr(_spc, "save_attempt", _fake_save_attempt)
    monkeypatch.setattr(_spc, "save_phase_state", _fake_save_phase_state)

    return attempt_repo, phase_repo


class TestCompletedResultWriteOrdering:
    """AK4: _handle_completed_result schreibt save_attempt VOR save_phase_state."""

    def test_completed_result_save_ordering(
        self,
        story_dir: Path,
        story_ctx: StoryContext,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workflow = Workflow("wo-test").phase("setup").build()
        registry = PhaseHandlerRegistry()
        registry.register("setup", CompletingHandler())
        engine = PipelineEngine(workflow, registry, story_dir)

        log: list[tuple[str, Any]] = []
        _instrument_engine(engine, monkeypatch, log)

        state = make_phase_state(story_id="WO-001", phase="setup", status=PhaseStatus.PENDING)
        result = engine.run_phase(story_ctx, _make_envelope(state))  # type: ignore[arg-type]

        assert result.status == "phase_completed"
        # Extract only the save-ordering calls
        save_calls = [k for k, _ in log if k in ("save_attempt", "save_phase_state")]
        assert len(save_calls) >= 2, "Expected at least save_attempt + save_phase_state"
        # AttemptRecord ZUERST
        first_save_attempt = next(i for i, k in enumerate(save_calls) if k == "save_attempt")
        first_save_phase_state = next(i for i, k in enumerate(save_calls) if k == "save_phase_state")
        assert first_save_attempt < first_save_phase_state, (
            f"save_attempt (idx={first_save_attempt}) must come before "
            f"save_phase_state (idx={first_save_phase_state})"
        )

    def test_completed_attempt_record_has_completed_outcome(
        self,
        story_dir: Path,
        story_ctx: StoryContext,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workflow = Workflow("wo-test2").phase("setup").build()
        registry = PhaseHandlerRegistry()
        registry.register("setup", CompletingHandler())
        engine = PipelineEngine(workflow, registry, story_dir)

        log: list[tuple[str, Any]] = []
        _instrument_engine(engine, monkeypatch, log)

        state = make_phase_state(story_id="WO-001", phase="setup", status=PhaseStatus.PENDING)
        engine.run_phase(story_ctx, _make_envelope(state))  # type: ignore[arg-type]

        attempt_records = [v for k, v in log if k == "save_attempt"]
        assert len(attempt_records) == 1
        assert attempt_records[0].outcome == AttemptOutcome.COMPLETED
        assert attempt_records[0].failure_cause is None


class TestTerminalResultWriteOrdering:
    """AK4: _handle_terminal_result schreibt save_attempt VOR save_phase_state."""

    @pytest.mark.parametrize("outcome_status,expected_outcome,expected_cause", [
        (PhaseStatus.FAILED, AttemptOutcome.FAILED, FailureCause.HANDLER_REPORTED_FAILED),
        (PhaseStatus.ESCALATED, AttemptOutcome.ESCALATED, FailureCause.HANDLER_REPORTED_ESCALATED),
    ])
    def test_terminal_result_save_ordering(
        self,
        story_dir: Path,
        story_ctx: StoryContext,
        monkeypatch: pytest.MonkeyPatch,
        outcome_status: PhaseStatus,
        expected_outcome: AttemptOutcome,
        expected_cause: FailureCause,
    ) -> None:
        class TerminalHandler:
            def on_enter(self, ctx: StoryContext, envelope: object) -> HandlerResult:
                return HandlerResult(status=outcome_status, errors=("terminal",))

            def on_exit(self, ctx: StoryContext, envelope: object) -> None:
                pass

            def on_resume(self, ctx: StoryContext, envelope: object, trigger: str) -> HandlerResult:
                return HandlerResult(status=outcome_status, errors=("terminal",))

        workflow = Workflow("wo-terminal").phase("setup").build()
        registry = PhaseHandlerRegistry()
        registry.register("setup", TerminalHandler())
        engine = PipelineEngine(workflow, registry, story_dir)

        log: list[tuple[str, Any]] = []
        _instrument_engine(engine, monkeypatch, log)

        state = make_phase_state(story_id="WO-001", phase="setup", status=PhaseStatus.PENDING)
        engine.run_phase(story_ctx, _make_envelope(state))  # type: ignore[arg-type]

        save_calls = [k for k, _ in log if k in ("save_attempt", "save_phase_state")]
        first_save_attempt = next(i for i, k in enumerate(save_calls) if k == "save_attempt")
        first_save_phase_state = next(i for i, k in enumerate(save_calls) if k == "save_phase_state")
        assert first_save_attempt < first_save_phase_state

        attempt_records = [v for k, v in log if k == "save_attempt"]
        assert len(attempt_records) >= 1
        assert attempt_records[0].outcome == expected_outcome
        assert attempt_records[0].failure_cause == expected_cause


class TestGuardFailureResultWriteOrdering:
    """AK4: _handle_guard_failure_result schreibt save_attempt VOR save_phase_state."""

    def test_guard_failure_result_save_ordering(
        self,
        story_dir: Path,
        story_ctx: StoryContext,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from agentkit.process.language.guards import GuardResult, guard

        @guard("always_fail", description="Always fails")
        def _always_fail(ctx: StoryContext, state: PhaseState) -> GuardResult:
            return GuardResult.FAIL(reason="Guard always fails")

        workflow = (
            Workflow("wo-guard")
            .phase("setup")
                .guard(_always_fail)
            .build()
        )
        registry = PhaseHandlerRegistry()
        registry.register("setup", CompletingHandler())
        engine = PipelineEngine(workflow, registry, story_dir)

        log: list[tuple[str, Any]] = []
        _instrument_engine(engine, monkeypatch, log)

        state = make_phase_state(story_id="WO-001", phase="setup", status=PhaseStatus.PENDING)
        result = engine.run_phase(story_ctx, _make_envelope(state))  # type: ignore[arg-type]

        assert result.status == "failed"
        save_calls = [k for k, _ in log if k in ("save_attempt", "save_phase_state")]
        first_save_attempt = next(i for i, k in enumerate(save_calls) if k == "save_attempt")
        first_save_phase_state = next(i for i, k in enumerate(save_calls) if k == "save_phase_state")
        assert first_save_attempt < first_save_phase_state

        attempt_records = [v for k, v in log if k == "save_attempt"]
        assert len(attempt_records) >= 1
        assert attempt_records[0].outcome == AttemptOutcome.BLOCKED
        assert attempt_records[0].failure_cause == FailureCause.GUARD_REJECTED


class TestPausedResultWriteOrdering:
    """AK4: _handle_paused_result schreibt save_attempt VOR save_phase_state."""

    def test_paused_result_save_ordering(
        self,
        story_dir: Path,
        story_ctx: StoryContext,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workflow = (
            Workflow("wo-paused")
            .phase("setup")
                .yield_to(
                    "review",
                    on="awaiting_design_review",
                    resume_triggers=["approved"],
                )
            .build()
        )
        registry = PhaseHandlerRegistry()
        registry.register("setup", PausingHandler())
        engine = PipelineEngine(workflow, registry, story_dir)

        log: list[tuple[str, Any]] = []
        _instrument_engine(engine, monkeypatch, log)

        state = make_phase_state(story_id="WO-001", phase="setup", status=PhaseStatus.PENDING)
        result = engine.run_phase(story_ctx, _make_envelope(state))  # type: ignore[arg-type]

        assert result.status == "yielded"
        save_calls = [k for k, _ in log if k in ("save_attempt", "save_phase_state")]
        first_save_attempt = next(i for i, k in enumerate(save_calls) if k == "save_attempt")
        first_save_phase_state = next(i for i, k in enumerate(save_calls) if k == "save_phase_state")
        assert first_save_attempt < first_save_phase_state

        attempt_records = [v for k, v in log if k == "save_attempt"]
        assert len(attempt_records) == 1
        assert attempt_records[0].outcome == AttemptOutcome.YIELDED
        assert attempt_records[0].failure_cause is None


class TestCrashSafetyInvariant:
    """AK5: Crash-Safety — nach Crash zwischen Saves bleibt AttemptRecord erhalten."""

    def test_crash_between_saves_keeps_attempt_record(
        self,
        story_dir: Path,
        story_ctx: StoryContext,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Simulated crash after save_attempt, before save_phase_state."""
        workflow = Workflow("crash-test").phase("setup").build()
        registry = PhaseHandlerRegistry()
        registry.register("setup", CompletingHandler())
        engine = PipelineEngine(workflow, registry, story_dir)

        log: list[tuple[str, Any]] = []
        _instrument_engine(engine, monkeypatch, log, crash_on_save_attempt=True)

        state = make_phase_state(story_id="WO-001", phase="setup", status=PhaseStatus.PENDING)
        with pytest.raises(RuntimeError, match="Simulated crash"):
            engine.run_phase(story_ctx, _make_envelope(state))  # type: ignore[arg-type]

        save_attempt_calls = [k for k, _ in log if k == "save_attempt"]
        save_phase_calls = [k for k, _ in log if k == "save_phase_state"]

        # AttemptRecord-Call ist erfolgt
        assert len(save_attempt_calls) >= 1, "save_attempt must have been called"
        # PhaseState-Call ist NICHT erfolgt (Crash dazwischen)
        assert len(save_phase_calls) == 0, "save_phase_state must NOT have been called after crash"
