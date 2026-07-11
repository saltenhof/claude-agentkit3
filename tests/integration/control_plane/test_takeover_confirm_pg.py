"""Postgres integration coverage for AG3-148 takeover confirm."""

from __future__ import annotations

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from functools import partial
from http import HTTPStatus
from threading import Event
from types import SimpleNamespace
from typing import TYPE_CHECKING

import psycopg
import pytest

from agentkit.backend.auth.middleware import AuthMiddleware
from agentkit.backend.auth.tokens import issue_project_api_token
from agentkit.backend.bootstrap.story_reset_adapters import ResetDisownAdapter
from agentkit.backend.config.models import (
    SUPPORTED_CONFIG_VERSION,
    Features,
    JenkinsConfig,
    PipelineConfig,
    ProjectConfig,
    RepositoryConfig,
    SonarQubeConfig,
)
from agentkit.backend.control_plane.http import ControlPlaneApplication, HttpResponse
from agentkit.backend.control_plane.models import (
    AdminTakeoverReconcileClearRequest,
    ClosureCompleteRequest,
    ControlPlaneMutationResult,
    EdgeBundle,
    EdgeCommandMutationResult,
    EdgeCommandResultRequest,
    EdgePointer,
    OpenEdgeCommandsResponse,
    PhaseDispatchResult,
    PhaseMutationRequest,
    ProjectEdgeSyncRequest,
    ProvisionWorktreeCommandPayload,
    SessionRunBindingView,
    StoryExecutionLockView,
    TakeoverConfirmRequest,
    TakeoverDenyRequest,
    TakeoverErrorResult,
    TakeoverReconcileWorktreeRequest,
    TakeoverRequest,
    WorktreeReport,
)
from agentkit.backend.control_plane.ownership import (
    OWNERSHIP_TRANSFERRED_REVOCATION_REASON,
    BindingStatus,
    OwnershipAcquisition,
    OwnershipStatus,
    TakeoverApprovalStatus,
)
from agentkit.backend.control_plane.ownership_transfer import OwnershipBasis
from agentkit.backend.control_plane.push_sync import (
    PushBarrierVerdict,
    PushBarrierVerdictStatus,
    PushFreshnessRecord,
    RepoPushVerificationInput,
    SyncPointBarrierType,
)
from agentkit.backend.control_plane.records import (
    ControlPlaneOperationRecord,
    RunOwnershipRecord,
    SessionRunBindingRecord,
    TakeoverApprovalRecord,
    TakeoverChallengeRecord,
    TakeoverChallengeRepoRecord,
    TakeoverConfirmTerminalRecords,
    TakeoverTransferRecord,
)
from agentkit.backend.control_plane.repository import (
    ControlPlaneRuntimeRepository,
    ObjectMutationClaimRepository,
)
from agentkit.backend.control_plane.runtime import (
    ControlPlaneRuntimeService,
    TakeoverConfirmCommand,
    TakeoverDenyCommand,
)
from agentkit.backend.control_plane.runtime._ownership_transfer import (
    _commit_takeover_invalidation,
    _reconcile_takeover_confirm_cas_loss,
)
from agentkit.backend.core_types.freeze import FreezeKind
from agentkit.backend.exceptions import OwnershipFenceViolationError
from agentkit.backend.governance.guard_system.records import StoryExecutionLockRecord
from agentkit.backend.governance.principal_capabilities.principals import Principal
from agentkit.backend.state_backend import postgres_store
from agentkit.backend.state_backend.governance_runtime_store import (
    load_story_execution_lock_global,
    save_story_execution_lock_global,
)
from agentkit.backend.state_backend.operation_ledger import (
    acquire_object_mutation_claim_global,
    commit_control_plane_operation_with_side_effects_global,
    commit_takeover_confirm_global,
    commit_takeover_deny_global,
    commit_takeover_expiry_global,
    commit_takeover_invalidation_global,
    commit_takeover_reissue_global,
    delete_object_mutation_claim_global,
    load_control_plane_operation_global,
    reconcile_takeover_confirm_cas_loss_global,
    save_control_plane_operation_global,
)
from agentkit.backend.state_backend.state_backend_connection_manager import (
    boot_backend_instance_identity_global,
)
from agentkit.backend.state_backend.store.freeze_repository import (
    FreezeRepository,
    LocalFreezeJsonExport,
)
from agentkit.backend.state_backend.story_closure_store import (
    upsert_push_barrier_verdict_global,
    upsert_push_freshness_record_global,
)
from agentkit.backend.state_backend.story_lifecycle_store import (
    insert_run_ownership_record_global,
    insert_takeover_approval_global,
    insert_takeover_challenge_global,
    load_active_run_ownership_record_global,
    load_run_ownership_record_global,
    load_session_run_binding_global,
    load_takeover_approval_for_challenge_global,
    load_takeover_approval_global,
    load_takeover_challenge_global,
    load_takeover_transfer_record_global,
    save_session_run_binding_global,
    save_story_context_global,
    save_takeover_transfer_record_global,
    update_takeover_approval_status_global,
    update_takeover_challenge_status_global,
)
from agentkit.backend.state_backend.telemetry_event_store import (
    load_execution_events_global,
)
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.types import StoryMode, StoryType
from agentkit.backend.story_exit import (
    ExitReason,
    ExitRunState,
    StoryExitRequest,
    StoryExitService,
)
from agentkit.backend.story_reset import (
    FileResetRecordStore,
    StoryResetRequest,
    StoryResetService,
)
from agentkit.backend.story_split import (
    SplitPlan,
    SplitSourceState,
    StorySplitRequest,
    StorySplitSagaGuard,
    StorySplitService,
    compute_plan_ref,
    derive_split_id,
)
from agentkit.backend.telemetry.contract.records import ExecutionEventRecord
from agentkit.backend.telemetry.events import EventType
from agentkit.harness_client.projectedge import (
    LocalEdgePublisher,
    ProjectEdgeResolver,
    process_open_commands,
)
from agentkit.harness_client.projectedge.command_executor import (
    execute_provision_worktree,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from agentkit.backend.auth.entities import ProjectApiToken

pytest_plugins = ("tests.fixtures.postgres_backend",)

_NOW = datetime(2026, 6, 7, 10, 0, tzinfo=UTC)
_LATER = datetime(2026, 6, 7, 10, 5, tzinfo=UTC)
_EXPIRED_NOW = datetime(2026, 6, 7, 13, 0, tzinfo=UTC)
_PROJECT = "tenant-a"
_REPO = "api"
_SHA = "a" * 40
_FAULT_STEPS = (
    "control_plane_op_upsert",
    "ownership_update",
    "previous_binding_revoke",
    "approval_approve",
    "new_binding_insert",
    "request_operation_terminalize",
    "challenge_terminalize",
    "lock_insert",
    f"transfer_record_insert:{_REPO}",
    "takeover_reconcile_required",
    "takeover_reconcile_commands",
    f"event_insert:{EventType.SESSION_RUN_BINDING_TRANSFERRED.value}",
    f"event_insert:{EventType.SESSION_DISOWNED.value}",
    f"event_insert:{EventType.TAKEOVER_APPROVAL_CHANGED.value}",
)
_DENY_FAULT_STEPS = (
    "control_plane_op_upsert",
    "approval_deny",
    "request_operation_terminalize",
    "challenge_terminalize",
    f"event_insert:{EventType.TAKEOVER_APPROVAL_CHANGED.value}",
)
_RECONCILE_FAULT_STEPS = (
    "control_plane_op_upsert",
    "approval_invalidate",
    "request_operation_terminalize",
    "challenge_terminalize",
    f"event_insert:{EventType.TAKEOVER_APPROVAL_CHANGED.value}",
)


@pytest.mark.integration
def test_takeover_approval_unique_migration_rejects_existing_duplicate_links(
    postgres_backend_env: object,
) -> None:
    del postgres_backend_env
    duplicate_check = next(
        statement
        for statement in postgres_store._schema_alter_statements()  # noqa: SLF001
        if statement.startswith("DO $$ BEGIN IF EXISTS (SELECT challenge_ref")
    )
    with pytest.raises(
        psycopg.errors.RaiseException,
        match="duplicate takeover_approvals.challenge_ref",
    ), postgres_store._connect_global() as conn:  # noqa: SLF001 -- migration transaction
        # Everything stays in this transaction. The expected exception rolls back
        # both the index drop and duplicate fixtures, so parallel workers never see
        # a catalog mutation and cannot race pg_indexes relation OIDs.
        conn.execute("DROP INDEX takeover_approvals_challenge_ref_uidx")
        for approval_id in ("approval-duplicate-a", "approval-duplicate-b"):
            conn.execute(
                """
                INSERT INTO takeover_approvals (
                    approval_id, project_key, story_id, run_id,
                    requested_by_session_id, requested_by_principal_type,
                    reason, challenge_ref, status, requested_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    approval_id,
                    _PROJECT,
                    "AG3-148-DUP",
                    "run-duplicate",
                    approval_id,
                    "interactive_agent",
                    "duplicate migration fixture",
                    "challenge-duplicate",
                    _NOW.isoformat(),
                    (_NOW + timedelta(hours=2)).isoformat(),
                ),
            )
        conn.execute(duplicate_check)


class _AdmittedDispatcher:
    def dispatch(
        self,
        *,
        ctx: StoryContext,
        phase: str,
        run_id: str,
        run_admitted: bool,
        detail: dict[str, object] | None = None,
    ) -> PhaseDispatchResult:
        del ctx, run_id, run_admitted, detail
        return PhaseDispatchResult(
            phase=phase,
            status="phase_completed",
            reaction="advance",
            dispatched=True,
            next_phase="implementation",
        )


class _StoryExitBoundary:
    def administratively_cancel_for_story_exit(self, *_args: object, **_kwargs: object) -> object:
        return SimpleNamespace(status="Cancelled")


class _GovernanceExitBoundary:
    def deactivate_locks(self, _story_id: str) -> object:
        return SimpleNamespace(restored_to_ai_augmented=True)


class _ResetPhaseBoundaryPorts:
    def __init__(self, *, project_key: str, story_id: str, run_id: str) -> None:
        self.project_key = project_key
        self.story_id = story_id
        self.run_id = run_id
        self.story = SimpleNamespace(status="In Progress", project_key=project_key)

    def get_story(self, story_display_id: str) -> object | None:
        return self.story if story_display_id == self.story_id else None

    def begin_reset(self, _story_display_id: str) -> object:
        self.story.status = "Resetting"
        return self.story

    def complete_reset(self, _story_display_id: str) -> object:
        self.story.status = "In Progress"
        return self.story

    def mark_reset_failed(self, _story_display_id: str) -> object:
        self.story.status = "Reset Failed"
        return self.story

    def resume_reset_transition(self, _story_display_id: str) -> object:
        self.story.status = "Resetting"
        return self.story

    def resolve_run_id(self, project_key: str, story_id: str) -> str | None:
        if project_key == self.project_key and story_id == self.story_id:
            return self.run_id
        return None

    def has_escalation_finding(self, *_args: object) -> bool:
        return True

    def has_competing_admin_operation(self, *_args: object) -> bool:
        return False

    def purge_run(self, *_args: object) -> dict[str, int]:
        return {}

    def residue(self, *_args: object) -> dict[str, int]:
        return {}

    def deactivate_locks(self, _story_id: str) -> None:
        return None

    def has_active_locks(self, _story_id: str) -> bool:
        return False

    def purge_story_analytics(self, *_args: object) -> None:
        return None

    def purge_workspace(self, *_args: object) -> None:
        return None

    def detach_worktrees(self, *_args: object) -> None:
        return None

    def has_live_worktree(self, *_args: object) -> bool:
        return False


class _SplitStoryBoundary:
    def __init__(self, story_id: str) -> None:
        self.story_id = story_id
        self.cancelled = False
        self.successors: list[str] = []

    def get_story(self, story_display_id: str) -> object | None:
        if story_display_id == self.story_id:
            return SimpleNamespace(
                status=("Cancelled" if self.cancelled else "In Progress"),
                project_key=_PROJECT,
                story_type="implementation",
                participating_repos=("ak3",),
                epic="",
                module="",
                size="M",
                change_impact="Local",
                concept_quality="High",
                owner="",
                risk="medium",
                labels=(),
            )
        if story_display_id in self.successors:
            return SimpleNamespace(story_display_id=story_display_id)
        return None

    def create_story(self, _request: object, *, op_id: str) -> object:
        del op_id
        created_id = f"{self.story_id}-SUCCESSOR"
        if created_id not in self.successors:
            self.successors.append(created_id)
        return SimpleNamespace(story_display_id=created_id)

    def materialize_split_lineage(
        self,
        *,
        source_story_id: str,
        successor_ids: tuple[str, ...],
    ) -> None:
        assert source_story_id == self.story_id
        assert successor_ids == tuple(self.successors)

    def materialize_split_source_lineage(
        self,
        *,
        source_story_id: str,
        successor_ids: tuple[str, ...],
    ) -> None:
        self.materialize_split_lineage(
            source_story_id=source_story_id,
            successor_ids=successor_ids,
        )

    def materialize_split_successor_lineage(
        self,
        *,
        successor_story_id: str,
        source_story_id: str,
    ) -> None:
        assert source_story_id == self.story_id
        assert successor_story_id in self.successors

    def administratively_cancel_for_story_split(self, *_args: object, **_kwargs: object) -> object:
        self.cancelled = True
        return SimpleNamespace(status="Cancelled")


class _NoDependencies:
    def list_for_project(self, _project_key: str) -> list[object]:
        return []


class _SplitPhaseBoundary:
    def purge_run(self, *_args: object) -> int:
        return 1


class _UnusedSplitBoundary:
    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"split collaborator {name!r} ran past the tested boundary")


class _SuccessfulSplitExport:
    def export(self, *, story_id: str, story_dir: Path) -> object:
        del story_id, story_dir
        return SimpleNamespace(success=True)


class _SuccessfulSupersededIndex:
    def mark_superseded(self, *, story_id: str, superseded_by: tuple[str, ...]) -> int:
        del story_id, superseded_by
        return 1


class _VerifiedPushBoundary:
    def collect_repo_inputs(
        self,
        *,
        project_key: str,
        story_id: str,
        run_id: str,
        required_sync_point_id: str | None = None,
    ) -> tuple[RepoPushVerificationInput, ...]:
        del project_key, story_id, run_id
        return (
            RepoPushVerificationInput(
                repo_id=_REPO,
                edge_report_present=True,
                edge_reported_pushed=True,
                edge_reported_head_sha=_SHA,
                server_ref_resolved=True,
                server_head_sha=_SHA,
                edge_report_sync_point_id=required_sync_point_id,
                required_sync_point_id=required_sync_point_id,
            ),
        )


class _ShaPushBoundary:
    def __init__(self, shas: dict[str, str]) -> None:
        self._shas = shas

    def collect_repo_inputs(
        self,
        *,
        project_key: str,
        story_id: str,
        run_id: str,
        required_sync_point_id: str | None = None,
    ) -> tuple[RepoPushVerificationInput, ...]:
        del project_key, story_id, run_id
        return tuple(
            RepoPushVerificationInput(
                repo_id=repo_id,
                edge_report_present=True,
                edge_reported_pushed=True,
                edge_reported_head_sha=sha,
                server_ref_resolved=True,
                server_head_sha=sha,
                edge_report_sync_point_id=required_sync_point_id,
                required_sync_point_id=required_sync_point_id,
            )
            for repo_id, sha in self._shas.items()
        )


class _RuntimeEdgeClient:
    """In-process adapter over the real runtime and command-queue methods."""

    def __init__(
        self,
        service: ControlPlaneRuntimeService,
        publisher: LocalEdgePublisher,
    ) -> None:
        self._service = service
        self._publisher = publisher

    def fetch_open_commands(
        self, *, run_id: str, project_key: str, session_id: str
    ) -> OpenEdgeCommandsResponse:
        return self._service.list_and_ack_open_commands(
            run_id,
            project_key=project_key,
            session_id=session_id,
        )

    def reconcile_takeover_worktree(
        self, *, run_id: str, request: TakeoverReconcileWorktreeRequest
    ) -> ControlPlaneMutationResult:
        return self._service.reconcile_takeover_worktree(run_id, request)

    def sync(self, request: ProjectEdgeSyncRequest) -> ControlPlaneMutationResult:
        result = self._service.sync_project_edge(request)
        assert result.edge_bundle is not None
        self._publisher.publish(result.edge_bundle)
        return result

    def report_command_result(
        self, *, command_id: str, request: EdgeCommandResultRequest
    ) -> EdgeCommandMutationResult:
        return self._service.submit_command_result(command_id, request)

    def publish_unreadable_freeze_state(
        self, *, worktree_roots: list[Path]
    ) -> None:
        self._publisher.publish_unreadable_freeze_state(
            worktree_roots=worktree_roots
        )


class _InMemoryTokenRepository:
    def __init__(self) -> None:
        self.tokens: dict[str, ProjectApiToken] = {}

    def get(self, token_id: str) -> ProjectApiToken | None:
        return self.tokens.get(token_id)

    def get_by_hash(self, token_hash: str) -> ProjectApiToken | None:
        for token in self.tokens.values():
            if token.token_hash == token_hash:
                return token
        return None

    def list_for_project(self, project_key: str) -> list[ProjectApiToken]:
        return [token for token in self.tokens.values() if token.project_key == project_key]

    def save(self, token: ProjectApiToken) -> None:
        self.tokens[token.token_id] = token

    def revoke(self, project_key: str, token_id: str) -> None:
        del project_key
        del self.tokens[token_id]


def _human_headers(auth: AuthMiddleware, *, project_key: str) -> dict[str, str]:
    session = auth.session_store.create()
    return {
        "Cookie": f"{auth.session_cookie_name()}={session.session_id}",
        auth.csrf_header_name(): session.csrf_token,
        "X-Project-Key": project_key,
    }


def _response_json(response: HttpResponse) -> dict[str, object]:
    body = json.loads(response.body)
    assert isinstance(body, dict)
    return body


def _seed_story_context(
    tmp_path: Path,
    story_id: str,
    *,
    participating_repos: list[str] | None = None,
) -> None:
    project_root = tmp_path / _PROJECT
    (project_root / "stories" / story_id).mkdir(parents=True, exist_ok=True)
    save_story_context_global(
        None,
        StoryContext(
            project_key=_PROJECT,
            story_id=story_id,
            story_type=StoryType.IMPLEMENTATION,
            execution_route=StoryMode.EXECUTION,
            project_root=project_root,
            participating_repos=participating_repos or [_REPO],
        ),
    )


def _phase_request(
    *,
    story_id: str,
    op_id: str,
    session_id: str,
    principal_type: str = "orchestrator",
) -> PhaseMutationRequest:
    return PhaseMutationRequest(
        project_key=_PROJECT,
        story_id=story_id,
        session_id=session_id,
        op_id=op_id,
        principal_type=principal_type,
        worktree_roots=[f"T:/worktrees/{story_id}/{session_id}"],
    )


def _service(
    *,
    ident: str,
    now: datetime = _NOW,
    fault_after_step: Callable[[str], None] | None = None,
    invalidation_fault_after_step: Callable[[str], None] | None = None,
    reissue_fault_after_step: Callable[[str], None] | None = None,
    deny_fault_after_step: Callable[[str], None] | None = None,
    reconcile_fault_after_step: Callable[[str], None] | None = None,
    commit_takeover_confirm_override: Callable[..., None] | None = None,
    push_barrier_evidence: object | None = None,
    local_freeze_export: LocalFreezeJsonExport | None = None,
) -> ControlPlaneRuntimeService:
    identity = boot_backend_instance_identity_global(ident, now)
    repository = None
    object_claim_repository = None
    if any(
        hook is not None
        for hook in (
            fault_after_step,
            invalidation_fault_after_step,
            reissue_fault_after_step,
            deny_fault_after_step,
            reconcile_fault_after_step,
            commit_takeover_confirm_override,
        )
    ):
        repository = ControlPlaneRuntimeRepository(
            commit_takeover_confirm=partial(
                commit_takeover_confirm_global,
                fault_after_step=fault_after_step,
            ),
            commit_takeover_invalidation=partial(
                commit_takeover_invalidation_global,
                fault_after_step=invalidation_fault_after_step,
            ),
            commit_takeover_reissue=partial(
                commit_takeover_reissue_global,
                fault_after_step=reissue_fault_after_step,
            ),
            commit_takeover_deny=partial(
                commit_takeover_deny_global,
                fault_after_step=deny_fault_after_step,
            ),
            reconcile_takeover_confirm_cas_loss=partial(
                reconcile_takeover_confirm_cas_loss_global,
                fault_after_step=reconcile_fault_after_step,
            ),
        )
        if commit_takeover_confirm_override is not None:
            repository = replace(
                repository,
                commit_takeover_confirm=commit_takeover_confirm_override,
            )
        object_claim_repository = ObjectMutationClaimRepository()
    return ControlPlaneRuntimeService(
        repository=repository,
        object_claim_repository=object_claim_repository,
        phase_dispatcher=_AdmittedDispatcher(),  # type: ignore[arg-type]
        now_fn=lambda: now,
        instance_identity=identity,
        push_barrier_evidence=push_barrier_evidence,  # type: ignore[arg-type]
        local_freeze_export=local_freeze_export,
    )


def _admit_run(
    service: ControlPlaneRuntimeService,
    *,
    story_id: str,
    run_id: str,
    session_id: str = "sess-A",
) -> None:
    result = service.start_phase(
        run_id=run_id,
        phase="setup",
        request=_phase_request(
            story_id=story_id,
            op_id=f"op-setup-{story_id}",
            session_id=session_id,
        ),
    )
    assert result.status == "committed"


def _seed_pushed_only_evidence(
    *,
    story_id: str,
    run_id: str,
    repo_id: str = _REPO,
    sha: str = _SHA,
) -> None:
    upsert_push_freshness_record_global(
        PushFreshnessRecord(
            project_key=_PROJECT,
            story_id=story_id,
            run_id=run_id,
            repo_id=repo_id,
            last_reported_head_sha=sha,
            last_pushed_head_sha=sha,
            last_reported_at=_NOW,
            last_sync_point_id=f"phase_completion:{run_id}",
            last_command_id=f"{run_id}::sync_push::phase_completion:{run_id}::{repo_id}",
            backlog=False,
            backlog_detail=None,
        )
    )
    upsert_push_barrier_verdict_global(
        PushBarrierVerdict(
            project_key=_PROJECT,
            story_id=story_id,
            run_id=run_id,
            boundary_type=SyncPointBarrierType.PHASE_COMPLETION,
            boundary_id=run_id,
            repo_id=repo_id,
            producer="control_plane.push_barrier",
            boundary_epoch=1,
            expected_head_sha=sha,
            server_head_sha=sha,
            ownership_epoch=1,
            status=PushBarrierVerdictStatus.PASSED,
            created_at=_NOW,
            updated_at=_NOW,
            resolved_at=_NOW,
            status_detail="verified",
        )
    )


def _request_takeover(
    service: ControlPlaneRuntimeService,
    *,
    story_id: str,
    run_id: str,
    session_id: str = "sess-B",
    principal_type: str = "human_cli",
    op_id: str = "op-takeover-request",
    worktree_roots: list[str] | None = None,
) -> str:
    del run_id
    result = service.request_ownership_takeover(
        request=TakeoverRequest(
            project_key=_PROJECT,
            story_id=story_id,
            session_id=session_id,
            principal_type=principal_type,
            op_id=op_id,
            reason="owner unavailable",
            worktree_roots=(
                worktree_roots
                if worktree_roots is not None
                else [f"T:/worktrees/{story_id}/{session_id}"]
            ),
        )
    )
    assert result.status in {"offered", "pending_human_approval"}
    challenge = result.takeover_challenge
    if challenge is None:
        assert result.pending_human_approval is not None
        approval = load_takeover_approval_global(result.pending_human_approval.approval_id)
        assert approval is not None
        challenge_id = approval.challenge_ref
        return challenge_id
    return challenge.challenge_id


def _confirm_request(
    *,
    story_id: str,
    challenge_id: str,
    op_id: str,
    session_id: str = "sess-B",
) -> TakeoverConfirmCommand:
    return TakeoverConfirmCommand(
        request=TakeoverConfirmRequest(
            project_key=_PROJECT,
            story_id=story_id,
            op_id=op_id,
            challenge_id=challenge_id,
            reason="human confirmed",
        ),
        confirmed_by_session_id=session_id,
        confirmed_by_principal=Principal.HUMAN_CLI,
    )


def _deny_request(
    *,
    story_id: str,
    approval_id: str,
    op_id: str,
    session_id: str = "sess-human-deny",
) -> TakeoverDenyCommand:
    return TakeoverDenyCommand(
        request=TakeoverDenyRequest(
            project_key=_PROJECT,
            story_id=story_id,
            op_id=op_id,
            approval_id=approval_id,
            reason="human denied",
        ),
        denied_by_session_id=session_id,
        denied_by_principal=Principal.HUMAN_CLI,
    )


def _story_id(number: int) -> str:
    return f"AG3148-{number}"


def _wire_time(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


@pytest.mark.integration
def test_ping_pong_barrier_uses_current_epoch_transfer_and_challenge_history(
    postgres_backend_env: object,
    tmp_path: Path,
) -> None:
    del postgres_backend_env
    story_id = _story_id(1490)
    run_id = "run-ping-pong"
    service = _service(ident="inst-ping-pong")
    _seed_story_context(tmp_path, story_id)
    _admit_run(service, story_id=story_id, run_id=run_id, session_id="sess-A")
    _seed_pushed_only_evidence(story_id=story_id, run_id=run_id)

    first_challenge = _request_takeover(
        service,
        story_id=story_id,
        run_id=run_id,
        session_id="sess-B",
        principal_type="human_cli",
        op_id="op-ping-first-request",
    )
    first = service.confirm_ownership_takeover(
        command=_confirm_request(
            story_id=story_id,
            challenge_id=first_challenge,
            op_id="op-ping-first-confirm",
            session_id="sess-B",
        ),
    )
    assert first.status == "committed"

    tokens = _InMemoryTokenRepository()
    issued = issue_project_api_token(
        project_key=_PROJECT,
        label="disowned-read",
        repository=tokens,
    )
    read_response = ControlPlaneApplication(
        runtime_service=service,
        auth_middleware=AuthMiddleware(token_repository=tokens),
    ).handle_request(
        method="GET",
        path="/v1/project-edge/operations/op-ping-first-confirm",
        body=b"",
        request_headers={
            "Authorization": f"Bearer {issued.plaintext_token}",
            "X-Project-Key": _PROJECT,
        },
    )
    assert read_response.status_code == HTTPStatus.OK

    later_service = _service(ident="inst-ping-pong-later", now=_EXPIRED_NOW)
    refreshed = later_service.sync_project_edge(
        ProjectEdgeSyncRequest(
            project_key=_PROJECT,
            session_id="sess-A",
            op_id="op-ping-disowned-renewed-contact",
        )
    )
    assert refreshed.status == "synced"
    assert refreshed.edge_bundle is not None
    assert refreshed.edge_bundle.current.operating_mode == "binding_invalid"
    assert refreshed.edge_bundle.session is not None
    assert refreshed.edge_bundle.session.new_owner_ref == "sess-B"

    reclaim_request = later_service.request_ownership_takeover(
        request=TakeoverRequest(
            project_key=_PROJECT,
            story_id=story_id,
            session_id="sess-A",
            principal_type="orchestrator",
            op_id="op-ping-reclaim-request",
            reason="reclaim immediately",
            worktree_roots=[f"T:/worktrees/{story_id}/sess-A"],
        ),
    )
    assert reclaim_request.status == "rejected"
    assert (
        reclaim_request.error_code
        == "repeat_transfer_requires_privileged_principal_and_reason"
    )

    repeat = service.request_ownership_takeover(
        request=TakeoverRequest(
            project_key=_PROJECT,
            story_id=story_id,
            session_id="sess-C",
            principal_type="orchestrator",
            op_id="op-ping-repeat-request",
            reason="repeat transfer",
            worktree_roots=[f"T:/worktrees/{story_id}/sess-C"],
        ),
    )
    assert repeat.status == "rejected"
    assert (
        repeat.error_code
        == "repeat_transfer_requires_privileged_principal_and_reason"
    )

    privileged = service.request_ownership_takeover(
        request=TakeoverRequest(
            project_key=_PROJECT,
            story_id=story_id,
            session_id="sess-C",
            principal_type="human_cli",
            op_id="op-ping-privileged-request",
            reason="audited operator correction",
            worktree_roots=[f"T:/worktrees/{story_id}/sess-C"],
        ),
    )
    assert privileged.status == "offered"
    active = load_active_run_ownership_record_global(_PROJECT, story_id)
    assert active is not None
    assert active.owner_session_id == "sess-B"


@pytest.mark.integration
def test_active_owner_self_takeover_is_rejected_and_foreign_gets_no_exemption(
    postgres_backend_env: object,
    tmp_path: Path,
) -> None:
    del postgres_backend_env
    story_id = _story_id(1491)
    run_id = "run-self-rebind"
    service = _service(ident="inst-self-rebind")
    _seed_story_context(tmp_path, story_id)
    _admit_run(service, story_id=story_id, run_id=run_id, session_id="sess-A")
    _seed_pushed_only_evidence(story_id=story_id, run_id=run_id)

    own = service.request_ownership_takeover(
        request=TakeoverRequest(
            project_key=_PROJECT,
            story_id=story_id,
            session_id="sess-A",
            principal_type="orchestrator",
            op_id="op-self-rebind",
            reason="resume own orphaned work",
            worktree_roots=[f"T:/worktrees/{story_id}/sess-A"],
        ),
    )
    assert own.status == "rejected"
    assert own.error_code == "requester_already_owner"
    assert own.pending_human_approval is None

    foreign = service.request_ownership_takeover(
        request=TakeoverRequest(
            project_key=_PROJECT,
            story_id=story_id,
            session_id="sess-B",
            principal_type="orchestrator",
            op_id="op-foreign-rebind",
            reason="foreign takeover",
            worktree_roots=[f"T:/worktrees/{story_id}/sess-B"],
        ),
    )
    assert foreign.status == "pending_human_approval"
    assert foreign.pending_human_approval is not None


@pytest.mark.integration
def test_official_setup_rebind_supersedes_only_revoked_one_slot_binding(
    postgres_backend_env: object,
    tmp_path: Path,
) -> None:
    del postgres_backend_env
    old_story = _story_id(1492)
    new_story = _story_id(1493)
    service = _service(ident="inst-revoked-rebind")
    _seed_story_context(tmp_path, old_story)
    _admit_run(service, story_id=old_story, run_id="run-old", session_id="sess-A")
    _run_real_invalidating_predecessor(
        operation_kind="story_exit",
        story_id=old_story,
        run_id="run-old",
        service=service,
        tmp_path=tmp_path,
    )
    revoked = load_session_run_binding_global("sess-A")
    assert revoked is not None
    assert revoked.status == "revoked"
    assert revoked.revocation_reason == "story_ended"

    _seed_story_context(tmp_path, new_story)
    rebound = service.start_phase(
        run_id="run-new",
        phase="setup",
        request=_phase_request(
            story_id=new_story,
            op_id="op-official-rebind",
            session_id="sess-A",
        ),
    )

    assert rebound.status == "committed"
    active_binding = load_session_run_binding_global("sess-A")
    assert active_binding is not None
    assert active_binding.status == "active"
    assert active_binding.story_id == new_story
    assert active_binding.run_id == "run-new"


@pytest.mark.integration
def test_setup_after_real_reset_admits_new_run_and_supersedes_revoked_binding(
    postgres_backend_env: object,
    tmp_path: Path,
) -> None:
    del postgres_backend_env
    story_id = _story_id(1494)
    service = _service(ident="inst-reset-restart")
    _seed_story_context(tmp_path, story_id)
    _admit_run(service, story_id=story_id, run_id="run-reset-old", session_id="sess-A")
    holder = boot_backend_instance_identity_global("inst-reset-inflight-holder", _NOW)
    save_control_plane_operation_global(
        ControlPlaneOperationRecord(
            op_id="op-inflight-before-reset",
            project_key=_PROJECT,
            story_id=story_id,
            run_id="run-reset-old",
            session_id="sess-A",
            operation_kind="phase_complete",
            phase="implementation",
            status="claimed",
            response_payload={"status": "claimed"},
            created_at=_NOW,
            updated_at=_NOW,
            claimed_by="owner-inflight-before-reset",
            claimed_at=_NOW,
            operation_epoch=1,
            backend_instance_id=holder.backend_instance_id,
            instance_incarnation=holder.instance_incarnation,
            declared_serialization_scope=f"{_PROJECT}:{story_id}",
        )
    )
    assert acquire_object_mutation_claim_global(
        project_key=_PROJECT,
        serialization_scope="story",
        scope_key=story_id,
        op_id="op-inflight-before-reset",
        backend_instance_id=holder.backend_instance_id,
        instance_incarnation=holder.instance_incarnation,
        acquired_at=_NOW,
    )
    _run_real_invalidating_predecessor(
        operation_kind="story_reset",
        story_id=story_id,
        run_id="run-reset-old",
        service=service,
        tmp_path=tmp_path,
    )

    quiesced = load_control_plane_operation_global("op-inflight-before-reset")
    assert quiesced is not None
    assert quiesced.status == "failed"
    assert quiesced.response_payload["admin_note"].startswith(
        "quiesced_by_story_reset:"
    )
    after_reset = boot_backend_instance_identity_global(
        "inst-after-reset-claim-probe",
        _LATER,
    )
    assert acquire_object_mutation_claim_global(
        project_key=_PROJECT,
        serialization_scope="story",
        scope_key=story_id,
        op_id="op-after-reset-claim-probe",
        backend_instance_id=after_reset.backend_instance_id,
        instance_incarnation=after_reset.instance_incarnation,
        acquired_at=_LATER,
    )
    assert delete_object_mutation_claim_global(
        _PROJECT,
        "story",
        story_id,
        "op-after-reset-claim-probe",
    )

    old_mutation = service.complete_phase(
        run_id="run-reset-old",
        phase="implementation",
        request=_phase_request(
            story_id=story_id,
            op_id="op-old-run-after-reset",
            session_id="sess-A",
        ),
    )
    assert old_mutation.status == "rejected"
    assert old_mutation.error_code == "story_reset"

    restarted = service.start_phase(
        run_id="run-reset-new",
        phase="setup",
        request=_phase_request(
            story_id=story_id,
            op_id="op-setup-after-reset",
            session_id="sess-A",
        ),
    )

    assert restarted.status == "committed"
    active = load_active_run_ownership_record_global(_PROJECT, story_id)
    assert active is not None
    assert active.run_id == "run-reset-new"
    old = load_run_ownership_record_global(_PROJECT, story_id, "run-reset-old")
    assert old is not None
    assert old.status is OwnershipStatus.RESET


def _set_challenge_expires_at(challenge_id: str, expires_at: datetime) -> None:
    with postgres_store._connect_global() as conn:  # noqa: SLF001 -- test setup
        conn.execute(
            """
            UPDATE takeover_challenges
            SET expires_at = ?
            WHERE challenge_id = ?
            """,
            (expires_at.isoformat(), challenge_id),
        )


def _force_approval_denied(approval_id: str, *, decided_at: datetime) -> None:
    with postgres_store._connect_global() as conn:  # noqa: SLF001 -- race setup
        conn.execute(
            """
            UPDATE takeover_approvals
            SET status = 'denied',
                decided_at = ?,
                decided_by_session_id = 'sess-race-denier',
                decision_reason = 'concurrent deny'
            WHERE approval_id = ?
            """,
            (decided_at.isoformat(), approval_id),
        )


@pytest.mark.integration
def test_takeover_confirm_global_commits_all_side_effects_atomically(
    postgres_backend_env: object,
) -> None:
    del postgres_backend_env
    insert_run_ownership_record_global(
        RunOwnershipRecord(
            project_key="tenant-a",
            story_id="AG3-148",
            run_id="run-148",
            owner_session_id="sess-A",
            ownership_epoch=1,
            status=OwnershipStatus.ACTIVE,
            acquired_via=OwnershipAcquisition.SETUP,
            acquired_at=_NOW,
            audit_ref="op-setup",
        )
    )
    save_session_run_binding_global(
        SessionRunBindingRecord(
            session_id="sess-A",
            project_key="tenant-a",
            story_id="AG3-148",
            run_id="run-148",
            principal_type="orchestrator",
            worktree_roots=("T:/worktrees/a",),
            binding_version="1",
            updated_at=_NOW,
        )
    )
    save_story_execution_lock_global(
        StoryExecutionLockRecord(
            project_key="tenant-a",
            story_id="AG3-148",
            run_id="run-148",
            lock_type="story_execution",
            status="ACTIVE",
            worktree_roots=("T:/worktrees/a",),
            binding_version="1",
            activated_at=_NOW,
            updated_at=_NOW,
        )
    )
    new_binding = SessionRunBindingRecord(
        session_id="sess-B",
        project_key="tenant-a",
        story_id="AG3-148",
        run_id="run-148",
        principal_type="strategist",
        worktree_roots=("T:/worktrees/b",),
        binding_version="2",
        updated_at=_NOW,
    )
    lock = StoryExecutionLockRecord(
        project_key="tenant-a",
        story_id="AG3-148",
        run_id="run-148",
        lock_type="story_execution",
        status="ACTIVE",
        worktree_roots=("T:/worktrees/b",),
        binding_version="2",
        activated_at=_NOW,
        updated_at=_NOW,
    )
    op = _op_record(new_binding)
    challenge = _challenge_record(
        challenge_id="challenge-op",
        request_op_id="op-request",
        project_key="tenant-a",
        story_id="AG3-148",
        run_id="run-148",
    )
    insert_takeover_challenge_global(challenge)
    save_control_plane_operation_global(
        _request_op_record(
            op_id=challenge.request_op_id,
            project_key=challenge.project_key,
            story_id=challenge.story_id,
            run_id=challenge.run_id,
            session_id=challenge.requesting_session_id,
            status="pending_human_approval",
        )
    )

    commit_takeover_confirm_global(
        op,
        expected_basis=OwnershipBasis("sess-A", 1, "1"),
        revoked_binding=SessionRunBindingRecord(
            session_id="sess-A",
            project_key="tenant-a",
            story_id="AG3-148",
            run_id="run-148",
            principal_type="orchestrator",
            worktree_roots=("T:/worktrees/a",),
            binding_version="1",
            updated_at=_NOW,
            status=BindingStatus.REVOKED.value,
            revocation_reason=OWNERSHIP_TRANSFERRED_REVOCATION_REASON,
        ),
        new_binding=new_binding,
        locks=(lock,),
        transfers=(
            TakeoverTransferRecord(
                project_key="tenant-a",
                story_id="AG3-148",
                run_id="run-148",
                ownership_epoch=2,
                repo_id="backend",
                takeover_base_sha="abc123",
                last_push_at=_NOW,
                base_quality="pushed",
                challenge_ref=challenge.challenge_id,
                confirm_ref="op-confirm",
            ),
        ),
        events=(
            ExecutionEventRecord(
                project_key="tenant-a",
                story_id="AG3-148",
                run_id="run-148",
                event_id="evt-confirm",
                event_type=EventType.SESSION_RUN_BINDING_TRANSFERRED.value,
                occurred_at=_NOW,
                source_component="project_edge_client",
                severity="info",
                phase="ownership",
                payload={
                    "previous_owner_session_id": "sess-A",
                    "new_owner_session_id": "sess-B",
                    "ownership_epoch": 2,
                },
            ),
        ),
        terminal_records=TakeoverConfirmTerminalRecords(
            challenge=_terminal_challenge_record(challenge, terminal_op_id=op.op_id),
            request_op_record=_request_op_record(
                op_id=challenge.request_op_id,
                project_key=challenge.project_key,
                story_id=challenge.story_id,
                run_id=challenge.run_id,
                session_id=challenge.requesting_session_id,
                status="approved",
                finalized_at=_NOW,
            ),
        ),
    )

    active = load_active_run_ownership_record_global("tenant-a", "AG3-148")
    assert active is not None
    assert active.owner_session_id == "sess-B"
    assert active.ownership_epoch == 2
    assert active.status is OwnershipStatus.ACTIVE
    old_binding = load_session_run_binding_global("sess-A")
    assert old_binding is not None
    assert old_binding.status == "revoked"
    assert old_binding.revocation_reason == "ownership_transferred"
    assert load_session_run_binding_global("sess-B") == new_binding
    assert load_story_execution_lock_global(
        "tenant-a", "AG3-148", "run-148", "story_execution"
    ) == lock
    transfer = load_takeover_transfer_record_global(
        "tenant-a", "AG3-148", "run-148", 2, "backend"
    )
    assert transfer is not None
    assert transfer.takeover_base_sha == "abc123"
    request_op = load_control_plane_operation_global("op-request")
    assert request_op is not None
    assert request_op.status == "approved"
    events = load_execution_events_global("tenant-a", "AG3-148", run_id="run-148")
    assert [event.event_type for event in events] == [
        EventType.SESSION_RUN_BINDING_TRANSFERRED.value
    ]


@pytest.mark.integration
def test_takeover_confirm_global_approves_pending_approval_in_same_transaction(
    postgres_backend_env: object,
) -> None:
    del postgres_backend_env
    insert_run_ownership_record_global(
        RunOwnershipRecord(
            project_key="tenant-b",
            story_id="AG3-148B",
            run_id="run-148b",
            owner_session_id="sess-A2",
            ownership_epoch=1,
            status=OwnershipStatus.ACTIVE,
            acquired_via=OwnershipAcquisition.SETUP,
            acquired_at=_NOW,
            audit_ref="op-setup-2",
        )
    )
    save_session_run_binding_global(
        SessionRunBindingRecord(
            session_id="sess-A2",
            project_key="tenant-b",
            story_id="AG3-148B",
            run_id="run-148b",
            principal_type="orchestrator",
            worktree_roots=("T:/worktrees/a2",),
            binding_version="1",
            updated_at=_NOW,
        )
    )
    pending = TakeoverApprovalRecord(
        approval_id="approval-confirm-atomic",
        project_key="tenant-b",
        story_id="AG3-148B",
        run_id="run-148b",
        requested_by_session_id="sess-agent",
        requested_by_principal_type="interactive_agent",
        reason="owner unavailable",
        challenge_ref="challenge-op-2",
        status=TakeoverApprovalStatus.PENDING,
        requested_at=_NOW,
        expires_at=datetime(2026, 6, 7, 12, 0, tzinfo=UTC),
    )
    insert_takeover_approval_global(pending)
    challenge = _challenge_record(
        challenge_id=pending.challenge_ref,
        request_op_id="op-request-2",
        project_key=pending.project_key,
        story_id=pending.story_id,
        run_id=pending.run_id,
        owner_session_id="sess-A2",
    )
    insert_takeover_challenge_global(challenge)
    save_control_plane_operation_global(
        _request_op_record(
            op_id=challenge.request_op_id,
            project_key=challenge.project_key,
            story_id=challenge.story_id,
            run_id=challenge.run_id,
            session_id=challenge.requesting_session_id,
            status="pending_human_approval",
        )
    )
    approved = TakeoverApprovalRecord(
        **{
            **pending.__dict__,
            "status": TakeoverApprovalStatus.APPROVED,
            "decided_at": _NOW,
            "decided_by_session_id": "sess-human",
            "decision_reason": "human_confirm",
        }
    )
    new_binding = SessionRunBindingRecord(
        session_id="sess-B2",
        project_key="tenant-b",
        story_id="AG3-148B",
        run_id="run-148b",
        principal_type="human_bff_session",
        worktree_roots=("T:/worktrees/b2",),
        binding_version="2",
        updated_at=_NOW,
    )

    commit_takeover_confirm_global(
        (op := _op_record(new_binding, op_id="op-confirm-2")),
        expected_basis=OwnershipBasis("sess-A2", 1, "1"),
        revoked_binding=SessionRunBindingRecord(
            session_id="sess-A2",
            project_key="tenant-b",
            story_id="AG3-148B",
            run_id="run-148b",
            principal_type="orchestrator",
            worktree_roots=("T:/worktrees/a2",),
            binding_version="1",
            updated_at=_NOW,
            status=BindingStatus.REVOKED.value,
            revocation_reason=OWNERSHIP_TRANSFERRED_REVOCATION_REASON,
        ),
        new_binding=new_binding,
        locks=(),
        transfers=(),
        events=(),
        terminal_records=TakeoverConfirmTerminalRecords(
            challenge=_terminal_challenge_record(challenge, terminal_op_id=op.op_id),
            request_op_record=_request_op_record(
                op_id=challenge.request_op_id,
                project_key=challenge.project_key,
                story_id=challenge.story_id,
                run_id=challenge.run_id,
                session_id=challenge.requesting_session_id,
                status="approved",
                finalized_at=_NOW,
            ),
            approved_approval=approved,
        ),
    )

    stored = load_takeover_approval_global("approval-confirm-atomic")
    assert stored is not None
    assert stored.status is TakeoverApprovalStatus.APPROVED
    assert stored.decided_by_session_id == "sess-human"
    active = load_active_run_ownership_record_global("tenant-b", "AG3-148B")
    assert active is not None
    assert active.owner_session_id == "sess-B2"
    request_op = load_control_plane_operation_global("op-request-2")
    assert request_op is not None
    assert request_op.status == "approved"


@pytest.mark.integration
def test_takeover_confirm_global_checks_ownership_update_rowcount(
    postgres_backend_env: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del postgres_backend_env
    new_binding = SessionRunBindingRecord(
        session_id="sess-B-rowcount",
        project_key="tenant-a",
        story_id="AG3-148-rowcount",
        run_id="run-rowcount",
        principal_type="human_cli",
        worktree_roots=("T:/worktrees/rowcount",),
        binding_version="2",
        updated_at=_NOW,
    )
    op = _op_record(new_binding, op_id="op-rowcount-confirm")
    challenge = _challenge_record(
        challenge_id="challenge-rowcount",
        request_op_id="op-rowcount-request",
        project_key="tenant-a",
        story_id="AG3-148-rowcount",
        run_id="run-rowcount",
    )

    monkeypatch.setattr(
        "agentkit.backend.state_backend.postgres_store._takeover_rows."
        "_verify_takeover_confirm_cas",
        lambda *args, **kwargs: None,
    )

    with pytest.raises(OwnershipFenceViolationError, match="active ownership update"):
        commit_takeover_confirm_global(
            op,
            expected_basis=OwnershipBasis("sess-A", 1, "1"),
            revoked_binding=SessionRunBindingRecord(
                session_id="sess-A",
                project_key="tenant-a",
                story_id="AG3-148-rowcount",
                run_id="run-rowcount",
                principal_type="orchestrator",
                worktree_roots=("T:/worktrees/a",),
                binding_version="1",
                updated_at=_NOW,
                status=BindingStatus.REVOKED.value,
                revocation_reason=OWNERSHIP_TRANSFERRED_REVOCATION_REASON,
            ),
            new_binding=new_binding,
            locks=(),
            transfers=(),
            events=(),
            terminal_records=TakeoverConfirmTerminalRecords(
                challenge=_terminal_challenge_record(
                    challenge,
                    terminal_op_id=op.op_id,
                ),
                request_op_record=_request_op_record(
                    op_id=challenge.request_op_id,
                    project_key=challenge.project_key,
                    story_id=challenge.story_id,
                    run_id=challenge.run_id,
                    session_id=challenge.requesting_session_id,
                    status="approved",
                    finalized_at=_NOW,
                ),
            ),
        )
    assert _operation_row_count(op.op_id) == 0


@pytest.mark.parametrize(
    ("reconcile_case", "expected_error", "expected_status"),
    [
        ("stale", "challenge_invalidated", "invalidated"),
        ("terminal", "challenge_invalidated", "invalidated"),
        ("transient", "takeover_confirm_cas_lost", "pending"),
    ],
)
@pytest.mark.integration
def test_post_cas_loss_reconcile_classifies_all_outcomes_under_lock(
    postgres_backend_env: object,
    tmp_path: Path,
    reconcile_case: str,
    expected_error: str,
    expected_status: str,
) -> None:
    del postgres_backend_env
    story_id = _story_id(250 + len(reconcile_case))
    run_id = f"run-cas-loss-{reconcile_case}"
    _seed_story_context(tmp_path, story_id)
    setup = _service(ident=f"inst-cas-loss-{reconcile_case}-setup")
    _admit_run(setup, story_id=story_id, run_id=run_id)
    _seed_pushed_only_evidence(story_id=story_id, run_id=run_id)
    challenge_id = _request_takeover(
        setup,
        story_id=story_id,
        run_id=run_id,
        op_id=f"op-cas-loss-{reconcile_case}-request",
    )

    def lose_row_cas(*args: object, **kwargs: object) -> None:
        del args, kwargs
        if reconcile_case == "stale":
            binding = load_session_run_binding_global("sess-A")
            assert binding is not None
            save_session_run_binding_global(replace(binding, binding_version="2"))
        elif reconcile_case == "terminal":
            challenge = load_takeover_challenge_global(challenge_id)
            assert challenge is not None
            assert update_takeover_challenge_status_global(
                replace(
                    challenge,
                    status="invalidated",
                    decided_at=_LATER,
                    terminal_op_id="op-concurrent-invalidation",
                )
            )
        raise OwnershipFenceViolationError("injected confirm row CAS loss")

    result = _service(
        ident=f"inst-cas-loss-{reconcile_case}-confirm",
        commit_takeover_confirm_override=lose_row_cas,
    ).confirm_ownership_takeover(
        command=_confirm_request(
            story_id=story_id,
            challenge_id=challenge_id,
            op_id=f"op-cas-loss-{reconcile_case}-confirm",
        )
    )

    assert result.status == "rejected"
    assert result.error_code == expected_error
    challenge = load_takeover_challenge_global(challenge_id)
    assert challenge is not None
    assert challenge.status == expected_status
    assert load_takeover_transfer_record_global(
        _PROJECT,
        story_id,
        run_id,
        2,
        _REPO,
    ) is None


@pytest.mark.integration
def test_post_cas_loss_reconcile_waits_for_concurrent_binding_drift_then_invalidates(
    postgres_backend_env: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Close the second window by classifying after the concurrent binding lock."""
    del postgres_backend_env
    from agentkit.backend.state_backend.postgres_store import _takeover_rows

    story_id = _story_id(264)
    run_id = "run-cas-loss-concurrent-binding"
    _seed_story_context(tmp_path, story_id)
    setup = _service(ident="inst-cas-loss-concurrent-binding-setup")
    _admit_run(setup, story_id=story_id, run_id=run_id)
    challenge_id = _request_takeover(
        setup,
        story_id=story_id,
        run_id=run_id,
        op_id="op-cas-loss-concurrent-binding-request",
    )

    monkeypatch.setenv("AGENTKIT_STATE_POOL_MAX_SIZE", "2")
    postgres_store._dispose_pool()  # noqa: SLF001 -- enable real concurrent row locks
    binding_locked = Event()
    release_binding = Event()
    reconcile_entered = Event()
    original_lock_basis = _takeover_rows._lock_takeover_basis_rows  # noqa: SLF001

    def observed_lock_basis(*args: object, **kwargs: object) -> tuple[object, object]:
        reconcile_entered.set()
        return original_lock_basis(*args, **kwargs)

    monkeypatch.setattr(
        _takeover_rows,
        "_lock_takeover_basis_rows",
        observed_lock_basis,
    )

    def hold_binding_drift() -> None:
        with postgres_store._connect_global() as conn:  # noqa: SLF001 -- lock fixture
            cursor = conn.execute(
                """
                UPDATE session_run_bindings
                SET binding_version = '2'
                WHERE session_id = 'sess-A' AND project_key = ?
                  AND story_id = ? AND run_id = ? AND status = 'active'
                """,
                (_PROJECT, story_id, run_id),
            )
            assert cursor.rowcount == 1
            binding_locked.set()
            assert release_binding.wait(timeout=10)

    reconcile_service = _service(ident="inst-cas-loss-concurrent-binding-reconcile")
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            drift_future = pool.submit(hold_binding_drift)
            assert binding_locked.wait(timeout=10)
            reconcile_future = pool.submit(
                _reconcile_takeover_confirm_cas_loss,
                reconcile_service._repo,  # noqa: SLF001 -- row-lock integration
                command=_confirm_request(
                    story_id=story_id,
                    challenge_id=challenge_id,
                    op_id="op-cas-loss-concurrent-binding-reconcile",
                ),
                now=_NOW,
            )
            assert reconcile_entered.wait(timeout=10)
            release_binding.set()
            drift_future.result(timeout=20)
            result = reconcile_future.result(timeout=20)
    finally:
        release_binding.set()
        postgres_store._dispose_pool()  # noqa: SLF001 -- restore fixture pool shape

    assert result.error_code == "challenge_invalidated"
    challenge = load_takeover_challenge_global(challenge_id)
    assert challenge is not None
    assert challenge.status == "invalidated"
    request_operation = load_control_plane_operation_global(challenge.request_op_id)
    assert request_operation is not None
    assert request_operation.status == "invalidated"
    request_op = load_control_plane_operation_global(
        "op-cas-loss-concurrent-binding-request"
    )
    assert request_op is not None
    assert request_op.status == "invalidated"


@pytest.mark.integration
def test_t1_concurrent_takeover_confirm_same_challenge_one_commits_loser_writes_nothing(
    postgres_backend_env: object,
    tmp_path: Path,
) -> None:
    del postgres_backend_env
    story_id = _story_id(101)
    run_id = "run-t1"
    _seed_story_context(tmp_path, story_id)
    service = _service(ident="inst-t1")
    _admit_run(service, story_id=story_id, run_id=run_id)
    _seed_pushed_only_evidence(story_id=story_id, run_id=run_id)
    echo = _request_takeover(service, story_id=story_id, run_id=run_id)
    events_before_confirm = _event_count(story_id, run_id)

    def confirm(op_id: str, session_id: str) -> ControlPlaneMutationResult:
        local_service = _service(ident=f"inst-{op_id}", now=_LATER)
        return local_service._confirm_ownership_takeover_under_claim(  # noqa: SLF001
            command=_confirm_request(
                story_id=story_id,
                challenge_id=echo,
                op_id=op_id,
                session_id=session_id,
            )
        )

    def attempt(op_id: str, session_id: str) -> ControlPlaneMutationResult | str:
        try:
            return confirm(op_id, session_id)
        except OwnershipFenceViolationError:
            return "takeover_confirm_cas_lost"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(
            pool.map(
                lambda args: attempt(*args),
                (("op-t1-confirm-a", "sess-B"), ("op-t1-confirm-b", "sess-C")),
            )
        )

    committed_results = [
        result
        for result in results
        if isinstance(result, ControlPlaneMutationResult)
    ]
    assert len(committed_results) == 1
    assert committed_results[0].status == "committed"
    assert results.count("takeover_confirm_cas_lost") == 1
    active = load_active_run_ownership_record_global(_PROJECT, story_id)
    assert active is not None
    assert active.ownership_epoch == 2
    assert active.owner_session_id == "sess-B"
    losing_op_id = (
        "op-t1-confirm-a"
        if committed_results[0].op_id == "op-t1-confirm-b"
        else "op-t1-confirm-b"
    )
    assert _operation_row_count(losing_op_id) == 0
    assert _binding_exists("sess-B") == 1
    assert _binding_exists("sess-C") == 0
    assert _transfer_count(story_id, run_id) == 1
    assert _event_count(story_id, run_id) == events_before_confirm + 2


@pytest.mark.parametrize("contender", ["deny", "invalidation"])
@pytest.mark.integration
def test_canonical_lock_order_successful_confirm_and_terminalizer_complete_without_deadlock(
    postgres_backend_env: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    contender: str,
) -> None:
    """Exercise ownership/bindings->approval and approval->request->challenge concurrently."""
    del postgres_backend_env
    story_id = _story_id(260 if contender == "deny" else 262)
    run_id = f"run-lock-order-confirm-{contender}"
    _seed_story_context(tmp_path, story_id)
    setup = _service(ident="inst-lock-order-confirm-deny-setup")
    _admit_run(setup, story_id=story_id, run_id=run_id)
    _seed_pushed_only_evidence(story_id=story_id, run_id=run_id)
    challenge_id = _request_takeover(
        setup,
        story_id=story_id,
        run_id=run_id,
        session_id="sess-agent-lock-order",
        principal_type="interactive_agent",
        op_id="op-lock-order-confirm-deny-request",
    )
    approval = load_takeover_approval_for_challenge_global(challenge_id)
    assert approval is not None
    challenge = load_takeover_challenge_global(challenge_id)
    assert challenge is not None

    monkeypatch.setenv("AGENTKIT_STATE_POOL_MAX_SIZE", "2")
    postgres_store._dispose_pool()  # noqa: SLF001 -- enable real concurrent row locks
    confirm_holds_approval = Event()
    contender_started = Event()

    def pause_confirm_after_approval(step: str) -> None:
        if step == "approval_approve":
            confirm_holds_approval.set()
            assert contender_started.wait(timeout=10)

    confirm_service = _service(
        ident="inst-lock-order-confirm",
        fault_after_step=pause_confirm_after_approval,
    )
    deny_service = _service(ident="inst-lock-order-deny")

    def confirm() -> ControlPlaneMutationResult | str:
        try:
            return confirm_service._confirm_ownership_takeover_under_claim(  # noqa: SLF001
                _confirm_request(
                    story_id=story_id,
                    challenge_id=challenge_id,
                    op_id="op-lock-order-confirm",
                    session_id="sess-agent-lock-order",
                )
            )
        except OwnershipFenceViolationError:
            return "confirm_cas_lost"

    def deny() -> ControlPlaneMutationResult | str:
        assert confirm_holds_approval.wait(timeout=10)
        contender_started.set()
        try:
            if contender == "deny":
                return deny_service._deny_ownership_takeover_under_claim(  # noqa: SLF001
                    _deny_request(
                        story_id=story_id,
                        approval_id=approval.approval_id,
                        op_id="op-lock-order-deny",
                    )
                )
            return _commit_takeover_invalidation(
                deny_service._repo,  # noqa: SLF001 -- row-lock integration
                command=_confirm_request(
                    story_id=story_id,
                    challenge_id=challenge_id,
                    op_id="op-lock-order-invalidation",
                    session_id="sess-agent-lock-order",
                ),
                challenge=challenge,
                approval=approval,
                now=_NOW,
            )
        except OwnershipFenceViolationError:
            return f"{contender}_cas_lost"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = (pool.submit(confirm), pool.submit(deny))
            outcomes = tuple(future.result(timeout=20) for future in futures)
    finally:
        postgres_store._dispose_pool()  # noqa: SLF001 -- restore fixture pool shape

    assert len(outcomes) == 2
    assert isinstance(outcomes[0], ControlPlaneMutationResult)
    assert outcomes[0].status == "committed"
    stored_challenge = load_takeover_challenge_global(challenge_id)
    assert stored_challenge is not None
    assert stored_challenge.status == "confirmed"


@pytest.mark.integration
def test_canonical_lock_order_deny_invalidation_and_reconcile_complete_without_deadlock(
    postgres_backend_env: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run all approval->request->challenge subsequences against reconcile locks."""
    del postgres_backend_env
    story_id = _story_id(261)
    run_id = "run-lock-order-terminalizers"
    _seed_story_context(tmp_path, story_id)
    setup = _service(ident="inst-lock-order-terminalizers-setup")
    _admit_run(setup, story_id=story_id, run_id=run_id)
    _seed_pushed_only_evidence(story_id=story_id, run_id=run_id)
    challenge_id = _request_takeover(
        setup,
        story_id=story_id,
        run_id=run_id,
        session_id="sess-agent-terminalizers",
        principal_type="interactive_agent",
        op_id="op-lock-order-terminalizers-request",
    )
    approval = load_takeover_approval_for_challenge_global(challenge_id)
    binding = load_session_run_binding_global("sess-A")
    assert approval is not None
    assert binding is not None
    save_session_run_binding_global(replace(binding, binding_version="2"))

    monkeypatch.setenv("AGENTKIT_STATE_POOL_MAX_SIZE", "3")
    postgres_store._dispose_pool()  # noqa: SLF001 -- enable real concurrent row locks
    deny_service = _service(ident="inst-lock-order-terminalizers-deny")
    invalidate_service = _service(ident="inst-lock-order-terminalizers-invalidate")
    reconcile_service = _service(ident="inst-lock-order-terminalizers-reconcile")

    def run_and_classify(call: Callable[[], ControlPlaneMutationResult]) -> str:
        try:
            return call().error_code or "committed"
        except OwnershipFenceViolationError:
            return "cas_lost"

    deny_command = _deny_request(
        story_id=story_id,
        approval_id=approval.approval_id,
        op_id="op-lock-order-terminalizers-deny",
    )
    invalidation_command = _confirm_request(
        story_id=story_id,
        challenge_id=challenge_id,
        op_id="op-lock-order-terminalizers-invalidate",
        session_id="sess-agent-terminalizers",
    )
    reconcile_command = _confirm_request(
        story_id=story_id,
        challenge_id=challenge_id,
        op_id="op-lock-order-terminalizers-reconcile",
        session_id="sess-agent-terminalizers",
    )
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = (
                pool.submit(
                    run_and_classify,
                    lambda: deny_service._deny_ownership_takeover_under_claim(  # noqa: SLF001
                        deny_command
                    ),
                ),
                pool.submit(
                    run_and_classify,
                    lambda: invalidate_service._confirm_ownership_takeover_under_claim(  # noqa: SLF001
                        invalidation_command
                    ),
                ),
                pool.submit(
                    run_and_classify,
                    lambda: _reconcile_takeover_confirm_cas_loss(
                        reconcile_service._repo,  # noqa: SLF001 -- row-lock integration
                        command=reconcile_command,
                        now=_NOW,
                    ),
                ),
            )
            outcomes = tuple(future.result(timeout=20) for future in futures)
    finally:
        postgres_store._dispose_pool()  # noqa: SLF001 -- restore fixture pool shape

    assert len(outcomes) == 3
    challenge = load_takeover_challenge_global(challenge_id)
    assert challenge is not None
    assert challenge.status in {"denied", "invalidated"}
    assert challenge.status != "pending"


@pytest.mark.parametrize("fault_step", _FAULT_STEPS)
@pytest.mark.integration
def test_t2_takeover_confirm_fault_injection_rolls_back_each_write_step(
    postgres_backend_env: object,
    tmp_path: Path,
    fault_step: str,
) -> None:
    del postgres_backend_env
    story_id = _story_id(200 + _FAULT_STEPS.index(fault_step))
    run_id = f"run-{abs(hash(fault_step))}"
    _seed_story_context(tmp_path, story_id)
    setup_service = _service(ident=f"inst-t2-setup-{fault_step}")
    _admit_run(setup_service, story_id=story_id, run_id=run_id)
    _seed_pushed_only_evidence(story_id=story_id, run_id=run_id)
    pending_result = setup_service.request_ownership_takeover(
        request=TakeoverRequest(
            project_key=_PROJECT,
            story_id=story_id,
            session_id="sess-agent",
            principal_type="interactive_agent",
            op_id=f"op-t2-request-{fault_step}",
            reason="owner unavailable",
            worktree_roots=[f"T:/worktrees/{story_id}/agent"],
        )
    )
    assert pending_result.pending_human_approval is not None
    approval_id = pending_result.pending_human_approval.approval_id
    pending = load_takeover_approval_global(approval_id)
    assert pending is not None
    echo = _challenge_id_from_current(story_id, pending.challenge_ref)
    before = _state_snapshot(story_id, run_id, approval_id)

    def fault_hook(step: str) -> None:
        if step == fault_step:
            raise RuntimeError(f"fault after {step}")

    service = _service(
        ident=f"inst-t2-fault-{fault_step}",
        now=_LATER,
        fault_after_step=fault_hook,
    )
    with pytest.raises(RuntimeError, match="fault after"):
        service.confirm_ownership_takeover(
            command=_confirm_request(
                story_id=story_id,
                challenge_id=echo,
                op_id=f"op-t2-confirm-{fault_step}",
            )
        )

    assert _state_snapshot(story_id, run_id, approval_id) == before
    assert _operation_row_count(f"op-t2-confirm-{fault_step}") == 0


@pytest.mark.parametrize("fault_step", _DENY_FAULT_STEPS)
@pytest.mark.integration
def test_takeover_deny_fault_injection_rolls_back_each_write_step(
    postgres_backend_env: object,
    tmp_path: Path,
    fault_step: str,
) -> None:
    del postgres_backend_env
    story_id = _story_id(280 + _DENY_FAULT_STEPS.index(fault_step))
    run_id = f"run-deny-fault-{_DENY_FAULT_STEPS.index(fault_step)}"
    _seed_story_context(tmp_path, story_id)
    setup = _service(ident=f"inst-deny-fault-{fault_step}-setup")
    _admit_run(setup, story_id=story_id, run_id=run_id)
    pending_result = setup.request_ownership_takeover(
        request=TakeoverRequest(
            project_key=_PROJECT,
            story_id=story_id,
            session_id="sess-agent-deny-fault",
            principal_type="interactive_agent",
            op_id=f"op-deny-fault-{fault_step}-request",
            reason="owner unavailable",
            worktree_roots=[f"T:/worktrees/{story_id}/agent"],
        )
    )
    assert pending_result.pending_human_approval is not None
    approval_id = pending_result.pending_human_approval.approval_id
    approval = load_takeover_approval_global(approval_id)
    assert approval is not None
    before = _state_snapshot(story_id, run_id, approval_id)
    challenge_before = load_takeover_challenge_global(approval.challenge_ref)
    request_before = load_control_plane_operation_global(
        f"op-deny-fault-{fault_step}-request"
    )

    def fault_hook(step: str) -> None:
        if step == fault_step:
            raise RuntimeError(f"fault after {step}")

    service = _service(
        ident=f"inst-deny-fault-{fault_step}",
        deny_fault_after_step=fault_hook,
    )
    with pytest.raises(RuntimeError, match="fault after"):
        service.deny_ownership_takeover(
            command=_deny_request(
                story_id=story_id,
                approval_id=approval_id,
                op_id=f"op-deny-fault-{fault_step}",
            )
        )

    assert _state_snapshot(story_id, run_id, approval_id) == before
    assert load_takeover_challenge_global(approval.challenge_ref) == challenge_before
    assert load_control_plane_operation_global(
        f"op-deny-fault-{fault_step}-request"
    ) == request_before
    assert _operation_row_count(f"op-deny-fault-{fault_step}") == 0


@pytest.mark.parametrize("fault_step", _RECONCILE_FAULT_STEPS)
@pytest.mark.integration
def test_takeover_cas_loss_reconcile_fault_releases_claim_and_rolls_back_each_write_step(
    postgres_backend_env: object,
    tmp_path: Path,
    fault_step: str,
) -> None:
    del postgres_backend_env
    story_id = _story_id(290 + _RECONCILE_FAULT_STEPS.index(fault_step))
    run_id = f"run-reconcile-fault-{_RECONCILE_FAULT_STEPS.index(fault_step)}"
    _seed_story_context(tmp_path, story_id)
    setup = _service(ident=f"inst-reconcile-fault-{fault_step}-setup")
    _admit_run(setup, story_id=story_id, run_id=run_id)
    _seed_pushed_only_evidence(story_id=story_id, run_id=run_id)
    pending_result = setup.request_ownership_takeover(
        request=TakeoverRequest(
            project_key=_PROJECT,
            story_id=story_id,
            session_id="sess-agent-reconcile-fault",
            principal_type="interactive_agent",
            op_id=f"op-reconcile-fault-{fault_step}-request",
            reason="owner unavailable",
            worktree_roots=[f"T:/worktrees/{story_id}/agent"],
        )
    )
    assert pending_result.pending_human_approval is not None
    approval_id = pending_result.pending_human_approval.approval_id
    approval = load_takeover_approval_global(approval_id)
    assert approval is not None
    before = _state_snapshot(story_id, run_id, approval_id)
    challenge_before = load_takeover_challenge_global(approval.challenge_ref)
    request_before = load_control_plane_operation_global(
        f"op-reconcile-fault-{fault_step}-request"
    )

    def fault_hook(step: str) -> None:
        if step == fault_step:
            raise RuntimeError(f"fault after {step}")

    def lose_confirm_cas(*args: object, **kwargs: object) -> None:
        del args, kwargs
        binding = load_session_run_binding_global("sess-A")
        assert binding is not None
        save_session_run_binding_global(replace(binding, binding_version="2"))
        raise OwnershipFenceViolationError("injected confirm row CAS loss")

    service = _service(
        ident=f"inst-reconcile-fault-{fault_step}-confirm",
        reconcile_fault_after_step=fault_hook,
        commit_takeover_confirm_override=lose_confirm_cas,
    )
    with pytest.raises(RuntimeError, match="fault after"):
        service.confirm_ownership_takeover(
            command=_confirm_request(
                story_id=story_id,
                challenge_id=approval.challenge_ref,
                op_id=f"op-reconcile-fault-{fault_step}",
            )
        )

    assert _state_snapshot(story_id, run_id, approval_id) == before
    assert load_takeover_challenge_global(approval.challenge_ref) == challenge_before
    assert load_control_plane_operation_global(
        f"op-reconcile-fault-{fault_step}-request"
    ) == request_before
    assert _operation_row_count(f"op-reconcile-fault-{fault_step}") == 0
    follower = boot_backend_instance_identity_global(
        f"inst-reconcile-fault-{fault_step}-follower",
        _LATER,
    )
    assert acquire_object_mutation_claim_global(
        project_key=_PROJECT,
        serialization_scope="story",
        scope_key=story_id,
        op_id=f"op-after-reconcile-fault-{fault_step}",
        backend_instance_id=follower.backend_instance_id,
        instance_incarnation=follower.instance_incarnation,
        acquired_at=_LATER,
    ), "the failed reconcile must not leave the story mutation-blocked"
    assert delete_object_mutation_claim_global(
        _PROJECT,
        "story",
        story_id,
        f"op-after-reconcile-fault-{fault_step}",
    )


@pytest.mark.integration
def test_t4_expired_approval_confirm_rejects_and_only_lazy_expiry_is_written(
    postgres_backend_env: object,
    tmp_path: Path,
) -> None:
    del postgres_backend_env
    story_id = _story_id(104)
    run_id = "run-t4"
    _seed_story_context(tmp_path, story_id)
    setup_service = _service(ident="inst-t4-setup")
    _admit_run(setup_service, story_id=story_id, run_id=run_id)
    _seed_pushed_only_evidence(story_id=story_id, run_id=run_id)
    pending_result = setup_service.request_ownership_takeover(
        request=TakeoverRequest(
            project_key=_PROJECT,
            story_id=story_id,
            session_id="sess-agent-t4",
            principal_type="interactive_agent",
            op_id="op-t4-request",
            reason="owner unavailable",
            worktree_roots=[f"T:/worktrees/{story_id}/agent"],
        )
    )
    assert pending_result.pending_human_approval is not None
    approval_id = pending_result.pending_human_approval.approval_id
    pending = load_takeover_approval_global(approval_id)
    assert pending is not None
    echo = _challenge_id_from_current(story_id, pending.challenge_ref)
    before = _state_snapshot(story_id, run_id, approval_id)
    service = _service(ident="inst-t4-confirm", now=_EXPIRED_NOW)

    result = service.confirm_ownership_takeover(
        command=_confirm_request(
            story_id=story_id,
            challenge_id=echo,
            op_id="op-t4-confirm",
        )
    )

    assert result.status == "rejected"
    assert result.error_code == "approval_not_approved"
    after = _state_snapshot(story_id, run_id, approval_id)
    assert after == {
        **before,
        "approval_status": "expired",
        "approval_decided": True,
        "events": before["events"] + 1,
    }
    confirm_op = load_control_plane_operation_global("op-t4-confirm")
    assert confirm_op is not None
    assert confirm_op.status == "rejected"
    request_op = load_control_plane_operation_global("op-t4-request")
    assert request_op is not None
    assert request_op.status == "expired"
    challenge = load_takeover_challenge_global(pending.challenge_ref)
    assert challenge is not None
    assert challenge.status == "expired"
    approval_events = _event_payloads(story_id, run_id, EventType.TAKEOVER_APPROVAL_CHANGED)
    assert approval_events[-1]["approval"]["status"] == "expired"


@pytest.mark.integration
def test_human_bff_takeover_deny_persists_denied_event_and_blocks_later_confirm(
    postgres_backend_env: object,
    tmp_path: Path,
) -> None:
    del postgres_backend_env
    story_id = _story_id(204)
    run_id = "run-deny"
    _seed_story_context(tmp_path, story_id)
    service = _service(ident="inst-deny-setup")
    _admit_run(service, story_id=story_id, run_id=run_id)
    _seed_pushed_only_evidence(story_id=story_id, run_id=run_id)
    pending_result = service.request_ownership_takeover(
        request=TakeoverRequest(
            project_key=_PROJECT,
            story_id=story_id,
            session_id="sess-agent-deny",
            principal_type="interactive_agent",
            op_id="op-deny-request",
            reason="owner unavailable",
            worktree_roots=[f"T:/worktrees/{story_id}/agent"],
        )
    )
    assert pending_result.pending_human_approval is not None
    approval_id = pending_result.pending_human_approval.approval_id
    pending = load_takeover_approval_global(approval_id)
    assert pending is not None
    echo = _challenge_id_from_current(story_id, pending.challenge_ref)
    auth = AuthMiddleware()
    app = ControlPlaneApplication(runtime_service=service, auth_middleware=auth)
    human_session = auth.session_store.create()

    response = app.handle_request(
        method="POST",
        path=f"/v1/project-edge/story-runs/{run_id}/ownership/takeover-deny",
        body=json.dumps(
            {
                "project_key": _PROJECT,
                "story_id": story_id,
                "op_id": "op-deny-decision",
                "approval_id": approval_id,
                "reason": "human denied",
            }
        ).encode(),
        request_headers={
            "Cookie": f"{auth.session_cookie_name()}={human_session.session_id}",
            auth.csrf_header_name(): human_session.csrf_token,
            "X-Project-Key": _PROJECT,
        },
    )

    assert response.status_code == HTTPStatus.OK
    assert _response_json(response)["status"] == "denied"
    stored = load_takeover_approval_global(approval_id)
    assert stored is not None
    assert stored.status is TakeoverApprovalStatus.DENIED
    assert stored.decided_by_session_id == human_session.session_id
    request_op = load_control_plane_operation_global("op-deny-request")
    assert request_op is not None
    assert request_op.status == "denied"
    assert request_op.response_payload["status"] == "denied"
    denied_challenge = load_takeover_challenge_global(pending.challenge_ref)
    assert denied_challenge is not None
    assert denied_challenge.status == "denied"
    approval_events = _event_payloads(
        story_id,
        run_id,
        EventType.TAKEOVER_APPROVAL_CHANGED,
    )
    denied_events = [
        event
        for event in approval_events
        if isinstance(event.get("approval"), dict)
        and event["approval"].get("status") == "denied"
    ]
    assert denied_events == [
        {
            "project_key": _PROJECT,
            "story_id": story_id,
            "approval_id": approval_id,
            "challenge_id": pending.challenge_ref,
            "approval": {
                "approval_id": approval_id,
                "project_key": _PROJECT,
                "story_id": story_id,
                "run_id": run_id,
                "requested_by_session_id": "sess-agent-deny",
                "requested_by_principal_type": "interactive_agent",
                "reason": "owner unavailable",
                "challenge_id": pending.challenge_ref,
                "status": "denied",
                "requested_at": _wire_time(pending.requested_at),
                "expires_at": _wire_time(pending.expires_at),
                "decided_at": _wire_time(_NOW),
                "decided_by_session_id": human_session.session_id,
                "decision_reason": "human denied",
            },
        }
    ]

    follow_up = service.confirm_ownership_takeover(
        command=_confirm_request(
            story_id=story_id,
            challenge_id=echo,
            op_id="op-denied-confirm",
        )
    )

    assert follow_up.status == "rejected"
    assert follow_up.error_code == "challenge_not_pending"
    active = load_active_run_ownership_record_global(_PROJECT, story_id)
    assert active is not None
    assert active.owner_session_id == "sess-A"
    assert active.ownership_epoch == 1
    assert _binding_exists("sess-B") == 0
    assert _operation_row_count("op-denied-confirm") == 0


@pytest.mark.integration
def test_deny_rejects_foreign_challenge_ref_as_integrity_error_without_terminalizing(
    postgres_backend_env: object,
    tmp_path: Path,
) -> None:
    del postgres_backend_env
    story_a = _story_id(272)
    story_b = _story_id(273)
    run_a = "run-deny-scope-a"
    run_b = "run-deny-scope-b"
    service = _service(ident="inst-deny-scope-setup")
    for story_id, run_id, owner_session_id in (
        (story_a, run_a, "sess-deny-scope-owner-a"),
        (story_b, run_b, "sess-deny-scope-owner-b"),
    ):
        _seed_story_context(tmp_path, story_id)
        _admit_run(
            service,
            story_id=story_id,
            run_id=run_id,
            session_id=owner_session_id,
        )
        _seed_pushed_only_evidence(story_id=story_id, run_id=run_id)
    pending = service.request_ownership_takeover(
        request=TakeoverRequest(
            project_key=_PROJECT,
            story_id=story_a,
            session_id="sess-deny-scope-agent-a",
            principal_type="interactive_agent",
            op_id="op-deny-scope-request-a",
            reason="owner unavailable",
            worktree_roots=[f"T:/worktrees/{story_a}/agent"],
        )
    )
    assert pending.pending_human_approval is not None
    approval_id = pending.pending_human_approval.approval_id
    approval = load_takeover_approval_global(approval_id)
    assert approval is not None
    original_challenge_id = approval.challenge_ref
    foreign_challenge_id = _request_takeover(
        service,
        story_id=story_b,
        run_id=run_b,
        session_id="sess-deny-scope-human-b",
        op_id="op-deny-scope-request-b",
    )
    events_a_before = _event_count(story_a, run_a)
    events_b_before = _event_count(story_b, run_b)
    with postgres_store._connect_global() as conn:  # noqa: SLF001 -- corruption fixture
        cursor = conn.execute(
            "UPDATE takeover_approvals SET challenge_ref = ? WHERE approval_id = ?",
            (foreign_challenge_id, approval_id),
        )
        assert cursor.rowcount == 1

    with pytest.raises(RuntimeError, match="violates the stored challenge scope"):
        service.deny_ownership_takeover(
            command=_deny_request(
                story_id=story_a,
                approval_id=approval_id,
                op_id="op-deny-scope-decision",
            )
        )

    stored_approval = load_takeover_approval_global(approval_id)
    original_challenge = load_takeover_challenge_global(original_challenge_id)
    foreign_challenge = load_takeover_challenge_global(foreign_challenge_id)
    request_a = load_control_plane_operation_global("op-deny-scope-request-a")
    request_b = load_control_plane_operation_global("op-deny-scope-request-b")
    assert stored_approval is not None
    assert stored_approval.status is TakeoverApprovalStatus.PENDING
    assert original_challenge is not None and original_challenge.status == "pending"
    assert foreign_challenge is not None and foreign_challenge.status == "pending"
    assert request_a is not None and request_a.status == "pending_human_approval"
    assert request_b is not None and request_b.status == "offered"
    assert _operation_row_count("op-deny-scope-decision") == 0
    assert _event_count(story_a, run_a) == events_a_before
    assert _event_count(story_b, run_b) == events_b_before


@pytest.mark.integration
def test_token_authenticated_takeover_deny_is_forbidden_and_writes_nothing(
    postgres_backend_env: object,
    tmp_path: Path,
) -> None:
    del postgres_backend_env
    story_id = _story_id(205)
    run_id = "run-deny-token"
    _seed_story_context(tmp_path, story_id)
    service = _service(ident="inst-deny-token-setup")
    _admit_run(service, story_id=story_id, run_id=run_id)
    pending_result = service.request_ownership_takeover(
        request=TakeoverRequest(
            project_key=_PROJECT,
            story_id=story_id,
            session_id="sess-agent-deny-token",
            principal_type="interactive_agent",
            op_id="op-deny-token-request",
            reason="owner unavailable",
            worktree_roots=[f"T:/worktrees/{story_id}/agent"],
        )
    )
    assert pending_result.pending_human_approval is not None
    approval_id = pending_result.pending_human_approval.approval_id
    before = _state_snapshot(story_id, run_id, approval_id)
    tokens = _InMemoryTokenRepository()
    issued = issue_project_api_token(
        project_key=_PROJECT,
        label="agent",
        repository=tokens,
    )
    app = ControlPlaneApplication(
        runtime_service=service,
        auth_middleware=AuthMiddleware(token_repository=tokens),
    )

    response = app.handle_request(
        method="POST",
        path=f"/v1/project-edge/story-runs/{run_id}/ownership/takeover-deny",
        body=json.dumps(
            {
                "project_key": _PROJECT,
                "story_id": story_id,
                "session_id": "sess-agent-deny-token",
                "principal_type": "human_cli",
                "op_id": "op-forbidden-deny",
                "approval_id": approval_id,
                "reason": "forged",
            }
        ).encode(),
        request_headers={
            "Authorization": f"Bearer {issued.plaintext_token}",
            "X-Project-Key": _PROJECT,
        },
    )

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert _response_json(response)["error_code"] == "agent_deny_forbidden"
    assert _state_snapshot(story_id, run_id, approval_id) == before
    assert _operation_row_count("op-forbidden-deny") == 0


@pytest.mark.integration
def test_t5_pending_approval_survives_backend_restart_and_remains_usable(
    postgres_backend_env: object,
    tmp_path: Path,
) -> None:
    del postgres_backend_env
    story_id = _story_id(105)
    run_id = "run-t5"
    _seed_story_context(tmp_path, story_id)
    first_service = _service(ident="inst-t5-before")
    _admit_run(first_service, story_id=story_id, run_id=run_id)
    _seed_pushed_only_evidence(story_id=story_id, run_id=run_id)
    pending_result = first_service.request_ownership_takeover(
        request=TakeoverRequest(
            project_key=_PROJECT,
            story_id=story_id,
            session_id="sess-agent-t5",
            principal_type="interactive_agent",
            op_id="op-t5-request",
            reason="owner unavailable",
            worktree_roots=[f"T:/worktrees/{story_id}/agent"],
        )
    )
    assert pending_result.pending_human_approval is not None
    approval_id = pending_result.pending_human_approval.approval_id

    restarted = _service(ident="inst-t5-after", now=_LATER)
    loaded = load_takeover_approval_global(approval_id)
    assert loaded is not None
    assert loaded.status is TakeoverApprovalStatus.PENDING
    echo = _challenge_id_from_current(story_id, loaded.challenge_ref)
    result = restarted.confirm_ownership_takeover(
        command=_confirm_request(
            story_id=story_id,
            challenge_id=echo,
            op_id="op-t5-confirm",
        )
    )

    assert result.status == "committed"
    stored = load_takeover_approval_global(approval_id)
    assert stored is not None
    assert stored.status is TakeoverApprovalStatus.APPROVED
    active = load_active_run_ownership_record_global(_PROJECT, story_id)
    assert active is not None
    assert active.owner_session_id == "sess-agent-t5"
    new_binding = load_session_run_binding_global("sess-agent-t5")
    assert new_binding is not None
    assert new_binding.principal_type == "interactive_agent"
    assert new_binding.worktree_roots == (f"T:/worktrees/{story_id}/agent",)
    assert load_session_run_binding_global("sess-B") is None
    replayed_request = restarted.get_operation("op-t5-request")
    assert replayed_request is not None
    assert replayed_request.status == "approved"


@pytest.mark.integration
def test_agent_initiated_challenge_resolves_approval_without_client_hint(
    postgres_backend_env: object,
    tmp_path: Path,
) -> None:
    del postgres_backend_env
    story_id = _story_id(213)
    run_id = "run-agent-approval-required"
    _seed_story_context(tmp_path, story_id)
    service = _service(ident="inst-agent-approval-required")
    _admit_run(service, story_id=story_id, run_id=run_id)
    _seed_pushed_only_evidence(story_id=story_id, run_id=run_id)
    pending_result = service.request_ownership_takeover(
        request=TakeoverRequest(
            project_key=_PROJECT,
            story_id=story_id,
            session_id="sess-agent-required",
            principal_type="interactive_agent",
            op_id="op-agent-required-request",
            reason="owner unavailable",
            worktree_roots=[f"T:/worktrees/{story_id}/agent"],
        )
    )
    assert pending_result.pending_human_approval is not None
    approval_id = pending_result.pending_human_approval.approval_id
    approval = load_takeover_approval_global(approval_id)
    assert approval is not None

    result = service.confirm_ownership_takeover(
        command=_confirm_request(
            story_id=story_id,
            challenge_id=_challenge_id_from_current(story_id, approval.challenge_ref),
            op_id="op-agent-required-confirm",
        )
    )

    assert result.status == "committed"
    active = load_active_run_ownership_record_global(_PROJECT, story_id)
    assert active is not None
    assert active.owner_session_id == "sess-agent-required"
    assert load_session_run_binding_global("sess-agent-required") is not None
    stored = load_takeover_approval_global(approval_id)
    assert stored is not None
    assert stored.status is TakeoverApprovalStatus.APPROVED
    assert load_takeover_transfer_record_global(_PROJECT, story_id, run_id, 2, _REPO) is not None


@pytest.mark.integration
def test_expired_direct_challenge_is_invalidated_after_ownership_drift(
    postgres_backend_env: object,
    tmp_path: Path,
) -> None:
    del postgres_backend_env
    story_id = _story_id(270)
    run_id = "run-expired-direct-ownership-drift"
    _seed_story_context(tmp_path, story_id)
    service = _service(ident="inst-expired-direct-drift-setup")
    _admit_run(service, story_id=story_id, run_id=run_id)
    _seed_pushed_only_evidence(story_id=story_id, run_id=run_id)
    stale_challenge_id = _request_takeover(
        service,
        story_id=story_id,
        run_id=run_id,
        session_id="sess-stale-direct",
        op_id="op-expired-direct-drift-request",
    )
    foreign_challenge_id = _request_takeover(
        service,
        story_id=story_id,
        run_id=run_id,
        session_id="sess-foreign-owner",
        op_id="op-expired-direct-foreign-request",
    )
    moved = service.confirm_ownership_takeover(
        command=_confirm_request(
            story_id=story_id,
            challenge_id=foreign_challenge_id,
            op_id="op-expired-direct-foreign-confirm",
        )
    )
    assert moved.status == "committed"

    result = _service(
        ident="inst-expired-direct-drift-confirm",
        now=_NOW + timedelta(minutes=20),
    ).confirm_ownership_takeover(
        command=_confirm_request(
            story_id=story_id,
            challenge_id=stale_challenge_id,
            op_id="op-expired-direct-drift-confirm",
        )
    )

    assert result.status == "rejected"
    assert result.error_code == "challenge_invalidated"
    challenge = load_takeover_challenge_global(stale_challenge_id)
    assert challenge is not None
    assert challenge.status == "invalidated"
    request_op = load_control_plane_operation_global("op-expired-direct-drift-request")
    assert request_op is not None
    assert request_op.status == "invalidated"


@pytest.mark.integration
def test_expired_agent_challenge_is_invalidated_not_reissued_after_intervening_transfer(
    postgres_backend_env: object,
    tmp_path: Path,
) -> None:
    del postgres_backend_env
    story_id = _story_id(214)
    run_id = "run-reissue-intervening-transfer"
    _seed_story_context(tmp_path, story_id)
    service = _service(ident="inst-reissue-intervening-request")
    _admit_run(service, story_id=story_id, run_id=run_id)
    _seed_pushed_only_evidence(story_id=story_id, run_id=run_id)
    pending_result = service.request_ownership_takeover(
        request=TakeoverRequest(
            project_key=_PROJECT,
            story_id=story_id,
            session_id="sess-agent-stale",
            principal_type="interactive_agent",
            op_id="op-stale-agent-request",
            reason="owner unavailable",
            worktree_roots=[f"T:/worktrees/{story_id}/agent"],
        )
    )
    assert pending_result.pending_human_approval is not None
    stale_approval = load_takeover_approval_global(
        pending_result.pending_human_approval.approval_id
    )
    assert stale_approval is not None
    stale_echo = _challenge_id_from_current(story_id, stale_approval.challenge_ref)

    human_echo = _request_takeover(
        service,
        story_id=story_id,
        run_id=run_id,
        session_id="sess-C",
        principal_type="human_cli",
        op_id="op-transfer-c-request",
    )
    moved = service.confirm_ownership_takeover(
        command=_confirm_request(
            story_id=story_id,
            challenge_id=human_echo,
            op_id="op-transfer-c-confirm",
            session_id="sess-human-confirmer",
        )
    )
    assert moved.status == "committed"

    stale_result = _service(
        ident="inst-reissue-intervening-confirm",
        now=_NOW + timedelta(minutes=20),
    ).confirm_ownership_takeover(
        command=_confirm_request(
            story_id=story_id,
            challenge_id=stale_echo,
            op_id="op-stale-agent-confirm",
        )
    )

    assert stale_result.status == "rejected"
    assert stale_result.error_code == "challenge_invalidated"
    active = load_active_run_ownership_record_global(_PROJECT, story_id)
    assert active is not None
    assert active.owner_session_id == "sess-C"
    assert active.ownership_epoch == 2
    assert load_session_run_binding_global("sess-agent-stale") is None
    refreshed = load_takeover_approval_global(stale_approval.approval_id)
    assert refreshed is not None
    assert refreshed.status is TakeoverApprovalStatus.INVALIDATED
    assert refreshed.challenge_ref == stale_approval.challenge_ref
    assert refreshed.decided_at == _NOW + timedelta(minutes=20)
    assert refreshed.decision_reason == "challenge_invalidated"
    invalidated_challenge = load_takeover_challenge_global(stale_approval.challenge_ref)
    assert invalidated_challenge is not None
    assert invalidated_challenge.status == "invalidated"
    assert invalidated_challenge.terminal_op_id == "op-stale-agent-confirm"
    request_op = load_control_plane_operation_global("op-stale-agent-request")
    assert request_op is not None
    assert request_op.status == "invalidated"
    assert request_op.response_payload["status"] == "invalidated"
    assert request_op.response_payload["error_code"] == "challenge_invalidated"
    approval_events = [
        payload
        for payload in _event_payloads(
            story_id,
            run_id,
            EventType.TAKEOVER_APPROVAL_CHANGED,
        )
        if payload["approval_id"] == stale_approval.approval_id
    ]
    assert approval_events[-1]["approval"]["status"] == "invalidated"
    assert load_takeover_transfer_record_global(_PROJECT, story_id, run_id, 3, _REPO) is None


@pytest.mark.integration
def test_reissue_guard_invalidates_challenge_and_request_but_keeps_approved_approval(
    postgres_backend_env: object,
    tmp_path: Path,
) -> None:
    del postgres_backend_env
    story_id = _story_id(215)
    run_id = "run-reissue-approved-intervening-transfer"
    _seed_story_context(tmp_path, story_id)
    service = _service(ident="inst-reissue-approved-request")
    _admit_run(service, story_id=story_id, run_id=run_id)
    _seed_pushed_only_evidence(story_id=story_id, run_id=run_id)
    pending_result = service.request_ownership_takeover(
        request=TakeoverRequest(
            project_key=_PROJECT,
            story_id=story_id,
            session_id="sess-agent-approved-stale",
            principal_type="interactive_agent",
            op_id="op-stale-approved-agent-request",
            reason="owner unavailable",
            worktree_roots=[f"T:/worktrees/{story_id}/agent"],
        )
    )
    assert pending_result.pending_human_approval is not None
    approval = load_takeover_approval_global(
        pending_result.pending_human_approval.approval_id
    )
    assert approval is not None
    assert update_takeover_approval_status_global(
        replace(
            approval,
            status=TakeoverApprovalStatus.APPROVED,
            decided_at=_NOW + timedelta(minutes=1),
            decided_by_session_id="sess-human-approver",
            decision_reason="approved for takeover",
        )
    )
    stale_echo = _challenge_id_from_current(story_id, approval.challenge_ref)

    human_echo = _request_takeover(
        service,
        story_id=story_id,
        run_id=run_id,
        session_id="sess-C",
        principal_type="human_cli",
        op_id="op-transfer-c-approved-request",
    )
    moved = service.confirm_ownership_takeover(
        command=_confirm_request(
            story_id=story_id,
            challenge_id=human_echo,
            op_id="op-transfer-c-approved-confirm",
            session_id="sess-human-confirmer",
        )
    )
    assert moved.status == "committed"

    stale_result = _service(
        ident="inst-reissue-approved-confirm",
        now=_NOW + timedelta(minutes=20),
    ).confirm_ownership_takeover(
        command=_confirm_request(
            story_id=story_id,
            challenge_id=stale_echo,
            op_id="op-stale-approved-agent-confirm",
        )
    )

    assert stale_result.status == "rejected"
    assert stale_result.error_code == "challenge_invalidated"
    active = load_active_run_ownership_record_global(_PROJECT, story_id)
    assert active is not None
    assert active.owner_session_id == "sess-C"
    assert active.ownership_epoch == 2
    refreshed = load_takeover_approval_global(approval.approval_id)
    assert refreshed is not None
    assert refreshed.status is TakeoverApprovalStatus.APPROVED
    assert refreshed.decided_by_session_id == "sess-human-approver"
    invalidated_challenge = load_takeover_challenge_global(approval.challenge_ref)
    assert invalidated_challenge is not None
    assert invalidated_challenge.status == "invalidated"
    assert invalidated_challenge.terminal_op_id == "op-stale-approved-agent-confirm"
    request_op = load_control_plane_operation_global("op-stale-approved-agent-request")
    assert request_op is not None
    assert request_op.status == "invalidated"
    assert request_op.response_payload["error_code"] == "challenge_invalidated"
    assert load_session_run_binding_global("sess-agent-approved-stale") is None
    assert load_takeover_transfer_record_global(_PROJECT, story_id, run_id, 3, _REPO) is None


@pytest.mark.integration
def test_expired_approval_challenge_is_invalidated_after_ownership_drift(
    postgres_backend_env: object,
    tmp_path: Path,
) -> None:
    del postgres_backend_env
    story_id = _story_id(271)
    run_id = "run-expired-approval-ownership-drift"
    _seed_story_context(tmp_path, story_id)
    service = _service(ident="inst-expired-approval-drift-setup")
    _admit_run(service, story_id=story_id, run_id=run_id)
    _seed_pushed_only_evidence(story_id=story_id, run_id=run_id)
    pending_result = service.request_ownership_takeover(
        request=TakeoverRequest(
            project_key=_PROJECT,
            story_id=story_id,
            session_id="sess-expired-approval-requester",
            principal_type="interactive_agent",
            op_id="op-expired-approval-drift-request",
            reason="owner unavailable",
            worktree_roots=[f"T:/worktrees/{story_id}/agent"],
        )
    )
    assert pending_result.pending_human_approval is not None
    approval = load_takeover_approval_global(
        pending_result.pending_human_approval.approval_id
    )
    assert approval is not None
    foreign_challenge_id = _request_takeover(
        service,
        story_id=story_id,
        run_id=run_id,
        session_id="sess-expired-approval-foreign-owner",
        op_id="op-expired-approval-foreign-request",
    )
    moved = service.confirm_ownership_takeover(
        command=_confirm_request(
            story_id=story_id,
            challenge_id=foreign_challenge_id,
            op_id="op-expired-approval-foreign-confirm",
        )
    )
    assert moved.status == "committed"

    result = _service(
        ident="inst-expired-approval-drift-confirm",
        now=_EXPIRED_NOW,
    ).confirm_ownership_takeover(
        command=_confirm_request(
            story_id=story_id,
            challenge_id=approval.challenge_ref,
            op_id="op-expired-approval-drift-confirm",
        )
    )

    assert result.status == "rejected"
    assert result.error_code == "challenge_invalidated"
    challenge = load_takeover_challenge_global(approval.challenge_ref)
    assert challenge is not None
    assert challenge.status == "invalidated"
    request_op = load_control_plane_operation_global("op-expired-approval-drift-request")
    assert request_op is not None
    assert request_op.status == "invalidated"


def _run_real_invalidating_predecessor(
    *,
    operation_kind: str,
    story_id: str,
    run_id: str,
    service: ControlPlaneRuntimeService,
    tmp_path: Path,
) -> None:
    predecessor_op_id = f"op-terminal-{operation_kind}-{story_id}"
    if operation_kind == "story_exit":
        result = StoryExitService(
            control_plane_repository=ControlPlaneRuntimeRepository(),
            story_service=_StoryExitBoundary(),  # type: ignore[arg-type]
            governance=_GovernanceExitBoundary(),  # type: ignore[arg-type]
            artifact_root=tmp_path / "story-exit",
            run_state_loader=lambda _request: ExitRunState(
                project_key=_PROJECT,
                story_id=story_id,
                run_id=run_id,
                session_id="sess-A",
                human_design_required=True,
                remediation_exhausted=True,
                architecture_blockers=("human architecture decision required",),
            ),
            now_fn=lambda: _NOW,
        ).exit_story(
            StoryExitRequest(
                project_key=_PROJECT,
                story_id=story_id,
                run_id=run_id,
                session_id="sess-A",
                reason=ExitReason.SOLUTION_VIABILITY_REQUIRES_HUMAN_DESIGN,
                principal=Principal.HUMAN_CLI,
                exit_id=predecessor_op_id,
            )
        )
        assert result.exit_finalized
    elif operation_kind == "story_reset":
        ports = _ResetPhaseBoundaryPorts(
            project_key=_PROJECT,
            story_id=story_id,
            run_id=run_id,
        )
        reset_id = predecessor_op_id
        cp_repo = ControlPlaneRuntimeRepository()
        reset_service = StoryResetService(
            story_status=ports,  # type: ignore[arg-type]
            record_store=FileResetRecordStore(tmp_path / "story-reset"),
            run_scope=ports,
            escalation_evidence=ports,
            competing_operation=ports,
            fence=ResetDisownAdapter(cp_repo),
            runtime_purge=ports,
            lock_purge=ports,
            read_model_purge=ports,
            analytics_purge=ports,
            workspace=ports,
            worktree=ports,
            now_fn=lambda: _NOW,
        )
        record = reset_service.request_reset(
            StoryResetRequest(
                project_key=_PROJECT,
                story_id=story_id,
                requested_by="human_cli",
                reason="real reset predecessor",
                reset_id=reset_id,
            )
        )
        assert record.reset_id == reset_id
        result = reset_service.execute_reset(reset_id)
        assert result.clean_state.is_clean
    elif operation_kind == "story_split":
        split_story_boundary = _SplitStoryBoundary(story_id)
        split_service = StorySplitService(
            control_plane_repository=ControlPlaneRuntimeRepository(),
            story_service=split_story_boundary,  # type: ignore[arg-type]
            dependency_repository=_NoDependencies(),  # type: ignore[arg-type]
            phase_state_quiesce=_SplitPhaseBoundary(),  # type: ignore[arg-type]
            governance=_ResetPhaseBoundaryPorts(  # type: ignore[arg-type]
                project_key=_PROJECT,
                story_id=story_id,
                run_id=run_id,
            ),
            successor_export=_SuccessfulSplitExport(),  # type: ignore[arg-type]
            superseded_index=_SuccessfulSupersededIndex(),  # type: ignore[arg-type]
            stories_root=tmp_path / "stories",
            source_state_loader=lambda _request: SplitSourceState(
                scope_explosion_established=True,
                paused_with_scope_explosion=True,
                competing_admin_operation_active=False,
            ),
            saga_guard=StorySplitSagaGuard(
                freeze_store=FreezeRepository(),
                object_claim_store=ObjectMutationClaimRepository(),
                backend_instance_id="integration-instance",
                instance_incarnation=1,
                now_fn=lambda: _NOW,
            ),
            now_fn=lambda: _NOW,
        )
        plan = SplitPlan.model_validate(
            {
                "project_key": _PROJECT,
                "source_story_id": story_id,
                "reason": "scope_explosion",
                "successors": [
                    {
                        "story_id": f"{story_id}-SUCCESSOR",
                        "title": "Real split successor",
                        "scope_slice": "isolated slice",
                    }
                ],
            }
        )
        plan_text = plan.model_dump_json()
        predecessor_op_id = derive_split_id(
            _PROJECT,
            story_id,
            compute_plan_ref(plan_text),
        )
        split_result = split_service.split_story(
            StorySplitRequest(
                project_key=_PROJECT,
                source_story_id=story_id,
                plan=plan,
                plan_text=plan_text,
                reason="scope_explosion",
                requested_by="human_cli",
                run_id=run_id,
                principal=Principal.HUMAN_CLI,
            )
        )
        assert split_result.successor_ids == (f"{story_id}-SUCCESSOR",)
        assert split_story_boundary.cancelled
        assert split_result.record.successor_ids == split_result.successor_ids
    else:
        upsert_push_barrier_verdict_global(
            PushBarrierVerdict(
                project_key=_PROJECT,
                story_id=story_id,
                run_id=run_id,
                boundary_type=SyncPointBarrierType.CLOSURE_ENTRY,
                boundary_id=run_id,
                repo_id=_REPO,
                producer="control_plane.push_barrier",
                boundary_epoch=1,
                expected_head_sha=_SHA,
                server_head_sha=_SHA,
                ownership_epoch=1,
                status=PushBarrierVerdictStatus.PASSED,
                created_at=_NOW,
                updated_at=_NOW,
                resolved_at=_NOW,
                status_detail="verified",
            )
        )
        closure_service = _service(
            ident=f"inst-real-closure-{story_id}",
            push_barrier_evidence=_VerifiedPushBoundary(),
        )
        result = closure_service.complete_closure(
            run_id=run_id,
            request=ClosureCompleteRequest(
                project_key=_PROJECT,
                story_id=story_id,
                session_id="sess-A",
                op_id=predecessor_op_id,
            ),
        )
        assert result.status == "committed"

    predecessor = load_control_plane_operation_global(predecessor_op_id)
    assert predecessor is not None
    assert predecessor.operation_kind == operation_kind
    assert predecessor.status == "committed"


@pytest.mark.integration
@pytest.mark.parametrize(
    "operation_kind",
    ["story_exit", "story_reset", "story_split", "closure_complete"],
)
def test_confirm_after_terminal_predecessor_is_rejected_as_challenge_invalidated(
    postgres_backend_env: object,
    tmp_path: Path,
    operation_kind: str,
) -> None:
    del postgres_backend_env
    story_id = _story_id(132 + len(operation_kind))
    run_id = f"run-invalidating-{operation_kind}"
    _seed_story_context(tmp_path, story_id)
    service = _service(ident=f"inst-invalidating-{operation_kind}")
    _admit_run(service, story_id=story_id, run_id=run_id)
    _seed_pushed_only_evidence(story_id=story_id, run_id=run_id)
    echo = _request_takeover(
        service,
        story_id=story_id,
        run_id=run_id,
        op_id=f"op-request-{operation_kind}",
    )
    _run_real_invalidating_predecessor(
        operation_kind=operation_kind,
        story_id=story_id,
        run_id=run_id,
        service=service,
        tmp_path=tmp_path,
    )

    result = service.confirm_ownership_takeover(
        command=_confirm_request(
            story_id=story_id,
            challenge_id=echo,
            op_id=f"op-confirm-{operation_kind}",
        )
    )

    assert result.status == "rejected"
    assert result.error_code == (
        "challenge_not_pending"
        if operation_kind == "story_split"
        else "challenge_invalidated"
    )
    active = load_active_run_ownership_record_global(_PROJECT, story_id)
    if operation_kind in {"story_exit", "story_reset", "story_split"}:
        assert active is None
        historical = load_run_ownership_record_global(_PROJECT, story_id, run_id)
        assert historical is not None
        expected_status = {
            "story_exit": "ended",
            "story_reset": "reset",
            "story_split": "split",
        }[operation_kind]
        expected_reason = {
            "story_exit": "story_ended",
            "story_reset": "story_reset",
            "story_split": "story_split",
        }[operation_kind]
        assert historical.status.value == expected_status
        revoked = load_session_run_binding_global("sess-A")
        assert revoked is not None
        assert revoked.status == "revoked"
        assert revoked.revocation_reason == expected_reason
        synced = service.sync_project_edge(
            ProjectEdgeSyncRequest(
                project_key=_PROJECT,
                session_id="sess-A",
                op_id=f"op-sync-{operation_kind}",
            ),
        )
        assert synced.edge_bundle is not None
        assert synced.edge_bundle.current.operating_mode == "binding_invalid"
        assert synced.edge_bundle.session is not None
        assert synced.edge_bundle.session.revocation_reason == expected_reason
        assert synced.edge_bundle.tombstone_worktree_roots == list(
            revoked.worktree_roots,
        )
        source_mutation = service.complete_phase(
            run_id=run_id,
            phase="implementation",
            request=_phase_request(
                story_id=story_id,
                op_id=f"op-source-after-{operation_kind}",
                session_id="sess-A",
            ),
        )
        assert source_mutation.status == "rejected"
        assert source_mutation.error_code == expected_reason
        if operation_kind == "story_split":
            successor_mutation = service.complete_phase(
                run_id=f"{run_id}-successor",
                phase="implementation",
                request=_phase_request(
                    story_id=f"{story_id}-SUCCESSOR",
                    op_id="op-unowned-split-successor-mutation",
                    session_id="sess-A",
                ),
            )
            assert successor_mutation.status == "rejected"
            assert successor_mutation.error_code is None
            assert successor_mutation.phase_dispatch is not None
            assert successor_mutation.phase_dispatch.rejection_reason is not None
            assert (
                "no prior admitted start"
                in successor_mutation.phase_dispatch.rejection_reason
            )
    else:
        assert active is not None
        assert active.owner_session_id == "sess-A"
        assert active.ownership_epoch == 1
    assert load_session_run_binding_global("sess-B") is None
    assert _transfer_count(story_id, run_id) == 0
    challenge = load_takeover_challenge_global(echo)
    assert challenge is not None
    assert challenge.status == "invalidated"
    assert challenge.terminal_op_id == (
        "freeze:split_admin_freeze:1"
        if operation_kind == "story_split"
        else f"op-confirm-{operation_kind}"
    )
    request_op = load_control_plane_operation_global(f"op-request-{operation_kind}")
    assert request_op is not None
    assert request_op.status == "invalidated"
    if operation_kind == "story_split":
        assert request_op.response_payload["status"] == "invalidated"
    else:
        assert request_op.response_payload["error_code"] == "challenge_invalidated"


@pytest.mark.integration
@pytest.mark.parametrize("terminal_kind", ["story_exit", "story_split"])
def test_terminal_uow_fault_rolls_back_marker_status_and_revocation_together(
    postgres_backend_env: object,
    tmp_path: Path,
    terminal_kind: str,
) -> None:
    """R2-2: a write fault cannot leave a committed-marker-only terminal state."""
    del postgres_backend_env
    story_id = _story_id(1495 + (terminal_kind == "story_split"))
    run_id = f"run-terminal-uow-{terminal_kind}"
    _seed_story_context(tmp_path, story_id)
    setup = _service(ident=f"inst-terminal-uow-{terminal_kind}")
    _admit_run(setup, story_id=story_id, run_id=run_id)

    def fail_after_status(step: str) -> None:
        if step == "ownership_status":
            raise RuntimeError("injected terminal-uow fault")

    repository = ControlPlaneRuntimeRepository(
        commit_operation_with_side_effects=partial(
            commit_control_plane_operation_with_side_effects_global,
            fault_after_step=fail_after_status,
        )
    )
    if terminal_kind == "story_exit":
        op_id = f"op-uow-{terminal_kind}"
        service = StoryExitService(
            control_plane_repository=repository,
            story_service=_StoryExitBoundary(),  # type: ignore[arg-type]
            governance=_GovernanceExitBoundary(),  # type: ignore[arg-type]
            artifact_root=tmp_path / terminal_kind,
            run_state_loader=lambda _request: ExitRunState(
                project_key=_PROJECT,
                story_id=story_id,
                run_id=run_id,
                session_id="sess-A",
                human_design_required=True,
                remediation_exhausted=True,
                architecture_blockers=("human decision",),
            ),
            now_fn=lambda: _NOW,
        )
        with pytest.raises(RuntimeError, match="injected terminal-uow fault"):
            service.exit_story(
                StoryExitRequest(
                    project_key=_PROJECT,
                    story_id=story_id,
                    run_id=run_id,
                    session_id="sess-A",
                    reason=ExitReason.SOLUTION_VIABILITY_REQUIRES_HUMAN_DESIGN,
                    principal=Principal.HUMAN_CLI,
                    exit_id=op_id,
                )
            )
    else:
        plan = SplitPlan.model_validate(
            {
                "project_key": _PROJECT,
                "source_story_id": story_id,
                "reason": "scope_explosion",
                "successors": [
                    {
                        "story_id": f"{story_id}-SUCCESSOR",
                        "title": "Rollback successor",
                        "scope_slice": "isolated slice",
                    }
                ],
            }
        )
        plan_text = plan.model_dump_json()
        op_id = derive_split_id(_PROJECT, story_id, compute_plan_ref(plan_text))
        service = StorySplitService(
            control_plane_repository=repository,
            story_service=_SplitStoryBoundary(story_id),  # type: ignore[arg-type]
            dependency_repository=_NoDependencies(),  # type: ignore[arg-type]
            phase_state_quiesce=_SplitPhaseBoundary(),  # type: ignore[arg-type]
            governance=_UnusedSplitBoundary(),  # type: ignore[arg-type]
            successor_export=_SuccessfulSplitExport(),  # type: ignore[arg-type]
            superseded_index=_SuccessfulSupersededIndex(),  # type: ignore[arg-type]
            stories_root=tmp_path / "stories",
            source_state_loader=lambda _request: SplitSourceState(
                scope_explosion_established=True,
                paused_with_scope_explosion=True,
                competing_admin_operation_active=False,
            ),
            saga_guard=StorySplitSagaGuard(
                freeze_store=FreezeRepository(),
                object_claim_store=ObjectMutationClaimRepository(),
                backend_instance_id="integration-instance",
                instance_incarnation=1,
                now_fn=lambda: _NOW,
            ),
            now_fn=lambda: _NOW,
        )
        with pytest.raises(RuntimeError, match="injected terminal-uow fault"):
            service.split_story(
                StorySplitRequest(
                    project_key=_PROJECT,
                    source_story_id=story_id,
                    plan=plan,
                    plan_text=plan_text,
                    reason="scope_explosion",
                    requested_by="human_cli",
                    run_id=run_id,
                    principal=Principal.HUMAN_CLI,
                )
            )

    assert load_control_plane_operation_global(op_id) is None
    active = load_active_run_ownership_record_global(_PROJECT, story_id)
    assert active is not None
    assert active.status.value == "active"
    binding = load_session_run_binding_global("sess-A")
    assert binding is not None
    assert binding.status == "active"


@pytest.mark.integration
def test_backend_unknown_revocation_reason_is_generic(
    postgres_backend_env: object,
    tmp_path: Path,
) -> None:
    """R2-5: backend mutation rejection closes the reason vocabulary."""
    del postgres_backend_env
    story_id = _story_id(1497)
    run_id = "run-unknown-revocation"
    _seed_story_context(tmp_path, story_id)
    service = _service(ident="inst-unknown-revocation")
    _admit_run(service, story_id=story_id, run_id=run_id)
    _run_real_invalidating_predecessor(
        operation_kind="story_exit",
        story_id=story_id,
        run_id=run_id,
        service=service,
        tmp_path=tmp_path,
    )
    with postgres_store._connect_global() as conn:  # noqa: SLF001 -- corrupt-row probe
        conn.execute(
            "UPDATE session_run_bindings SET revocation_reason = ? WHERE session_id = ?",
            ("future_untrusted_reason", "sess-A"),
        )

    result = service.complete_phase(
        run_id=run_id,
        phase="implementation",
        request=_phase_request(
            story_id=story_id,
            op_id="op-unknown-revocation-mutation",
            session_id="sess-A",
        ),
    )

    assert result.status == "rejected"
    assert result.error_code == "session_binding_mismatch"
    assert result.phase_dispatch is not None
    assert result.phase_dispatch.rejection_reason is not None
    assert "future_untrusted_reason" not in result.phase_dispatch.rejection_reason


@pytest.mark.integration
def test_stale_push_freshness_does_not_trigger_automatic_takeover(
    postgres_backend_env: object,
    tmp_path: Path,
) -> None:
    del postgres_backend_env
    story_id = _story_id(143)
    run_id = "run-stale-freshness-no-auto"
    _seed_story_context(tmp_path, story_id)
    service = _service(ident="inst-stale-freshness-no-auto")
    _admit_run(service, story_id=story_id, run_id=run_id)
    upsert_push_freshness_record_global(
        PushFreshnessRecord(
            project_key=_PROJECT,
            story_id=story_id,
            run_id=run_id,
            repo_id=_REPO,
            last_reported_head_sha=_SHA,
            last_pushed_head_sha=_SHA,
            last_reported_at=_NOW - timedelta(days=3),
            last_sync_point_id=f"stale:{run_id}",
            last_command_id=f"{run_id}::stale::{_REPO}",
            backlog=False,
            backlog_detail=None,
        )
    )

    result = service.start_phase(
        run_id=run_id,
        phase="implementation",
        request=_phase_request(
            story_id=story_id,
            op_id="op-stale-freshness-normal-mutation",
            session_id="sess-A",
        ),
    )

    assert result.status == "committed"
    active = load_active_run_ownership_record_global(_PROJECT, story_id)
    assert active is not None
    assert active.owner_session_id == "sess-A"
    assert active.ownership_epoch == 1
    assert _transfer_count(story_id, run_id) == 0
    assert load_session_run_binding_global("sess-B") is None


@pytest.mark.integration
def test_binding_version_only_phase_drift_terminally_invalidates_challenge(
    postgres_backend_env: object,
    tmp_path: Path,
) -> None:
    del postgres_backend_env
    story_id = _story_id(244)
    run_id = "run-binding-version-drift"
    _seed_story_context(tmp_path, story_id)
    service = _service(ident="inst-binding-version-drift")
    _admit_run(service, story_id=story_id, run_id=run_id)
    _seed_pushed_only_evidence(story_id=story_id, run_id=run_id)
    challenge_id = _request_takeover(
        service,
        story_id=story_id,
        run_id=run_id,
        session_id="sess-agent-binding-drift",
        principal_type="interactive_agent",
        op_id="op-binding-drift-request",
    )
    linked_approval = load_takeover_approval_for_challenge_global(challenge_id)
    assert linked_approval is not None
    assert linked_approval.status is TakeoverApprovalStatus.PENDING

    phase_result = service.start_phase(
        run_id=run_id,
        phase="implementation",
        request=_phase_request(
            story_id=story_id,
            op_id="op-binding-drift-phase",
            session_id="sess-A",
        ),
    )
    assert phase_result.status == "committed"
    active = load_active_run_ownership_record_global(_PROJECT, story_id)
    binding = load_session_run_binding_global("sess-A")
    assert active is not None
    assert binding is not None
    assert active.owner_session_id == "sess-A"
    assert active.ownership_epoch == 1
    assert binding.binding_version == "2"

    result = service.confirm_ownership_takeover(
        command=_confirm_request(
            story_id=story_id,
            challenge_id=challenge_id,
            op_id="op-binding-drift-confirm",
        )
    )

    assert result.status == "rejected"
    assert result.error_code == "challenge_invalidated"
    stored = load_takeover_challenge_global(challenge_id)
    assert stored is not None
    assert stored.status == "invalidated"
    assert stored.terminal_op_id == "op-binding-drift-confirm"
    invalidated_approval = load_takeover_approval_global(linked_approval.approval_id)
    assert invalidated_approval is not None
    assert invalidated_approval.status is TakeoverApprovalStatus.INVALIDATED
    assert load_takeover_transfer_record_global(
        _PROJECT,
        story_id,
        run_id,
        2,
        _REPO,
    ) is None


@pytest.mark.integration
def test_takeover_invalidation_uow_fault_rolls_back_every_protocol_row(
    postgres_backend_env: object,
    tmp_path: Path,
) -> None:
    del postgres_backend_env
    story_id = _story_id(245)
    run_id = "run-invalidation-rollback"
    setup = _service(ident="inst-invalidation-rollback-setup")
    _seed_story_context(tmp_path, story_id)
    _admit_run(setup, story_id=story_id, run_id=run_id)
    _seed_pushed_only_evidence(story_id=story_id, run_id=run_id)
    challenge_id = _request_takeover(
        setup,
        story_id=story_id,
        run_id=run_id,
        session_id="sess-agent-invalidation-rollback",
        principal_type="interactive_agent",
        op_id="op-invalidation-rollback-request",
    )
    approval = load_takeover_approval_for_challenge_global(challenge_id)
    assert approval is not None
    assert setup.start_phase(
        run_id=run_id,
        phase="implementation",
        request=_phase_request(
            story_id=story_id,
            op_id="op-invalidation-rollback-phase",
            session_id="sess-A",
        ),
    ).status == "committed"
    events_before = _event_count(story_id, run_id)

    def fail_after_challenge(step: str) -> None:
        if step == "challenge_terminalize":
            raise RuntimeError("injected invalidation rollback")

    with pytest.raises(RuntimeError, match="injected invalidation rollback"):
        _service(
            ident="inst-invalidation-rollback-confirm",
            invalidation_fault_after_step=fail_after_challenge,
        ).confirm_ownership_takeover(
            command=_confirm_request(
                story_id=story_id,
                challenge_id=challenge_id,
                op_id="op-invalidation-rollback-confirm",
            )
        )

    challenge = load_takeover_challenge_global(challenge_id)
    stored_approval = load_takeover_approval_global(approval.approval_id)
    request_op = load_control_plane_operation_global("op-invalidation-rollback-request")
    assert challenge is not None and challenge.status == "pending"
    assert stored_approval is not None
    assert stored_approval.status is TakeoverApprovalStatus.PENDING
    assert request_op is not None and request_op.status == "pending_human_approval"
    assert _operation_row_count("op-invalidation-rollback-confirm") == 0
    assert _event_count(story_id, run_id) == events_before


@pytest.mark.integration
def test_takeover_confirm_respects_running_story_mutation_object_claim(
    postgres_backend_env: object,
    tmp_path: Path,
) -> None:
    del postgres_backend_env
    story_id = _story_id(144)
    run_id = "run-confirm-object-claim"
    _seed_story_context(tmp_path, story_id)
    service = _service(ident="inst-confirm-object-claim")
    _admit_run(service, story_id=story_id, run_id=run_id)
    _seed_pushed_only_evidence(story_id=story_id, run_id=run_id)
    echo = _request_takeover(
        service,
        story_id=story_id,
        run_id=run_id,
        op_id="op-confirm-claim-request",
    )
    holder = boot_backend_instance_identity_global("inst-confirm-claim-holder", _NOW)
    assert acquire_object_mutation_claim_global(
        project_key=_PROJECT,
        serialization_scope="story",
        scope_key=story_id,
        op_id="op-held-story-mutation",
        backend_instance_id=holder.backend_instance_id,
        instance_incarnation=holder.instance_incarnation,
        acquired_at=_NOW,
    )
    try:
        result = service.confirm_ownership_takeover(
            command=_confirm_request(
                story_id=story_id,
                challenge_id=echo,
                op_id="op-confirm-behind-running-mutation",
            )
        )
    finally:
        assert delete_object_mutation_claim_global(
            _PROJECT,
            "story",
            story_id,
            "op-held-story-mutation",
        )

    assert result.status == "rejected"
    assert result.error_code == "conflict"
    assert load_control_plane_operation_global("op-confirm-behind-running-mutation") is None
    active = load_active_run_ownership_record_global(_PROJECT, story_id)
    assert active is not None
    assert active.owner_session_id == "sess-A"
    assert active.ownership_epoch == 1
    assert _transfer_count(story_id, run_id) == 0
    assert load_session_run_binding_global("sess-B") is None


@pytest.mark.integration
def test_server_stored_challenge_ttl_controls_expiry_without_client_echo(
    postgres_backend_env: object,
    tmp_path: Path,
) -> None:
    del postgres_backend_env
    story_id = _story_id(206)
    run_id = "run-server-ttl"
    _seed_story_context(tmp_path, story_id)
    service = _service(ident="inst-server-ttl")
    _admit_run(service, story_id=story_id, run_id=run_id)
    _seed_pushed_only_evidence(story_id=story_id, run_id=run_id)
    echo = _request_takeover(service, story_id=story_id, run_id=run_id)
    _set_challenge_expires_at(echo, _NOW + timedelta(minutes=1))

    result = _service(
        ident="inst-server-ttl-confirm",
        now=_NOW + timedelta(minutes=5),
    ).confirm_ownership_takeover(
        command=_confirm_request(
            story_id=story_id,
            challenge_id=echo,
            op_id="op-server-ttl-confirm",
        )
    )

    assert result.status == "rejected"
    assert result.error_code == "challenge_expired"
    challenge = load_takeover_challenge_global(echo)
    assert challenge is not None
    assert challenge.status == "expired"
    request_op = load_control_plane_operation_global("op-takeover-request")
    assert request_op is not None
    assert request_op.status == "expired"


@pytest.mark.integration
def test_expired_challenge_with_valid_agent_approval_reissues_fresh_basis(
    postgres_backend_env: object,
    tmp_path: Path,
) -> None:
    del postgres_backend_env
    story_id = _story_id(207)
    run_id = "run-reissue"
    _seed_story_context(tmp_path, story_id)
    service = _service(ident="inst-reissue-request")
    _admit_run(service, story_id=story_id, run_id=run_id)
    _seed_pushed_only_evidence(story_id=story_id, run_id=run_id)
    pending_result = service.request_ownership_takeover(
        request=TakeoverRequest(
            project_key=_PROJECT,
            story_id=story_id,
            session_id="sess-agent-reissue",
            principal_type="interactive_agent",
            op_id="op-reissue-request",
            reason="owner unavailable",
            worktree_roots=[f"T:/worktrees/{story_id}/agent"],
        )
    )
    assert pending_result.pending_human_approval is not None
    approval = load_takeover_approval_global(
        pending_result.pending_human_approval.approval_id
    )
    assert approval is not None
    old_challenge_id = approval.challenge_ref
    echo = _challenge_id_from_current(story_id, old_challenge_id)

    result = _service(
        ident="inst-reissue-confirm",
        now=_NOW + timedelta(minutes=20),
    ).confirm_ownership_takeover(
        command=_confirm_request(
            story_id=story_id,
            challenge_id=echo,
            op_id="op-reissue-confirm",
        )
    )

    assert result.status == "challenge_reissued"
    assert result.takeover_challenge is not None
    refreshed = load_takeover_approval_global(approval.approval_id)
    assert refreshed is not None
    assert refreshed.status is TakeoverApprovalStatus.APPROVED
    assert refreshed.challenge_ref != old_challenge_id
    old_challenge = load_takeover_challenge_global(old_challenge_id)
    new_challenge = load_takeover_challenge_global(refreshed.challenge_ref)
    assert old_challenge is not None
    assert old_challenge.status == "expired"
    assert new_challenge is not None
    assert new_challenge.status == "pending"
    assert load_takeover_transfer_record_global(
        _PROJECT,
        story_id,
        run_id,
        2,
        _REPO,
    ) is None
    first_op = load_control_plane_operation_global("op-reissue-confirm")
    assert first_op is not None
    assert first_op.status == "challenge_reissued"
    replay = _service(
        ident="inst-reissue-replay",
        now=_NOW + timedelta(minutes=20),
    ).confirm_ownership_takeover(
        command=_confirm_request(
            story_id=story_id,
            challenge_id=old_challenge_id,
            op_id="op-reissue-confirm",
        )
    )
    assert replay.model_dump(mode="json") == result.model_dump(mode="json")

    from agentkit.backend.story_context_manager.errors import IdempotencyMismatchError

    with pytest.raises(IdempotencyMismatchError):
        _service(
            ident="inst-reissue-mismatch",
            now=_NOW + timedelta(minutes=20),
        ).confirm_ownership_takeover(
            command=_confirm_request(
                story_id=story_id,
                challenge_id=refreshed.challenge_ref,
                op_id="op-reissue-confirm",
            )
        )

    repeated = _service(
        ident="inst-reissue-repeat",
        now=_NOW + timedelta(minutes=40),
    ).confirm_ownership_takeover(
        command=_confirm_request(
            story_id=story_id,
            challenge_id=refreshed.challenge_ref,
            op_id="op-reissue-confirm-repeat",
        )
    )
    assert repeated.status == "challenge_reissued"
    twice_refreshed = load_takeover_approval_global(approval.approval_id)
    assert twice_refreshed is not None
    assert twice_refreshed.status is TakeoverApprovalStatus.APPROVED
    assert twice_refreshed.challenge_ref != refreshed.challenge_ref
    approval_events = [
        event
        for event in load_execution_events_global(_PROJECT, story_id, run_id=run_id)
        if event.event_type == EventType.TAKEOVER_APPROVAL_CHANGED.value
    ]
    assert approval_events[-1].payload["challenge_id"] == twice_refreshed.challenge_ref
    assert approval_events[-1].payload["approval"]["status"] == "approved"  # type: ignore[index]
    assert load_takeover_transfer_record_global(
        _PROJECT,
        story_id,
        run_id,
        2,
        _REPO,
    ) is None

    second = _service(
        ident="inst-reissue-second-confirm",
        now=_NOW + timedelta(minutes=41),
    ).confirm_ownership_takeover(
        command=_confirm_request(
            story_id=story_id,
            challenge_id=twice_refreshed.challenge_ref,
            op_id="op-reissue-confirm-2",
        )
    )
    assert second.status == "committed"
    new_challenge = load_takeover_challenge_global(twice_refreshed.challenge_ref)
    assert new_challenge is not None
    assert new_challenge.status == "confirmed"
    transfer = load_takeover_transfer_record_global(
        _PROJECT,
        story_id,
        run_id,
        2,
        _REPO,
    )
    assert transfer is not None
    assert transfer.challenge_ref == twice_refreshed.challenge_ref


@pytest.mark.integration
def test_takeover_reissue_uow_fault_rolls_back_old_new_approval_and_event(
    postgres_backend_env: object,
    tmp_path: Path,
) -> None:
    del postgres_backend_env
    story_id = _story_id(246)
    run_id = "run-reissue-rollback"
    _seed_story_context(tmp_path, story_id)
    setup = _service(ident="inst-reissue-rollback-setup")
    _admit_run(setup, story_id=story_id, run_id=run_id)
    _seed_pushed_only_evidence(story_id=story_id, run_id=run_id)
    challenge_id = _request_takeover(
        setup,
        story_id=story_id,
        run_id=run_id,
        session_id="sess-agent-reissue-rollback",
        principal_type="interactive_agent",
        op_id="op-reissue-rollback-request",
    )
    approval = load_takeover_approval_for_challenge_global(challenge_id)
    assert approval is not None
    events_before = _event_count(story_id, run_id)

    def fail_after_fresh_insert(step: str) -> None:
        if step == "fresh_challenge_insert":
            raise RuntimeError("injected reissue rollback")

    with pytest.raises(RuntimeError, match="injected reissue rollback"):
        _service(
            ident="inst-reissue-rollback-confirm",
            now=_NOW + timedelta(minutes=20),
            reissue_fault_after_step=fail_after_fresh_insert,
        ).confirm_ownership_takeover(
            command=_confirm_request(
                story_id=story_id,
                challenge_id=challenge_id,
                op_id="op-reissue-rollback-confirm",
            )
        )

    old = load_takeover_challenge_global(challenge_id)
    stored_approval = load_takeover_approval_global(approval.approval_id)
    assert old is not None and old.status == "pending"
    assert stored_approval is not None
    assert stored_approval.status is TakeoverApprovalStatus.PENDING
    assert stored_approval.challenge_ref == challenge_id
    assert _challenge_count_for_request("op-reissue-rollback-request") == 1
    assert _operation_row_count("op-reissue-rollback-confirm") == 0
    assert _event_count(story_id, run_id) == events_before


@pytest.mark.integration
def test_confirm_resolves_only_the_challenge_ref_linked_approval(
    postgres_backend_env: object,
    tmp_path: Path,
) -> None:
    del postgres_backend_env
    story_a = _story_id(209)
    story_b = _story_id(210)
    run_a = "run-cross-a"
    run_b = "run-cross-b"
    service = _service(ident="inst-cross-story-setup")
    for story_id, run_id, owner_session_id in (
        (story_a, run_a, "sess-cross-owner-a"),
        (story_b, run_b, "sess-cross-owner-b"),
    ):
        _seed_story_context(tmp_path, story_id)
        _admit_run(
            service,
            story_id=story_id,
            run_id=run_id,
            session_id=owner_session_id,
        )
        _seed_pushed_only_evidence(story_id=story_id, run_id=run_id)

    pending_a = service.request_ownership_takeover(
        request=TakeoverRequest(
            project_key=_PROJECT,
            story_id=story_a,
            session_id="sess-agent-cross-a",
            principal_type="interactive_agent",
            op_id="op-cross-a-request",
            reason="owner unavailable",
            worktree_roots=[f"T:/worktrees/{story_a}/agent"],
        )
    )
    pending_b = service.request_ownership_takeover(
        request=TakeoverRequest(
            project_key=_PROJECT,
            story_id=story_b,
            session_id="sess-agent-cross-b",
            principal_type="interactive_agent",
            op_id="op-cross-b-request",
            reason="owner unavailable",
            worktree_roots=[f"T:/worktrees/{story_b}/agent"],
        )
    )
    assert pending_a.pending_human_approval is not None
    assert pending_b.pending_human_approval is not None
    approval_a = load_takeover_approval_global(pending_a.pending_human_approval.approval_id)
    approval_b = load_takeover_approval_global(pending_b.pending_human_approval.approval_id)
    assert approval_a is not None
    assert approval_b is not None

    result = _service(ident="inst-cross-story-confirm", now=_LATER).confirm_ownership_takeover(
        command=_confirm_request(
            story_id=story_b,
            challenge_id=_challenge_id_from_current(story_b, approval_b.challenge_ref),
            op_id="op-cross-story-confirm",
        )
    )

    assert result.status == "committed"
    stored_a = load_takeover_approval_global(approval_a.approval_id)
    stored_b = load_takeover_approval_global(approval_b.approval_id)
    assert stored_a is not None
    assert stored_b is not None
    assert stored_a.status is TakeoverApprovalStatus.PENDING
    assert stored_b.status is TakeoverApprovalStatus.APPROVED
    assert load_takeover_transfer_record_global(_PROJECT, story_b, run_b, 2, _REPO) is not None


@pytest.mark.integration
def test_concurrent_denied_approval_is_not_overwritten_by_lazy_expiry(
    postgres_backend_env: object,
    tmp_path: Path,
) -> None:
    del postgres_backend_env
    story_id = _story_id(211)
    run_id = "run-denied-expiry-race"
    _seed_story_context(tmp_path, story_id)
    service = _service(ident="inst-denied-expiry-request")
    _admit_run(service, story_id=story_id, run_id=run_id)
    _seed_pushed_only_evidence(story_id=story_id, run_id=run_id)
    pending_result = service.request_ownership_takeover(
        request=TakeoverRequest(
            project_key=_PROJECT,
            story_id=story_id,
            session_id="sess-agent-denied-expiry",
            principal_type="interactive_agent",
            op_id="op-denied-expiry-request",
            reason="owner unavailable",
            worktree_roots=[f"T:/worktrees/{story_id}/agent"],
        )
    )
    assert pending_result.pending_human_approval is not None
    approval_id = pending_result.pending_human_approval.approval_id
    pending = load_takeover_approval_global(approval_id)
    assert pending is not None
    echo = _challenge_id_from_current(story_id, pending.challenge_ref)

    def deny_before_expiry_commit(*args: object, **kwargs: object) -> None:
        _force_approval_denied(approval_id, decided_at=_LATER)
        commit_takeover_expiry_global(*args, **kwargs)

    race_service = ControlPlaneRuntimeService(
        repository=ControlPlaneRuntimeRepository(
            commit_takeover_expiry=deny_before_expiry_commit,
        ),
        object_claim_repository=ObjectMutationClaimRepository(),
        phase_dispatcher=_AdmittedDispatcher(),  # type: ignore[arg-type]
        now_fn=lambda: _EXPIRED_NOW,
        instance_identity=boot_backend_instance_identity_global(
            "inst-denied-expiry-confirm",
            _EXPIRED_NOW,
        ),
    )
    result = race_service.confirm_ownership_takeover(
        command=_confirm_request(
            story_id=story_id,
            challenge_id=echo,
            op_id="op-denied-expiry-confirm",
        )
    )

    assert result.status == "rejected"
    assert result.error_code == "takeover_confirm_cas_lost"
    stored = load_takeover_approval_global(approval_id)
    assert stored is not None
    assert stored.status is TakeoverApprovalStatus.DENIED
    assert stored.decision_reason == "concurrent deny"


@pytest.mark.integration
def test_t6_late_ex_owner_push_does_not_modify_committed_transfer_record(
    postgres_backend_env: object,
    tmp_path: Path,
) -> None:
    del postgres_backend_env
    story_id = _story_id(106)
    run_id = "run-t6"
    _seed_story_context(tmp_path, story_id)
    service = _service(ident="inst-t6")
    _admit_run(service, story_id=story_id, run_id=run_id)
    _seed_pushed_only_evidence(story_id=story_id, run_id=run_id)
    echo = _request_takeover(service, story_id=story_id, run_id=run_id)
    result = service.confirm_ownership_takeover(
        command=_confirm_request(
            story_id=story_id,
            challenge_id=echo,
            op_id="op-t6-confirm",
        )
    )
    assert result.status == "committed"
    before = _transfer_row(story_id, run_id)

    upsert_push_freshness_record_global(
        PushFreshnessRecord(
            project_key=_PROJECT,
            story_id=story_id,
            run_id=run_id,
            repo_id=_REPO,
            last_reported_head_sha="b" * 40,
            last_pushed_head_sha="b" * 40,
            last_reported_at=_LATER,
            last_sync_point_id="late-ex-owner-push",
            last_command_id="late-ex-owner-command",
            backlog=False,
            backlog_detail=None,
        )
    )

    assert _transfer_row(story_id, run_id) == before


@pytest.mark.integration
def test_reconcile_obligation_blocks_until_attested_admin_clear_and_story_upsert_does_not_clear(
    postgres_backend_env: object,
    tmp_path: Path,
) -> None:
    del postgres_backend_env
    story_id = _story_id(208)
    run_id = "run-reconcile-obligation"
    _seed_story_context(tmp_path, story_id)
    service = _service(ident="inst-reconcile-obligation")
    _admit_run(service, story_id=story_id, run_id=run_id)
    _seed_pushed_only_evidence(story_id=story_id, run_id=run_id)
    _seed_pushed_only_evidence(
        story_id=story_id,
        run_id=run_id,
        repo_id="web",
        sha="c" * 40,
    )
    echo = _request_takeover(
        service,
        story_id=story_id,
        run_id=run_id,
        op_id="op-reconcile-request",
    )
    confirmed = service.confirm_ownership_takeover(
        command=_confirm_request(
            story_id=story_id,
            challenge_id=echo,
            op_id="op-reconcile-confirm",
        )
    )
    assert confirmed.status == "committed"

    blocked = service.start_phase(
        run_id=run_id,
        phase="exploration",
        request=_phase_request(
            story_id=story_id,
            op_id="op-reconcile-blocked",
            session_id="sess-B",
        ),
    )
    assert blocked.status == "rejected"
    assert blocked.error_code == "takeover_reconcile_required"
    assert load_control_plane_operation_global("op-reconcile-blocked") is None

    _seed_story_context(tmp_path, story_id)
    still_blocked = service.start_phase(
        run_id=run_id,
        phase="implementation",
        request=_phase_request(
            story_id=story_id,
            op_id="op-reconcile-after-story-upsert",
            session_id="sess-B",
        ),
    )
    assert still_blocked.status == "rejected"
    assert still_blocked.error_code == "takeover_reconcile_required"

    transfer = load_takeover_transfer_record_global(
        _PROJECT,
        story_id,
        run_id,
        2,
        _REPO,
    )
    assert transfer is not None
    with pytest.raises(ValueError, match="admin_transition"):
        TakeoverTransferRecord(
            project_key=transfer.project_key,
            story_id=transfer.story_id,
            run_id=transfer.run_id,
            ownership_epoch=transfer.ownership_epoch,
            repo_id=transfer.repo_id,
            takeover_base_sha=transfer.takeover_base_sha,
            last_push_at=transfer.last_push_at,
            push_lag_hint=transfer.push_lag_hint,
            base_quality=transfer.base_quality,
            challenge_ref=transfer.challenge_ref,
            confirm_ref=transfer.confirm_ref,
            reconciled_at=_LATER,
            reconcile_ref="agentic_clear:unattested",
        )
    with pytest.raises(ValueError, match=r"admin_transition:\{op_id\}"):
        TakeoverTransferRecord(
            project_key=transfer.project_key,
            story_id=transfer.story_id,
            run_id=transfer.run_id,
            ownership_epoch=transfer.ownership_epoch,
            repo_id=transfer.repo_id,
            takeover_base_sha=transfer.takeover_base_sha,
            last_push_at=transfer.last_push_at,
            push_lag_hint=transfer.push_lag_hint,
            base_quality=transfer.base_quality,
            challenge_ref=transfer.challenge_ref,
            confirm_ref=transfer.confirm_ref,
            reconciled_at=_LATER,
            reconcile_ref="admin_transition:",
        )

    with pytest.raises(ValueError, match="generic transfer upsert"):
        save_takeover_transfer_record_global(
            TakeoverTransferRecord(
                project_key=transfer.project_key,
                story_id=transfer.story_id,
                run_id=transfer.run_id,
                ownership_epoch=transfer.ownership_epoch,
                repo_id=transfer.repo_id,
                takeover_base_sha=transfer.takeover_base_sha,
                last_push_at=transfer.last_push_at,
                push_lag_hint=transfer.push_lag_hint,
                base_quality=transfer.base_quality,
                challenge_ref=transfer.challenge_ref,
                confirm_ref=transfer.confirm_ref,
                reconciled_at=_LATER,
                reconcile_ref="admin_transition:manual-clear",
            )
        )
    raw_forged_row = {
        "project_key": transfer.project_key,
        "story_id": transfer.story_id,
        "run_id": transfer.run_id,
        "ownership_epoch": transfer.ownership_epoch,
        "repo_id": transfer.repo_id,
        "takeover_base_sha": transfer.takeover_base_sha,
        "last_push_at": (
            transfer.last_push_at.isoformat()
            if transfer.last_push_at is not None
            else None
        ),
        "push_lag_hint": transfer.push_lag_hint,
        "base_quality": transfer.base_quality,
        "challenge_ref": transfer.challenge_ref,
        "confirm_ref": transfer.confirm_ref,
        "reconciled_at": _LATER.isoformat(),
        "reconcile_ref": "admin_transition:raw-forged-clear",
    }
    with pytest.raises(ValueError, match="generic transfer upsert"):
        postgres_store.save_takeover_transfer_record_global_row(raw_forged_row)
    agentic_clear = service.clear_takeover_reconcile_obligation(
        request=AdminTakeoverReconcileClearRequest(
            project_key=_PROJECT,
            story_id=story_id,
            run_id=run_id,
            session_id="sess-agent-reconcile",
            principal_type="interactive_agent",
            op_id="op-reconcile-agentic-clear",
            reason="forged clear",
        )
    )
    assert agentic_clear.status == "rejected"
    assert agentic_clear.error_code == "takeover_reconcile_clear_forbidden"
    assert load_control_plane_operation_global("op-reconcile-agentic-clear") is None

    auth = AuthMiddleware()
    attested_session = auth.session_store.create()
    app = ControlPlaneApplication(runtime_service=service, auth_middleware=auth)
    clear_response = app.handle_request(
        method="POST",
        path=f"/v1/project-edge/story-runs/{run_id}/ownership/takeover-reconcile-clear",
        body=json.dumps(
            {
                "project_key": _PROJECT,
                "story_id": story_id,
                "run_id": run_id,
                "session_id": "sess-client-forged-audit-actor",
                "principal_type": "human_cli",
                "op_id": "op-reconcile-admin-clear",
                "reason": "manual pre-AG3-151 reconcile clear",
            }
        ).encode(),
        request_headers={
            "Cookie": f"{auth.session_cookie_name()}={attested_session.session_id}",
            auth.csrf_header_name(): attested_session.csrf_token,
            "X-Project-Key": _PROJECT,
        },
    )
    assert clear_response.status_code == HTTPStatus.OK
    assert _response_json(clear_response)["status"] == "resolved"
    clear_op = load_control_plane_operation_global("op-reconcile-admin-clear")
    assert clear_op is not None
    assert clear_op.status == "resolved"
    assert clear_op.operation_kind == "takeover_reconcile_clear"
    assert clear_op.session_id == attested_session.session_id
    assert "admin_transition" in str(clear_op.response_payload["admin_note"])
    assert "sess-client-forged-audit-actor" not in str(
        clear_op.response_payload["admin_note"]
    )
    cleared_transfer = load_takeover_transfer_record_global(
        _PROJECT,
        story_id,
        run_id,
        2,
        _REPO,
    )
    assert cleared_transfer is not None
    assert cleared_transfer.reconciled_at == _NOW
    assert cleared_transfer.reconcile_ref == "admin_transition:op-reconcile-admin-clear"
    cleared_web_transfer = load_takeover_transfer_record_global(
        _PROJECT,
        story_id,
        run_id,
        2,
        "web",
    )
    assert cleared_web_transfer is not None
    assert cleared_web_transfer.reconciled_at == _NOW
    assert (
        cleared_web_transfer.reconcile_ref
        == "admin_transition:op-reconcile-admin-clear"
    )

    allowed = service.start_phase(
        run_id=run_id,
        phase="qa",
        request=_phase_request(
            story_id=story_id,
            op_id="op-reconcile-cleared",
            session_id="sess-B",
        ),
    )
    assert allowed.status == "committed"


@pytest.mark.integration
def test_takeover_reconcile_admin_clear_respects_story_object_claim(
    postgres_backend_env: object,
    tmp_path: Path,
) -> None:
    del postgres_backend_env
    story_id = _story_id(209)
    run_id = "run-reconcile-object-claim"
    _seed_story_context(tmp_path, story_id)
    service = _service(ident="inst-reconcile-object-claim")
    _admit_run(service, story_id=story_id, run_id=run_id)
    _seed_pushed_only_evidence(story_id=story_id, run_id=run_id)
    echo = _request_takeover(
        service,
        story_id=story_id,
        run_id=run_id,
        op_id="op-reconcile-claim-request",
    )
    confirmed = service.confirm_ownership_takeover(
        command=_confirm_request(
            story_id=story_id,
            challenge_id=echo,
            op_id="op-reconcile-claim-confirm",
        )
    )
    assert confirmed.status == "committed"

    holder = boot_backend_instance_identity_global("inst-reconcile-claim-holder", _NOW)
    assert acquire_object_mutation_claim_global(
        project_key=_PROJECT,
        serialization_scope="story",
        scope_key=story_id,
        op_id="op-held-reconcile-clear-claim",
        backend_instance_id=holder.backend_instance_id,
        instance_incarnation=holder.instance_incarnation,
        acquired_at=_NOW,
    )
    try:
        busy = service.clear_takeover_reconcile_obligation(
            request=AdminTakeoverReconcileClearRequest(
                project_key=_PROJECT,
                story_id=story_id,
                run_id=run_id,
                session_id="sess-admin-reconcile",
                principal_type="human_cli",
                op_id="op-reconcile-busy-clear",
                reason="manual pre-AG3-151 reconcile clear",
            )
        )
    finally:
        assert delete_object_mutation_claim_global(
            _PROJECT,
            "story",
            story_id,
            "op-held-reconcile-clear-claim",
        )

    assert busy.status == "rejected"
    assert busy.error_code == "conflict"
    assert load_control_plane_operation_global("op-reconcile-busy-clear") is None
    transfer = load_takeover_transfer_record_global(_PROJECT, story_id, run_id, 2, _REPO)
    assert transfer is not None
    assert transfer.reconciled_at is None
    assert transfer.reconcile_ref is None


@pytest.mark.integration
def test_successful_takeover_reconcile_clears_obligation_and_admits(
    postgres_backend_env: object,
    tmp_path: Path,
) -> None:
    del postgres_backend_env
    story_id = _story_id(221)
    run_id = "run-reconcile-success"
    _seed_story_context(tmp_path, story_id)
    service = _service(
        ident="inst-reconcile-success",
        push_barrier_evidence=_VerifiedPushBoundary(),
        local_freeze_export=LocalFreezeJsonExport(tmp_path),
    )
    _admit_run(service, story_id=story_id, run_id=run_id)
    _seed_pushed_only_evidence(story_id=story_id, run_id=run_id)
    challenge_id = _request_takeover(
        service,
        story_id=story_id,
        run_id=run_id,
        op_id="op-reconcile-success-request",
    )
    confirmed = service.confirm_ownership_takeover(
        command=_confirm_request(
            story_id=story_id,
            challenge_id=challenge_id,
            op_id="op-reconcile-success-confirm",
        )
    )
    assert confirmed.status == "committed"
    commands = service.list_and_ack_open_commands(
        run_id,
        project_key=_PROJECT,
        session_id="sess-B",
    ).commands
    assert [(command.command_kind, command.payload["repo_id"]) for command in commands] == [
        ("takeover_reconcile", _REPO)
    ]
    assert commands[0].payload["takeover_base_sha"] == _SHA

    reconciled = service.reconcile_takeover_worktree(
        run_id,
        TakeoverReconcileWorktreeRequest(
            project_key=_PROJECT,
            story_id=story_id,
            session_id="sess-B",
            op_id="op-reconcile-success",
            results=[
                WorktreeReport(
                    repo_id=_REPO,
                    outcome="provisioned",
                    worktree_root=f"T:/worktrees/{story_id}/sess-B",
                    branch=f"story/{story_id}",
                    head_sha=_SHA,
                    marker_present=True,
                )
            ],
        ),
    )
    assert reconciled.status == "resolved"
    assert reconciled.takeover_reconcile is not None
    assert reconciled.takeover_reconcile.results[0].result_type == "identity_ok"
    transfer = load_takeover_transfer_record_global(
        _PROJECT, story_id, run_id, 2, _REPO
    )
    assert transfer is not None
    assert transfer.reconcile_ref == "takeover_reconcile:op-reconcile-success"

    admitted = service.start_phase(
        run_id=run_id,
        phase="exploration",
        request=_phase_request(
            story_id=story_id,
            op_id="op-after-reconcile-success",
            session_id="sess-B",
        ),
    )
    assert admitted.status == "committed"


@pytest.mark.integration
def test_failed_takeover_reconcile_enters_contested_and_successful_retry_clears_both(
    postgres_backend_env: object,
    tmp_path: Path,
) -> None:
    del postgres_backend_env
    story_id = _story_id(222)
    run_id = "run-reconcile-contested"
    _seed_story_context(tmp_path, story_id)
    local_export = LocalFreezeJsonExport(tmp_path)
    service = _service(
        ident="inst-reconcile-contested",
        push_barrier_evidence=_VerifiedPushBoundary(),
        local_freeze_export=local_export,
    )
    _admit_run(service, story_id=story_id, run_id=run_id)
    _seed_pushed_only_evidence(story_id=story_id, run_id=run_id)
    challenge_id = _request_takeover(
        service,
        story_id=story_id,
        run_id=run_id,
        op_id="op-contested-request",
    )
    confirmed = service.confirm_ownership_takeover(
        command=_confirm_request(
            story_id=story_id,
            challenge_id=challenge_id,
            op_id="op-contested-confirm",
        )
    )
    assert confirmed.status == "committed"
    pending_challenge_id = _request_takeover(
        service,
        story_id=story_id,
        run_id=run_id,
        session_id="sess-C",
        op_id="op-pending-before-contested",
    )

    failed = service.reconcile_takeover_worktree(
        run_id,
        TakeoverReconcileWorktreeRequest(
            project_key=_PROJECT,
            story_id=story_id,
            session_id="sess-B",
            op_id="op-reconcile-contested",
            results=[
                TakeoverErrorResult(
                    result_type="contested_local_writes",
                    repo_id=_REPO,
                    detail="worktree marker could not be verified",
                )
            ],
        ),
    )
    assert failed.status == "failed"
    freeze = FreezeRepository().read_freeze(
        story_id, FreezeKind.CONTESTED_LOCAL_WRITES
    )
    assert freeze is not None
    assert local_export.read() == {
        "story_id": story_id,
        "frozen_at": _NOW.isoformat(),
        "freeze_reason": freeze.freeze_reason,
        "freeze_version": 1,
        "kind": "contested_local_writes",
        "freeze_epoch": freeze.freeze_epoch,
    }
    ownership = load_active_run_ownership_record_global(_PROJECT, story_id)
    assert ownership is not None
    assert ownership.status is OwnershipStatus.ACTIVE
    assert ownership.owner_session_id == "sess-B"
    invalidated = load_takeover_challenge_global(pending_challenge_id)
    assert invalidated is not None
    assert invalidated.status == "invalidated"

    blocked = service.start_phase(
        run_id=run_id,
        phase="exploration",
        request=_phase_request(
            story_id=story_id,
            op_id="op-blocked-by-contested",
            session_id="sess-B",
        ),
    )
    assert blocked.status == "rejected"
    assert blocked.error_code == "contested_local_writes"
    synced = service.sync_project_edge(
        ProjectEdgeSyncRequest(
            project_key=_PROJECT,
            session_id="sess-B",
            op_id="op-sync-contested-bundle",
        )
    )
    assert [state.kind for state in synced.edge_bundle.active_freezes] == [
        "contested_local_writes"
    ]

    cleared = service.reconcile_takeover_worktree(
        run_id,
        TakeoverReconcileWorktreeRequest(
            project_key=_PROJECT,
            story_id=story_id,
            session_id="sess-B",
            op_id="op-reconcile-clear-both",
            results=[
                WorktreeReport(
                    repo_id=_REPO,
                    outcome="provisioned",
                    worktree_root=f"T:/worktrees/{story_id}/sess-B",
                    branch=f"story/{story_id}",
                    head_sha=_SHA,
                    marker_present=True,
                )
            ],
        ),
    )
    assert cleared.status == "resolved"
    transfer = load_takeover_transfer_record_global(
        _PROJECT, story_id, run_id, 2, _REPO
    )
    assert transfer is not None
    assert transfer.reconcile_ref == "takeover_reconcile:op-reconcile-clear-both"
    assert (
        FreezeRepository().read_freeze(
            story_id, FreezeKind.CONTESTED_LOCAL_WRITES
        )
        is None
    )
    assert local_export.read() is None
    admitted = service.start_phase(
        run_id=run_id,
        phase="implementation",
        request=_phase_request(
            story_id=story_id,
            op_id="op-after-dual-clear",
            session_id="sess-B",
        ),
    )
    assert admitted.status == "committed"


@pytest.mark.integration
@pytest.mark.requires_git
def test_real_transfer_command_queue_contested_bundle_blocks_active_owner(
    postgres_backend_env: object,
    tmp_path: Path,
) -> None:
    """Full AG3-148 -> AG3-145 -> edge -> freeze -> resolve round-trip."""
    del postgres_backend_env
    story_id = _story_id(223)
    run_id = "run-reconcile-edge-roundtrip"
    project_root = tmp_path / "edge-project"
    repo_ids = [_REPO, "web"]
    repo_roots: dict[str, Path] = {}
    base_shas: dict[str, str] = {}
    for repo_id in repo_ids:
        repo_root = project_root / repo_id
        repo_roots[repo_id] = repo_root
        repo_root.mkdir(parents=True)
        subprocess.run(
            ["git", "-C", str(repo_root), "init", "-q", "-b", "main"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo_root), "config", "user.email", "t@example.com"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo_root), "config", "user.name", "T"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo_root), "config", "commit.gpgsign", "false"],
            check=True,
        )
        (repo_root / "README.md").write_text(f"{repo_id}\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo_root), "add", "README.md"], check=True)
        subprocess.run(
            ["git", "-C", str(repo_root), "commit", "-q", "-m", "seed"],
            check=True,
        )
        base_shas[repo_id] = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    config = ProjectConfig(
        project_key=_PROJECT,
        project_name="Tenant A",
        repositories=[
            RepositoryConfig(name=repo_id, path=repo_roots[repo_id])
            for repo_id in repo_ids
        ],
        pipeline=PipelineConfig(
            config_version=SUPPORTED_CONFIG_VERSION,
            features=Features(multi_llm=False),
            sonarqube=SonarQubeConfig(available=False, enabled=False),
            ci=JenkinsConfig(available=False, enabled=False),
        ),
    )
    worktrees = {
        repo_id: repo_roots[repo_id] / "worktrees" / story_id for repo_id in repo_ids
    }
    for repo_id in repo_ids:
        execute_provision_worktree(
            ProvisionWorktreeCommandPayload(
                story_id=story_id,
                project_key=_PROJECT,
                run_id=run_id,
                repo_id=repo_id,
                branch=f"story/{story_id}",
                base_ref=base_shas[repo_id],
            ),
            project_config=config,
            project_root=project_root,
        )

    _seed_story_context(tmp_path, story_id, participating_repos=repo_ids)
    service = _service(
        ident="inst-edge-roundtrip",
        push_barrier_evidence=_ShaPushBoundary(base_shas),
        local_freeze_export=LocalFreezeJsonExport(tmp_path),
    )
    _admit_run(service, story_id=story_id, run_id=run_id)
    for repo_id, base_sha in base_shas.items():
        _seed_pushed_only_evidence(
            story_id=story_id,
            run_id=run_id,
            repo_id=repo_id,
            sha=base_sha,
        )
    challenge_id = _request_takeover(
        service,
        story_id=story_id,
        run_id=run_id,
        op_id="op-edge-roundtrip-request",
        worktree_roots=[str(worktrees[repo_id]) for repo_id in repo_ids],
    )
    confirmed = service.confirm_ownership_takeover(
        command=_confirm_request(
            story_id=story_id,
            challenge_id=challenge_id,
            op_id="op-edge-roundtrip-confirm",
        )
    )
    assert confirmed.status == "committed"
    # Partial multi-repo failure: api has a foreign marker while web remains clean.
    marker_path = worktrees[_REPO] / ".agentkit-story.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["story_id"] = "FOREIGN-1"
    marker_path.write_text(json.dumps(marker), encoding="utf-8")

    client = _RuntimeEdgeClient(
        service,
        LocalEdgePublisher(project_root=project_root),
    )
    outcomes = process_open_commands(
        client,  # type: ignore[arg-type]
        project_config=config,
        project_root=project_root,
        run_id=run_id,
        project_key=_PROJECT,
        session_id="sess-B",
        story_id=story_id,
    )

    assert len(outcomes) == 2
    freeze = FreezeRepository().read_freeze(
        story_id,
        FreezeKind.CONTESTED_LOCAL_WRITES,
    )
    assert freeze is not None
    ownership = load_active_run_ownership_record_global(_PROJECT, story_id)
    assert ownership is not None
    assert ownership.status is OwnershipStatus.ACTIVE
    assert ownership.owner_session_id == "sess-B"
    resolved = ProjectEdgeResolver(project_root=project_root).resolve(
        session_id="sess-B",
        cwd=worktrees[_REPO],
        freshness_class="guarded_read",
    )
    assert resolved.operating_mode == "binding_invalid"
    assert resolved.block_reason == "contested_local_writes"
    guard_freeze = json.loads(
        (worktrees[_REPO] / ".agent-guard" / "freeze.json").read_text(
            encoding="utf-8"
        )
    )
    assert guard_freeze["active_freezes"][0]["block_reason"] == (
        "contested_local_writes"
    )


def _challenge_id_from_current(story_id: str, challenge_id: str) -> str:
    active = load_active_run_ownership_record_global(_PROJECT, story_id)
    assert active is not None
    binding = load_session_run_binding_global(active.owner_session_id)
    assert binding is not None
    return challenge_id


def _state_snapshot(
    story_id: str,
    run_id: str,
    approval_id: str,
) -> dict[str, object]:
    active = load_active_run_ownership_record_global(_PROJECT, story_id)
    approval = load_takeover_approval_global(approval_id)
    old_binding = load_session_run_binding_global("sess-A")
    return {
        "active_owner": active.owner_session_id if active is not None else None,
        "active_epoch": active.ownership_epoch if active is not None else None,
        "active_acquired_via": active.acquired_via.value if active is not None else None,
        "old_binding_status": old_binding.status if old_binding is not None else None,
        "old_binding_revocation": (
            old_binding.revocation_reason if old_binding is not None else None
        ),
        "new_binding": _binding_exists("sess-B"),
        "transfers": _transfer_count(story_id, run_id),
        "blocker": _story_blocker(story_id),
        "events": _event_count(story_id, run_id),
        "approval_status": approval.status.value if approval is not None else None,
        "approval_decided": approval.decided_at is not None if approval is not None else None,
    }


def _operation_row_count(op_id: str) -> int:
    with postgres_store._connect_global() as conn:  # noqa: SLF001 -- read-only test assertion
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM control_plane_operations WHERE op_id = ?",
            (op_id,),
        ).fetchone()
    assert row is not None
    return int(row["n"])


def _challenge_count_for_request(request_op_id: str) -> int:
    with postgres_store._connect_global() as conn:  # noqa: SLF001 -- assertion
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM takeover_challenges WHERE request_op_id = ?",
            (request_op_id,),
        ).fetchone()
    assert row is not None
    return int(row["n"])


def _binding_exists(session_id: str) -> int:
    with postgres_store._connect_global() as conn:  # noqa: SLF001 -- read-only test assertion
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM session_run_bindings WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    assert row is not None
    return int(row["n"])


def _transfer_count(story_id: str, run_id: str) -> int:
    with postgres_store._connect_global() as conn:  # noqa: SLF001 -- read-only test assertion
        row = conn.execute(
            """
            SELECT COUNT(*) AS n FROM takeover_transfer_records
            WHERE project_key = ? AND story_id = ? AND run_id = ?
            """,
            (_PROJECT, story_id, run_id),
        ).fetchone()
    assert row is not None
    return int(row["n"])


def _event_count(story_id: str, run_id: str) -> int:
    with postgres_store._connect_global() as conn:  # noqa: SLF001 -- read-only test assertion
        row = conn.execute(
            """
            SELECT COUNT(*) AS n FROM execution_events
            WHERE project_key = ? AND story_id = ? AND run_id = ?
            """,
            (_PROJECT, story_id, run_id),
        ).fetchone()
    assert row is not None
    return int(row["n"])


def _story_blocker(story_id: str) -> str | None:
    with postgres_store._connect_global() as conn:  # noqa: SLF001 -- read-only test assertion
        row = conn.execute(
            """
            SELECT blocker FROM stories
            WHERE project_key = ? AND story_display_id = ?
            """,
            (_PROJECT, story_id),
        ).fetchone()
    return str(row["blocker"]) if row is not None and row["blocker"] is not None else None


def _event_payloads(
    story_id: str,
    run_id: str,
    event_type: EventType,
) -> list[dict[str, object]]:
    return [
        event.payload
        for event in load_execution_events_global(_PROJECT, story_id, run_id=run_id)
        if event.event_type == event_type.value
    ]


def _transfer_row(story_id: str, run_id: str) -> dict[str, object]:
    with postgres_store._connect_global() as conn:  # noqa: SLF001 -- read-only test assertion
        row = conn.execute(
            """
            SELECT * FROM takeover_transfer_records
            WHERE project_key = ? AND story_id = ? AND run_id = ? AND repo_id = ?
            """,
            (_PROJECT, story_id, run_id, _REPO),
        ).fetchone()
    assert row is not None
    return dict(row)


def _op_record(
    new_binding: SessionRunBindingRecord,
    *,
    op_id: str = "op-confirm",
) -> ControlPlaneOperationRecord:
    result = ControlPlaneMutationResult(
        status="committed",
        op_id=op_id,
        operation_kind="ownership_takeover_confirm",
        run_id=new_binding.run_id,
        phase="ownership",
        edge_bundle=EdgeBundle(
            current=EdgePointer(
                project_key=new_binding.project_key,
                export_version="edge-test",
                operating_mode="story_execution",
                bundle_dir="_temp/governance/bundles/edge-test",
                sync_after=_NOW,
                freshness_class="mutation",
                generated_at=_NOW,
            ),
            session=SessionRunBindingView(
                session_id=new_binding.session_id,
                project_key=new_binding.project_key,
                story_id=new_binding.story_id,
                run_id=new_binding.run_id,
                principal_type=new_binding.principal_type,
                worktree_roots=list(new_binding.worktree_roots),
                binding_version=new_binding.binding_version,
                operating_mode="story_execution",
                status=new_binding.status,
                revocation_reason=new_binding.revocation_reason,
            ),
            lock=StoryExecutionLockView(
                project_key=new_binding.project_key,
                story_id=new_binding.story_id,
                run_id=new_binding.run_id,
                lock_type="story_execution",
                status="ACTIVE",
                worktree_roots=list(new_binding.worktree_roots),
                binding_version=new_binding.binding_version,
                activated_at=_NOW,
                updated_at=_NOW,
            ),
            tombstone_worktree_roots=["T:/worktrees/a"],
        ),
        ownership_epoch=2,
    )
    return ControlPlaneOperationRecord(
        op_id=result.op_id,
        project_key=new_binding.project_key,
        story_id=new_binding.story_id,
        run_id=new_binding.run_id,
        session_id=new_binding.session_id,
        operation_kind=result.operation_kind,
        phase=result.phase,
        status=result.status,
        response_payload=result.model_dump(mode="json"),
        created_at=_NOW,
        updated_at=_NOW,
    )


def _request_op_record(
    *,
    op_id: str,
    project_key: str,
    story_id: str,
    run_id: str,
    session_id: str,
    status: str,
    finalized_at: datetime | None = None,
) -> ControlPlaneOperationRecord:
    return ControlPlaneOperationRecord(
        op_id=op_id,
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
        session_id=session_id,
        operation_kind="ownership_takeover_request",
        phase="ownership",
        status=status,
        response_payload={"status": status, "op_id": op_id},
        created_at=_NOW,
        updated_at=_NOW,
        finalized_at=finalized_at,
    )


def _challenge_record(
    *,
    challenge_id: str,
    request_op_id: str,
    project_key: str,
    story_id: str,
    run_id: str,
    owner_session_id: str = "sess-A",
) -> TakeoverChallengeRecord:
    return TakeoverChallengeRecord(
        challenge_id=challenge_id,
        request_op_id=request_op_id,
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
        requesting_session_id="sess-agent",
        requesting_principal_type="interactive_agent",
        requesting_worktree_roots=("T:/worktrees/agent",),
        reason="owner unavailable",
        owner_session_id=owner_session_id,
        ownership_epoch=1,
        binding_version="1",
        phase_status="ACTIVE",
        issued_at=_NOW,
        expires_at=_NOW + timedelta(minutes=10),
        repos=(
            TakeoverChallengeRepoRecord(
                repo_id="backend",
                takeover_base_sha="abc123",
                last_push_at=_NOW,
                push_lag_hint=None,
                base_quality="pushed",
            ),
        ),
        open_operation_ids=(),
        takeover_history_refs=(),
    )


def _terminal_challenge_record(
    challenge: TakeoverChallengeRecord,
    *,
    terminal_op_id: str,
) -> TakeoverChallengeRecord:
    return TakeoverChallengeRecord(
        challenge_id=challenge.challenge_id,
        request_op_id=challenge.request_op_id,
        project_key=challenge.project_key,
        story_id=challenge.story_id,
        run_id=challenge.run_id,
        requesting_session_id=challenge.requesting_session_id,
        requesting_principal_type=challenge.requesting_principal_type,
        requesting_worktree_roots=challenge.requesting_worktree_roots,
        reason=challenge.reason,
        owner_session_id=challenge.owner_session_id,
        ownership_epoch=challenge.ownership_epoch,
        binding_version=challenge.binding_version,
        phase_status=challenge.phase_status,
        issued_at=challenge.issued_at,
        expires_at=challenge.expires_at,
        repos=challenge.repos,
        open_operation_ids=challenge.open_operation_ids,
        takeover_history_refs=challenge.takeover_history_refs,
        status="confirmed",
        decided_at=_NOW,
        terminal_op_id=terminal_op_id,
    )


@pytest.mark.parametrize("kind", tuple(FreezeKind), ids=lambda kind: kind.value)
def test_freeze_entry_invalidates_challenge_per_family_kind_and_never_revives(
    postgres_backend_env: object,
    tmp_path: Path,
    kind: FreezeKind,
) -> None:
    del postgres_backend_env
    suffix = kind.value.replace("_", "-")
    story_id = f"AG3-{740 + tuple(FreezeKind).index(kind)}"
    run_id = f"run-150-{suffix}"
    _seed_story_context(tmp_path, story_id)
    service = _service(ident=f"inst-150-{suffix}")
    _admit_run(service, story_id=story_id, run_id=run_id)
    _seed_pushed_only_evidence(story_id=story_id, run_id=run_id)
    challenge_id = _request_takeover(
        service,
        story_id=story_id,
        run_id=run_id,
        op_id=f"op-request-{suffix}",
    )

    FreezeRepository().set_freeze(
        story_id,
        frozen_at="2026-07-11T12:00:00+00:00",
        freeze_reason=f"active {kind.value}",
        freeze_version=1,
        kind=kind,
    )

    challenge = load_takeover_challenge_global(challenge_id)
    assert challenge is not None
    assert challenge.status == "invalidated"
    active_rejection = service.confirm_ownership_takeover(
        command=_confirm_request(
            story_id=story_id,
            challenge_id=challenge_id,
            op_id=f"op-confirm-frozen-{suffix}",
        )
    )
    assert active_rejection.status == "rejected"
    assert active_rejection.error_code == "story_not_takeover_admissible"

    assert FreezeRepository().clear_freeze(story_id, kind) == 1
    after_release = service.confirm_ownership_takeover(
        command=_confirm_request(
            story_id=story_id,
            challenge_id=challenge_id,
            op_id=f"op-confirm-after-release-{suffix}",
        )
    )
    assert after_release.status == "rejected"
    assert after_release.error_code == "challenge_not_pending"
    challenge_after = load_takeover_challenge_global(challenge_id)
    assert challenge_after is not None
    assert challenge_after.status == "invalidated"
