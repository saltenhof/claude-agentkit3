"""Unit tests for the high-level pipeline runner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from agentkit.exceptions import CorruptStateError
from agentkit.pipeline.engine import EngineResult
from agentkit.pipeline.runner import run_pipeline
from agentkit.process.language.model import FlowDefinition, NodeDefinition
from agentkit.story_context_manager.models import PhaseState, PhaseStatus, StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from pathlib import Path

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
        self.run_calls: list[tuple[StoryContext, PhaseState]] = []

    def __call__(
        self,
        workflow: WorkflowDefinition,
        handler_registry: object,
        story_dir: Path,
    ) -> _EngineFactory:
        self.created_with.append((workflow, handler_registry, story_dir))
        return self

    def run_phase(self, ctx: StoryContext, state: PhaseState) -> EngineResult:
        self.run_calls.append((ctx, state))
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
        "agentkit.pipeline.runner.resolve_workflow",
        lambda story_type: workflow,
    )
    monkeypatch.setattr(
        "agentkit.pipeline.runner.read_phase_state_record",
        lambda story_dir: None,
    )
    monkeypatch.setattr(
        "agentkit.pipeline.runner.save_phase_state",
        lambda story_dir, state: saved.append(state),
    )
    monkeypatch.setattr("agentkit.pipeline.runner.PipelineEngine", engine_factory)

    result = run_pipeline(ctx, tmp_path, object())

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
        "agentkit.pipeline.runner.read_phase_state_record",
        lambda story_dir: (_ for _ in ()).throw(CorruptStateError("broken")),
    )

    result = run_pipeline(ctx, tmp_path, object(), workflow=_workflow("setup"))

    assert result.final_status == "failed"
    assert result.final_phase == ""
    assert result.phases_executed == ()
    assert "Corrupt phase-state.json" in result.errors[0]


def test_run_pipeline_returns_yielded_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _story_context()
    state = PhaseState(
        story_id=ctx.story_id,
        phase="setup",
        status=PhaseStatus.PENDING,
    )
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
        "agentkit.pipeline.runner.read_phase_state_record",
        lambda story_dir: state,
    )
    monkeypatch.setattr("agentkit.pipeline.runner.PipelineEngine", engine_factory)

    result = run_pipeline(ctx, tmp_path, object(), workflow=_workflow("setup"))

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
    state = PhaseState(
        story_id=ctx.story_id,
        phase="verify",
        status=PhaseStatus.PENDING,
    )
    engine_factory = _EngineFactory(
        [
            EngineResult(
                status=status,
                phase="verify",
                errors=("terminal error",),
            )
        ],
    )

    monkeypatch.setattr(
        "agentkit.pipeline.runner.read_phase_state_record",
        lambda story_dir: state,
    )
    monkeypatch.setattr("agentkit.pipeline.runner.PipelineEngine", engine_factory)

    result = run_pipeline(ctx, tmp_path, object(), workflow=_workflow("verify"))

    assert result.final_status == status
    assert result.final_phase == "verify"
    assert result.errors == ("terminal error",)


def test_run_pipeline_advances_and_saves_next_phase(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _story_context()
    state = PhaseState(
        story_id=ctx.story_id,
        phase="setup",
        status=PhaseStatus.PENDING,
    )
    saved: list[PhaseState] = []
    engine_factory = _EngineFactory(
        [
            EngineResult(
                status="phase_completed",
                phase="setup",
                next_phase="verify",
            ),
            EngineResult(
                status="phase_completed",
                phase="verify",
                next_phase=None,
            ),
        ],
    )

    monkeypatch.setattr(
        "agentkit.pipeline.runner.read_phase_state_record",
        lambda story_dir: state,
    )
    monkeypatch.setattr(
        "agentkit.pipeline.runner.save_phase_state",
        lambda story_dir, phase_state: saved.append(phase_state),
    )
    monkeypatch.setattr("agentkit.pipeline.runner.PipelineEngine", engine_factory)

    result = run_pipeline(
        ctx,
        tmp_path,
        object(),
        workflow=_workflow("setup", "verify"),
    )

    assert result.final_status == "completed"
    assert result.phases_executed == ("setup", "verify")
    assert [phase_state.phase for phase_state in saved] == ["verify"]
    assert saved[0].status is PhaseStatus.PENDING


def test_run_pipeline_reloads_persisted_context_between_phases(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ctx = _story_context()
    enriched = ctx.model_copy(update={"title": "Enriched", "issue_nr": 42})
    state = PhaseState(
        story_id=ctx.story_id,
        phase="setup",
        status=PhaseStatus.PENDING,
    )
    engine_factory = _EngineFactory(
        [
            EngineResult(
                status="phase_completed",
                phase="setup",
                next_phase="verify",
                updated_context=enriched,
            ),
            EngineResult(
                status="phase_completed",
                phase="verify",
                next_phase=None,
            ),
        ],
    )

    monkeypatch.setattr(
        "agentkit.pipeline.runner.read_phase_state_record",
        lambda story_dir: state,
    )
    monkeypatch.setattr(
        "agentkit.pipeline.runner.save_phase_state",
        lambda story_dir, phase_state: None,
    )
    monkeypatch.setattr("agentkit.pipeline.runner.PipelineEngine", engine_factory)

    result = run_pipeline(
        ctx,
        tmp_path,
        object(),
        workflow=_workflow("setup", "verify"),
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
    state = PhaseState(
        story_id=ctx.story_id,
        phase="loop",
        status=PhaseStatus.PENDING,
    )
    engine_factory = _EngineFactory(
        [
            EngineResult(
                status="phase_completed",
                phase="loop",
                next_phase="loop",
            )
            for _ in range(20)
        ],
    )

    monkeypatch.setattr(
        "agentkit.pipeline.runner.read_phase_state_record",
        lambda story_dir: state,
    )
    monkeypatch.setattr(
        "agentkit.pipeline.runner.save_phase_state",
        lambda story_dir, phase_state: None,
    )
    monkeypatch.setattr("agentkit.pipeline.runner.PipelineEngine", engine_factory)

    result = run_pipeline(ctx, tmp_path, object(), workflow=_workflow("loop"))

    assert result.final_status == "failed"
    assert result.final_phase == "loop"
    assert result.errors == ("Max iteration limit reached",)
    assert len(engine_factory.run_calls) == 20
