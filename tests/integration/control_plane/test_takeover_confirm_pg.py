"""Postgres integration coverage for AG3-148 takeover confirm."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from functools import partial
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.auth.middleware import AuthMiddleware
from agentkit.backend.auth.tokens import issue_project_api_token
from agentkit.backend.control_plane.http import ControlPlaneApplication, HttpResponse
from agentkit.backend.control_plane.models import (
    ControlPlaneMutationResult,
    EdgeBundle,
    EdgePointer,
    PhaseDispatchResult,
    PhaseMutationRequest,
    SessionRunBindingView,
    StoryExecutionLockView,
    TakeoverChallengeEcho,
    TakeoverChallengeEchoRequest,
    TakeoverRequest,
)
from agentkit.backend.control_plane.ownership import (
    OWNERSHIP_TRANSFERRED_REVOCATION_REASON,
    BindingStatus,
    OwnershipAcquisition,
    OwnershipStatus,
    TakeoverApprovalStatus,
)
from agentkit.backend.control_plane.push_sync import (
    PushBarrierVerdict,
    PushBarrierVerdictStatus,
    PushFreshnessRecord,
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
from agentkit.backend.control_plane.runtime import ControlPlaneRuntimeService
from agentkit.backend.exceptions import OwnershipFenceViolationError
from agentkit.backend.governance.guard_system.records import StoryExecutionLockRecord
from agentkit.backend.state_backend import postgres_store
from agentkit.backend.state_backend.governance_runtime_store import (
    load_story_execution_lock_global,
    save_story_execution_lock_global,
)
from agentkit.backend.state_backend.operation_ledger import (
    commit_takeover_confirm_global,
    commit_takeover_expiry_global,
    load_control_plane_operation_global,
    save_control_plane_operation_global,
)
from agentkit.backend.state_backend.state_backend_connection_manager import (
    boot_backend_instance_identity_global,
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
    load_session_run_binding_global,
    load_takeover_approval_global,
    load_takeover_challenge_global,
    load_takeover_transfer_record_global,
    save_session_run_binding_global,
    save_story_context_global,
    save_takeover_transfer_record_global,
)
from agentkit.backend.state_backend.telemetry_event_store import (
    load_execution_events_global,
)
from agentkit.backend.story_context_manager.models import StoryContext
from agentkit.backend.story_context_manager.types import StoryMode, StoryType
from agentkit.backend.telemetry.contract.records import ExecutionEventRecord
from agentkit.backend.telemetry.events import EventType

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
    "lock_insert",
    f"transfer_record_insert:{_REPO}",
    "takeover_reconcile_required",
    f"event_insert:{EventType.SESSION_RUN_BINDING_TRANSFERRED.value}",
    f"event_insert:{EventType.SESSION_DISOWNED.value}",
    f"event_insert:{EventType.TAKEOVER_APPROVAL_CHANGED.value}",
)


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


def _seed_story_context(tmp_path: Path, story_id: str) -> None:
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
            participating_repos=[_REPO],
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
) -> ControlPlaneRuntimeService:
    identity = boot_backend_instance_identity_global(ident, now)
    repository = None
    object_claim_repository = None
    if fault_after_step is not None:
        repository = ControlPlaneRuntimeRepository(
            commit_takeover_confirm=partial(
                commit_takeover_confirm_global,
                fault_after_step=fault_after_step,
            )
        )
        object_claim_repository = ObjectMutationClaimRepository()
    return ControlPlaneRuntimeService(
        repository=repository,
        object_claim_repository=object_claim_repository,
        phase_dispatcher=_AdmittedDispatcher(),  # type: ignore[arg-type]
        now_fn=lambda: now,
        instance_identity=identity,
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


def _seed_pushed_only_evidence(*, story_id: str, run_id: str) -> None:
    upsert_push_freshness_record_global(
        PushFreshnessRecord(
            project_key=_PROJECT,
            story_id=story_id,
            run_id=run_id,
            repo_id=_REPO,
            last_reported_head_sha=_SHA,
            last_pushed_head_sha=_SHA,
            last_reported_at=_NOW,
            last_sync_point_id=f"phase_completion:{run_id}",
            last_command_id=f"{run_id}::sync_push::phase_completion:{run_id}::{_REPO}",
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


def _request_takeover(
    service: ControlPlaneRuntimeService,
    *,
    story_id: str,
    run_id: str,
    session_id: str = "sess-B",
    principal_type: str = "human_cli",
    op_id: str = "op-takeover-request",
) -> TakeoverChallengeEcho:
    del run_id
    result = service.request_ownership_takeover(
        request=TakeoverRequest(
            project_key=_PROJECT,
            story_id=story_id,
            session_id=session_id,
            principal_type=principal_type,
            op_id=op_id,
            reason="owner unavailable",
            worktree_roots=[f"T:/worktrees/{story_id}/{session_id}"],
        )
    )
    assert result.status in {"offered", "pending_human_approval"}
    challenge = result.takeover_challenge
    if challenge is None:
        assert result.pending_human_approval is not None
        approval = load_takeover_approval_global(result.pending_human_approval.approval_id)
        assert approval is not None
        challenge_id = approval.challenge_ref
        active = load_active_run_ownership_record_global(_PROJECT, story_id)
        binding = load_session_run_binding_global("sess-A")
        assert active is not None
        assert binding is not None
        return TakeoverChallengeEcho(
            challenge_id=challenge_id,
            owner_session_id=active.owner_session_id,
            ownership_epoch=active.ownership_epoch,
            binding_version=binding.binding_version,
            expires_at=_NOW + timedelta(minutes=15),
        )
    return TakeoverChallengeEcho(
        challenge_id=challenge.challenge_id,
        owner_session_id=challenge.current_owner_session_id,
        ownership_epoch=challenge.ownership_epoch,
        binding_version=challenge.binding_version,
        expires_at=challenge.expires_at,
    )


def _confirm_request(
    *,
    story_id: str,
    echo: TakeoverChallengeEcho,
    op_id: str,
    session_id: str = "sess-B",
    approval_id: str | None = None,
) -> TakeoverChallengeEchoRequest:
    return TakeoverChallengeEchoRequest(
        project_key=_PROJECT,
        story_id=story_id,
        session_id=session_id,
        principal_type="human_cli",
        op_id=op_id,
        reason="human confirmed",
        worktree_roots=[f"T:/worktrees/{story_id}/{session_id}"],
        challenge_echo=echo,
        approval_id=approval_id,
    )


def _story_id(number: int) -> str:
    return f"AG3148-{number}"


def _wire_time(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


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
        expected_owner_session_id="sess-A",
        expected_ownership_epoch=1,
        expected_binding_version="1",
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
        expected_owner_session_id="sess-A2",
        expected_ownership_epoch=1,
        expected_binding_version="1",
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
            request=_confirm_request(
                story_id=story_id,
                echo=echo,
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
    assert active.owner_session_id in {"sess-B", "sess-C"}
    losing_op_id = (
        "op-t1-confirm-a"
        if committed_results[0].op_id == "op-t1-confirm-b"
        else "op-t1-confirm-b"
    )
    assert _operation_row_count(losing_op_id) == 0
    assert _binding_exists("sess-B") + _binding_exists("sess-C") == 1
    assert _transfer_count(story_id, run_id) == 1
    assert _event_count(story_id, run_id) == events_before_confirm + 2


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
    echo = _challenge_echo_from_current(story_id, pending.challenge_ref)
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
            request=_confirm_request(
                story_id=story_id,
                echo=echo,
                op_id=f"op-t2-confirm-{fault_step}",
                approval_id=approval_id,
            )
        )

    assert _state_snapshot(story_id, run_id, approval_id) == before
    assert _operation_row_count(f"op-t2-confirm-{fault_step}") == 0


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
    echo = _challenge_echo_from_current(story_id, pending.challenge_ref).model_copy(
        update={"expires_at": _EXPIRED_NOW + timedelta(minutes=1)}
    )
    before = _state_snapshot(story_id, run_id, approval_id)
    service = _service(ident="inst-t4-confirm", now=_EXPIRED_NOW)

    result = service.confirm_ownership_takeover(
        request=_confirm_request(
            story_id=story_id,
            echo=echo,
            op_id="op-t4-confirm",
            approval_id=approval_id,
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
    echo = _challenge_echo_from_current(story_id, pending.challenge_ref)
    auth = AuthMiddleware()
    app = ControlPlaneApplication(runtime_service=service, auth_middleware=auth)

    response = app.handle_request(
        method="POST",
        path=f"/v1/project-edge/story-runs/{run_id}/ownership/takeover-deny",
        body=json.dumps(
            {
                "project_key": _PROJECT,
                "story_id": story_id,
                "session_id": "sess-human-deny",
                "principal_type": "interactive_agent",
                "op_id": "op-deny-decision",
                "approval_id": approval_id,
                "reason": "human denied",
            }
        ).encode(),
        request_headers=_human_headers(auth, project_key=_PROJECT),
    )

    assert response.status_code == HTTPStatus.OK
    assert _response_json(response)["status"] == "denied"
    stored = load_takeover_approval_global(approval_id)
    assert stored is not None
    assert stored.status is TakeoverApprovalStatus.DENIED
    assert stored.decided_by_session_id == "sess-human-deny"
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
            "approval": {
                "approval_id": approval_id,
                "project_key": _PROJECT,
                "story_id": story_id,
                "run_id": run_id,
                "requested_by_session_id": "sess-agent-deny",
                "requested_by_principal_type": "interactive_agent",
                "reason": "owner unavailable",
                "challenge_ref": pending.challenge_ref,
                "status": "denied",
                "requested_at": _wire_time(pending.requested_at),
                "expires_at": _wire_time(pending.expires_at),
                "decided_at": _wire_time(_NOW),
                "decided_by_session_id": "sess-human-deny",
                "decision_reason": "human denied",
            },
        }
    ]

    follow_up = service.confirm_ownership_takeover(
        request=_confirm_request(
            story_id=story_id,
            echo=echo,
            op_id="op-denied-confirm",
            approval_id=approval_id,
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
    echo = _challenge_echo_from_current(story_id, loaded.challenge_ref)
    result = restarted.confirm_ownership_takeover(
        request=_confirm_request(
            story_id=story_id,
            echo=echo,
            op_id="op-t5-confirm",
            approval_id=approval_id,
        )
    )

    assert result.status == "committed"
    stored = load_takeover_approval_global(approval_id)
    assert stored is not None
    assert stored.status is TakeoverApprovalStatus.APPROVED
    replayed_request = restarted.get_operation("op-t5-request")
    assert replayed_request is not None
    assert replayed_request.status == "approved"


@pytest.mark.integration
def test_server_stored_challenge_ttl_rejects_forged_future_echo(
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
    _set_challenge_expires_at(echo.challenge_id, _NOW + timedelta(minutes=1))
    forged_echo = echo.model_copy(update={"expires_at": _NOW + timedelta(hours=2)})

    result = _service(
        ident="inst-server-ttl-confirm",
        now=_NOW + timedelta(minutes=5),
    ).confirm_ownership_takeover(
        request=_confirm_request(
            story_id=story_id,
            echo=forged_echo,
            op_id="op-server-ttl-confirm",
        )
    )

    assert result.status == "rejected"
    assert result.error_code == "challenge_expired"
    challenge = load_takeover_challenge_global(echo.challenge_id)
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
    echo = _challenge_echo_from_current(story_id, old_challenge_id)

    result = _service(
        ident="inst-reissue-confirm",
        now=_NOW + timedelta(minutes=20),
    ).confirm_ownership_takeover(
        request=_confirm_request(
            story_id=story_id,
            echo=echo,
            op_id="op-reissue-confirm",
            approval_id=approval.approval_id,
        )
    )

    assert result.status == "committed"
    refreshed = load_takeover_approval_global(approval.approval_id)
    assert refreshed is not None
    assert refreshed.status is TakeoverApprovalStatus.APPROVED
    assert refreshed.challenge_ref != old_challenge_id
    old_challenge = load_takeover_challenge_global(old_challenge_id)
    new_challenge = load_takeover_challenge_global(refreshed.challenge_ref)
    assert old_challenge is not None
    assert old_challenge.status == "expired"
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
    assert transfer.challenge_ref == refreshed.challenge_ref


@pytest.mark.integration
def test_cross_story_approval_is_rejected_even_when_challenge_matches_request(
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
        request=_confirm_request(
            story_id=story_b,
            echo=_challenge_echo_from_current(story_b, approval_b.challenge_ref),
            op_id="op-cross-story-confirm",
            approval_id=approval_a.approval_id,
        )
    )

    assert result.status == "rejected"
    assert result.error_code == "approval_required"
    assert load_takeover_transfer_record_global(_PROJECT, story_b, run_b, 2, _REPO) is None


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
    echo = _challenge_echo_from_current(story_id, pending.challenge_ref)

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
        request=_confirm_request(
            story_id=story_id,
            echo=echo,
            op_id="op-denied-expiry-confirm",
            approval_id=approval_id,
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
        request=_confirm_request(story_id=story_id, echo=echo, op_id="op-t6-confirm")
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
def test_reconcile_obligation_blocks_until_audited_admin_clear_and_story_upsert_does_not_clear(
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
    echo = _request_takeover(
        service,
        story_id=story_id,
        run_id=run_id,
        op_id="op-reconcile-request",
    )
    confirmed = service.confirm_ownership_takeover(
        request=_confirm_request(
            story_id=story_id,
            echo=echo,
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


def _challenge_echo_from_current(story_id: str, challenge_id: str) -> TakeoverChallengeEcho:
    active = load_active_run_ownership_record_global(_PROJECT, story_id)
    assert active is not None
    binding = load_session_run_binding_global(active.owner_session_id)
    assert binding is not None
    return TakeoverChallengeEcho(
        challenge_id=challenge_id,
        owner_session_id=active.owner_session_id,
        ownership_epoch=active.ownership_epoch,
        binding_version=binding.binding_version,
        expires_at=_NOW + timedelta(minutes=15),
    )


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
