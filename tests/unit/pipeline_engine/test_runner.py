"""Unit tests for the high-level pipeline runner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import pytest

from agentkit.exceptions import CorruptStateError
from agentkit.pipeline_engine.engine import EngineResult
from agentkit.pipeline_engine.runner import run_pipeline
from agentkit.process.language.model import FlowDefinition, NodeDefinition
from agentkit.story_context_manager.models import PhaseState, PhaseStatus, StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.pipeline_engine.lifecycle import PhaseHandlerRegistry
    from agentkit.pipeline_engine.phase_envelope.envelope import PhaseEnvelope
    from agentkit.process.language.model import WorkflowDefinition


def _story_context() -> StoryContext:
    return StoryContext(
        project_key="test-project",
        story_id="AG3-123",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        title="Runner Test",
    )


def _workflow(*phases: str) -> WorkflowDefinition:
    return FlowDefinition(
        flow_id="implementation",
        nodes=tuple(NodeDefinition(name=phase) for phase in phases),
    )


@dataclass
class _EngineFactory:
    results: list[EngineResult]

    def __post_init__(self) -> None:
        self.created_with: list[tuple[WorkflowDefinition, object, Path]] = []
        self.run_calls: list[tuple[StoryContext, PhaseEnvelope]] = []

    def __call__(
        self,
        workflow: WorkflowDefinition,
        handler_registry: object,
        story_dir: Path,
    ) -> _EngineFactory:
        self.created_with.append((workflow, handler_registry, story_dir))
        return self

    def run_phase(self, ctx: StoryContext, envelope: PhaseEnvelope) -> EngineResult:
        self.run_calls.append((ctx, envelope))
        return self.results.pop(0)


def test_run_pipeline_resolves_workflow_and_initializes_phase_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _story_context()
    workflow = _workflow("setup")
    saved: list[PhaseState] = []
    engine_factory = _EngineFactory(
        [EngineResult(status="phase_completed", phase="setup", next_phase=None)],
    )

    monkeypatch.setattr(
        "agentkit.pipeline_engine.runner.resolve_workflow",
        lambda story_type: workflow,
    )
    # Patch the repository's load to return None (fresh start)
    monkeypatch.setattr(
        "agentkit.pipeline_engine.runner.StateBackendPhaseEnvelopeRepository",
        lambda story_dir: _make_null_repo(),
    )
    monkeypatch.setattr(
        "agentkit.pipeline_engine.runner.save_phase_state",
        lambda story_dir, state: saved.append(state),
    )
    monkeypatch.setattr("agentkit.pipeline_engine.runner.PipelineEngine", engine_factory)

    result = run_pipeline(ctx, tmp_path, cast("PhaseHandlerRegistry", object()))

    assert result.final_status == "completed"
    assert result.phases_executed == ("setup",)
    assert len(saved) == 1
    assert saved[0].phase == "setup"
    assert saved[0].status is PhaseStatus.PENDING
    assert len(engine_factory.created_with) == 1
    assert engine_factory.created_with[0][0] is workflow
    assert engine_factory.created_with[0][2] == tmp_path


def test_run_pipeline_fails_closed_on_corrupt_phase_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _story_context()

    monkeypatch.setattr(
        "agentkit.pipeline_engine.runner.StateBackendPhaseEnvelopeRepository",
        lambda story_dir: _make_corrupt_repo(),
    )

    result = run_pipeline(ctx, tmp_path, cast("PhaseHandlerRegistry", object()), workflow=_workflow("setup"))

    assert result.final_status == "failed"
    assert result.final_phase == ""
    assert result.phases_executed == ()
    assert "Corrupt phase-state.json" in result.errors[0]


def test_run_pipeline_returns_yielded_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _story_context()
    engine_factory = _EngineFactory(
        [
            EngineResult(
                status="yielded",
                phase="setup",
                yield_status="awaiting_review",
            )
        ],
    )

    monkeypatch.setattr(
        "agentkit.pipeline_engine.runner.StateBackendPhaseEnvelopeRepository",
        lambda story_dir: _make_null_repo(),
    )
    monkeypatch.setattr(
        "agentkit.pipeline_engine.runner.save_phase_state",
        lambda story_dir, state: None,
    )
    monkeypatch.setattr("agentkit.pipeline_engine.runner.PipelineEngine", engine_factory)

    result = run_pipeline(ctx, tmp_path, cast("PhaseHandlerRegistry", object()), workflow=_workflow("setup"))

    assert result.final_status == "yielded"
    assert result.yielded is True
    assert result.yield_status == "awaiting_review"
    assert result.final_phase == "setup"


@pytest.mark.parametrize("status", ["failed", "escalated", "blocked"])
def test_run_pipeline_returns_terminal_engine_statuses(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    status: str,
) -> None:
    ctx = _story_context()
    engine_factory = _EngineFactory(
        [
            EngineResult(
                status=status,
                phase="implementation",
                errors=("terminal error",),
            )
        ],
    )

    monkeypatch.setattr(
        "agentkit.pipeline_engine.runner.StateBackendPhaseEnvelopeRepository",
        lambda story_dir: _make_null_repo(),
    )
    monkeypatch.setattr(
        "agentkit.pipeline_engine.runner.save_phase_state",
        lambda story_dir, state: None,
    )
    monkeypatch.setattr("agentkit.pipeline_engine.runner.PipelineEngine", engine_factory)

    result = run_pipeline(ctx, tmp_path, cast("PhaseHandlerRegistry", object()), workflow=_workflow("implementation"))

    assert result.final_status == status
    assert result.final_phase == "implementation"
    assert result.errors == ("terminal error",)


def test_run_pipeline_advances_and_saves_next_phase(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _story_context()
    saved: list[PhaseState] = []
    engine_factory = _EngineFactory(
        [
            EngineResult(
                status="phase_completed",
                phase="setup",
                next_phase="implementation",
            ),
            EngineResult(
                status="phase_completed",
                phase="implementation",
                next_phase=None,
            ),
        ],
    )

    monkeypatch.setattr(
        "agentkit.pipeline_engine.runner.StateBackendPhaseEnvelopeRepository",
        lambda story_dir: _make_null_repo(),
    )
    monkeypatch.setattr(
        "agentkit.pipeline_engine.runner.save_phase_state",
        lambda story_dir, phase_state: saved.append(phase_state),
    )
    monkeypatch.setattr("agentkit.pipeline_engine.runner.PipelineEngine", engine_factory)

    result = run_pipeline(
        ctx,
        tmp_path,
        cast("PhaseHandlerRegistry", object()),
        workflow=_workflow("setup", "implementation"),
    )

    assert result.final_status == "completed"
    assert result.phases_executed == ("setup", "implementation")
    # First save: initial state for "setup"; second save: state for "implementation"
    implementation_saves = [s for s in saved if s.phase == "implementation"]
    assert len(implementation_saves) == 1
    assert implementation_saves[0].status is PhaseStatus.PENDING


def test_run_pipeline_reloads_persisted_context_between_phases(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _story_context()
    enriched = ctx.model_copy(update={"title": "Enriched", "issue_nr": 42})
    engine_factory = _EngineFactory(
        [
            EngineResult(
                status="phase_completed",
                phase="setup",
                next_phase="implementation",
                updated_context=enriched,
            ),
            EngineResult(
                status="phase_completed",
                phase="implementation",
                next_phase=None,
            ),
        ],
    )

    monkeypatch.setattr(
        "agentkit.pipeline_engine.runner.StateBackendPhaseEnvelopeRepository",
        lambda story_dir: _make_null_repo(),
    )
    monkeypatch.setattr(
        "agentkit.pipeline_engine.runner.save_phase_state",
        lambda story_dir, phase_state: None,
    )
    monkeypatch.setattr("agentkit.pipeline_engine.runner.PipelineEngine", engine_factory)

    result = run_pipeline(
        ctx,
        tmp_path,
        cast("PhaseHandlerRegistry", object()),
        workflow=_workflow("setup", "implementation"),
    )

    assert result.final_status == "completed"
    assert len(engine_factory.run_calls) == 2
    assert engine_factory.run_calls[0][0] == ctx
    assert engine_factory.run_calls[1][0] == enriched


def test_run_pipeline_fails_when_iteration_limit_is_reached(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _story_context()
    engine_factory = _EngineFactory(
        [
            EngineResult(
                status="phase_completed",
                phase="implementation",
                next_phase="implementation",
            )
            for _ in range(20)
        ],
    )

    monkeypatch.setattr(
        "agentkit.pipeline_engine.runner.StateBackendPhaseEnvelopeRepository",
        lambda story_dir: _make_null_repo(),
    )
    monkeypatch.setattr(
        "agentkit.pipeline_engine.runner.save_phase_state",
        lambda story_dir, phase_state: None,
    )
    monkeypatch.setattr("agentkit.pipeline_engine.runner.PipelineEngine", engine_factory)

    result = run_pipeline(
        ctx,
        tmp_path,
        cast("PhaseHandlerRegistry", object()),
        workflow=_workflow("implementation"),
    )

    assert result.final_status == "failed"
    assert result.final_phase == "implementation"
    assert result.errors == ("Max iteration limit reached",)
    assert len(engine_factory.run_calls) == 20


# ---------------------------------------------------------------------------
# Stub helpers for repository patching
# ---------------------------------------------------------------------------


class _NullRepo:
    """Repository stub that always returns None (fresh start)."""

    def load_state(self, story_id: str, phase: object) -> None:
        return None

    def save_state(self, state: PhaseState) -> None:
        pass

    def exists_state(self, story_id: str, phase: object) -> bool:
        return False


class _CorruptRepo:
    """Repository stub that raises CorruptStateError on load."""

    def load_state(self, story_id: str, phase: object) -> None:
        raise CorruptStateError("broken")

    def save_state(self, state: PhaseState) -> None:
        pass

    def exists_state(self, story_id: str, phase: object) -> bool:
        return False


def _make_null_repo() -> _NullRepo:
    return _NullRepo()


def _make_corrupt_repo() -> _CorruptRepo:
    return _CorruptRepo()
