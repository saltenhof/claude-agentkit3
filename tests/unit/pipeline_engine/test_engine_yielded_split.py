"""Tests for YIELDED/PauseReason-Trennung (AG3-025 §2.1.4).

Verifiziert:
1. AttemptRecord traegt outcome=YIELDED, failure_cause=None.
2. paused_reason lebt NUR in PhaseEnvelope.state.paused_reason.
3. AttemptRecord.detail enthaelt KEIN paused_reason, KEIN pause_reason,
   KEIN yield_status.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from agentkit.core_types import PauseReason
from agentkit.core_types.attempt import AttemptOutcome
from agentkit.pipeline_engine.engine import PipelineEngine
from agentkit.pipeline_engine.lifecycle import HandlerResult, PhaseHandlerRegistry
from agentkit.pipeline_engine.phase_envelope.store import PhaseEnvelopeStore
from agentkit.process.language.builder import Workflow
from agentkit.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.state_backend.store import reset_backend_cache_for_tests
from agentkit.story_context_manager.models import PhaseState, PhaseStatus, StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from agentkit.pipeline_engine.phase_executor.records import AttemptRecord


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
        story_id="YS-001",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        title="Yielded Split Test",
    )


@pytest.fixture()
def story_dir(tmp_path: Path, story_ctx: StoryContext) -> Path:
    path = tmp_path / "stories" / story_ctx.story_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _make_envelope(state: PhaseState) -> object:
    return PhaseEnvelopeStore.make_fresh_envelope(state)


def _run_paused_phase(
    story_dir: Path,
    story_ctx: StoryContext,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[tuple[str, Any]], list[tuple[str, Any]]]:
    """Run a phase that pauses and collect recorded calls."""
    workflow = (
        Workflow("yield-split")
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

    attempt_calls: list[tuple[str, Any]] = []
    phase_state_calls: list[tuple[str, Any]] = []

    import agentkit.state_backend.store as _store

    def _fake_save_attempt(story_dir: object, record: AttemptRecord) -> None:
        attempt_calls.append(("save_attempt", record))

    def _fake_save_phase_state(story_dir: object, state: PhaseState) -> None:
        phase_state_calls.append(("save_phase_state", state))

    monkeypatch.setattr(_store, "save_attempt", _fake_save_attempt)
    monkeypatch.setattr(_store, "save_phase_state", _fake_save_phase_state)
    import agentkit.pipeline_engine.phase_executor.save_phase_completion as _spc
    monkeypatch.setattr(_spc, "save_attempt", _fake_save_attempt)
    monkeypatch.setattr(_spc, "save_phase_state", _fake_save_phase_state)

    state = PhaseState(story_id="YS-001", phase="setup", status=PhaseStatus.PENDING)
    result = engine.run_phase(story_ctx, _make_envelope(state))  # type: ignore[arg-type]
    assert result.status == "yielded", f"Expected 'yielded', got {result.status!r}"

    return attempt_calls, phase_state_calls


class TestYieldedSplit:
    """AK8: outcome=YIELDED korrekt belegt; keine Doppelpflege."""

    def test_attempt_record_has_yielded_outcome(
        self,
        story_dir: Path,
        story_ctx: StoryContext,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        attempt_calls, _ = _run_paused_phase(story_dir, story_ctx, monkeypatch)

        assert len(attempt_calls) == 1
        record: AttemptRecord = attempt_calls[0][1]
        assert record.outcome == AttemptOutcome.YIELDED

    def test_attempt_record_has_no_failure_cause(
        self,
        story_dir: Path,
        story_ctx: StoryContext,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """YIELDED ist kein Failure; failure_cause muss None sein."""
        attempt_calls, _ = _run_paused_phase(story_dir, story_ctx, monkeypatch)

        record: AttemptRecord = attempt_calls[0][1]
        assert record.failure_cause is None

    def test_attempt_record_detail_has_no_paused_reason(
        self,
        story_dir: Path,
        story_ctx: StoryContext,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AG3-025 §2.1.4: kein paused_reason/pause_reason/yield_status in detail."""
        attempt_calls, _ = _run_paused_phase(story_dir, story_ctx, monkeypatch)

        record: AttemptRecord = attempt_calls[0][1]
        detail = record.detail or {}
        assert "paused_reason" not in detail, (
            f"detail must not contain 'paused_reason'; got {detail!r}"
        )
        assert "pause_reason" not in detail, (
            f"detail must not contain 'pause_reason'; got {detail!r}"
        )
        assert "yield_status" not in detail, (
            f"detail must not contain 'yield_status'; got {detail!r}"
        )

    def test_phase_state_has_paused_reason(
        self,
        story_dir: Path,
        story_ctx: StoryContext,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """paused_reason lebt NUR in PhaseState (AG3-024 Owner)."""
        _, phase_state_calls = _run_paused_phase(story_dir, story_ctx, monkeypatch)

        assert len(phase_state_calls) == 1
        persisted_state: PhaseState = phase_state_calls[0][1]
        assert persisted_state.paused_reason == PauseReason.AWAITING_DESIGN_REVIEW

    def test_write_ordering_attempt_before_state(
        self,
        story_dir: Path,
        story_ctx: StoryContext,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """FK-39 §39.4.4: save_attempt VOR save_phase_state auch bei PAUSED."""
        all_calls: list[tuple[str, Any]] = []

        workflow = (
            Workflow("yield-split-order")
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

        import agentkit.state_backend.store as _store2

        def _fake_save_attempt(story_dir: object, record: AttemptRecord) -> None:
            all_calls.append(("save_attempt", record))

        def _fake_save_phase_state(story_dir: object, state: PhaseState) -> None:
            all_calls.append(("save_phase_state", state))

        monkeypatch.setattr(_store2, "save_attempt", _fake_save_attempt)
        monkeypatch.setattr(_store2, "save_phase_state", _fake_save_phase_state)
        import agentkit.pipeline_engine.phase_executor.save_phase_completion as _spc2
        monkeypatch.setattr(_spc2, "save_attempt", _fake_save_attempt)
        monkeypatch.setattr(_spc2, "save_phase_state", _fake_save_phase_state)

        state = PhaseState(story_id="YS-001", phase="setup", status=PhaseStatus.PENDING)
        engine.run_phase(story_ctx, _make_envelope(state))  # type: ignore[arg-type]

        save_keys = [k for k, _ in all_calls if k in ("save_attempt", "save_phase_state")]
        idx_attempt = next(i for i, k in enumerate(save_keys) if k == "save_attempt")
        idx_state = next(i for i, k in enumerate(save_keys) if k == "save_phase_state")
        assert idx_attempt < idx_state
