"""Control-plane runtime phase-resume responsibilities."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from agentkit.backend.control_plane.models import (
    ControlPlaneMutationResult,
    EdgeBundle,
    PhaseDispatchResult,
    PhaseMutationRequest,
)
from agentkit.backend.control_plane.push_sync import (
    SyncPointBarrierType,
)
from agentkit.backend.exceptions import (
    ControlPlaneBindingCollisionError,
    OwnershipFenceViolationError,
)

from ._edge_bundles import _build_edge_bundle, _build_fast_edge_bundle
from ._models import (
    _phase_binding_collision_reason,
)
from ._operation_records import (
    _control_plane_request_body_hash,
    _object_claim_busy_rejection,
    _operation_record,
    _push_barrier_rejection,
    _rejection_result,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from agentkit.backend.control_plane import object_claims
    from agentkit.backend.control_plane.models import ClosureCompleteRequest
    from agentkit.backend.control_plane.ownership_fence import OwnershipAdmission
    from agentkit.backend.control_plane.push_sync import BarrierVerdict
    from agentkit.backend.control_plane.repository import ControlPlaneRuntimeRepository

    from ._models import _ClaimOutcome

logger = logging.getLogger(__name__)


class _ControlPlaneResumeMixin:
    """Resume paused phases through the deterministic dispatcher."""

    if TYPE_CHECKING:
        _repo: ControlPlaneRuntimeRepository
        _now_fn: Callable[[], datetime]

        def _require_postgres_backend_on_first_use(self) -> None: ...

        def _load_existing_operation(
            self,
            request: PhaseMutationRequest | ClosureCompleteRequest,
            *,
            operation_kind: str,
            phase: str | None,
            mutating_retry: bool = True,
        ) -> ControlPlaneMutationResult | None: ...

        def _repair_locked_rejection(
            self,
            *,
            project_key: str,
            story_id: str,
            operation_kind: str,
            op_id: str,
            run_id: str | None,
            phase: str,
        ) -> ControlPlaneMutationResult | None: ...

        def _run_was_admitted(
            self, request: PhaseMutationRequest, *, run_id: str, command_id: str
        ) -> OwnershipAdmission: ...

        def _unadmitted_run_rejection(
            self,
            admission: OwnershipAdmission,
            *,
            op_id: str,
            operation_kind: str,
            run_id: str | None,
            phase: str | None,
            reason: str,
            session_id: str,
        ) -> ControlPlaneMutationResult: ...

        def _mint_owner_token(self) -> str: ...

        def _acquire_claim(
            self,
            request: PhaseMutationRequest,
            *,
            run_id: str,
            phase: str,
            owner_token: str,
            operation_kind: str = "phase_start",
        ) -> _ClaimOutcome: ...

        def _acquire_object_claim(
            self, *, project_key: str, story_id: str, op_id: str
        ) -> object_claims.ObjectClaimConflict | None: ...

        def _release_my_claim(self, op_id: str, owner_token: str, claimed_at_raw: str | None) -> None: ...

        def _release_my_claim_best_effort(self, op_id: str, owner_token: str, claimed_at_raw: str | None) -> None: ...

        def _release_object_claim(self, *, project_key: str, story_id: str, op_id: str) -> None: ...

        def _release_object_claim_best_effort(self, *, project_key: str, story_id: str, op_id: str) -> None: ...

        def _dispatch_phase(
            self,
            *,
            run_id: str,
            phase: str,
            request: PhaseMutationRequest,
            run_admitted: bool,
        ) -> PhaseDispatchResult | None: ...

        def _push_barrier_block(
            self,
            barrier_type: SyncPointBarrierType,
            *,
            project_key: str,
            story_id: str,
            run_id: str,
            sync_point_id: str,
        ) -> BarrierVerdict | None: ...

        def _ownership_fence_violation_rejection(
            self,
            exc: OwnershipFenceViolationError,
            *,
            op_id: str,
            operation_kind: str,
            run_id: str | None,
            phase: str | None,
        ) -> ControlPlaneMutationResult: ...

        def _in_flight_rejection(
            self, request: PhaseMutationRequest, *, operation_kind: str = "phase_start"
        ) -> ControlPlaneMutationResult: ...

    def resume_phase(
        self,
        *,
        run_id: str,
        phase: str,
        request: PhaseMutationRequest,
    ) -> ControlPlaneMutationResult:
        """Resume a PAUSED phase server-side by driving the pipeline-engine resume.

        AG3-130: the operator CLI ``resume`` is a thin REST requester; the core
        drives the real resume path here. The deterministic single-phase
        dispatcher derives resume-vs-start from the persisted PAUSED phase-state
        and calls :meth:`PipelineEngine.resume_phase` with the resume trigger the
        caller supplies in ``request.detail['resume_trigger']`` -- no phase
        business logic lives in the HTTP adapter or the CLI (FK-45 §45.2/§45.4,
        FK-10 §10.1.0 I3).

        The admission and idempotency rules mirror complete/fail
        (:meth:`_mutate_admitted_phase`): a replay of the same ``op_id`` returns
        the stored result; a resume for a run with no prior admitted start is
        rejected fail-closed (it must not materialize story-scoped state for an
        unadmitted run). The normalized phase outcome rides back on the SAME
        :class:`ControlPlaneMutationResult` via ``phase_dispatch`` (one truth, no
        second dispatch/state path).

        Args:
            run_id: The story run identifier.
            phase: The PAUSED phase to resume.
            request: The phase mutation request; ``detail['resume_trigger']``
                carries the resume trigger event name.

        Returns:
            The committed (or replayed) :class:`ControlPlaneMutationResult`
            carrying the ``phase_dispatch`` resume outcome, or a fail-closed
            rejection.
        """
        self._require_postgres_backend_on_first_use()
        existing = self._load_existing_operation(request, operation_kind="phase_resume", phase=phase)
        if existing is not None:
            return existing
        locked = self._repair_locked_rejection(
            project_key=request.project_key,
            story_id=request.story_id,
            operation_kind="phase_resume",
            op_id=request.op_id,
            run_id=run_id,
            phase=phase,
        )
        if locked is not None:
            return locked
        resume_admission = self._run_was_admitted(
            request,
            run_id=run_id,
            command_id="phase_resume",
        )
        if not resume_admission.admitted:
            return self._unadmitted_run_rejection(
                resume_admission,
                op_id=request.op_id,
                operation_kind="phase_resume",
                run_id=run_id,
                phase=phase,
                session_id=request.session_id,
                reason=(
                    "phase_resume rejected: the run has no active run-ownership "
                    "record for THIS project/story/run; fail-closed -- a resume "
                    "must not materialize story-scoped state for an unadmitted "
                    "run (FK-56 §56.8a)."
                ),
            )
        #: AG3-130 (Codex B1): reserve the op_id via the SAME owner-scoped
        #: claim as ``start_phase`` BEFORE the side-effecting engine resume runs.
        #: Exactly one concurrent caller wins; a loser is handed a fail-closed
        #: result (replay of a terminal row, or an in-flight-retry rejection) and
        #: NEVER runs ``PipelineEngine.resume_phase`` a second time (no double
        #: resume).
        owner_token = self._mint_owner_token()
        claim = self._acquire_claim(
            request,
            run_id=run_id,
            phase=phase,
            owner_token=owner_token,
            operation_kind="phase_resume",
        )
        if not claim.won:
            return claim.result_or_raise()
        owner_claimed_at = claim.claimed_at_raw
        owner_operation_epoch = claim.operation_epoch
        finalized = False
        try:
            #: SOLL-054: acquire the durable object-mutation claim BEFORE the
            #: side-effecting engine resume (a separate transaction from the
            #: control-plane finalize below, FK-10 §10.5.4). A busy object
            #: releases MY op_id claim (never resumed) and returns the K4
            #: deterministic 409 + Retry-After (IMPL-016).
            object_conflict = self._acquire_object_claim(
                project_key=request.project_key,
                story_id=request.story_id,
                op_id=request.op_id,
            )
            if object_conflict is not None:
                self._release_my_claim(request.op_id, owner_token, owner_claimed_at)
                return _object_claim_busy_rejection(
                    op_id=request.op_id,
                    operation_kind="phase_resume",
                    run_id=run_id,
                    phase=phase,
                    conflict=object_conflict,
                )
            #: Drive the deterministic dispatcher: with the persisted phase-state
            #: PAUSED for this phase it derives a resume (not a fresh start) and
            #: runs ``PipelineEngine.resume_phase`` with the trigger from
            #: ``request.detail`` -- now protected by the claims.
            dispatch_result = self._dispatch_phase(
                run_id=run_id,
                phase=phase,
                request=request,
                run_admitted=resume_admission.admitted,
            )
            rejection = self._resume_rejection_if_unsuccessful(dispatch_result, run_id=run_id, phase=phase, request=request)
            if rejection is not None:
                #: AG3-130 (Codex M3): a resume that did NOT advance/re-pause the
                #: phase (absent ctx, not-PAUSED, invalid trigger -> EngineResult
                #: failed with ``dispatched=True``, or a failed/escalated resume)
                #: must NOT commit an operation or materialize a binding/lock/
                #: SESSION_RUN_BINDING_CREATED. Release MY claims and return the
                #: NON-stored rejection (the engine's own phase-state, if any,
                #: stands). A retry then re-evaluates.
                self._release_my_claim(request.op_id, owner_token, owner_claimed_at)
                self._release_object_claim(
                    project_key=request.project_key,
                    story_id=request.story_id,
                    op_id=request.op_id,
                )
                return rejection
            #: AG3-147 (FK-10 §10.2.4b boundary type 3): the yield-point push
            #: barrier -- a phase that RE-PAUSES (yields to the worker) is
            #: fail-closed BLOCKED until the current state is server-verified-
            #: pushed (a takeover during the yield can never lose unpushed work).
            #: Checked BEFORE the finalize commit; a block releases MY claims and
            #: stores NO operation (the engine phase-state stands; a retry
            #: re-evaluates once the push lands).
            yield_rejection = self._yield_point_barrier_rejection(
                dispatch_result,
                request=request,
                run_id=run_id,
                phase=phase,
                owner_token=owner_token,
                owner_claimed_at=owner_claimed_at,
            )
            if yield_rejection is not None:
                return yield_rejection
            #: ``resume_admission.admitted`` is True, so ``active_record`` is
            #: present (``evaluate_ownership_admission``).
            assert resume_admission.active_record is not None  # noqa: S101
            result = self._finalize_resume_phase(
                run_id=run_id,
                phase=phase,
                request=request,
                owner_token=owner_token,
                owner_claimed_at=owner_claimed_at,
                owner_operation_epoch=owner_operation_epoch,
                phase_dispatch=dispatch_result,
                expected_ownership_epoch=resume_admission.active_record.ownership_epoch,
            )
            #: Codex-R1 (BLOCKER): mark ``finalized`` (op terminal) BEFORE releasing,
            #: then NON-best-effort release -- a release failure SURFACES (5xx),
            #: never swallowed while the API returns ``committed`` with a held claim.
            finalized = True
            self._release_object_claim(
                project_key=request.project_key,
                story_id=request.story_id,
                op_id=request.op_id,
            )
            return result
        except OwnershipFenceViolationError as exc:
            #: AG3-142 (no TOCTOU): the ownership fence re-check at commit time
            #: failed -- a takeover landed between the early admission check and
            #: this commit. The whole finalize rolled back (no side effect, no
            #: stored op). Release MY claims and surface the rich ex-owner
            #: rejection.
            self._release_my_claim_best_effort(request.op_id, owner_token, owner_claimed_at)
            self._release_object_claim(
                project_key=request.project_key,
                story_id=request.story_id,
                op_id=request.op_id,
            )
            return self._ownership_fence_violation_rejection(
                exc,
                op_id=request.op_id,
                operation_kind="phase_resume",
                run_id=run_id,
                phase=phase,
            )
        except ControlPlaneBindingCollisionError as exc:
            #: AG3-054 run-scoping: the binding SAVE would overwrite a live binding
            #: belonging to a DIFFERENT run that rebound the same session. The store
            #: refused fail-closed and the WHOLE transaction rolled back -- a resume
            #: for an old run must never clobber a foreign run's live binding.
            self._release_my_claim_best_effort(request.op_id, owner_token, owner_claimed_at)
            #: Codex-R1 (BLOCKER): NON-best-effort object-claim release on this
            #: handled-return rejection (surface failures, never a swallowed held
            #: claim behind a normal rejection).
            self._release_object_claim(
                project_key=request.project_key,
                story_id=request.story_id,
                op_id=request.op_id,
            )
            reason = _phase_binding_collision_reason("phase_resume", exc)
            return _rejection_result(
                op_id=request.op_id,
                operation_kind="phase_resume",
                run_id=run_id,
                phase=phase,
                reason=reason,
                dispatch_phase=phase,
            )
        except BaseException:
            #: Any error before the terminal finalize MUST release MY claims (best
            #: effort, never masking the original error) so the op_id/object are
            #: not stranded (NO ERROR BYPASSING). A crash here leaves BOTH claims
            #: durably held -- ended ONLY via the AG3-138 startup reconciliation
            #: or an explicit admin_abort_inflight_operation.
            if not finalized:
                self._release_my_claim_best_effort(request.op_id, owner_token, owner_claimed_at)
                self._release_object_claim_best_effort(
                    project_key=request.project_key,
                    story_id=request.story_id,
                    op_id=request.op_id,
                )
            raise

    def _yield_point_barrier_rejection(
        self,
        dispatch_result: PhaseDispatchResult | None,
        *,
        request: PhaseMutationRequest,
        run_id: str,
        phase: str,
        owner_token: str,
        owner_claimed_at: str | None,
    ) -> ControlPlaneMutationResult | None:
        """Yield-point push barrier (FK-10 §10.2.4b type 3); rejection or ``None``.

        A phase that RE-PAUSES (``yielded``) is fail-closed BLOCKED until the
        current state is server-verified-pushed. On a block MY op_id + object
        claims are released and the NON-stored ``push_barrier_unverified``
        rejection is returned; a passed/absent barrier returns ``None`` and the
        resume proceeds to finalize (behaviour identical to the inlined check).
        """
        if dispatch_result is None or dispatch_result.status != "yielded":
            return None
        yield_block = self._push_barrier_block(
            SyncPointBarrierType.YIELD_POINT,
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=run_id,
            sync_point_id=f"{run_id}:{phase}",
        )
        if yield_block is None:
            return None
        self._release_my_claim(request.op_id, owner_token, owner_claimed_at)
        self._release_object_claim(
            project_key=request.project_key,
            story_id=request.story_id,
            op_id=request.op_id,
        )
        return _push_barrier_rejection(
            yield_block,
            op_id=request.op_id,
            operation_kind="phase_resume",
            run_id=run_id,
            phase=phase,
        )

    def _resume_rejection_if_unsuccessful(
        self,
        dispatch_result: PhaseDispatchResult | None,
        *,
        run_id: str,
        phase: str,
        request: PhaseMutationRequest,
    ) -> ControlPlaneMutationResult | None:
        """Return a NON-stored resume rejection, or ``None`` when the resume advanced.

        AG3-130 (Codex M3): a resume commits (materializes binding/locks + a
        terminal op) ONLY when it actually advanced or re-paused the phase
        (``phase_completed`` / ``yielded``). Every other outcome -- an absent
        StoryContext, a dispatcher rejection, an invalid resume trigger (the engine
        returns ``EngineResult(status="failed")`` which ``_normalize`` reports as
        ``dispatched=True``), or a failed/escalated resume -- is a fail-closed
        rejection that stores NO operation and NO side effects.
        """
        if dispatch_result is None:
            return _rejection_result(
                op_id=request.op_id,
                operation_kind="phase_resume",
                run_id=run_id,
                phase=phase,
                reason=(
                    "phase_resume rejected: the run's StoryContext is absent, so "
                    "the PAUSED phase cannot be resolved server-side; fail-closed "
                    "(FK-20 §20.8.2)."
                ),
                dispatch_phase=phase,
            )
        if dispatch_result.status in ("phase_completed", "yielded"):
            return None
        #: Not advanced (rejected / failed / escalated). Carry the normalized
        #: dispatch outcome on ``phase_dispatch`` (edge_bundle stays None -> the
        #: ``rejected`` result invariant holds).
        return ControlPlaneMutationResult(
            status="rejected",
            op_id=request.op_id,
            operation_kind="phase_resume",
            run_id=run_id,
            phase=phase,
            edge_bundle=None,
            phase_dispatch=dispatch_result,
        )

    def _finalize_resume_phase(
        self,
        *,
        run_id: str,
        phase: str,
        request: PhaseMutationRequest,
        owner_token: str,
        owner_claimed_at: str | None,
        owner_operation_epoch: int | None = None,
        phase_dispatch: PhaseDispatchResult | None,
        expected_ownership_epoch: int,
    ) -> ControlPlaneMutationResult:
        """Commit ONLY the ``phase_resume`` op record; never re-materialize a start.

        Codex N1: a successful resume CONTINUES an existing run. The engine already
        persisted the phase-state transition during the dispatch. The control plane
        therefore persists ONLY (a) the idempotent ``phase_resume`` operation record
        (op_id replay) under the ownership CAS -- with NO binding / lock / event side
        effects -- and returns an edge bundle that MIRRORS the run's CURRENT
        (unchanged) session binding + story-execution lock. It writes NO new
        :class:`SessionRunBindingRecord`, NO new / re-activated ACTIVE lock and emits
        NO ``SESSION_RUN_BINDING_CREATED`` / ``STORY_EXECUTION_REGIME_ACTIVATED``
        events: those were materialized by the ORIGINAL start; a resume must not
        duplicate them (a false second activation / a clobbered ``activated_at`` /
        ``binding_version``).

        A lost ownership CAS (e.g. a concurrent admin-abort of the same claim)
        replays the resolved terminal row; the loser writes nothing.
        """
        now = self._now_fn()
        bundle = self._resume_edge_bundle(request, run_id=run_id, now=now)
        result = ControlPlaneMutationResult(
            status="committed",
            op_id=request.op_id,
            operation_kind="phase_resume",
            run_id=run_id,
            phase=phase,
            edge_bundle=bundle,
            phase_dispatch=phase_dispatch,
            #: SOLL-017 accountability: a resume never mints -- always the
            #: active record's epoch observed at admission.
            ownership_epoch=expected_ownership_epoch,
        )
        record = _operation_record(
            op_id=request.op_id,
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=run_id,
            session_id=request.session_id,
            operation_kind="phase_resume",
            phase=phase,
            result=result,
            now=now,
            request_body_hash=_control_plane_request_body_hash(request, operation_kind="phase_resume", phase=phase),
        )
        #: Ownership-CAS finalize of ONLY the op record (binding/locks/events are
        #: EMPTY -- mirrors the fast-start finalize which materializes no side
        #: effects). The resume never re-writes the run's binding/lock regime.
        if self._repo.finalize_start_phase(
            record,
            owner_token=owner_token,
            owner_claimed_at=owner_claimed_at,
            owner_operation_epoch=owner_operation_epoch,
            binding=None,
            locks=(),
            events=(),
            #: AG3-142 (SOLL-015, no TOCTOU): a resume commits against the run's
            #: EXISTING active record -- it never mints one.
            expected_ownership_epoch=expected_ownership_epoch,
        ):
            return result
        #: LATE-OWNER resume finalize (ownership CAS lost): surface my own terminal
        #: row VERBATIM (``mutating_retry=False``), not the fresh-retry conflict.
        existing = self._load_existing_operation(
            request,
            operation_kind="phase_resume",
            phase=phase,
            mutating_retry=False,
        )
        if existing is not None:
            return existing
        return self._in_flight_rejection(request, operation_kind="phase_resume")

    def _resume_edge_bundle(
        self,
        request: PhaseMutationRequest,
        *,
        run_id: str,
        now: datetime,
    ) -> EdgeBundle:
        """Build the resume edge bundle from the run's EXISTING binding/lock (read-only).

        The bundle MIRRORS the current story-execution regime so the local edge
        keeps its operating mode; it triggers NO write (Codex N1). When no
        run-matched binding/lock exists (a fast story or an already-cleaned run) an
        ``ai_augmented`` bundle is returned.
        """
        binding = self._repo.load_binding(request.session_id)
        if (
            binding is None
            or binding.project_key != request.project_key
            or binding.story_id != request.story_id
            or binding.run_id != run_id
        ):
            return _build_fast_edge_bundle(project_key=request.project_key, sync_class="mutation", now=now)
        lock = self._repo.load_lock(binding.project_key, binding.story_id, binding.run_id, "story_execution")
        if lock is None:
            return _build_fast_edge_bundle(project_key=request.project_key, sync_class="mutation", now=now)
        qa_lock = self._repo.load_lock(binding.project_key, binding.story_id, binding.run_id, "qa_artifact_write")
        return _build_edge_bundle(
            binding=binding,
            lock=lock,
            qa_lock=qa_lock,
            sync_class="mutation",
            now=now,
        )


__all__ = ["_ControlPlaneResumeMixin"]
