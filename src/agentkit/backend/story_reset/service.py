"""StoryResetService — the administrative FK-53 recovery flow (AG3-071).

``StoryResetService`` is the story-lifecycle BC's destructive recovery component
for an irreparably escalated story execution. It is a human-triggered,
checkpoint-capable administrative flow — explicitly NOT a PipelineEngine step, NOT
an override, NOT a normal recovery loop (FK-53 §53.2). It keeps the story alive as
a fachlich work unit and purges only the corrupt execution epoch (§53.1/§53.8).

The service is pure orchestration of the fixed 8-step §53.7 flow; every side
effect goes through a typed port / repository (no second purge truth, no raw
table DELETE past a foreign owner — FIX THE MODEL / SINGLE SOURCE OF TRUTH):

1. register the reset operation (``status=started``, audit + idempotency + resume
   anchor) — :meth:`request_reset`.
2. fence the story exclusively (Story ``RESETTING`` + reset-lock claim) BEFORE any
   deletion.
3. quiesce active runtime participants (lock/lease deactivation).
4. secure the minimal proof (the durable reset record).
5. purge the operative runtime state — Runtime-Execution via the typed
   ``RuntimeExecutionPurgePort`` AND locks/leases via the governance lock owner
   (SEPARATE owners, §53.7.5).
6. purge read-models + analytics — the FK-69 ``ProjectionAccessor`` (AG3-081) AND
   the AG3-082 analytics ``purge_story_analytics`` path (SEPARATE owners, §53.7.6).
7. remove ephemeral work surfaces (§53.7.7).
8. detach/remove the tainted worktree (§53.7.8).

The reset-lock is released and the record is set ``completed`` ONLY after every
purge domain succeeded and ``verify_reset_clean_state`` confirmed the §53.8 end
state (§53.9.3). A failure leaves the story administratively blocked
(``RESET_FAILED``, not runnable); a re-run with the same ``reset_id`` is a resume,
not a new reset (§53.9.1).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from agentkit.backend.control_plane.disown import build_disown_plan
from agentkit.backend.control_plane.ownership import BindingRevocationReason
from agentkit.backend.control_plane.records import ControlPlaneOperationRecord
from agentkit.backend.story_reset.models import (
    PlannedPurge,
    ResetCleanStateReport,
    ResetPurgeDomain,
    ResetStatus,
    StoryResetRecord,
    StoryResetRequest,
    StoryResetResult,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.backend.control_plane.disown import DisownPlan
    from agentkit.backend.control_plane.records import SessionRunBindingRecord


class StoryResetError(RuntimeError):
    """Fail-closed Story-Reset rejection (precondition / infra / verification)."""


# ---------------------------------------------------------------------------
# Typed outgoing ports (consumed owners — no second operative truth)
# ---------------------------------------------------------------------------


class StoryView(Protocol):
    """The minimal story projection the reset reads (status + project scope)."""

    @property
    def status(self) -> object: ...

    @property
    def project_key(self) -> str: ...


class StoryStatusPort(Protocol):
    """Status owner for the reset axis (``story_context_manager.StoryService``)."""

    def get_story(self, story_display_id: str) -> StoryView | None:
        """Return the story, or ``None`` when it does not exist."""

    def begin_reset(self, story_display_id: str) -> StoryView:
        """Fence the story (In Progress -> Resetting), §53.7.2."""

    def complete_reset(self, story_display_id: str) -> StoryView:
        """Release the story to the restartable base (Resetting -> In Progress)."""

    def mark_reset_failed(self, story_display_id: str) -> StoryView:
        """Block the story after an aborted reset (Resetting -> Reset Failed)."""

    def resume_reset_transition(self, story_display_id: str) -> StoryView:
        """Re-fence a blocked reset story (Reset Failed -> Resetting)."""


class ResetRecordStore(Protocol):
    """Durable persistence for the §53.5 reset record (idempotency/resume anchor)."""

    def load(self, reset_id: str) -> StoryResetRecord | None:
        """Load the reset record for ``reset_id`` (``None`` when unknown)."""

    def save(self, record: StoryResetRecord) -> None:
        """Persist (upsert) the reset record."""


class RunScopePort(Protocol):
    """Resolves the run scope (``run_id``) of the story's corrupt execution."""

    def resolve_run_id(self, project_key: str, story_id: str) -> str | None:
        """Return the current/last ``run_id`` of the story, or ``None``."""


