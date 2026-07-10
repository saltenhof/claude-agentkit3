"""Composition-root adapters for the FK-53 Story-Reset service (AG3-071).

These thin adapters bind the typed ``story_reset`` ports onto the REAL purge /
status / fence owners (no second operative truth). They live in the
composition-root layer (which is allowed to depend on every BC); the
``story_reset`` BC itself depends only on its own Protocols.
"""

from __future__ import annotations

import shutil
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.control_plane.disown import DisownPlan
    from agentkit.backend.control_plane.records import (
        ControlPlaneOperationRecord,
        SessionRunBindingRecord,
    )
    from agentkit.backend.control_plane.repository import (
        ControlPlaneRuntimeRepository,
        EdgeCommandRepository,
        RunOwnershipRepository,
    )
    from agentkit.backend.governance.runner import Governance
    from agentkit.backend.kpi_analytics.aggregation import RefreshWorker
    from agentkit.backend.state_backend.store.lock_record_repository import LockRecordRepository
    from agentkit.backend.state_backend.store.runtime_execution_purge import (
        RuntimeExecutionPurgePort,
        RuntimeExecutionResidueProbe,
    )
    from agentkit.backend.story.repository import StoryReadPort
    from agentkit.backend.telemetry.projection_accessor import ProjectionAccessor

from agentkit.backend.control_plane import object_claims
from agentkit.backend.control_plane.ownership import BindingStatus, OwnershipStatus
from agentkit.backend.control_plane.repository import ObjectMutationClaimRepository
from agentkit.backend.telemetry.contract.records import ExecutionEventRecord
from agentkit.backend.telemetry.events import EventType


class StoryResetLockError(RuntimeError):
    """Real lock-owner infra failure surfaced during a Story-Reset purge."""


class StoryResetWorktreeError(RuntimeError):
    """Fail-closed: a reset cannot commission the worktree teardown edge command."""


#: FK-25 / FK-53 §53.4 escalation/exception event signals (a FINDING from
#: runtime/audit artifacts, not a story stammdaten status).
_ESCALATION_SIGNALS = ("scope_explosion_check", "mandate_classification", "escalation")
#: Ephemeral work-surface subdirectories purged in §53.7.7.
_WORKSPACE_SUBDIRS = ("scratch", "tmp", "adversarial_sandbox", "exports")


@dataclass(frozen=True)
class RunScopeAdapter:
    """Resolve the story's current run_id via the canonical FlowExecution read."""

    story_repo: StoryReadPort

    def resolve_run_id(self, project_key: str, story_id: str) -> str | None:
        """Return the current/last ``run_id`` of the story, or ``None``."""
        flow = self.story_repo.load_flow_execution(project_key, story_id)
        return flow.run_id if flow is not None else None


@dataclass(frozen=True)
class EscalationEvidenceAdapter:
    """Confirm the §53.4 escalation/exception finding from execution events."""

    story_repo: StoryReadPort

    def has_escalation_finding(
        self, project_key: str, story_id: str, run_id: str | None
    ) -> bool:
        """Return whether a belastbarer escalation/exception finding exists."""
        if run_id is None:
            return False
        events = self.story_repo.load_recent_execution_events(
            project_key, story_id, run_id, 1000
        )
        for event in events:
            payload = event.payload if isinstance(event.payload, dict) else {}
            if event.event_type in _ESCALATION_SIGNALS:
                return True
            if str(payload.get("escalation_class")):
                return True
        return False


@dataclass(frozen=True)
class CompetingOperationAdapter:
    """Detect a competing committed admin operation for the same run (§53.4.4)."""

    cp_repo: ControlPlaneRuntimeRepository

    def has_competing_admin_operation(
        self,
        project_key: str,
        story_id: str,
        run_id: str | None,
        reset_id: str,
    ) -> bool:
        """Return whether a foreign committed admin op blocks this reset."""
        del reset_id
        if run_id is None:
            return False
        return self.cp_repo.has_committed_ownership_invalidating_operation_for_run(
            project_key, story_id, run_id
        )


