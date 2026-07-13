"""Closure-to-Project-Edge merge command boundary (AG3-152)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from agentkit.backend.control_plane.edge_commands import edge_command_id
from agentkit.backend.control_plane.models import (
    MergeLocalCommandPayload,
    MergeLocalReport,
    MergeLocalRepository,
    ProvisionWorktreeCommandPayload,
    PushStatusReport,
    WorktreeReport,
)
from agentkit.backend.control_plane.records import EdgeCommandRecord

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.control_plane.repository import EdgeCommandRepository
    from agentkit.backend.pipeline_engine.phase_executor import (
        ClosureProgress,
        MultiRepoClosureState,
    )


class EdgeMergeState(StrEnum):
    """Backend orchestration state for an asynchronous edge merge command."""

    PENDING = "pending"
    MERGED = "merged"
    ESCALATED = "escalated"


@dataclass(frozen=True)
class EdgeCandidateEvidence:
    """Edge-reported candidate binding consumed by CI and Integrity-Gate."""

    repo_id: str
    commit_sha: str
    tree_hash: str
    worktree_clean: bool
    base_ancestor: bool


@dataclass(frozen=True)
class EdgeMergeOutcome:
    """One backend observation of the commissioned edge merge sequence."""

    state: EdgeMergeState
    report: MergeLocalReport | None = None
    detail: str = ""


class MergeLocalCommandPort(Protocol):
    """Commission/read the edge-local closure merge without running git."""

    def candidate(
        self, *, project_key: str, story_id: str, run_id: str, repo_id: str
    ) -> EdgeCandidateEvidence | None:
        """Return a pushed edge candidate or ``None`` fail-closed."""
        ...

    def execute(
        self,
        *,
        project_key: str,
        story_id: str,
        run_id: str,
        repo_ids: tuple[str, ...],
        candidate: EdgeCandidateEvidence,
        mode: str,
    ) -> EdgeMergeOutcome:
        """Commission or observe the idempotent edge merge command."""
        ...


@dataclass(frozen=True)
class QueueMergeLocalCommandPort:
    """Productive Postgres Edge-Command-Queue adapter for closure merge."""

    edge_commands: EdgeCommandRepository

    def candidate(
        self, *, project_key: str, story_id: str, run_id: str, repo_id: str
    ) -> EdgeCandidateEvidence | None:
        """Load candidate evidence bound to the passed closure-entry barrier."""
        from agentkit.backend.control_plane.push_barrier_lifecycle import (
            boundary_sync_point_id,
        )
        from agentkit.backend.control_plane.push_sync import (
            PushBarrierVerdictStatus,
            SyncPointBarrierType,
        )
        from agentkit.backend.state_backend.story_closure_store import (
            load_push_barrier_verdict_global,
            load_push_freshness_record_global,
        )

        freshness = load_push_freshness_record_global(
            project_key, story_id, run_id, repo_id
        )
        verdict = load_push_barrier_verdict_global(
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            boundary_type=SyncPointBarrierType.CLOSURE_ENTRY,
            boundary_id=run_id,
            repo_id=repo_id,
        )
        if (
            freshness is None
            or freshness.backlog
            or freshness.last_command_id is None
            or verdict is None
            or verdict.status is not PushBarrierVerdictStatus.PASSED
            or verdict.expected_head_sha is None
            or verdict.server_head_sha != verdict.expected_head_sha
            or freshness.last_sync_point_id
            != boundary_sync_point_id(
                SyncPointBarrierType.CLOSURE_ENTRY,
                run_id,
                verdict.boundary_epoch,
            )
        ):
            return None
        command = self.edge_commands.load_command(freshness.last_command_id)
        if command is None or command.status != "completed":
            return None
        try:
            report = PushStatusReport.model_validate(command.result_payload)
        except ValueError:
            return None
        if (
            report.push_outcome != "pushed"
            or not report.head_sha
            or report.head_sha != verdict.expected_head_sha
            or not report.tree_hash
            or report.worktree_clean is None
            or report.base_ancestor is None
        ):
            return None
        return EdgeCandidateEvidence(
            repo_id=repo_id,
            commit_sha=report.head_sha,
            tree_hash=report.tree_hash,
            worktree_clean=report.worktree_clean,
            base_ancestor=report.base_ancestor,
        )

    def execute(
        self,
        *,
        project_key: str,
        story_id: str,
        run_id: str,
        repo_ids: tuple[str, ...],
        candidate: EdgeCandidateEvidence,
        mode: str,
    ) -> EdgeMergeOutcome:
        """Ensure reprovisioning, then commission/read one ``merge_local``."""
        owner = _active_owner(project_key, story_id, run_id)
        if owner is None:
            return EdgeMergeOutcome(
                EdgeMergeState.ESCALATED,
                detail="no active ownership record for merge_local commissioning",
            )
        session_id, ownership_epoch = owner
        provision = self._ensure_reprovision(
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            repo_id=candidate.repo_id,
            session_id=session_id,
            ownership_epoch=ownership_epoch,
        )
        if provision is not None:
            return provision
        command_id = (
            f"{edge_command_id(run_id, 'merge_local', candidate.repo_id)}"
            f"::epoch:{ownership_epoch}"
        )
        existing = self.edge_commands.load_command(command_id)
        if existing is None:
            payload = MergeLocalCommandPayload(
                story_id=story_id,
                project_key=project_key,
                run_id=run_id,
                repositories=[MergeLocalRepository(repo_id=repo) for repo in repo_ids],
                mode="fast" if mode == "fast" else "standard",
                expected_candidate_commit=candidate.commit_sha,
                expected_candidate_tree_hash=candidate.tree_hash,
            )
            self.edge_commands.commission_command(
                _record(
                    command_id,
                    project_key=project_key,
                    story_id=story_id,
                    run_id=run_id,
                    session_id=session_id,
                    ownership_epoch=ownership_epoch,
                    command_kind="merge_local",
                    payload=payload.model_dump(mode="json"),
                )
            )
            return EdgeMergeOutcome(EdgeMergeState.PENDING)
        if existing.status in {"created", "delivered"}:
            return EdgeMergeOutcome(EdgeMergeState.PENDING)
        try:
            report = MergeLocalReport.model_validate(existing.result_payload)
        except ValueError as exc:
            return EdgeMergeOutcome(EdgeMergeState.ESCALATED, detail=str(exc))
        state = (
            EdgeMergeState.ESCALATED if report.escalated else EdgeMergeState.MERGED
        )
        return EdgeMergeOutcome(state, report=report, detail=report.detail)

    def _ensure_reprovision(
        self,
        *,
        project_key: str,
        story_id: str,
        run_id: str,
        repo_id: str,
        session_id: str,
        ownership_epoch: int,
    ) -> EdgeMergeOutcome | None:
        command_id = (
            f"{edge_command_id(run_id, 'provision_worktree', repo_id)}"
            f"::closure:epoch:{ownership_epoch}"
        )
        existing = self.edge_commands.load_command(command_id)
        if existing is None:
            payload = ProvisionWorktreeCommandPayload(
                story_id=story_id,
                project_key=project_key,
                run_id=run_id,
                repo_id=repo_id,
                branch=f"story/{story_id}",
                base_ref=f"origin/story/{story_id}",
                reuse_existing_branch=True,
            )
            self.edge_commands.commission_command(
                _record(
                    command_id,
                    project_key=project_key,
                    story_id=story_id,
                    run_id=run_id,
                    session_id=session_id,
                    ownership_epoch=ownership_epoch,
                    command_kind="provision_worktree",
                    payload=payload.model_dump(mode="json"),
                )
            )
            return EdgeMergeOutcome(EdgeMergeState.PENDING)
        if existing.status in {"created", "delivered"}:
            return EdgeMergeOutcome(EdgeMergeState.PENDING)
        try:
            report = WorktreeReport.model_validate(existing.result_payload)
        except ValueError as exc:
            return EdgeMergeOutcome(EdgeMergeState.ESCALATED, detail=str(exc))
        if report.outcome not in {"provisioned", "no_op"}:
            return EdgeMergeOutcome(
                EdgeMergeState.ESCALATED,
                detail="closure reprovisioning did not produce a usable worktree",
            )
        return None


@dataclass(frozen=True)
class ClosureEntryPushVerificationPort:
    """Read the authoritative AG3-147 closure-entry barrier verdicts."""

    def confirm_story_pushed(self, story_dir: Path) -> bool:
        """Return true only when every closure-entry repo verdict passed."""
        from agentkit.backend.control_plane.push_sync import (
            PushBarrierVerdictStatus,
            SyncPointBarrierType,
        )
        from agentkit.backend.state_backend.runtime_scope_resolver import (
            resolve_runtime_scope,
        )
        from agentkit.backend.state_backend.story_closure_store import (
            list_push_barrier_verdicts_global,
        )

        try:
            scope = resolve_runtime_scope(story_dir)
            if not scope.run_id:
                return False
            verdicts = list_push_barrier_verdicts_global(
                project_key=scope.project_key,
                story_id=scope.story_id,
                run_id=scope.run_id,
                boundary_type=SyncPointBarrierType.CLOSURE_ENTRY,
                boundary_id=scope.run_id,
            )
        except Exception:  # noqa: BLE001 -- unavailable checkpoint fails closed
            return False
        return bool(verdicts) and all(
            verdict.status is PushBarrierVerdictStatus.PASSED for verdict in verdicts
        )


def apply_merge_local_report(
    progress: ClosureProgress, report: MergeLocalReport
) -> tuple[ClosureProgress, MultiRepoClosureState]:
    """Map the wire report onto the unchanged closure progress contract."""
    from agentkit.backend.pipeline_engine.phase_executor import MultiRepoClosureState

    pushed = [item.repo_id for item in report.repositories if item.pushed]
    merged = [item.repo_id for item in report.repositories if item.merged]
    rolled_back = [item.repo_id for item in report.repositories if item.rolled_back]
    failed = next(
        (item.repo_id for item in report.repositories if item.outcome == "failed"),
        None,
    )
    updated = progress.model_copy(update={"merge_done": not report.escalated})
    return updated, MultiRepoClosureState(
        pushed_repos=pushed,
        merged_repos=merged,
        rolled_back_repos=rolled_back,
        failed_repo=failed,
    )


def _active_owner(
    project_key: str, story_id: str, run_id: str
) -> tuple[str, int] | None:
    from agentkit.backend.control_plane.repository import RunOwnershipRepository

    record = RunOwnershipRepository().load_active_ownership(project_key, story_id)
    if record is None or record.run_id != run_id:
        return None
    return record.owner_session_id, record.ownership_epoch


def _record(
    command_id: str,
    *,
    project_key: str,
    story_id: str,
    run_id: str,
    session_id: str,
    ownership_epoch: int,
    command_kind: str,
    payload: dict[str, object],
) -> EdgeCommandRecord:
    return EdgeCommandRecord(
        command_id=command_id,
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
        session_id=session_id,
        command_kind=command_kind,
        payload=payload,
        status="created",
        ownership_epoch=ownership_epoch,
        created_at=datetime.now(tz=UTC),
    )
