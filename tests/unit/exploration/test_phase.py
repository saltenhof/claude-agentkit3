"""Unit tests for ExplorationPhaseHandler (AC1/AC7; Option Y consume/validate).

Option Y (PO 2026-06-05): the handler CONSUMES / VALIDATES a worker-produced
change-frame (AG3-055); it never fabricates one. AG3-046 replaced the AG3-045
provisional "pause awaiting review" branch with the three-stage
``ExplorationReview`` exit-gate. Covered here (the gate-driven outcomes live in
``tests/integration/pipeline/exploration``; these cover the plumbing edges):

* a valid persisted change-frame but NO review wired -> fail-closed ``FAILED``
  (never auto-APPROVE; the gate guard still denies);
* no change-frame -> fail-closed ESCALATED (the gate guard denies);
* unconfigured ``story_dir`` -> FAILED;
* no bound ``FlowExecution`` -> ``CorruptStateError`` (via the adapter).

The machinery is exercised against the static FK-23 fixture
(``persist_example_change_frame``), not a deterministic producer or a fake approve.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from tests.exploration_change_frame_fixture import (
    example_change_frame,
    persist_example_change_frame,
)
from tests.phase_state_factory import make_phase_state

from agentkit.backend.artifacts import (
    ArtifactEnvelope,
    EnvelopeStatus,
    Producer,
    ProducerId,
    ProducerType,
)
from agentkit.backend.bootstrap.composition_root import (
    build_artifact_manager,
    build_exploration_phase_handler,
)
from agentkit.backend.core_types import ArtifactClass, ExplorationGateStatus
from agentkit.backend.core_types.qa_artifact_names import CHANGE_FRAME_FILE
from agentkit.backend.exceptions import CorruptStateError
from agentkit.backend.exploration.phase import ExplorationConfig, ExplorationPhaseHandler
from agentkit.backend.exploration.register import (
    EXPLORATION_ENTWURF_PRODUCER,
    EXPLORATION_ENTWURF_STAGE,
)
from agentkit.backend.installer.paths import resolve_qa_story_dir
from agentkit.backend.phase_state_store.models import FlowExecution
from agentkit.backend.pipeline_engine.lifecycle import PhaseHandler
from agentkit.backend.pipeline_engine.phase_envelope.store import PhaseEnvelopeStore
from agentkit.backend.pipeline_engine.phase_executor import (
    ExplorationPayload,
    PhaseState,
    PhaseStatus,
)
from agentkit.backend.process.language.guards import exploration_gate_approved
from agentkit.backend.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.backend.state_backend.persistence_test_support import reset_backend_cache_for_tests
from agentkit.backend.state_backend.store import (
    save_flow_execution,
)
from agentkit.backend.state_backend.store.exploration_change_frame_repository import (
    StateBackendExplorationChangeFrameAdapter,
)
from agentkit.backend.story_context_manager.models import (
    StoryContext as _StoryContext,
)
from agentkit.backend.story_context_manager.types import StoryMode, StoryType

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from agentkit.backend.pipeline_engine.phase_envelope.envelope import PhaseEnvelope

#: FK-02 §2.3.1: ``run_id`` is a UUID. Pinned stable UUIDs for the tests.
_RUN_ID = "22222222-2222-4222-8222-222222222222"
_FOREIGN_RUN_ID = "33333333-3333-4333-8333-333333333333"


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
    # The sqlite flow-execution lookup keys ``flow_executions.story_id`` on the
    # story dir NAME, so the dir must be ``<project_root>/stories/<story_id>``.
    story_dir = tmp_path / "stories" / "AG3-045"
    story_dir.mkdir(parents=True, exist_ok=True)
    return story_dir


def _ctx(story_dir: Path) -> _StoryContext:
    return _StoryContext(
        project_key="test-project",
        story_id="AG3-045",
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXPLORATION,
        title="Exploration phase handler",
        project_root=story_dir.parent.parent,
    )


def _bind_flow(story_dir: Path, run_id: str = _RUN_ID) -> None:
    save_flow_execution(
        story_dir,
        FlowExecution(
            project_key="test-project",
            story_id="AG3-045",
            run_id=run_id,
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


def _envelope() -> PhaseEnvelope:
    return PhaseEnvelopeStore.make_fresh_envelope(_state())


def test_handler_satisfies_protocol(tmp_path: Path) -> None:
    assert isinstance(
        build_exploration_phase_handler(_story_dir(tmp_path)), PhaseHandler
    )


def test_on_enter_valid_frame_without_review_fails_closed(
    tmp_path: Path,
) -> None:
    """AC7: provisional gone. A valid frame but no review wired -> FAILED.

    The default ``build_exploration_phase_handler`` wires ``review=None`` (the
    per-run review is injected by AG3-054). With a valid change-frame but no gate
    to run, the handler fails closed -- it NEVER auto-APPROVEs (NO ERROR
    BYPASSING). The gate-driven outcomes are covered in the integration tests.
    """
    sd = _story_dir(tmp_path)
    _bind_flow(sd)
    # The AG3-055 worker analogue persists the FK-23 fixture change-frame.
    persist_example_change_frame(
        build_artifact_manager(sd), story_dir=sd, run_id=_RUN_ID
    )

    result = build_exploration_phase_handler(sd).on_enter(_ctx(sd), _envelope())

    assert result.status is PhaseStatus.FAILED
    payload = result.updated_state.payload
    assert isinstance(payload, ExplorationPayload)
    # No fake APPROVED -- the gate stays PENDING.
    assert payload.gate_status is ExplorationGateStatus.PENDING


def test_valid_change_frame_does_not_release_the_gate(tmp_path: Path) -> None:
    """A valid change-frame is NOT enough to enter implementation (no fake-APPROVE)."""
    sd = _story_dir(tmp_path)
    _bind_flow(sd)
    persist_example_change_frame(
        build_artifact_manager(sd), story_dir=sd, run_id=_RUN_ID
    )
    ctx = _ctx(sd)

    result = build_exploration_phase_handler(sd).on_enter(ctx, _envelope())

    assert exploration_gate_approved(ctx, result.updated_state).passed is False


def test_on_enter_no_frame_no_draft_emits_worker_spawn(
    tmp_path: Path,
) -> None:
    """AG3-055 loop: no change-frame and no worker draft -> emit a typed spawn.

    The productive handler wires the drafting + draft-presence ports, so the
    no-change-frame case is no longer a dead-end ESCALATED: with no worker draft
    present yet, the handler EMITS a typed ``SpawnRequest`` (WORKER / INITIAL)
    into ``agents_to_spawn`` and returns ``IN_PROGRESS`` (spawn-and-await), the
    AG3-044/054 engine re-entry mechanism. The gate stays denied (no fake APPROVE).
    """
    from agentkit.backend.core_types import SpawnKind, SpawnReason

    sd = _story_dir(tmp_path)
    _bind_flow(sd)
    ctx = _ctx(sd)

    result = build_exploration_phase_handler(sd).on_enter(ctx, _envelope())

    assert result.status is PhaseStatus.IN_PROGRESS
    state = result.updated_state
    assert state is not None
    assert len(state.agents_to_spawn) == 1
    order = state.agents_to_spawn[0]
    assert order.kind is SpawnKind.WORKER
    assert order.spawn_reason is SpawnReason.INITIAL
    assert order.target_id == "AG3-045"
    payload = state.payload
    assert isinstance(payload, ExplorationPayload)
    assert payload.gate_status is ExplorationGateStatus.PENDING
    assert exploration_gate_approved(ctx, state).passed is False


def test_on_enter_without_drafting_wired_escalates_fail_closed(
    tmp_path: Path,
) -> None:
    """Legacy plumbing-only construction (no drafting/presence) -> ESCALATED.

    When neither the drafting core nor the draft-presence port is wired the
    no-change-frame branch keeps the original fail-closed ESCALATED with the
    AG3-055 message (no pseudo-draft, no silent pass).
    """
    sd = _story_dir(tmp_path)
    _bind_flow(sd)
    ctx = _ctx(sd)
    adapter = StateBackendExplorationChangeFrameAdapter(build_artifact_manager(sd))
    handler = ExplorationPhaseHandler(
        change_frame_reader=adapter,
        run_scope_resolver=adapter,
        config=ExplorationConfig(story_dir=sd),
    )

    result = handler.on_enter(ctx, _envelope())

    assert result.status is PhaseStatus.ESCALATED
    assert any("AG3-055" in e for e in result.errors)
    payload = result.updated_state.payload
    assert isinstance(payload, ExplorationPayload)
    assert payload.gate_status is ExplorationGateStatus.PENDING
    # Fail-closed: the gate stays denied.
    assert exploration_gate_approved(ctx, result.updated_state).passed is False


def test_on_enter_fail_closed_without_story_dir(tmp_path: Path) -> None:
    sd = _story_dir(tmp_path)
    adapter = StateBackendExplorationChangeFrameAdapter(build_artifact_manager(sd))
    handler = ExplorationPhaseHandler(
        change_frame_reader=adapter,
        run_scope_resolver=adapter,
        config=ExplorationConfig(story_dir=None),
    )
    result = handler.on_enter(_ctx(sd), _envelope())
    assert result.status is PhaseStatus.FAILED
    assert any("story_dir" in e for e in result.errors)


def test_on_enter_fail_closed_without_flow_execution(tmp_path: Path) -> None:
    # Story dir exists but no flow execution bound -> no run_id -> fail closed.
    sd = _story_dir(tmp_path)
    with pytest.raises(CorruptStateError):
        build_exploration_phase_handler(sd).on_enter(_ctx(sd), _envelope())


def test_adapter_rejects_foreign_inner_frame_fail_closed(tmp_path: Path) -> None:
    """A corrupt envelope wrapping a FOREIGN inner frame is rejected (FIX #2).

    The envelope is addressed by the (story_id, run_id) scope, but the inner
    change-frame carries a DIFFERENT story_id/run_id. The adapter must not
    accept it as this scope's artifact -- fail-closed CorruptStateError.
    """
    sd = _story_dir(tmp_path)
    _bind_flow(sd)
    manager = build_artifact_manager(sd)
    ts = datetime(2026, 6, 5, 10, 30, tzinfo=UTC)
    # Inner frame stamped with a DIFFERENT identity than the envelope scope.
    foreign = example_change_frame(story_id="AG3-099", run_id=_FOREIGN_RUN_ID)
    manager.write(
        ArtifactEnvelope(
            schema_version="3.0",
            story_id="AG3-045",
            run_id=_RUN_ID,
            stage=EXPLORATION_ENTWURF_STAGE,
            attempt=1,
            producer=Producer(
                type=ProducerType.WORKER,
                name=EXPLORATION_ENTWURF_PRODUCER,
                id=ProducerId(f"{EXPLORATION_ENTWURF_PRODUCER}-{_RUN_ID}"),
            ),
            started_at=ts,
            finished_at=ts,
            status=EnvelopeStatus.PASS,
            artifact_class=ArtifactClass.ENTWURF,
            payload=foreign.model_dump(mode="json"),
        )
    )
    adapter = StateBackendExplorationChangeFrameAdapter(manager)
    with pytest.raises(CorruptStateError):
        adapter.load_change_frame(story_id="AG3-045", run_id=_RUN_ID)


def test_writer_rejects_foreign_inner_frame_fail_closed(tmp_path: Path) -> None:
    """The WRITER refuses a frame whose identity differs from the write scope.

    The write-path mirror of ``test_adapter_rejects_foreign_inner_frame...``:
    a frame stamped with a foreign story_id/run_id must never be materialized
    under this scope's protected path. The write fails closed and NO file is
    written (FIX #3).
    """
    sd = _story_dir(tmp_path)
    manager = build_artifact_manager(sd)
    adapter = StateBackendExplorationChangeFrameAdapter(manager)
    foreign = example_change_frame(story_id="AG3-099", run_id=_FOREIGN_RUN_ID)

    with pytest.raises(CorruptStateError):
        adapter.write_change_frame_file(
            sd, story_id="AG3-045", run_id=_RUN_ID, frame=foreign
        )

    # Fail-closed: no change_frame.json was materialized under the write scope.
    target = resolve_qa_story_dir(sd, story_id="AG3-045") / CHANGE_FRAME_FILE
    assert not target.exists()


def test_on_resume_revalidates(tmp_path: Path) -> None:
    sd = _story_dir(tmp_path)
    _bind_flow(sd)
    persist_example_change_frame(
        build_artifact_manager(sd), story_dir=sd, run_id=_RUN_ID
    )
    # on_resume re-runs on_enter idempotently; with review=None it fails closed.
    result = build_exploration_phase_handler(sd).on_resume(
        _ctx(sd), _envelope(), "resume-trigger"
    )
    assert result.status is PhaseStatus.FAILED
    payload = result.updated_state.payload
    assert isinstance(payload, ExplorationPayload)
    assert payload.gate_status is ExplorationGateStatus.PENDING
