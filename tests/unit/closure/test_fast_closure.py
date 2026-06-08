"""Fast-mode closure tests (AG3-018, FK-29 §29.1a.6 / FK-24 §24.3.4).

Covers the closure-side fast behaviour wired by AG3-018:

* fast closure routes through the Sanity-Gate (not the 9-dim block) and reaches
  MERGED (AC3 smoke, closure leg);
* a fast Sanity-Gate failure (e.g. a rebase conflict) ESCALATES (AC4);
* the project mode-lock is released at close (DELTA-E) once, idempotently (a
  resumed closure does not double-release).

Stubs only at the external boundaries (sanity runner, git, mode-lock release
port) -- the real ``ClosureProgress`` model + merge saga over a stub git backend
drive the orchestration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from tests.phase_state_factory import make_phase_state
from tests.unit.closure.closure_fakes import (
    NoOpStoryService,
    RecordingBuildTestPort,
    RecordingDocFidelityPort,
    RecordingGuardDeactivationPort,
    RecordingIntegrityGate,
    RecordingSanityPort,
    RecordingScanPort,
    RecordingVectorDbSyncPort,
    StubGitBackend,
    build_progress_store,
)

from agentkit.bootstrap.composition_root import build_artifact_manager
from agentkit.closure.phase import ClosureConfig, ClosurePhaseHandler
from agentkit.phase_state_store.models import FlowExecution
from agentkit.pipeline_engine.phase_executor import (
    ClosurePayload,
    ClosureProgress,
    PhaseSnapshot,
    PhaseState,
    PhaseStatus,
)
from agentkit.state_backend.store import (
    append_execution_event,
    save_flow_execution,
    save_phase_snapshot,
)
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.story_model import WireStoryMode
from agentkit.story_context_manager.types import StoryMode, StoryType
from agentkit.telemetry.contract.records import ExecutionEventRecord
from agentkit.telemetry.events import EventType

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _sqlite_backend(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    from agentkit.state_backend.store import reset_backend_cache_for_tests

    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    monkeypatch.delenv("AGENTKIT_STATE_DATABASE_URL", raising=False)
    reset_backend_cache_for_tests()
    yield
    reset_backend_cache_for_tests()


@dataclass
class _RecordingModeLockReleasePort:
    """Stub mode-lock release seam that models the marker idempotency (FIX-4).

    Mirrors :class:`ProductiveModeLockReleasePort`: the durable per-story acquire
    marker is the SOLE idempotency truth (no seventh ``ClosureProgress``
    checkpoint). The stub records a release only when the marker is present, then
    clears it -- so a resumed closure (marker already cleared) does NOT
    double-release.
    """

    released: bool = True
    warning: str | None = None
    calls: list[tuple[str, str]] = field(default_factory=list)

    def release(self, story_dir: Path, project_key: str) -> tuple[bool, str | None]:
        from agentkit.governance.setup_preflight_gate.mode_lock_marker import (
            acquired_mode,
            clear_mode_lock_marker,
        )

        if acquired_mode(story_dir) is None:
            # No marker -> no release owed (idempotent no-op; resume safety).
            return (True, None)
        self.calls.append((str(story_dir), project_key))
        clear_mode_lock_marker(story_dir)
        return (self.released, self.warning)


def _fast_ctx(story_id: str = "FAST-001", project_root: Path | None = None) -> StoryContext:
    return StoryContext(
        project_key="proj",
        story_id=story_id,
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        mode=WireStoryMode.FAST,
        project_root=project_root,
    )


def _state(
    story_id: str = "FAST-001", progress: ClosureProgress | None = None
) -> PhaseState:
    return make_phase_state(
        story_id=story_id,
        phase="closure",
        status=PhaseStatus.IN_PROGRESS,
        payload=ClosurePayload(progress=progress or ClosureProgress()),
    )


def _prepare(tmp_path: Path, story_id: str = "FAST-001") -> Path:
    s_dir = tmp_path / "stories" / story_id
    s_dir.mkdir(parents=True)
    # Fast impl story: prior phases are setup + implementation (NO exploration).
    for phase in ("setup", "implementation"):
        save_phase_snapshot(
            s_dir,
            PhaseSnapshot(
                story_id=story_id,
                phase=phase,
                status=PhaseStatus.COMPLETED,
                completed_at=datetime.now(tz=UTC),
                artifacts=[],
                evidence={},
            ),
        )
    save_flow_execution(
        s_dir,
        FlowExecution(
            project_key="proj",
            story_id=story_id,
            run_id=f"run-{story_id.lower()}",
            flow_id="implementation",
            level="story",
            owner="pipeline_engine",
            status="COMPLETED",
            started_at=datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC),
        ),
    )
    append_execution_event(
        s_dir,
        ExecutionEventRecord(
            project_key="proj",
            story_id=story_id,
            run_id=f"run-{story_id.lower()}",
            event_id=f"evt-start-{story_id.lower()}",
            event_type=EventType.AGENT_START.value,
            occurred_at=datetime(2026, 1, 1, 9, 45, 0, tzinfo=UTC),
            source_component="test",
            severity="info",
            payload={},
        ),
    )
    return s_dir


def _fast_config(
    s_dir: Path,
    *,
    sanity: RecordingSanityPort | None = None,
    release_port: _RecordingModeLockReleasePort | None = None,
    git_backend: StubGitBackend | None = None,
) -> ClosureConfig:
    return ClosureConfig(
        story_dir=s_dir,
        close_issue=False,
        story_service=NoOpStoryService(),  # type: ignore[arg-type]
        integrity_gate=RecordingIntegrityGate(),  # type: ignore[arg-type]
        scan_port=RecordingScanPort(),
        build_test_port=RecordingBuildTestPort(),
        sanity_port=sanity or RecordingSanityPort(),
        artifact_manager=build_artifact_manager(s_dir),
        doc_fidelity_port=RecordingDocFidelityPort(),
        vectordb_sync_port=RecordingVectorDbSyncPort(),
        guard_deactivation_port=RecordingGuardDeactivationPort(),
        git_backend=git_backend or StubGitBackend(),
        progress_store=build_progress_store(s_dir),  # type: ignore[arg-type]
        mode_lock_release_port=release_port,  # type: ignore[arg-type]
    )


def _envelope(state: PhaseState) -> object:
    class _Env:
        def __init__(self, st: PhaseState) -> None:
            self.state = st

    return _Env(state)


def test_fast_closure_uses_sanity_gate_and_merges(tmp_path: Path) -> None:
    s_dir = _prepare(tmp_path)
    sanity = RecordingSanityPort(passed=True)
    integrity = RecordingIntegrityGate()
    cfg = _fast_config(s_dir, sanity=sanity)
    cfg.integrity_gate = integrity  # type: ignore[assignment]
    handler = ClosurePhaseHandler(cfg)

    result = handler.on_enter(_fast_ctx(project_root=tmp_path), _envelope(_state()))  # type: ignore[arg-type]

    assert result.status is PhaseStatus.COMPLETED
    # Fast routed through the Sanity-Gate, NOT the 9-dim IntegrityGate.
    assert sanity.calls == ["sanity"]
    assert integrity.calls == []


def test_fast_closure_rebase_conflict_escalates(tmp_path: Path) -> None:
    s_dir = _prepare(tmp_path)
    sanity = RecordingSanityPort(
        passed=False, reason="pre-merge rebase onto origin/main failed (conflict)"
    )
    handler = ClosurePhaseHandler(_fast_config(s_dir, sanity=sanity))

    result = handler.on_enter(_fast_ctx(project_root=tmp_path), _envelope(_state()))  # type: ignore[arg-type]

    assert result.status is PhaseStatus.ESCALATED
    assert any("conflict" in e for e in result.errors)


def test_fast_closure_releases_mode_lock_once(tmp_path: Path) -> None:
    from agentkit.governance.setup_preflight_gate.mode_lock_marker import (
        mode_lock_acquired,
        record_mode_lock_acquired,
    )

    s_dir = _prepare(tmp_path)
    # This story acquired the lock at Setup -> the durable marker is present.
    record_mode_lock_acquired(s_dir, mode="fast")
    release = _RecordingModeLockReleasePort()
    handler = ClosurePhaseHandler(_fast_config(s_dir, release_port=release))

    result = handler.on_enter(_fast_ctx(project_root=tmp_path), _envelope(_state()))  # type: ignore[arg-type]

    assert result.status is PhaseStatus.COMPLETED
    assert len(release.calls) == 1
    assert release.calls[0][1] == "proj"
    # FIX-4: idempotency is the durable marker alone (no seventh checkpoint); the
    # release cleared it, so a resume would find nothing to release.
    assert mode_lock_acquired(s_dir) is False
    # FIX-4: there is no ``lock_released`` field on ClosureProgress anymore.
    assert not hasattr(ClosureProgress(), "lock_released")


def test_resumed_closure_does_not_double_release(tmp_path: Path) -> None:
    # FIX-4: idempotency via the durable marker ALONE. A resume after a completed
    # release (marker already cleared) must NOT release again.
    # Pre-write the metrics projection so the metrics-resume read finds it (the
    # metrics_written checkpoint guarantees a persisted projection on resume).
    s_dir = _prepare(tmp_path)
    from agentkit.bootstrap.composition_root import build_projection_accessor
    from agentkit.closure.post_merge_finalization.metrics import (
        build_story_metrics_record,
    )
    from agentkit.telemetry.projection_accessor import ProjectionKind

    metrics = build_story_metrics_record(
        s_dir,
        _fast_ctx(project_root=tmp_path),
        completed_at=datetime(2026, 1, 1, 11, 0, 0, tzinfo=UTC),
        final_status="completed",
    )
    build_projection_accessor(s_dir).write_projection(
        ProjectionKind.STORY_METRICS, metrics
    )

    # No acquire marker present (a prior release already cleared it).
    release = _RecordingModeLockReleasePort()
    handler = ClosurePhaseHandler(_fast_config(s_dir, release_port=release))
    already = ClosureProgress(
        integrity_passed=True,
        story_branch_pushed=True,
        merge_done=True,
        story_closed=True,
        metrics_written=True,
        postflight_done=True,
    )
    result = handler.on_resume(
        _fast_ctx(project_root=tmp_path),
        _envelope(_state(progress=already)),  # type: ignore[arg-type]
        "trigger",
    )
    assert result.status is PhaseStatus.COMPLETED
    assert release.calls == []  # no double-release on resume (marker absent)
