"""Postgres integration coverage for AG3-148 takeover confirm."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agentkit.backend.control_plane.models import (
    ControlPlaneMutationResult,
    EdgeBundle,
    EdgePointer,
    SessionRunBindingView,
    StoryExecutionLockView,
)
from agentkit.backend.control_plane.ownership import (
    OWNERSHIP_TRANSFERRED_REVOCATION_REASON,
    BindingStatus,
    OwnershipAcquisition,
    OwnershipStatus,
    TakeoverApprovalStatus,
)
from agentkit.backend.control_plane.records import (
    ControlPlaneOperationRecord,
    RunOwnershipRecord,
    SessionRunBindingRecord,
    TakeoverApprovalRecord,
    TakeoverTransferRecord,
)
from agentkit.backend.governance.guard_system.records import StoryExecutionLockRecord
from agentkit.backend.state_backend.governance_runtime_store import (
    load_story_execution_lock_global,
    save_story_execution_lock_global,
)
from agentkit.backend.state_backend.operation_ledger import commit_takeover_confirm_global
from agentkit.backend.state_backend.story_lifecycle_store import (
    insert_run_ownership_record_global,
    insert_takeover_approval_global,
    load_active_run_ownership_record_global,
    load_session_run_binding_global,
    load_takeover_approval_global,
    load_takeover_transfer_record_global,
    save_session_run_binding_global,
)
from agentkit.backend.state_backend.telemetry_event_store import (
    load_execution_events_global,
)
from agentkit.backend.telemetry.contract.records import ExecutionEventRecord
from agentkit.backend.telemetry.events import EventType

pytest_plugins = ("tests.fixtures.postgres_backend",)

_NOW = datetime(2026, 6, 7, 10, 0, tzinfo=UTC)


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
                challenge_ref="takeover-op",
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
        challenge_ref="takeover-op-2",
        status=TakeoverApprovalStatus.PENDING,
        requested_at=_NOW,
        expires_at=datetime(2026, 6, 7, 12, 0, tzinfo=UTC),
    )
    insert_takeover_approval_global(pending)
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
        _op_record(new_binding, op_id="op-confirm-2"),
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
        approved_approval=approved,
    )

    stored = load_takeover_approval_global("approval-confirm-atomic")
    assert stored is not None
    assert stored.status is TakeoverApprovalStatus.APPROVED
    assert stored.decided_by_session_id == "sess-human"
    active = load_active_run_ownership_record_global("tenant-b", "AG3-148B")
    assert active is not None
    assert active.owner_session_id == "sess-B2"


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
