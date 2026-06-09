"""Integration test: ExplorationPhaseHandler.on_enter end-to-end (Option Y).

Drives the productive ``build_exploration_phase_handler`` against a real sqlite
backend and the productive ``ArtifactManager`` (so the ENTWURF producer must
really be wired). The AG3-055 worker is stood in for by ``persist_example_change_frame``
which persists the static FK-23 fixture change-frame; the handler then CONSUMES
and VALIDATES it. The positive path pauses awaiting design review with the gate
still PENDING; the negative phase-boundary path (no change-frame) escalates
fail-closed and keeps implementation closed.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from tests.exploration_change_frame_fixture import persist_example_change_frame
from tests.phase_state_factory import make_phase_state

from agentkit.bootstrap.composition_root import (
    build_artifact_manager,
    build_exploration_phase_handler,
)
from agentkit.core_types import ArtifactClass, ExplorationGateStatus
from agentkit.core_types.qa_artifact_names import CHANGE_FRAME_FILE
from agentkit.exploration.register import EXPLORATION_ENTWURF_STAGE
from agentkit.installer.paths import resolve_qa_story_dir
from agentkit.phase_state_store.models import FlowExecution
from agentkit.pipeline_engine.phase_envelope.store import PhaseEnvelopeStore
from agentkit.pipeline_engine.phase_executor import (
    ExplorationPayload,
    PhaseState,
    PhaseStatus,
)
from agentkit.process.language.guards import exploration_gate_approved
from agentkit.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.state_backend.store import (
    reset_backend_cache_for_tests,
    save_flow_execution,
)
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

#: FK-02 §2.3.1: ``run_id`` is a UUID. Pinned stable UUID for the e2e flow.
_RUN_ID = "44444444-4444-4444-8444-444444444444"


@pytest.fixture(autouse=True)
def sqlite_backend_env(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None, None, None]:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


def _story_dir(tmp_path: Path) -> Path:
    story_dir = tmp_path / "stories" / "AG3-045"
    story_dir.mkdir(parents=True, exist_ok=True)
    return story_dir


def _ctx(story_dir: Path) -> StoryContext:
    return StoryContext(
        project_key="test-project",
        story_id="AG3-045",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXPLORATION,
        title="Exploration phase handler",
        project_root=story_dir.parent.parent,
    )


def _bind_flow(story_dir: Path) -> None:
    save_flow_execution(
        story_dir,
        FlowExecution(
            project_key="test-project",
            story_id="AG3-045",
            run_id=_RUN_ID,
            flow_id="exploration",
            level="story",
            owner="pipeline_engine",
            status="IN_PROGRESS",
        ),
    )


def _state() -> PhaseState:
    return make_phase_state(
        story_id="AG3-045",
        phase="exploration",
        status=PhaseStatus.IN_PROGRESS,
        payload=ExplorationPayload(),
    )


def test_on_enter_validates_persisted_change_frame(tmp_path: Path) -> None:
    story_dir = _story_dir(tmp_path)
    _bind_flow(story_dir)
    manager = build_artifact_manager(story_dir)
    # The worker analogue writes BOTH the ENTWURF envelope AND the materialized
    # change_frame.json file (FK-23 §23.4.3 / AG3-045 AC7).
    persist_example_change_frame(manager, story_dir=story_dir, run_id=_RUN_ID)
    envelope = manager.read_latest(
        story_id="AG3-045",
        run_id=_RUN_ID,
        artifact_class=ArtifactClass.ENTWURF,
        stage=EXPLORATION_ENTWURF_STAGE,
    )
    assert envelope.artifact_class is ArtifactClass.ENTWURF
    assert envelope.producer.name == "exploration-worker"

    # AC7 / FK-23 §23.4.3: the protected change_frame.json file is REALLY on disk
    # (the protected path guards a file that actually exists, not a phantom).
    change_frame_file = (
        resolve_qa_story_dir(story_dir, story_id="AG3-045") / CHANGE_FRAME_FILE
    )
    assert change_frame_file.is_file()
    on_disk = json.loads(change_frame_file.read_text(encoding="utf-8"))
    assert on_disk["story_id"] == "AG3-045"
    assert on_disk["run_id"] == _RUN_ID

    ctx = _ctx(story_dir)
    # Default handler wires review=None (the per-run review is injected by
    # AG3-054). With a valid change-frame but no gate to run, the handler fails
    # closed -- it NEVER auto-APPROVEs. The gate-driven outcomes (APPROVED /
    # escalation / REJECTED) are covered in tests/integration/pipeline/exploration.
    handler = build_exploration_phase_handler(story_dir)
    result = handler.on_enter(ctx, PhaseEnvelopeStore.make_fresh_envelope(_state()))

    assert result.status is PhaseStatus.FAILED
    assert exploration_gate_approved(ctx, result.updated_state).passed is False


def test_on_enter_without_change_frame_emits_worker_spawn(tmp_path: Path) -> None:
    """No change-frame + no worker draft -> AG3-055 spawn-and-await, gate closed.

    The productive handler drives the AG3-055 produce->consume loop: with no
    worker draft present it EMITS a typed exploration-worker ``SpawnRequest`` and
    returns ``IN_PROGRESS`` (not a dead-end ESCALATED). The gate stays denied.
    """
    from agentkit.core_types import SpawnKind

    story_dir = _story_dir(tmp_path)
    _bind_flow(story_dir)
    ctx = _ctx(story_dir)

    handler = build_exploration_phase_handler(story_dir)
    result = handler.on_enter(ctx, PhaseEnvelopeStore.make_fresh_envelope(_state()))

    assert result.status is PhaseStatus.IN_PROGRESS
    assert result.updated_state is not None
    assert [o.kind for o in result.updated_state.agents_to_spawn] == [
        SpawnKind.WORKER
    ]
    assert exploration_gate_approved(ctx, result.updated_state).passed is False


def test_negative_gate_keeps_implementation_closed(tmp_path: Path) -> None:
    """A COMPLETED exploration phase whose gate is not APPROVED stays closed."""
    ctx = _ctx(_story_dir(tmp_path))
    not_approved = make_phase_state(
        story_id="AG3-045",
        phase="exploration",
        status=PhaseStatus.COMPLETED,
        payload=ExplorationPayload(gate_status=ExplorationGateStatus.REJECTED),
    )
    assert exploration_gate_approved(ctx, not_approved).passed is False