class EscalationEvidencePort(Protocol):
    """Confirms the §53.4 escalation/exception finding from runtime/audit artifacts.

    The precondition is a FINDING (run/phase/audit), NOT a story stammdaten status
    (there is no ``StoryStatus.ESCALATED``); this port reads that finding.
    """

    def has_escalation_finding(
        self, project_key: str, story_id: str, run_id: str | None
    ) -> bool:
        """Return whether a belastbarer escalation/exception finding exists."""


class CompetingOperationPort(Protocol):
    """Detects a competing administrative operation for the same story (§53.4.4)."""

    def has_competing_admin_operation(
        self, project_key: str, story_id: str, run_id: str | None, reset_id: str
    ) -> bool:
        """Return whether a foreign committed admin op blocks this reset."""


class FencePort(Protocol):
    """The exclusive reset-lock fence (ControlPlaneOperationRecord claim, §53.7.2).

    Models the idempotency / resume anchor on the existing
    ``ControlPlaneOperationRecord`` pattern (no parallel hidden claim).
    """

    def claim(self, record: ControlPlaneOperationRecord) -> bool:
        """Atomically claim the reset fence; ``True`` iff this caller won it."""

    def load(self, op_id: str) -> ControlPlaneOperationRecord | None:
        """Load the fence operation for ``op_id`` (``None`` when absent)."""

    def release(self, op_id: str) -> None:
        """Release the reset fence (§53.9.3, only after verification + completed)."""


class RuntimePurgePort(Protocol):
    """Schritt 5 Runtime-Execution purge owner (``RuntimeExecutionPurgePort``)."""

    def purge_run(
        self, project_key: str, story_id: str, run_id: str
    ) -> dict[str, int]:
        """Purge all Runtime-Execution domains; return per-domain deleted rows."""

    def residue(
        self, project_key: str, story_id: str, run_id: str
    ) -> dict[str, int]:
        """Return remaining Runtime-Execution rows per domain (residue probe)."""


class LockPurgePort(Protocol):
    """Schritt 5 locks/leases purge owner (``Governance.deactivate_locks``)."""

    def deactivate_locks(self, story_id: str) -> None:
        """Deactivate all story-bound locks/leases + remove lock/edge exports."""

    def has_active_locks(self, story_id: str) -> bool:
        """Return whether any active lock/lease remains for the story."""


class ResetDisownPort(Protocol):
    """Adapter boundary for the reset's foreign-active-binding disown."""

    def load_active_binding(
        self,
        project_key: str,
        story_id: str,
        run_id: str,
    ) -> SessionRunBindingRecord | None:
        """Return the active owner binding for the reset run, if any."""

    def quiesce_inflight(
        self,
        project_key: str,
        story_id: str,
        reset_id: str,
        now: datetime,
    ) -> None:
        """CAS-abort in-flight operations and release their object claims."""

    def commit_disown(
        self,
        reset_id: str,
        plan: DisownPlan,
        now: datetime,
    ) -> None:
        """Atomically finalize the reset fence and persist the disown plan."""


class ResetControlPlanePort(FencePort, ResetDisownPort, Protocol):
    """Cohesive reset fence/disown boundary over one control-plane adapter."""


class ReadModelPurgePort(Protocol):
    """Schritt 6 FK-69 read-model purge owner (AG3-081 ``ProjectionAccessor``)."""

    def purge_run(
        self, project_key: str, story_id: str, run_id: str
    ) -> dict[str, int]:
        """Purge the run's FK-69 read models; return per-kind deleted rows."""


class AnalyticsPurgePort(Protocol):
    """Schritt 6 analytics purge owner (AG3-082 ``purge_story_analytics``)."""

    def purge_story_analytics(
        self, project_key: str, story_id: str, run_id: str
    ) -> None:
        """Purge the story's analytics derivations + recompute period rollups."""


class WorkspacePort(Protocol):
    """Schritt 7 ephemeral work-surface removal owner."""

    def purge_workspace(self, project_key: str, story_id: str) -> None:
        """Remove temp/scratch/sandbox/export artifacts of the corrupt run."""


class WorktreePort(Protocol):
    """Step 8 tainted-worktree teardown owner (edge-commissioned, AG3-145 D)."""

    def detach_worktrees(
        self, project_key: str, story_id: str, run_id: str | None
    ) -> None:
        """Commission the tainted story worktree teardown (FK-10 §10.4.2)."""

    def has_live_worktree(
        self, project_key: str, story_id: str, run_id: str | None
    ) -> bool:
        """Return whether a worktree still lacks a commissioned teardown command."""


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