@dataclass(frozen=True)
class FenceAdapter:
    """The reset fence over the ControlPlaneOperationRecord claim (§53.7.2)."""

    cp_repo: ControlPlaneRuntimeRepository

    def claim(self, record: ControlPlaneOperationRecord) -> bool:
        """Atomically claim the reset fence; ``True`` iff this caller won it."""
        return self.cp_repo.claim_operation(record)

    def load(self, op_id: str) -> ControlPlaneOperationRecord | None:
        """Load the fence operation for ``op_id`` (``None`` when absent)."""
        return self.cp_repo.load_operation(op_id)

    def release(self, op_id: str) -> None:
        """Release the live reset claim by retaining a committed terminal marker."""
        claimed = self.cp_repo.load_operation(op_id)
        if claimed is None:
            return
        if claimed.status == "committed":
            return
        if claimed.status != "claimed" or claimed.claimed_by is None:
            raise StoryResetLockError(
                f"reset fence {op_id!r} is not owned by the completing reset"
            )
        now = datetime.now(tz=UTC)
        response_payload = {
            **claimed.response_payload,
            "status": "committed",
            "reset_status": "completed",
        }
        terminal = replace(
            claimed,
            status="committed",
            response_payload=response_payload,
            updated_at=now,
            finalized_at=now,
            claimed_by=None,
            claimed_at=None,
        )
        if not self.cp_repo.finalize_operation(
            terminal,
            owner_token=claimed.claimed_by,
            owner_claimed_at=(
                claimed.claimed_at.isoformat() if claimed.claimed_at is not None else None
            ),
            owner_operation_epoch=claimed.operation_epoch,
        ):
            raise StoryResetLockError(
                f"reset fence {op_id!r} lost its ownership-scoped finalize CAS"
            )


@dataclass(frozen=True)
class ResetDisownAdapter:
    """Bind the reset disown port to the canonical control-plane transaction."""

    cp_repo: ControlPlaneRuntimeRepository
    object_claim_repo: ObjectMutationClaimRepository = field(
        default_factory=ObjectMutationClaimRepository,
    )

    def quiesce_inflight(
        self,
        project_key: str,
        story_id: str,
        reset_id: str,
        now: datetime,
    ) -> None:
        """Abort every foreign in-flight op and release its durable object claim."""

        for op_id in self.cp_repo.list_open_operation_ids_for_story(
            project_key,
            story_id,
        ):
            if op_id == reset_id:
                continue
            record = self.cp_repo.load_operation(op_id)
            if record is None or record.status != "claimed":
                continue
            response_payload = {
                "status": "failed",
                "op_id": record.op_id,
                "operation_kind": record.operation_kind,
                "run_id": record.run_id,
                "phase": record.phase,
                "admin_note": f"quiesced_by_story_reset:{reset_id}",
            }
            if not self.cp_repo.admin_abort_operation(
                op_id=record.op_id,
                status="failed",
                response_payload=response_payload,
                now=now,
            ):
                raise StoryResetLockError(
                    f"reset could not quiesce in-flight operation {record.op_id!r}",
                )
            claim_key = object_claims.parse_declared_scope(
                record.project_key,
                record.declared_serialization_scope,
            )
            if claim_key is not None and not self.object_claim_repo.release_claim(
                    claim_key.project_key,
                    claim_key.serialization_scope,
                    claim_key.scope_key,
                    record.op_id,
            ):
                remaining = self.object_claim_repo.load_claim(
                    claim_key.project_key,
                    claim_key.serialization_scope,
                    claim_key.scope_key,
                )
                if remaining is not None:
                    raise StoryResetLockError(
                        f"reset could not release object claim for {record.op_id!r}",
                    )

    def load_active_binding(
        self,
        project_key: str,
        story_id: str,
        run_id: str,
    ) -> SessionRunBindingRecord | None:
        """Load the active ownership projection and its exact active binding."""

        active = self.cp_repo.load_active_ownership(project_key, story_id)
        if active is None:
            return None
        if active.run_id != run_id:
            raise StoryResetLockError("reset disown active ownership belongs to another run")
        binding = self.cp_repo.load_binding(active.owner_session_id)
        if (
            binding is None
            or binding.status != BindingStatus.ACTIVE.value
            or binding.project_key != project_key
            or binding.story_id != story_id
            or binding.run_id != run_id
        ):
            raise StoryResetLockError(
                "reset disown requires the active owner's exact session binding",
            )
        return binding

    def commit_disown(
        self,
        reset_id: str,
        plan: DisownPlan,
        now: datetime,
    ) -> None:
        """Finalize the claimed reset op with revoke/status/audit atomically."""

        if plan.ownership_status_target is not OwnershipStatus.RESET:
            raise StoryResetLockError("reset disown plan must target ownership status reset")
        claimed = self.cp_repo.load_operation(reset_id)
        if (
            claimed is None
            or claimed.status != "claimed"
            or claimed.claimed_by is None
        ):
            raise StoryResetLockError("reset disown requires the owned claimed fence")
        terminal = replace(
            claimed,
            status="committed",
            response_payload={
                **claimed.response_payload,
                "status": "committed",
                "reset_status": "disowned",
                "revocation_reason": plan.reconcile_reason,
            },
            updated_at=now,
            finalized_at=now,
            claimed_by=None,
            claimed_at=None,
        )
        event = ExecutionEventRecord(
            project_key=plan.revoked_binding.project_key,
            story_id=plan.revoked_binding.story_id,
            run_id=plan.revoked_binding.run_id,
            event_id=f"evt-{uuid.uuid4().hex}",
            event_type=EventType.SESSION_DISOWNED.value,
            occurred_at=now,
            source_component="story_reset_service",
            severity="INFO",
            payload=plan.audit_payload,
        )
        if not self.cp_repo.finalize_disown(
            terminal,
            owner_token=claimed.claimed_by,
            owner_claimed_at=(
                claimed.claimed_at.isoformat() if claimed.claimed_at is not None else None
            ),
            owner_operation_epoch=claimed.operation_epoch,
            revoked_binding=plan.revoked_binding,
            ownership_status_target=plan.ownership_status_target,
            events=(event,),
        ):
            raise StoryResetLockError("reset disown lost its operation claim CAS")


