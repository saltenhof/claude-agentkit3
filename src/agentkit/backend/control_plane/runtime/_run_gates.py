"""Run-admission and AG3-147 push-barrier gates."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from agentkit.backend.control_plane import (
    push_barrier_lifecycle,
)
from agentkit.backend.control_plane.ownership_fence import (
    OwnershipAdmission,
    OwnershipRejectionReason,
    evaluate_ownership_admission,
)
from agentkit.backend.control_plane.push_sync import (
    BarrierVerdict,
    PushBarrierBlockCode,
    PushBarrierVerdict,
    RepoPushVerdict,
    RepoPushVerificationInput,
    SyncPointBarrierType,
)

from ._operation_records import _rejection_result
from ._push_barrier_results import _barrier_from_repo_verdicts, _merge_precondition_from_barrier

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from agentkit.backend.control_plane.models import (
        ClosureCompleteRequest,
        ControlPlaneMutationResult,
        PhaseMutationRequest,
    )
    from agentkit.backend.control_plane.push_verification import PushBarrierEvidencePort
    from agentkit.backend.control_plane.repository import (
        ControlPlaneRuntimeRepository,
        EdgeCommandRepository,
    )

    from ._models import MergePrecondition

logger = logging.getLogger(__name__)

class _RunGateMixin:
    """Pre-mutation run gates: run-admission + two-stage push barrier (AG3-147).

    Cohesive fail-closed gating evaluated BEFORE a run mutation commits -- the
    shared run-scoped ownership admission probe (AG3-142) and the two-stage push
    barrier evidence (FK-10 §10.2.4b) -- split out of
    :class:`_ControlPlaneRuntimeAdmissionBase` for cohesion (PY_CLASS_MAX_LOC_800;
    no behaviour change). The concrete runtime supplies the shared dependencies
    below.
    """

    if TYPE_CHECKING:
        _repo: ControlPlaneRuntimeRepository
        _push_barrier_evidence: PushBarrierEvidencePort | None
        _push_barrier_evidence_factory: Callable[[], PushBarrierEvidencePort] | None
        _edge_command_repo: EdgeCommandRepository
        _now_fn: Callable[[], datetime]

        def _ownership_admission_rejection(
            self,
            admission: OwnershipAdmission,
            *,
            op_id: str,
            operation_kind: str,
            run_id: str | None,
            phase: str | None,
        ) -> ControlPlaneMutationResult: ...

    def _resolve_push_barrier_evidence(self, *, require_wired: bool) -> PushBarrierEvidencePort | None:
        """Return the wired two-stage push-barrier evidence port.

        An explicitly injected port wins. Otherwise a composition-root injected
        factory lazily builds the real Postgres+code-backend port on first use
        (barrier fail-closed enforced). A DI-injected repository WITHOUT an
        explicit port/factory is a wiring error at a push-gated boundary. Legacy
        custom-repository unit fixtures with no participating repos are not
        push-gated boundaries.
        """
        if self._push_barrier_evidence is not None:
            return self._push_barrier_evidence
        if self._push_barrier_evidence_factory is not None:
            self._push_barrier_evidence = self._push_barrier_evidence_factory()
            return self._push_barrier_evidence
        if not require_wired:
            return None
        raise AssertionError(
            "push_barrier_evidence or push_barrier_evidence_factory must be "
            "injected before a push-gated control-plane boundary; otherwise the "
            "AG3-147 barrier would be skipped"
        )

    def _push_barrier_block(
        self,
        barrier_type: SyncPointBarrierType,
        *,
        project_key: str,
        story_id: str,
        run_id: str,
        sync_point_id: str,
    ) -> BarrierVerdict | None:
        """Read the persisted boundary verdict; return a block or ``None``.

        Boundary consumers do NOT re-run the two-stage predicate here. They bind
        a boundary instance, commission the edge wait-point producer, and read
        the persisted ``PushBarrierVerdict`` SSOT. Result handling resolves that
        verdict after the edge returns and the backend has performed its own
        server ref-read.
        """
        verdicts = self._bind_push_boundary(
            barrier_type,
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            boundary_id=sync_point_id,
        )
        if verdicts is None:
            return None
        self._commission_sync_push_best_effort(
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            barrier_type=barrier_type,
            boundary_id=sync_point_id,
            verdicts=verdicts,
        )
        verdicts = self._load_boundary_verdicts(
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            boundary_type=barrier_type,
            boundary_id=sync_point_id,
        )
        if not verdicts:
            return _barrier_from_repo_verdicts(
                barrier_type,
                (
                    RepoPushVerdict(
                        repo_id="",
                        verified=False,
                        block_code=PushBarrierBlockCode.NO_PARTICIPATING_REPOS,
                        detail="no push-barrier verdict rows exist for this boundary",
                    ),
                ),
            )
        block = self._aggregate_persisted_push_barrier(
            barrier_type,
            verdicts,
            expected_repo_ids=self._participating_repo_ids(project_key, story_id),
        )
        return None if block.passed else block

    def _participating_repo_ids(self, project_key: str, story_id: str) -> tuple[str, ...]:
        ctx = self._repo.load_story_context(project_key, story_id)
        return tuple(ctx.participating_repos) if ctx is not None else ()

    def _bind_push_boundary(
        self,
        barrier_type: SyncPointBarrierType,
        *,
        project_key: str,
        story_id: str,
        run_id: str,
        boundary_id: str,
    ) -> tuple[PushBarrierVerdict, ...] | None:
        """Ensure per-repo verdict rows exist for the current boundary epoch."""
        ctx = self._repo.load_story_context(project_key, story_id)
        has_participating_repos = bool(ctx is not None and ctx.participating_repos)
        if self._resolve_push_barrier_evidence(require_wired=has_participating_repos) is None:
            return None
        if ctx is None or not ctx.participating_repos:
            return ()
        active = self._repo.load_active_ownership(project_key, story_id)
        if active is None or active.run_id != run_id:
            return ()
        now = self._now_fn()
        return push_barrier_lifecycle.bind_push_boundary(
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            boundary_type=barrier_type,
            boundary_id=boundary_id,
            repo_ids=tuple(ctx.participating_repos),
            ownership_epoch=active.ownership_epoch,
            load_verdict=self._load_boundary_verdict,
            persist_verdict=self._upsert_boundary_verdict,
            now=now,
        )

    def _aggregate_persisted_push_barrier(
        self,
        barrier_type: SyncPointBarrierType,
        verdicts: tuple[PushBarrierVerdict, ...],
        *,
        expected_repo_ids: tuple[str, ...],
    ) -> BarrierVerdict:
        """Aggregate persisted verdict rows with a final server-fresh recheck."""
        return push_barrier_lifecycle.aggregate_persisted_push_barrier(
            barrier_type,
            verdicts,
            expected_repo_ids=expected_repo_ids,
            server_head_for_verdict=self._server_head_for_verdict,
            persist_blocked_verdict=self._upsert_boundary_verdict,
            now=self._now_fn(),
        )

    def _collect_push_barrier_inputs(
        self,
        *,
        project_key: str,
        story_id: str,
        run_id: str,
        required_sync_point_id: str | None = None,
    ) -> tuple[RepoPushVerificationInput, ...] | None:
        """Collect the two-stage barrier inputs, or ``None`` when unwired (DI test)."""
        ctx = self._repo.load_story_context(project_key, story_id)
        has_participating_repos = bool(ctx is not None and ctx.participating_repos)
        port = self._resolve_push_barrier_evidence(require_wired=has_participating_repos)
        if port is None:
            return None
        return port.collect_repo_inputs(
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            required_sync_point_id=required_sync_point_id,
        )

    def _load_boundary_verdict(
        self,
        *,
        project_key: str,
        story_id: str,
        run_id: str,
        boundary_type: SyncPointBarrierType,
        boundary_id: str,
        repo_id: str,
    ) -> PushBarrierVerdict | None:
        """Load one persisted push-barrier verdict row."""
        from agentkit.backend.state_backend.story_closure_store import (
            load_push_barrier_verdict_global,
        )

        return load_push_barrier_verdict_global(
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            boundary_type=boundary_type,
            boundary_id=boundary_id,
            repo_id=repo_id,
        )

    def _load_boundary_verdicts(
        self,
        *,
        project_key: str,
        story_id: str,
        run_id: str,
        boundary_type: SyncPointBarrierType,
        boundary_id: str,
    ) -> tuple[PushBarrierVerdict, ...]:
        """List persisted verdict rows for one boundary instance."""
        from agentkit.backend.state_backend.story_closure_store import (
            list_push_barrier_verdicts_global,
        )

        return list_push_barrier_verdicts_global(
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            boundary_type=boundary_type,
            boundary_id=boundary_id,
        )

    @staticmethod
    def _upsert_boundary_verdict(verdict: PushBarrierVerdict) -> None:
        """Persist one push-barrier verdict row."""
        from agentkit.backend.state_backend.story_closure_store import (
            upsert_push_barrier_verdict_global,
        )

        upsert_push_barrier_verdict_global(verdict)

    def _server_head_for_verdict(self, verdict: PushBarrierVerdict) -> str | None:
        """Read the current server head for a verdict's repo."""
        inputs = self._collect_push_barrier_inputs(
            project_key=verdict.project_key,
            story_id=verdict.story_id,
            run_id=verdict.run_id,
            required_sync_point_id=push_barrier_lifecycle.boundary_sync_point_id(
                verdict.boundary_type, verdict.boundary_id, verdict.boundary_epoch
            ),
        )
        if inputs is None:
            return None
        for inp in inputs:
            if inp.repo_id == verdict.repo_id:
                return inp.server_head_sha if inp.server_ref_resolved else None
        return None

    def _closure_push_precondition_block(
        self, *, project_key: str, story_id: str, run_id: str, sync_point_id: str
    ) -> MergePrecondition | None:
        """Closure-entry boundary verdict read (distinct from pre-merge)."""
        block = self._push_barrier_block(
            SyncPointBarrierType.CLOSURE_ENTRY,
            project_key=project_key,
            story_id=story_id,
            run_id=run_id,
            sync_point_id=sync_point_id,
        )
        if block is None:
            return None
        return _merge_precondition_from_barrier(block)

    def _commission_sync_push_best_effort(
        self,
        *,
        project_key: str,
        story_id: str,
        run_id: str,
        barrier_type: SyncPointBarrierType,
        boundary_id: str,
        verdicts: tuple[PushBarrierVerdict, ...],
    ) -> None:
        """Queue ``sync_push`` for participating repos before a hard boundary.

        The command is an evidence producer for the barrier. Commissioning is
        opportunistic: failures do not open the boundary; the following barrier
        evaluation remains fail-closed on missing/old evidence.
        """
        try:
            ctx = self._repo.load_story_context(project_key, story_id)
            active = self._repo.load_active_ownership(project_key, story_id)
            if ctx is None or active is None or active.run_id != run_id:
                return
            now = self._now_fn()
            push_barrier_lifecycle.commission_sync_push_commands(
                project_key=project_key,
                story_id=story_id,
                run_id=run_id,
                owner_session_id=active.owner_session_id,
                ownership_epoch=active.ownership_epoch,
                boundary_type=barrier_type,
                boundary_id=boundary_id,
                verdicts=verdicts,
                load_command=self._edge_command_repo.load_command,
                commission_command=self._edge_command_repo.commission_command,
                persist_blocked_verdict=self._upsert_boundary_verdict,
                supersede_open_command=self._edge_command_repo.supersede_command,
                now=now,
            )
        except Exception as exc:  # noqa: BLE001 -- queue failure cannot open barrier
            logger.warning("sync_push commissioning failed before barrier: %s", exc)

    def _run_was_admitted(
        self,
        request: PhaseMutationRequest,
        *,
        run_id: str,
    ) -> OwnershipAdmission:
        """Whether the active ownership record admits THIS exact run (E3 / AG3-142).

        Args:
            request: The phase mutation request (lookup keys + session id).
            run_id: The authoritative path run id of the completion/failure.

        Returns:
            The :class:`OwnershipAdmission` verdict for THIS run/session.
        """
        return self._evaluate_run_admission(
            project_key=request.project_key,
            story_id=request.story_id,
            session_id=request.session_id,
            run_id=run_id,
        )

    def _closure_run_was_admitted(
        self,
        request: ClosureCompleteRequest,
        *,
        run_id: str,
    ) -> OwnershipAdmission:
        """Whether the active ownership record admits THIS run for closure (#6).

        Same run-matched admission rule as :meth:`_run_was_admitted`. Closure
        shares the complete/fail admission rule so the entrypoint is consistent
        (no unexplained asymmetry).
        """
        return self._evaluate_run_admission(
            project_key=request.project_key,
            story_id=request.story_id,
            session_id=request.session_id,
            run_id=run_id,
        )

    def _evaluate_run_admission(
        self,
        *,
        project_key: str,
        story_id: str,
        session_id: str,
        run_id: str,
    ) -> OwnershipAdmission:
        """Shared RUN-scoped admission probe for ALL 5 regime paths (AG3-142).

        IMPL-021 / SOLL-014: replaces the retired committed-op admission
        heuristic (``_run_admission_evidence``) ENTIRELY -- there is no positive
        committed-op evidence left. Admission evidence is EXCLUSIVELY the story's
        active ``run_ownership_records`` row (the session binding is a
        subordinate projection, never a second admission path;
        ``historical_ownership_records_are_never_admission_evidence``,
        ``story_execution_mutations_require_current_ownership_epoch``): a record
        with any status other than ``active`` is never returned by
        :attr:`~agentkit.backend.control_plane.repository.ControlPlaneRuntimeRepository.load_active_ownership`
        and therefore never admits (SOLL-014 / AC3).

        The exit-fence negative check (``has_committed_story_exit_operation_for_run``)
        is kept as the transition-protection short-circuit (AC11) until AG3-149
        maintains the record status on the exit path -- it is consulted FIRST,
        unchanged from the retired heuristic.

        Fail-closed: no active record for THIS run, or an active record whose
        ``owner_session_id`` differs, means the run was never admitted.
        """
        if self._repo.has_committed_story_exit_operation_for_run(project_key, story_id, run_id):
            return OwnershipAdmission(
                admitted=False,
                active_record=None,
                rejection_reason=OwnershipRejectionReason.STORY_EXITED,
            )
        active = self._repo.load_active_ownership(project_key, story_id)
        return evaluate_ownership_admission(active_record=active, run_id=run_id, session_id=session_id)

    def _unadmitted_run_rejection(
        self,
        admission: OwnershipAdmission,
        *,
        op_id: str,
        operation_kind: str,
        run_id: str,
        phase: str,
        reason: str,
    ) -> ControlPlaneMutationResult:
        """Fail-closed rejection for a run the active ownership record does not admit.

        Shared by closure/resume and available to other run-boundary callers:
        a transferred-ownership admission yields the rich ex-owner rejection
        (:meth:`_ownership_admission_rejection`); every other unadmitted reason
        yields the generic fail-closed rejection carrying ``reason``. The caller
        guards on ``not admission.admitted``.
        """
        if admission.rejection_reason is OwnershipRejectionReason.OWNERSHIP_TRANSFERRED:
            return self._ownership_admission_rejection(
                admission,
                op_id=op_id,
                operation_kind=operation_kind,
                run_id=run_id,
                phase=phase,
            )
        return _rejection_result(
            op_id=op_id,
            operation_kind=operation_kind,
            run_id=run_id,
            phase=phase,
            reason=reason,
            dispatch_phase=phase,
        )