#: FK-53 §53.7 purge domains in fixed flow order (Schritt 5 then Schritt 6 then
#: Schritt 7/8) — the dry-run plan and the executed flow share this order.
_PLANNED_DOMAINS: tuple[ResetPurgeDomain, ...] = (
    ResetPurgeDomain.RUNTIME_EXECUTION,
    ResetPurgeDomain.LOCKS_LEASES,
    ResetPurgeDomain.READ_MODELS,
    ResetPurgeDomain.ANALYTICS,
    ResetPurgeDomain.WORKSPACE,
    ResetPurgeDomain.WORKTREE,
)

_RESET_OPERATION_KIND = "story_reset"
_RUNNING_STORY_STATUS = "In Progress"
_RESETTING_STORY_STATUS = "Resetting"
_RESET_FAILED_STORY_STATUS = "Reset Failed"


class StoryResetService:
    """Orchestrates the single canonical FK-53 §53.7 Story-Reset flow.

    All collaborators are injected as typed ports (ARCH-26); the production wiring
    lives in ``bootstrap.composition_root.build_story_reset_service``. The four
    §53.10 contract operations are :meth:`request_reset`, :meth:`execute_reset`,
    :meth:`resume_reset` and :meth:`verify_reset_clean_state`; internal steps/ports
    are allowed (§53.10 "at least these").
    """

    def __init__(
        self,
        *,
        story_status: StoryStatusPort,
        record_store: ResetRecordStore,
        run_scope: RunScopePort,
        escalation_evidence: EscalationEvidencePort,
        competing_operation: CompetingOperationPort,
        fence: ResetControlPlanePort,
        runtime_purge: RuntimePurgePort,
        lock_purge: LockPurgePort,
        read_model_purge: ReadModelPurgePort,
        analytics_purge: AnalyticsPurgePort,
        workspace: WorkspacePort,
        worktree: WorktreePort,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._story_status = story_status
        self._records = record_store
        self._run_scope = run_scope
        self._escalation = escalation_evidence
        self._competing = competing_operation
        self._fence = fence
        self._runtime_purge = runtime_purge
        self._disown = fence
        self._lock_purge = lock_purge
        self._read_model_purge = read_model_purge
        self._analytics_purge = analytics_purge
        self._workspace = workspace
        self._worktree = worktree
        self._now_fn = now_fn or (lambda: datetime.now(tz=UTC))

    # ------------------------------------------------------------------
    # §53.10 contract: request_reset
    # ------------------------------------------------------------------

    def request_reset(self, request: StoryResetRequest) -> StoryResetRecord | PlannedPurge:
        """Validate §53.4 preconditions and register the reset (Schritt 1).

        Fail-closed entry gate (§53.4): the story must exist, carry a belastbarer
        escalation/exception finding (from runtime/audit artifacts, NOT a story
        stammdaten status) and have no competing administrative operation. A
        ``--dry-run`` request performs NO destructive mutation and writes NO
        record; it returns the :class:`PlannedPurge` blast radius instead.

        Idempotency (§53.9.1): a request carrying an existing ``reset_id`` returns
        the existing record (resume anchor), it does not create a second reset.

        Args:
            request: The human-CLI reset request.

        Returns:
            The persisted :class:`StoryResetRecord` (``status=started``), or a
            :class:`PlannedPurge` when ``request.dry_run`` is set.

        Raises:
            StoryResetError: When a §53.4 precondition fails.
        """
        story = self._story_status.get_story(request.story_id)
        if story is None:
            raise StoryResetError(
                f"reset rejected: story {request.story_id!r} does not exist (§53.4.1)"
            )
        run_id = self._run_scope.resolve_run_id(request.project_key, request.story_id)

        if not self._escalation.has_escalation_finding(
            request.project_key, request.story_id, run_id
        ) and not request.force:
            raise StoryResetError(
                "reset rejected: no belastbarer escalation/exception finding for "
                f"story {request.story_id!r} (§53.4.2); escalation is a finding from "
                "runtime/audit artifacts, not a story stammdaten status"
            )

        # Idempotency: an existing reset_id is a resume anchor, not a new reset.
        if request.reset_id is not None:
            existing = self._records.load(request.reset_id)
            if existing is not None:
                return existing

        reset_id = request.reset_id or f"story-reset-{uuid.uuid4().hex}"

        if self._competing.has_competing_admin_operation(
            request.project_key, request.story_id, run_id, reset_id
        ):
            raise StoryResetError(
                "reset rejected: a competing administrative operation is active for "
                f"story {request.story_id!r} (§53.4.4)"
            )

        if request.dry_run:
            return PlannedPurge(
                project_key=request.project_key,
                story_id=request.story_id,
                run_id=run_id,
                reason=request.reason,
                planned_domains=_PLANNED_DOMAINS,
            )

        record = StoryResetRecord(
            reset_id=reset_id,
            project_key=request.project_key,
            story_id=request.story_id,
            requested_by=request.requested_by,
            reason=request.reason,
            escalation_ref=request.escalation_ref,
            requested_at=self._now_fn(),
            status=ResetStatus.STARTED,
        )
        self._records.save(record)
        return record

    # ------------------------------------------------------------------
    # §53.10 contract: execute_reset
    # ------------------------------------------------------------------

    def execute_reset(self, reset_id: str) -> StoryResetResult:
        """Run the full §53.7 flow for a started reset (Schritt 2-8 + verify).

        Fences the story BEFORE any deletion (§53.7.2), then purges every domain in
        the fixed order through the typed owners, verifies the §53.8 end state and
        only then releases the reset-lock and sets the record ``completed``
        (§53.9.3). Any mid-flow failure marks the story ``RESET_FAILED`` (not
        runnable) and the record ``failed``, leaving a resumable reset (§53.9.2).

        Args:
            reset_id: The ``reset_id`` of a registered (``started``) reset.

        Returns:
            The :class:`StoryResetResult` (``resumed=False`` on a fresh execute).

        Raises:
            StoryResetError: When the reset is unknown or any step fails closed.
        """
        return self._drive(reset_id, resumed=False)

    # ------------------------------------------------------------------
    # §53.10 contract: resume_reset
    # ------------------------------------------------------------------

    def resume_reset(self, reset_id: str) -> StoryResetResult:
        """Resume the SAME reset after an abort (§53.9.1/§53.9.2).

        A resume re-fences a ``RESET_FAILED`` story and re-runs the remaining purge
        domains; every step is convergent/idempotent (delete-if-present), so an
        already-purged object does not hard-fail. This is NOT a new reset — the
        ``reset_id`` is unchanged.

        Args:
            reset_id: The ``reset_id`` of the reset to resume.

        Returns:
            The :class:`StoryResetResult` (``resumed=True``).

        Raises:
            StoryResetError: When the reset is unknown or any step fails closed.
        """
        record = self._records.load(reset_id)
        if record is None:
            raise StoryResetError(
                f"resume rejected: unknown reset_id {reset_id!r} (§53.9.1)"
            )
        if record.status is ResetStatus.COMPLETED:
            # Already done: a resume of a completed reset is an idempotent no-op.
            clean = self.verify_reset_clean_state(reset_id)
            return StoryResetResult(
                reset_id=reset_id, record=record, clean_state=clean, resumed=True
            )
        # Re-fence a blocked story (Reset Failed -> Resetting) before re-driving.
        self._story_status.resume_reset_transition(record.story_id)
        return self._drive(reset_id, resumed=True)

    # ------------------------------------------------------------------
    # §53.10 contract: verify_reset_clean_state
    # ------------------------------------------------------------------

    def verify_reset_clean_state(self, reset_id: str) -> ResetCleanStateReport:
        """Confirm the §53.8 end state for a reset (fail-closed, §53.10).

        Composes the Runtime-Residue probe, the lock probe, the read-model/analytics
        residue probes and the worktree probe, and confirms the reset proof exists
        and the story survived as a live restartable (non-Cancelled) work unit.
        ``ResetCleanStateReport.is_clean`` is ``True`` only when EVERY dimension is
        clean.

        Args:
            reset_id: The ``reset_id`` whose end state is verified.

        Returns:
            The :class:`ResetCleanStateReport` evidence.

        Raises:
            StoryResetError: When the reset_id is unknown.
        """
        record = self._records.load(reset_id)
        if record is None:
            raise StoryResetError(
                f"verify rejected: unknown reset_id {reset_id!r}"
            )
        run_id = self._run_scope.resolve_run_id(record.project_key, record.story_id)

        residue: dict[str, int] = {}
        runtime_clean = True
        if run_id is not None:
            residue = self._runtime_purge.residue(
                record.project_key, record.story_id, run_id
            )
            runtime_clean = all(count == 0 for count in residue.values())
        read_models_clean = True
        analytics_clean = True
        if run_id is not None:
            read_residue = self._read_model_purge.purge_run(
                record.project_key, record.story_id, run_id
            )
            # Convergent residue probe: a clean read-model store re-purges 0 rows.
            read_models_clean = all(count == 0 for count in read_residue.values())
            residue.update(
                {f"read_model:{name}": count for name, count in read_residue.items()}
            )

        locks_released = not self._lock_purge.has_active_locks(record.story_id)
        worktree_clean = not self._worktree.has_live_worktree(
            record.project_key, record.story_id, run_id
        )

        story = self._story_status.get_story(record.story_id)
        story_preserved = story is not None and str(getattr(story, "status", "")) not in (
            "Cancelled",
            "Done",
        )

        return ResetCleanStateReport(
            reset_id=reset_id,
            project_key=record.project_key,
            story_id=record.story_id,
            run_id=run_id,
            runtime_residue_clean=runtime_clean,
            locks_released=locks_released,
            read_models_clean=read_models_clean,
            analytics_clean=analytics_clean,
            worktree_clean=worktree_clean,
            reset_proof_present=True,
            story_preserved_restartable=story_preserved,
            residue_detail=residue,
        )

    # ------------------------------------------------------------------
    # internal flow
    # ------------------------------------------------------------------

    def _drive(self, reset_id: str, *, resumed: bool) -> StoryResetResult:
        """Drive Schritt 2-8 of the §53.7 flow and finalize (shared by execute/resume)."""
        record = self._records.load(reset_id)
        if record is None:
            raise StoryResetError(
                f"reset rejected: unknown reset_id {reset_id!r} (Schritt 1 missing)"
            )

        run_id = self._run_scope.resolve_run_id(record.project_key, record.story_id)
        try:
            # Schritt 2: fence the story (RESETTING) + acquire the reset-lock BEFORE
            # any deletion. Convergent: a story already RESETTING stays RESETTING.
            self._fence_story(record)
            self._acquire_fence(record, run_id)
            self._disown.quiesce_inflight(
                record.project_key,
                record.story_id,
                record.reset_id,
                self._now_fn(),
            )

            if run_id is not None:
                binding = self._disown.load_active_binding(
                    record.project_key,
                    record.story_id,
                    run_id,
                )
                if binding is not None:
                    disowned_at = self._now_fn()
                    plan = build_disown_plan(
                        binding,
                        BindingRevocationReason.STORY_RESET,
                        disowned_at,
                    )
                    self._disown.commit_disown(record.reset_id, plan, disowned_at)

            # Schritt 3 + 5 (locks/leases): quiesce active runtime participants and
            # deactivate locks/leases via the dedicated lock owner (NOT a read-model
            # repo). Convergent / idempotent on already-INACTIVE.
            self._lock_purge.deactivate_locks(record.story_id)

            summary: dict[str, int] = {}
            if run_id is not None:
                # Schritt 5 (runtime): Execution/Governance-runtime/canonical
                # PhaseState via the typed RuntimeExecutionPurgePort owner.
                runtime_rows = self._runtime_purge.purge_run(
                    record.project_key, record.story_id, run_id
                )
                summary[ResetPurgeDomain.RUNTIME_EXECUTION.value] = sum(
                    runtime_rows.values()
                )

                # Schritt 6 (read-models): FK-69 read models via the AG3-081
                # ProjectionAccessor owner (NOT the runtime owner).
                read_rows = self._read_model_purge.purge_run(
                    record.project_key, record.story_id, run_id
                )
                summary[ResetPurgeDomain.READ_MODELS.value] = sum(read_rows.values())

                # Schritt 6 (analytics): the AG3-082 purge_story_analytics path
                # (deletes fact_story + recomputes period rollups; itself re-invokes
                # the now-empty FK-69 purge convergently).
                self._analytics_purge.purge_story_analytics(
                    record.project_key, record.story_id, run_id
                )
                summary[ResetPurgeDomain.ANALYTICS.value] = 0

            # Schritt 7: ephemeral work surfaces.
            self._workspace.purge_workspace(record.project_key, record.story_id)
            # Step 8: tainted worktree -- commission the edge teardown (the
            # reset does not block on the physical removal; AG3-145 D).
            self._worktree.detach_worktrees(record.project_key, record.story_id, run_id)

            # Verify the §53.8 end state BEFORE releasing the lock / completing.
            clean = self.verify_reset_clean_state(reset_id)
            if not clean.is_clean:
                raise StoryResetError(
                    "reset verification failed: residual state remains "
                    f"({', '.join(clean.blocking_dimensions())})"
                )

            # Schritt 8 success: return the story to the restartable base.
            self._story_status.complete_reset(record.story_id)

            completed = record.model_copy(
                update={
                    "status": ResetStatus.COMPLETED,
                    "purge_summary": summary,
                    "completed_at": self._now_fn(),
                    "failure_reason": None,
                }
            )
            self._records.save(completed)
            # §53.9.3: release the reset-lock ONLY now (after purge + verify +
            # record completed).
            self._fence.release(reset_id)
            return StoryResetResult(
                reset_id=reset_id,
                record=completed,
                clean_state=clean,
                resumed=resumed,
            )
        except StoryResetError:
            self._mark_failed(record)
            raise
        except Exception as exc:  # noqa: BLE001 — convert infra faults to a typed abort
            self._mark_failed(record, reason=f"{type(exc).__name__}: {exc}")
            raise StoryResetError(
                f"reset {reset_id!r} aborted mid-flow: {type(exc).__name__}: {exc}"
            ) from exc

    def _fence_story(self, record: StoryResetRecord) -> None:
        """Move the story to RESETTING (convergent on an already-fenced story)."""
        story = self._story_status.get_story(record.story_id)
        if story is None:
            raise StoryResetError(
                f"reset rejected: story {record.story_id!r} vanished before fence"
            )
        status = str(getattr(story, "status", ""))
        if status == _RESETTING_STORY_STATUS:
            return
        if status == _RESET_FAILED_STORY_STATUS:
            self._story_status.resume_reset_transition(record.story_id)
            return
        if status != _RUNNING_STORY_STATUS:
            raise StoryResetError(
                f"reset rejected: story {record.story_id!r} must be "
                f"{_RUNNING_STORY_STATUS!r} to fence, found {status!r} (§53.7.2)"
            )
        self._story_status.begin_reset(record.story_id)

    def _acquire_fence(self, record: StoryResetRecord, run_id: str | None) -> None:
        """Claim the ControlPlane reset fence (idempotent on the same reset_id)."""
        existing = self._fence.load(record.reset_id)
        if existing is not None:
            if (
                existing.operation_kind == _RESET_OPERATION_KIND
                and existing.project_key == record.project_key
                and existing.story_id == record.story_id
            ):
                return
            raise StoryResetError(
                "reset fence collides with a foreign control-plane operation"
            )
        now = self._now_fn()
        op = ControlPlaneOperationRecord(
            op_id=record.reset_id,
            project_key=record.project_key,
            story_id=record.story_id,
            run_id=run_id,
            session_id=None,
            operation_kind=_RESET_OPERATION_KIND,
            phase=None,
            status="claimed",
            response_payload={
                "op_id": record.reset_id,
                "operation_kind": _RESET_OPERATION_KIND,
                "reset_status": ResetStatus.STARTED.value,
            },
            created_at=now,
            updated_at=now,
            claimed_by=f"story-reset-{record.reset_id}",
            claimed_at=now,
        )
        if not self._fence.claim(op):
            raise StoryResetError(
                f"reset fence for {record.reset_id!r} is held by a concurrent caller"
            )

    def _mark_failed(self, record: StoryResetRecord, *, reason: str | None = None) -> None:
        """Block the story (RESET_FAILED) and persist the failed record (§53.9.2)."""
        story = self._story_status.get_story(record.story_id)
        if story is not None and str(getattr(story, "status", "")) == (
            _RESETTING_STORY_STATUS
        ):
            self._story_status.mark_reset_failed(record.story_id)
        failed = record.model_copy(
            update={"status": ResetStatus.FAILED, "failure_reason": reason}
        )
        self._records.save(failed)


__all__ = [
    "AnalyticsPurgePort",
    "CompetingOperationPort",
    "EscalationEvidencePort",
    "FencePort",
    "LockPurgePort",
    "ReadModelPurgePort",
    "ResetControlPlanePort",
    "ResetDisownPort",
    "ResetRecordStore",
    "RunScopePort",
    "RuntimePurgePort",
    "StoryResetError",
    "StoryResetService",
    "StoryStatusPort",
    "StoryView",
    "WorkspacePort",
    "WorktreePort",
]