@dataclass(frozen=True)
class RuntimePurgeAdapter:
    """Schritt 5 Runtime-Execution purge owner (``RuntimeExecutionPurgePort``)."""

    port: RuntimeExecutionPurgePort
    probe: RuntimeExecutionResidueProbe

    def purge_run(
        self, project_key: str, story_id: str, run_id: str
    ) -> dict[str, int]:
        """Purge all Runtime-Execution domains; return per-domain deleted rows."""
        return dict(self.port.purge_run(project_key, story_id, run_id).purged_rows)

    def residue(
        self, project_key: str, story_id: str, run_id: str
    ) -> dict[str, int]:
        """Return remaining Runtime-Execution rows per domain (residue probe)."""
        return dict(self.probe.check_run(project_key, story_id, run_id).residue_rows)


@dataclass(frozen=True)
class LockPurgeAdapter:
    """Schritt 5 locks/leases purge owner (``Governance.deactivate_locks``)."""

    governance: Governance
    lock_repo: LockRecordRepository

    def deactivate_locks(self, story_id: str) -> None:
        """Deactivate all story-bound locks/leases (convergent on absent rows)."""
        from agentkit.backend.governance.errors import LockRecordNotFoundError

        # FK-53 §53.9.1 convergence: a story with no lock rows (already purged /
        # never locked) must NOT hard-fail the reset. The lock owner raises
        # LockRecordNotFoundError for an unknown story; treat that as "nothing to
        # deactivate", but propagate a real infra error surfaced in ``errors``.
        try:
            result = self.governance.deactivate_locks(story_id)
        except LockRecordNotFoundError:
            return
        for err in result.errors:
            if "No lock records found" not in str(err):
                raise StoryResetLockError(str(err))

    def has_active_locks(self, story_id: str) -> bool:
        """Return whether any active lock/lease remains for the story."""
        return self.lock_repo.count_active_locks_for_story(story_id) > 0


@dataclass(frozen=True)
class ReadModelPurgeAdapter:
    """Schritt 6 FK-69 read-model purge owner (AG3-081 ``ProjectionAccessor``)."""

    accessor: ProjectionAccessor

    def purge_run(
        self, project_key: str, story_id: str, run_id: str
    ) -> dict[str, int]:
        """Purge the run's FK-69 read models; return per-kind deleted rows."""
        result = self.accessor.purge_run(project_key, story_id, run_id)
        rows = {kind.value: count for kind, count in result.purged_rows.items()}
        rows["guard_invocation_counters"] = result.purged_guard_counters
        return rows


@dataclass(frozen=True)
class AnalyticsPurgeAdapter:
    """Schritt 6 analytics purge owner (AG3-082 ``purge_story_analytics``)."""

    worker: RefreshWorker

    def purge_story_analytics(
        self, project_key: str, story_id: str, run_id: str
    ) -> None:
        """Purge the story's analytics derivations + recompute period rollups."""
        from agentkit.backend.kpi_analytics.aggregation.models import AffectedPeriods

        self.worker.purge_story_analytics(
            project_key, story_id, run_id, AffectedPeriods()
        )


