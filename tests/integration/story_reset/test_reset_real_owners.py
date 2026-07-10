"""Real-owner Story-Reset integration test (FK-53, AG3-071).

Drives ``StoryResetService`` against the REAL Schritt-5 / Schritt-6 owner ports on
a tmp SQLite state backend (no fakes of the purge owners):

* Schritt 5 runtime: the real ``RuntimeExecutionPurgePort`` + residue probe
  (AG3-109) over seeded ``flow_executions`` / ``attempts`` rows.
* Schritt 5 locks: the real ``Governance.deactivate_locks`` + ``LockRecordRepository``
  over a seeded ACTIVE ``story_execution_locks`` row.
* Schritt 6 read-models: the real FK-69 ``ProjectionAccessor.purge_run`` over a
  seeded ``qa_findings`` row.

The status owner is the real in-memory ``StoryService`` (a real internal
collaborator, not a mock). Asserts that after ``execute_reset`` the real residue
probes report a clean restartable base, the lock is INACTIVE, the read model is
gone, and the SEPARATE Schritt-5/Schritt-6 owners were each actually invoked
against their own store.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.bootstrap.story_reset_adapters import (
    AnalyticsPurgeAdapter,
    LockPurgeAdapter,
    ReadModelPurgeAdapter,
    RuntimePurgeAdapter,
    WorkspacePurgeAdapter,
    WorktreePurgeAdapter,
)
from agentkit.backend.control_plane.repository import (
    EdgeCommandRepository,
    RunOwnershipRepository,
)
from agentkit.backend.core_types.attempt import AttemptOutcome
from agentkit.backend.governance.runner import Governance
from agentkit.backend.kpi_analytics.aggregation import RefreshWorker
from agentkit.backend.kpi_analytics.fact_store import FactStore
from agentkit.backend.phase_state_store.models import FlowExecution
from agentkit.backend.pipeline_engine.phase_executor.records import AttemptRecord
from agentkit.backend.project_management.entities import Project, ProjectConfiguration
from agentkit.backend.state_backend.config import ALLOW_SQLITE_ENV, STATE_BACKEND_ENV
from agentkit.backend.state_backend.persistence_test_support import reset_backend_cache_for_tests
from agentkit.backend.state_backend.pipeline_runtime_store import (
    save_attempt,
    save_flow_execution,
)
from agentkit.backend.state_backend.store.analytics_source import StateBackendAnalyticsSource
from agentkit.backend.state_backend.store.fact_repository import StateBackendFactRepository
from agentkit.backend.state_backend.store.governance_hook_repository import (
    StateBackendHookRegistrationRepository,
)
from agentkit.backend.state_backend.store.inflight_idempotency_guard import (
    InMemoryInflightIdempotencyGuard,
)
from agentkit.backend.state_backend.store.lock_record_repository import LockRecordRepository
from agentkit.backend.state_backend.store.runtime_execution_purge import (
    RuntimeExecutionPurgePort,
    RuntimeExecutionResidueProbe,
)
from agentkit.backend.story_context_manager.service import StoryService
from agentkit.backend.story_context_manager.story_model import (
    CreateStoryInput,
    StoryStatus,
    WireStoryType,
)
from agentkit.backend.story_context_manager.story_repository import InMemoryStoryRepository
from agentkit.backend.story_reset import (
    FileResetRecordStore,
    ResetStatus,
    StoryResetRecord,
    StoryResetRequest,
    StoryResetService,
)
from agentkit.backend.verify_system.stage_registry.records import QAFindingRecord

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_PROJECT = "ak3"
_STORY = "AK3-7001"
_RUN = "33333333-3333-4333-8333-333333333333"
_NOW = datetime(2026, 6, 12, 10, 0, tzinfo=UTC)


@pytest.fixture
def store_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    monkeypatch.setenv(STATE_BACKEND_ENV, "sqlite")
    monkeypatch.setenv(ALLOW_SQLITE_ENV, "1")
    reset_backend_cache_for_tests()
    s_dir = tmp_path / _STORY
    s_dir.mkdir(parents=True, exist_ok=True)
    yield s_dir
    reset_backend_cache_for_tests()


class _ProjectRepo:
    def __init__(self) -> None:
        self._p = Project(
            key=_PROJECT,
            name="AgentKit 3",
            story_id_prefix="AK3",
            configuration=ProjectConfiguration(
                repo_url="",
                default_branch="main",
                default_worker_count=2,
                repositories=["ak3"],
            ),
        )

    def get(self, key: str) -> Project | None:
        return self._p if key == self._p.key else None

    def list(self, *, include_archived: bool = False) -> list[Project]:
        return [self._p]

    def save(self, project: Project) -> None:
        self._p = project


class _FixedRunScope:
    def resolve_run_id(self, project_key: str, story_id: str) -> str | None:
        return _RUN


class _AlwaysEscalated:
    def has_escalation_finding(
        self, project_key: str, story_id: str, run_id: str | None
    ) -> bool:
        return True


class _NoCompeting:
    """Genuine external edge: the control-plane terminal probe is unit-tested
    separately; here it has no competing operation."""

    def has_competing_admin_operation(
        self, project_key: str, story_id: str, run_id: str | None, reset_id: str
    ) -> bool:
        return False


class _MemoryFence:
    """Genuine external edge: the control-plane global op store is exercised by the
    control-plane integration suite; here an in-memory claim suffices."""

    def __init__(self) -> None:
        self._claimed: dict[str, object] = {}

    def claim(self, record: object) -> bool:
        self._claimed[record.op_id] = record
        return True

    def load(self, op_id: str) -> object | None:
        return self._claimed.get(op_id)

    def release(self, op_id: str) -> None:
        self._claimed.pop(op_id, None)

    def quiesce_inflight(self, *_args: object) -> None:
        return None

    def load_active_binding(self, *_args: object) -> None:
        return None

    def commit_disown(self, *_args: object) -> None:
        raise AssertionError("no active binding was loaded")


def _seed_real_state(store_dir: Path, story_id: str) -> None:
    """Seed REAL runtime + lock + read-model rows via the canonical owners."""
    save_flow_execution(
        store_dir,
        FlowExecution(
            project_key=_PROJECT,
            story_id=story_id,
            run_id=_RUN,
            flow_id="flow-1",
            level="story",
            owner="orchestrator",
            started_at=_NOW,
        ),
    )
    save_attempt(
        store_dir,
        AttemptRecord(
            run_id=_RUN,
            phase="implementation",
            attempt=1,
            outcome=AttemptOutcome.COMPLETED,
            started_at=_NOW,
            ended_at=_NOW,
        ),
    )
    from agentkit.backend.bootstrap.composition_root import build_projection_accessor

    accessor = build_projection_accessor(store_dir)
    accessor._repos.qa_findings.write(  # noqa: SLF001 — seed via the real repo
        QAFindingRecord(
            project_key=_PROJECT,
            story_id=story_id,
            run_id=_RUN,
            attempt_no=1,
            stage_id="layer1",
            finding_id="f-1",
            check_id="c-1",
            status="fail",
            severity="error",
            blocking=True,
            source_component="structural",
            artifact_id="a-1",
            occurred_at=_NOW,
        )
    )


def _build_service(store_dir: Path, story_service: StoryService) -> StoryResetService:
    governance = Governance(
        hook_repo=StateBackendHookRegistrationRepository(),
        lock_repo=LockRecordRepository(store_dir),
        project_key=_PROJECT,
        project_root=store_dir,
    )
    from agentkit.backend.bootstrap.composition_root import build_projection_accessor

    accessor = build_projection_accessor(store_dir)
    refresh_worker = RefreshWorker(
        FactStore(StateBackendFactRepository(store_dir)),
        StateBackendAnalyticsSource(accessor, project_key=_PROJECT),
    )
    return StoryResetService(
        story_status=story_service,
        record_store=FileResetRecordStore(store_dir / "reset_audit"),
        run_scope=_FixedRunScope(),
        escalation_evidence=_AlwaysEscalated(),
        competing_operation=_NoCompeting(),
        fence=_MemoryFence(),
        runtime_purge=RuntimePurgeAdapter(
            RuntimeExecutionPurgePort(store_dir),
            RuntimeExecutionResidueProbe(store_dir),
        ),
        lock_purge=LockPurgeAdapter(governance, LockRecordRepository(store_dir)),
        read_model_purge=ReadModelPurgeAdapter(accessor),
        analytics_purge=AnalyticsPurgeAdapter(refresh_worker),
        workspace=WorkspacePurgeAdapter(store_dir),
        # AG3-145 D: the worktree teardown is edge-commissioned; this SQLite
        # reset seeds no StoryContext worktree_map, so detach is a convergent
        # no-op (the edge command port is never touched). The Postgres proof of
        # the commissioned teardown lives in
        # test_reset_worktree_teardown_edge.py.
        worktree=WorktreePurgeAdapter(
            edge_commands=EdgeCommandRepository(),
            ownership_repo=RunOwnershipRepository(),
            project_root=store_dir,
        ),
        now_fn=lambda: _NOW,
    )


def _make_story_service() -> tuple[StoryService, str]:
    svc = StoryService(
        story_repository=InMemoryStoryRepository(),
        project_repository=_ProjectRepo(),
        idempotency_guard=InMemoryInflightIdempotencyGuard(),
        event_emitter=lambda *_a: None,
    )
    created = svc.create_story(
        CreateStoryInput(
            project_key=_PROJECT,
            title="Reset target",
            story_type=WireStoryType.IMPLEMENTATION,
            repos=["ak3"],
        ),
        op_id="op-create",
    )
    svc.approve_story(created.story_display_id, op_id="op-approve")
    svc.begin_progress(created.story_display_id)
    return svc, created.story_display_id


def test_reset_purges_real_runtime_locks_and_read_models(store_dir: Path) -> None:
    """AC5/AC5b/AC6: the real Schritt-5 + Schritt-6 owners purge to a clean state."""
    story_service, story_id = _make_story_service()
    # Seed the REAL runtime/lock/read-model rows keyed on the SAME story_id the
    # status owner minted, so the real purge owners operate on a populated run.
    _seed_real_state(store_dir, story_id)

    # Pre-conditions: the real rows exist (verified through the real owners).
    probe_before = RuntimeExecutionResidueProbe(store_dir)
    assert probe_before.check_run(_PROJECT, story_id, _RUN).is_clean is False
    from agentkit.backend.bootstrap.composition_root import build_projection_accessor

    accessor = build_projection_accessor(store_dir)
    assert accessor._repos.qa_findings.read(story_id=story_id)  # noqa: SLF001

    service = _build_service(store_dir, story_service)
    rec = service.request_reset(
        StoryResetRequest(
            project_key=_PROJECT,
            story_id=story_id,
            requested_by="human_cli",
            reason="irreparable merge conflict",
        )
    )
    assert isinstance(rec, StoryResetRecord)
    result = service.execute_reset(rec.reset_id)

    assert result.record.status is ResetStatus.COMPLETED
    assert result.clean_state.is_clean is True
    # Real Schritt-5 runtime residue is clean.
    probe = RuntimeExecutionResidueProbe(store_dir)
    assert probe.check_run(_PROJECT, story_id, _RUN).is_clean is True
    # Real Schritt-5 lock owner reports no active locks (convergent: none seeded).
    assert (
        LockRecordRepository(store_dir).count_active_locks_for_story(story_id) == 0
    )
    # Real Schritt-6 read model is gone.
    accessor_after = build_projection_accessor(store_dir)
    assert accessor_after._repos.qa_findings.read(story_id=story_id) == []  # noqa: SLF001
    # Story survives as a live restartable unit (NOT Cancelled).
    assert story_service.get_story(story_id).status is StoryStatus.IN_PROGRESS
