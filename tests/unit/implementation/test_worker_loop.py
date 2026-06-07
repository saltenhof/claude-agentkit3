"""Unit tests for WorkerLoop (FK-26 §26.3) four-step increment + drift stage 1."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from agentkit.core_types import SpawnReason
from agentkit.implementation.worker_loop import (
    INCREMENT_STEPS,
    IncrementInput,
    IncrementStep,
    WorkerLoop,
)
from agentkit.implementation.worker_session import WorkerSession
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType
from agentkit.telemetry.emitters import MemoryEmitter
from agentkit.telemetry.events import EventType
from agentkit.telemetry.hooks.commit_hook import CommitHook
from agentkit.telemetry.hooks.drift_check_hook import DriftCheckHook

if TYPE_CHECKING:
    from pathlib import Path


class _FakeLoader:
    def load(self, story_id: str, run_id: str) -> StoryContext | None:
        del run_id
        return StoryContext(
            project_key="test-project",
            story_id=story_id,
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
        )


def _session() -> WorkerSession:
    return WorkerSession(
        SpawnReason.INITIAL,
        "AG3-044",
        "run-1",
        context_loader=_FakeLoader(),
    )


def _loop(emitter: MemoryEmitter, project_root: Path) -> WorkerLoop:
    return WorkerLoop(
        DriftCheckHook(emitter, project_root=project_root),
        CommitHook(emitter),
        project_root=project_root,
    )


def test_increment_steps_order() -> None:
    """The four increment steps are ordered per FK-26 §26.3."""
    assert INCREMENT_STEPS == (
        IncrementStep.IMPLEMENT,
        IncrementStep.VERIFY_LOCAL,
        IncrementStep.DRIFT_CHECK,
        IncrementStep.COMMIT,
    )


def test_run_increment_walks_four_steps(tmp_path: Path) -> None:
    """A verifying increment walks all four steps and emits commit telemetry."""
    emitter = MemoryEmitter()
    loop = _loop(emitter, tmp_path)
    result = loop.run_increment(
        _session(),
        IncrementInput(
            index=1,
            description="add adapter",
            commit_sha="abc1234",
            files_changed=2,
            tests_added=("tests/test_adapter.py",),
            verify_passed=True,
        ),
    )
    assert result.steps_completed == INCREMENT_STEPS
    assert result.verify_passed is True
    assert result.summary.commit_sha == "abc1234"
    assert EventType.INCREMENT_COMMIT.value in result.events_emitted
    assert EventType.DRIFT_CHECK.value in result.events_emitted


def test_drift_check_skipped_without_design_artifact(tmp_path: Path) -> None:
    """No exploration design artifact -> drift check skipped (fail-closed marker)."""
    emitter = MemoryEmitter()
    loop = _loop(emitter, tmp_path)
    result = loop.run_increment(
        _session(),
        IncrementInput(index=1, description="x", commit_sha="abc"),
    )
    assert result.drift.skipped is True
    assert result.drift.drift_detected is False
    assert result.drift.reason == "no_design_artifact"


def test_drift_detected_with_design_artifact(tmp_path: Path) -> None:
    """With a design artifact present the worker drift verdict is recorded."""
    design = tmp_path / "_temp" / "qa" / "AG3-044" / "entwurfsartefakt.json"
    design.parent.mkdir(parents=True, exist_ok=True)
    design.write_text(json.dumps({"schema_version": "3.0"}), encoding="utf-8")
    emitter = MemoryEmitter()
    loop = _loop(emitter, tmp_path)
    result = loop.run_increment(
        _session(),
        IncrementInput(
            index=2,
            description="circuit breaker",
            commit_sha="def456",
            drift_detected=True,
            drift_reason="circuit-breaker instead of simple retry",
        ),
    )
    assert result.drift.skipped is False
    assert result.drift.drift_detected is True
    assert result.drift.reason == "circuit-breaker instead of simple retry"


def test_verify_failed_skips_verify_step(tmp_path: Path) -> None:
    """A non-verifying increment does not record the verify_local step."""
    emitter = MemoryEmitter()
    loop = _loop(emitter, tmp_path)
    result = loop.run_increment(
        _session(),
        IncrementInput(
            index=1, description="x", commit_sha="abc", verify_passed=False
        ),
    )
    assert IncrementStep.VERIFY_LOCAL not in result.steps_completed
    assert IncrementStep.COMMIT in result.steps_completed