@dataclass(frozen=True)
class WorkspacePurgeAdapter:
    """Schritt 7 ephemeral work-surface removal owner."""

    project_root: Path

    def purge_workspace(self, project_key: str, story_id: str) -> None:
        """Remove temp/scratch/sandbox/export artifacts of the corrupt run."""
        del project_key
        from agentkit.backend.installer.paths import story_dir as resolve_story_dir

        s_dir = resolve_story_dir(self.project_root, story_id)
        for sub in _WORKSPACE_SUBDIRS:
            target = s_dir / sub
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)


@dataclass(frozen=True)
class WorktreePurgeAdapter:
    """Step 8 tainted-worktree teardown owner (edge-commissioned, AG3-145 D).

    FK-10 §10.4.2 / §10.5.3: the reset no longer removes the worktree with a
    backend git subprocess. It COMMISSIONS a ``teardown_worktree`` edge command
    per worktree (idempotent, fire-and-forget) and does NOT block on the physical
    removal -- the open command stays auditably visible (FK-53 quiesce semantics
    untouched). The §53.8 worktree end-state is the commissioned command, not the
    physical absence.

    Attributes:
        edge_commands: The Edge-Command-Queue persistence port (commission).
        ownership_repo: The run-ownership port (owning session/epoch scope).
        project_root: The backend-local state anchor used to resolve the story
            directory when reading the participating-repo NAMES (never a path).
    """

    edge_commands: EdgeCommandRepository
    ownership_repo: RunOwnershipRepository
    project_root: Path

    def detach_worktrees(
        self, project_key: str, story_id: str, run_id: str | None
    ) -> None:
        """Commission a ``teardown_worktree`` edge command per worktree (§53.9.1).

        A worktree-less story (or a run-less reset) is a convergent no-op. When a
        worktree exists but no OWN active/reset ownership record scopes it, the reset
        fails closed (:class:`StoryResetWorktreeError`) -- never a silent skip.
        """
        if run_id is None:
            return
        repos = self._worktree_repos(story_id)
        if not repos:
            return
        record = self.ownership_repo.load_ownership(project_key, story_id, run_id)
        if record is None or record.status not in {
            OwnershipStatus.ACTIVE,
            OwnershipStatus.RESET,
        }:
            raise StoryResetWorktreeError(
                "story-reset worktree teardown cannot be commissioned: no owned "
                f"run-ownership record for (project={project_key!r}, "
                f"story={story_id!r}, run={run_id!r}); the owning session that "
                "scopes the teardown command is required (FK-56 §56.8a)."
            )
        from agentkit.backend.bootstrap.edge_provisioning_adapter import (
            commission_teardown_worktree,
        )

        commission_teardown_worktree(
            self.edge_commands,
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            session_id=record.owner_session_id,
            ownership_epoch=record.ownership_epoch,
            repos=tuple(repos),
            branch=f"story/{story_id}",
        )

    def has_live_worktree(
        self, project_key: str, story_id: str, run_id: str | None
    ) -> bool:
        """Return whether a worktree still lacks a commissioned teardown command.

        The §53.8 worktree end-state is satisfied once a teardown command is
        commissioned for every worktree (the auditable open command IS the proof,
        FK-10 §10.4.2); the reset never blocks on the physical removal.
        """
        del project_key
        if run_id is None:
            return False
        from agentkit.backend.control_plane.edge_commands import edge_command_id

        return any(
            self.edge_commands.load_command(
                edge_command_id(run_id, "teardown_worktree", repo)
            )
            is None
            for repo in self._worktree_repos(story_id)
        )

    def _worktree_repos(self, story_id: str) -> list[str]:
        """Return the participating repos holding a worktree (map keys, NOT paths).

        Reads the repo NAMES from ``StoryContext.worktree_map`` -- the backend
        derives no physical worktree PATH (FK-10 §10.2.4a); the teardown command
        carries only ``repo_id`` + branch and the edge resolves the path.
        """
        from agentkit.backend.installer.paths import story_dir as resolve_story_dir
        from agentkit.backend.state_backend.story_lifecycle_store import load_story_context

        ctx = load_story_context(resolve_story_dir(self.project_root, story_id))
        if ctx is None:
            return []
        return list(ctx.worktree_map.keys())


__all__ = [
    "AnalyticsPurgeAdapter",
    "CompetingOperationAdapter",
    "EscalationEvidenceAdapter",
    "FenceAdapter",
    "LockPurgeAdapter",
    "ReadModelPurgeAdapter",
    "ResetDisownAdapter",
    "RunScopeAdapter",
    "RuntimePurgeAdapter",
    "StoryResetLockError",
    "WorkspacePurgeAdapter",
    "WorktreePurgeAdapter",
]
