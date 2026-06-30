"""Composition-root adapters for the FK-53 Story-Reset service (AG3-071).

These thin adapters bind the typed ``story_reset`` ports onto the REAL purge /
status / fence owners (no second operative truth). They live in the
composition-root layer (which is allowed to depend on every BC); the
``story_reset`` BC itself depends only on its own Protocols.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.control_plane.records import ControlPlaneOperationRecord
    from agentkit.backend.control_plane.repository import ControlPlaneRuntimeRepository
    from agentkit.backend.governance.runner import Governance
    from agentkit.backend.kpi_analytics.aggregation import RefreshWorker
    from agentkit.backend.state_backend.store.lock_record_repository import LockRecordRepository
    from agentkit.backend.state_backend.store.runtime_execution_purge import (
        RuntimeExecutionPurgePort,
        RuntimeExecutionResidueProbe,
    )
    from agentkit.backend.state_backend.store.worktree_repository import (
        StateBackendWorktreeRepository,
    )
    from agentkit.backend.story.repository import StoryReadPort
    from agentkit.backend.telemetry.projection_accessor import ProjectionAccessor


class StoryResetLockError(RuntimeError):
    """Real lock-owner infra failure surfaced during a Story-Reset purge."""


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
        return self.cp_repo.has_committed_story_exit_operation_for_run(
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
        """Release the reset fence (§53.9.3)."""
        self.cp_repo.delete_operation(op_id)


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
    """Schritt 8 tainted-worktree teardown owner."""

    worktree_repo: StateBackendWorktreeRepository

    def detach_worktrees(self, story_id: str) -> None:
        """Remove/detach the tainted story worktree(s) (convergent, §53.9.1)."""
        from agentkit.backend.exceptions import WorktreeError
        from agentkit.backend.utils.git import remove_worktree

        for wt_path in self.worktree_repo.list_worktree_paths(story_id):
            repo_root = wt_path.parent
            try:
                remove_worktree(repo_root, wt_path)
            except WorktreeError:
                # A worktree that cannot be removed via its inferred repo root is
                # detached on a best-effort basis; the directory removal makes the
                # probe converge.
                if wt_path.exists():
                    shutil.rmtree(wt_path, ignore_errors=True)

    def has_live_worktree(self, story_id: str) -> bool:
        """Return whether a live (non-detached) story worktree remains."""
        return any(
            wt_path.exists()
            for wt_path in self.worktree_repo.list_worktree_paths(story_id)
        )


__all__ = [
    "AnalyticsPurgeAdapter",
    "CompetingOperationAdapter",
    "EscalationEvidenceAdapter",
    "FenceAdapter",
    "LockPurgeAdapter",
    "ReadModelPurgeAdapter",
    "RunScopeAdapter",
    "RuntimePurgeAdapter",
    "StoryResetLockError",
    "WorkspacePurgeAdapter",
    "WorktreePurgeAdapter",
]
