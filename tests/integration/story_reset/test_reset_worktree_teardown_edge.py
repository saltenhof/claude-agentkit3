"""Integration: the Story-Reset worktree teardown is edge-commissioned (AG3-145 D).

Drives the REAL ``StoryResetService`` Step-8 worktree owner (the REAL
``WorktreePurgeAdapter``) against a REAL Postgres Edge-Command-Queue + run
ownership record + persisted ``StoryContext``. Asserts AC7 for the reset path:

* ``execute_reset`` commissions a ``teardown_worktree`` edge command per worktree
  repo (from the REAL persisted ``worktree_map`` + active ownership -- no
  hand-assembled command), scoped to the run's OWN owning session;
* the reset does NOT block on the physical removal -- the open command stays
  auditably visible, and the §53.8 worktree end-state is the commissioned command
  (``worktree_clean``);
* re-running the reset detach is idempotent (the deterministic command id is not
  duplicated), and the REAL edge executor tears the worktree down as a reported
  no-op/torn-down (FK-10 §10.5.3).

The non-worktree purge owners are lightweight fakes (orthogonal to AC7); the
worktree owner under test and every input it reads are REAL Postgres state.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.bootstrap.story_reset_adapters import WorktreePurgeAdapter
from agentkit.backend.control_plane.edge_commands import edge_command_id
from agentkit.backend.control_plane.models import EdgeCommandView
from agentkit.backend.control_plane.ownership import OwnershipAcquisition, OwnershipStatus
from agentkit.backend.control_plane.records import (
    ControlPlaneOperationRecord,
    RunOwnershipRecord,
)
from agentkit.backend.control_plane.repository import (
    EdgeCommandRepository,
    RunOwnershipRepository,
)
from agentkit.backend.installer.paths import story_dir as resolve_story_dir
from agentkit.backend.project_management.entities import Project, ProjectConfiguration
from agentkit.backend.state_backend.harness_edge_command_store import (
    list_and_ack_open_edge_command_records_global,
    load_edge_command_record_global,
)
from agentkit.backend.state_backend.operation_ledger import commit_edge_command_result_global
from agentkit.backend.state_backend.store.inflight_idempotency_guard import (
    InMemoryInflightIdempotencyGuard,
)
from agentkit.backend.state_backend.story_lifecycle_store import (
    insert_run_ownership_record_global,
    save_story_context,
)
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.service import StoryService
from agentkit.backend.story_context_manager.story_model import (
    CreateStoryInput,
    WireStoryType,
)
from agentkit.backend.story_context_manager.story_repository import InMemoryStoryRepository
from agentkit.backend.story_context_manager.types import StoryMode, StoryType
from agentkit.backend.story_reset import (
    FileResetRecordStore,
    ResetStatus,
    StoryResetRecord,
    StoryResetRequest,
    StoryResetService,
)
from agentkit.harness_client.projectedge.command_executor import execute_command

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

_PROJECT = "ak3"
_REPO = "ak3"
_SESSION = "sess-reset-owner"
_NOW = datetime(2026, 7, 5, 10, 0, tzinfo=UTC)


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
                repositories=[_REPO],
            ),
        )

    def get(self, key: str) -> Project | None:
        return self._p if key == self._p.key else None

    def list(self, *, include_archived: bool = False) -> list[Project]:
        return [self._p]

    def save(self, project: Project) -> None:
        self._p = project


class _FakePorts:
    """Convergent fakes for every non-worktree reset port (orthogonal to AC7)."""

    def __init__(self, run_id: str) -> None:
        self._run_id = run_id
        self._fence: dict[str, object] = {}

    # RunScopePort
    def resolve_run_id(self, project_key: str, story_id: str) -> str | None:
        return self._run_id

    # EscalationEvidencePort
    def has_escalation_finding(
        self, project_key: str, story_id: str, run_id: str | None
    ) -> bool:
        return True

    # CompetingOperationPort
    def has_competing_admin_operation(
        self, project_key: str, story_id: str, run_id: str | None, reset_id: str
    ) -> bool:
        return False

    # FencePort
    def claim(self, record: object) -> bool:
        self._fence[record.op_id] = record  # type: ignore[attr-defined]
        return True

    def load(self, op_id: str) -> object | None:
        return self._fence.get(op_id)

    def release(self, op_id: str) -> None:
        self._fence.pop(op_id, None)

    def quiesce_inflight(self, *_args: object) -> None:
        return None

    def load_active_binding(self, *_args: object) -> None:
        return None

    def commit_disown(self, *_args: object) -> None:
        raise AssertionError("no active binding was loaded")

    # RuntimePurgePort (Step 5)
    def purge_run(self, project_key: str, story_id: str, run_id: str) -> dict[str, int]:
        return {}

    def residue(self, project_key: str, story_id: str, run_id: str) -> dict[str, int]:
        return {}

    # LockPurgePort (Step 5)
    def deactivate_locks(self, story_id: str) -> None:
        return None

    def has_active_locks(self, story_id: str) -> bool:
        return False

    # ReadModelPurgePort (Step 6)
    def purge_run_read_model(
        self, project_key: str, story_id: str, run_id: str
    ) -> dict[str, int]:
        return {}

    # AnalyticsPurgePort (Step 6)
    def purge_story_analytics(
        self, project_key: str, story_id: str, run_id: str
    ) -> None:
        return None

    # WorkspacePort (Step 7)
    def purge_workspace(self, project_key: str, story_id: str) -> None:
        return None


class _ReadModelAdapter:
    def __init__(self, ports: _FakePorts) -> None:
        self._ports = ports

    def purge_run(self, project_key: str, story_id: str, run_id: str) -> dict[str, int]:
        return self._ports.purge_run_read_model(project_key, story_id, run_id)


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
            repos=[_REPO],
        ),
        op_id="op-create",
    )
    svc.approve_story(created.story_display_id, op_id="op-approve")
    svc.begin_progress(created.story_display_id)
    return svc, created.story_display_id


def _seed_ownership(story_id: str, run_id: str) -> None:
    insert_run_ownership_record_global(
        RunOwnershipRecord(
            project_key=_PROJECT,
            story_id=story_id,
            run_id=run_id,
            owner_session_id=_SESSION,
            ownership_epoch=1,
            status=OwnershipStatus.ACTIVE,
            acquired_via=OwnershipAcquisition.SETUP,
            acquired_at=_NOW,
            audit_ref="audit:reset",
        )
    )


def _seed_worktree_context(
    project_root: Path, story_id: str, worktree_root: Path
) -> None:
    ctx = StoryContext(
        project_key=_PROJECT,
        story_id=story_id,
        story_type=StoryType.IMPLEMENTATION,
        execution_route=StoryMode.EXECUTION,
        title="Reset target",
        project_root=project_root,
        participating_repos=[_REPO],
        worktree_map={_REPO: worktree_root},
    )
    save_story_context(resolve_story_dir(project_root, story_id), ctx)


def _build_service(
    project_root: Path, story_service: StoryService, run_id: str
) -> StoryResetService:
    ports = _FakePorts(run_id)
    return StoryResetService(
        story_status=story_service,
        record_store=FileResetRecordStore(project_root / "reset_audit"),
        run_scope=ports,
        escalation_evidence=ports,
        competing_operation=ports,
        fence=ports,
        runtime_purge=ports,
        lock_purge=ports,
        read_model_purge=_ReadModelAdapter(ports),
        analytics_purge=ports,
        workspace=ports,
        worktree=WorktreePurgeAdapter(
            edge_commands=EdgeCommandRepository(),
            ownership_repo=RunOwnershipRepository(),
            project_root=project_root,
        ),
        now_fn=lambda: _NOW,
    )


def test_reset_commissions_teardown_edge_command(
    tmp_path: Path,
    postgres_isolated_schema: str,
) -> None:
    """AC7 (reset path): execute_reset commissions the worktree teardown edge command."""
    del postgres_isolated_schema
    story_service, story_id = _make_story_service()
    run_id = f"{story_id}-run-1"
    worktree_root = tmp_path / "worktrees" / story_id
    _seed_ownership(story_id, run_id)
    _seed_worktree_context(tmp_path, story_id, worktree_root)

    service = _build_service(tmp_path, story_service, run_id)
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

    # The reset completed and did NOT block on the physical removal (worktree_clean
    # is satisfied by the commissioned open command, FK-10 §10.4.2).
    assert result.record.status is ResetStatus.COMPLETED
    assert result.clean_state.worktree_clean is True

    teardown_id = edge_command_id(run_id, "teardown_worktree", _REPO)
    teardown = load_edge_command_record_global(teardown_id)
    assert teardown is not None
    assert teardown.command_kind == "teardown_worktree"
    assert teardown.status == "created"
    assert teardown.session_id == _SESSION
    assert teardown.payload["repo_id"] == _REPO
    assert teardown.payload["branch"] == f"story/{story_id}"


def test_reset_detach_is_idempotent_and_edge_executes(
    tmp_path: Path,
    postgres_isolated_schema: str,
) -> None:
    """AC7 (reset path): a double reset detach is idempotent; the edge tears down."""
    del postgres_isolated_schema
    story_service, story_id = _make_story_service()
    run_id = f"{story_id}-run-1"
    _seed_ownership(story_id, run_id)
    _seed_worktree_context(tmp_path, story_id, tmp_path / "worktrees" / story_id)

    adapter = WorktreePurgeAdapter(
        edge_commands=EdgeCommandRepository(),
        ownership_repo=RunOwnershipRepository(),
        project_root=tmp_path,
    )
    teardown_id = edge_command_id(run_id, "teardown_worktree", _REPO)

    # Before detach: the worktree still lacks a commissioned teardown (not clean).
    assert adapter.has_live_worktree(_PROJECT, story_id, run_id) is True
    adapter.detach_worktrees(_PROJECT, story_id, run_id)
    first = load_edge_command_record_global(teardown_id)
    assert first is not None
    # A double detach does not duplicate / re-open the deterministic command.
    adapter.detach_worktrees(_PROJECT, story_id, run_id)
    second = load_edge_command_record_global(teardown_id)
    assert second is not None
    assert second.created_at == first.created_at
    # The worktree end-state is now clean (the open command is the audit proof).
    assert adapter.has_live_worktree(_PROJECT, story_id, run_id) is False

    # The REAL edge executor runs the teardown idempotently (no worktree on disk
    # => reported no_op, never an error -- FK-10 §10.5.3).
    open_commands = list_and_ack_open_edge_command_records_global(
        project_key=_PROJECT, run_id=run_id, session_id=_SESSION, delivered_at=_NOW
    )
    assert [c.command_id for c in open_commands] == [teardown_id]
    from agentkit.backend.config.models import (
        SUPPORTED_CONFIG_VERSION,
        Features,
        JenkinsConfig,
        PipelineConfig,
        ProjectConfig,
        RepositoryConfig,
        SonarQubeConfig,
    )

    repo_dir = tmp_path / _REPO
    repo_dir.mkdir()
    project_config = ProjectConfig(
        project_key=_PROJECT,
        project_name="P",
        repositories=[RepositoryConfig(name=_REPO, path=repo_dir)],
        pipeline=PipelineConfig(  # type: ignore[call-arg]
            config_version=SUPPORTED_CONFIG_VERSION,
            features=Features(multi_llm=False),
            sonarqube=SonarQubeConfig(available=False, enabled=False),
            ci=JenkinsConfig(available=False, enabled=False),
        ),
    )
    import subprocess

    subprocess.run(["git", "init", "-q", str(repo_dir)], check=True, capture_output=True)
    record = open_commands[0]
    view = EdgeCommandView(
        command_id=record.command_id,
        command_kind=record.command_kind,
        payload=record.payload,
        status="delivered",
        created_at=record.created_at,
    )
    result = execute_command(view, project_config=project_config, project_root=tmp_path)
    op = ControlPlaneOperationRecord(
        op_id=f"op-{record.command_id}",
        project_key=_PROJECT,
        story_id=story_id,
        run_id=run_id,
        session_id=_SESSION,
        operation_kind="edge_command_result",
        phase=None,
        status="committed",
        response_payload={"command_id": record.command_id},
        created_at=_NOW,
        updated_at=_NOW,
    )
    commit_edge_command_result_global(
        op,
        command_id=record.command_id,
        result_status="completed",
        completed_at=_NOW,
        result_op_id=op.op_id,
        result_type=result.result_type,
        result_payload=result.model_dump(mode="json"),
        expected_ownership_epoch=1,
    )
    done = load_edge_command_record_global(teardown_id)
    assert done is not None
    assert done.result_type == "worktree_report"
    assert done.result_payload is not None
    assert done.result_payload["outcome"] == "no_op"
