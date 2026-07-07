"""Composed control-plane runtime service entrypoint."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from agentkit.backend.control_plane import (
    runtime_constants,
)
from agentkit.backend.control_plane.models import (
    ClosureCompleteRequest,
    ControlPlaneMutationResult,
    EdgeBundle,
    PhaseDispatchResult,
    PhaseMutationRequest,
)
from agentkit.backend.control_plane.push_sync import (
    SyncPointBarrierType,
)
from agentkit.backend.control_plane.records import (
    BindingDeleteScope,
    SessionRunBindingRecord,
)

# Deliberate RUNTIME re-import (not TYPE_CHECKING): this is the SSOT re-import of
# the canonical FK-56 operating-mode literal from its SINGLE foundation definition
# (``core_types.operating_mode``). It must be a runtime binding so the
# single-definition identity holds for consumers (and is assertable) -- moving it
# into a type-checking block would make ``control_plane.runtime.OperatingMode`` a
# different/absent object at runtime, defeating the AK2 SSOT consolidation.
from agentkit.backend.exceptions import (
    ControlPlaneBindingCollisionError,
    ControlPlaneClaimCollisionError,
    OwnershipFenceViolationError,
)
from agentkit.backend.governance.guard_system.records import StoryExecutionLockRecord
from agentkit.backend.governance.guard_system.story_scoped_guards import should_create_story_lock_records
from agentkit.backend.telemetry.events import EventType

from ._admin import _AdminTransitionMixin
from ._admission import _ControlPlaneRuntimeAdmissionBase
from ._closure import _complete_fast_closure
from ._edge_bundles import _build_edge_bundle, _build_fast_edge_bundle, _next_binding_version
from ._edge_commands import _EdgeCommandMixin
from ._materialization import _plan_fast_materialization, _plan_story_scoped_materialization
from ._models import (
    _claimed_operation_rejection_reason,
    _closure_binding_collision_reason,
    _ModeResolutionKeys,
    _phase_binding_collision_reason,
)
from ._operation_records import (
    _control_plane_request_body_hash,
    _lifecycle_event_record,
    _object_claim_busy_rejection,
    _operation_record,
    _push_barrier_rejection,
    _rejection_result,
    _replay_or_mismatch,
)
from ._project_edge_sync import _ProjectEdgeSyncMixin

logger = logging.getLogger(__name__)

class ControlPlaneRuntimeService(
    _AdminTransitionMixin,
    _EdgeCommandMixin,
    _ProjectEdgeSyncMixin,
    _ControlPlaneRuntimeAdmissionBase,
):
    """Implement control-plane mutations with idempotent op replay."""

    def complete_closure(
        self,
        *,
        run_id: str,
        request: ClosureCompleteRequest,
    ) -> ControlPlaneMutationResult:
        """Complete closure for a story run, tearing down its guard regime.

        AG3-018 FIX-2 (FK-24 §24.3.4; ``no_locks_active``): the authoritative
        story mode is resolved server-side (same sanctioned surface as
        ``_mutate_phase``; fail-closed-to-standard on an unresolvable
        ``StoryContext``). A FAST story never activated story-scoped guards, so
        its closure is a true no-op -- it creates NO ``story_execution`` /
        ``qa_artifact_write`` lock-records and emits NO story-execution
        deactivation events (see :meth:`_complete_fast_closure`). Standard /
        exploration closure is unchanged: it writes the INACTIVE lock-records and
        emits the binding-removed + regime-deactivated events.

        Args:
            run_id: The story run identifier.
            request: The closure completion request.

        Returns:
            The committed (or replayed) closure :class:`ControlPlaneMutationResult`.
        """
        self._require_postgres_backend_on_first_use()
        existing = self._load_existing_operation(request, operation_kind="closure_complete", phase="closure")
        if existing is not None:
            return existing
        locked = self._repair_locked_rejection(
            project_key=request.project_key,
            story_id=request.story_id,
            operation_kind="closure_complete",
            op_id=request.op_id,
            run_id=run_id,
            phase="closure",
        )
        if locked is not None:
            return locked

        closure_admission = self._closure_run_was_admitted(request, run_id=run_id)
        if not closure_admission.admitted:
            #: ERROR-6 fix (#6): closure is consistent with complete/fail admission
            #: -- a closure for a run with NO active ownership record must NOT
            #: commit. Fail-closed: an unadmitted closure never tears down (or
            #: fabricates) a guard regime. The AG3-018 fast-story no-op is
            #: PRESERVED when there WAS a prior admitted run (the fast story's
            #: admitted setup left an active record), so a legitimate fast
            #: closure still no-ops below.
            return self._unadmitted_run_rejection(
                closure_admission,
                op_id=request.op_id,
                operation_kind="closure_complete",
                run_id=run_id,
                phase="closure",
                reason=(
                    "closure_complete rejected: the run has no active "
                    "run-ownership record for THIS project/story/run; "
                    "fail-closed -- closure must not commit for an unadmitted "
                    "run (FK-56 §56.8a)."
                ),
            )

        #: AG3-147 (FK-10 §10.2.4b boundary type 4 + FK-12 §12.4.3, SOLL-190):
        #: the closure-entry push barrier. Closure entry is fail-closed BLOCKED
        #: unless the story branch is server-verified-pushed in EVERY participating
        #: repo -- via the persisted closure-entry barrier SSOT. Checked AFTER
        #: admission, BEFORE the object claim + teardown, so a blocked barrier
        #: tears down NOTHING.
        merge_block = self._closure_push_precondition_block(
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=run_id,
            sync_point_id=run_id,
        )
        if merge_block is not None:
            return _rejection_result(
                op_id=request.op_id,
                operation_kind="closure_complete",
                run_id=run_id,
                phase="closure",
                reason=(
                    f"{runtime_constants.PUSH_BARRIER_BLOCKED_CODE}: "
                    "closure_complete blocked -- the "
                    "story branch is not server-verified-pushed in every "
                    f"participating repo (FK-12 §12.4.3 / SOLL-190, fail-closed). "
                    f"{merge_block.detail}"
                ),
                dispatch_phase="closure",
            )

        #: SOLL-054: closure competes for the SAME per-story object claim as
        #: start/resume/complete/fail (FK-91 §91.1a Rule 13). A busy object
        #: returns the K4 deterministic 409 + Retry-After (IMPL-016); NO
        #: operation is stored for this attempt.
        object_conflict = self._acquire_object_claim(
            project_key=request.project_key,
            story_id=request.story_id,
            op_id=request.op_id,
        )
        if object_conflict is not None:
            return _object_claim_busy_rejection(
                op_id=request.op_id,
                operation_kind="closure_complete",
                run_id=run_id,
                phase="closure",
                conflict=object_conflict,
            )
        now = datetime.now(tz=UTC)
        #: ``closure_admission.admitted`` is True, so ``active_record`` is
        #: present (``evaluate_ownership_admission``).
        assert closure_admission.active_record is not None  # noqa: S101
        expected_ownership_epoch = closure_admission.active_record.ownership_epoch
        committed = False
        try:
            if not self._story_lock_records_apply(request):
                result = _complete_fast_closure(
                    self._repo,
                    run_id=run_id,
                    request=request,
                    now=now,
                    expected_ownership_epoch=expected_ownership_epoch,
                )
            else:
                result = self._complete_standard_closure(
                    run_id=run_id,
                    request=request,
                    now=now,
                    expected_ownership_epoch=expected_ownership_epoch,
                )
            committed = True
            #: Codex-R1 (BLOCKER) fix: NON-best-effort release on the committed
            #: path -- a release failure SURFACES (raises -> 5xx), never swallowed
            #: while the API returns ``committed`` with a durably-held claim (closure
            #: leaves NO ``claimed`` op row, so admin_abort cannot target a swallowed
            #: stuck claim -- only a same-instance restart reconciliation frees it).
            self._release_object_claim(
                project_key=request.project_key,
                story_id=request.story_id,
                op_id=request.op_id,
            )
            return result
        except OwnershipFenceViolationError as exc:
            #: AG3-142 (no TOCTOU): the ownership fence re-check at commit time
            #: failed -- a takeover landed between the early admission check
            #: above and this commit. The transaction rolled back (no side
            #: effect, no stored op, claim still held): release NON-best-effort
            #: before surfacing the rich ex-owner rejection.
            self._release_object_claim(
                project_key=request.project_key,
                story_id=request.story_id,
                op_id=request.op_id,
            )
            return self._ownership_fence_violation_rejection(
                exc,
                op_id=request.op_id,
                operation_kind="closure_complete",
                run_id=run_id,
                phase="closure",
            )
        except ControlPlaneClaimCollisionError:
            #: ERROR-3 fix (#3): the op_id is held by a LIVE ``claimed`` start
            #: claim; the store refused to clobber it. A closure reusing a live
            #: start's op_id is rejected fail-closed (consistent with
            #: complete/fail), never stealing the start's ownership. The commit
            #: transaction rolled back (no op committed, claim still held): release
            #: NON-best-effort (surface failures) before the fail-closed rejection.
            self._release_object_claim(
                project_key=request.project_key,
                story_id=request.story_id,
                op_id=request.op_id,
            )
            reason = _claimed_operation_rejection_reason("closure_complete", request.op_id, "closure")
            return _rejection_result(
                op_id=request.op_id,
                operation_kind="closure_complete",
                run_id=run_id,
                phase="closure",
                reason=reason,
                dispatch_phase="closure",
            )
        except ControlPlaneBindingCollisionError as exc:
            #: AG3-054 run-scoping sweep: the session is bound to a DIFFERENT run
            #: (it was rebound after this old run's setup). The tombstone derivation
            #: and/or the run-scoped binding DELETE refused fail-closed and the WHOLE
            #: teardown rolled back -- the foreign run's binding is intact, NO
            #: INACTIVE locks were written and NO deactivation events were emitted. A
            #: stale closure for an old run must never tear down a foreign run's live
            #: regime. The commit rolled back (claim still held): release
            #: NON-best-effort (surface failures) before the fail-closed rejection.
            self._release_object_claim(
                project_key=request.project_key,
                story_id=request.story_id,
                op_id=request.op_id,
            )
            reason = _closure_binding_collision_reason(exc)
            return _rejection_result(
                op_id=request.op_id,
                operation_kind="closure_complete",
                run_id=run_id,
                phase="closure",
                reason=reason,
                dispatch_phase="closure",
            )
        except BaseException:
            #: A pre-commit error (or a real process crash) BEFORE the op committed:
            #: best-effort release so the ORIGINAL error is never masked; a true
            #: crash leaves the claim held for reconcile/admin_abort only (AC1).
            if not committed:
                self._release_object_claim_best_effort(
                    project_key=request.project_key,
                    story_id=request.story_id,
                    op_id=request.op_id,
                )
            raise

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
        resume_admission = self._run_was_admitted(request, run_id=run_id)
        if not resume_admission.admitted:
            return self._unadmitted_run_rejection(
                resume_admission,
                op_id=request.op_id,
                operation_kind="phase_resume",
                run_id=run_id,
                phase=phase,
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

    def _complete_standard_closure(
        self,
        *,
        run_id: str,
        request: ClosureCompleteRequest,
        now: datetime,
        expected_ownership_epoch: int,
    ) -> ControlPlaneMutationResult:
        """Tear down a standard/exploration run's guard regime at closure.

        Writes the INACTIVE story/QA lock-records, removes the session binding and
        emits the binding-removed + regime-deactivated lifecycle events, then
        commits the idempotent closure operation -- ALL in ONE atomic transaction
        (ERROR-2, #2). The op-row write is the ERROR-3 conditional upsert with the
        collision gate running FIRST, so a closure that reuses a LIVE ``claimed``
        start's op_id raises :class:`ControlPlaneClaimCollisionError` (handled
        fail-closed by :meth:`complete_closure`) and the WHOLE transaction rolls
        back -- the binding is NOT deleted, the locks are NOT deactivated and no
        event is emitted (the prior code committed those side effects BEFORE the
        collision was detected -> orphan teardown).

        AG3-054 run-scoping sweep: the tombstone-root derivation uses the CLOSING
        run's binding, never "whatever binding exists". If the live binding for the
        session belongs to a DIFFERENT run (the session was rebound), this fails
        closed (:class:`ControlPlaneBindingCollisionError`) BEFORE any teardown is
        planned -- a stale closure for an old run must not derive its tombstone from,
        or tear down, a foreign run's live regime. The atomic binding DELETE is also
        run-scoped at the store, so even a TOCTOU rebind between this read and the
        commit is caught and rolls back the whole transaction.
        """
        binding = self._run_matched_binding_for_teardown(request, run_id=run_id)
        worktree_roots = binding.worktree_roots if binding is not None else ()
        binding_version = binding.binding_version if binding is not None else _next_binding_version(None)
        lock = StoryExecutionLockRecord(
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=run_id,
            lock_type="story_execution",
            status="INACTIVE",
            worktree_roots=tuple(worktree_roots),
            binding_version=binding_version,
            activated_at=now,
            updated_at=now,
            deactivated_at=now,
        )
        qa_lock = StoryExecutionLockRecord(
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=run_id,
            lock_type="qa_artifact_write",
            status="INACTIVE",
            worktree_roots=tuple(worktree_roots),
            binding_version=binding_version,
            activated_at=now,
            updated_at=now,
            deactivated_at=now,
        )
        bundle = _build_edge_bundle(
            binding=None,
            lock=lock,
            qa_lock=qa_lock,
            sync_class="mutation",
            now=now,
            tombstone_worktree_roots=tuple(worktree_roots),
        )
        events = (
            _lifecycle_event_record(
                event_type=EventType.SESSION_RUN_BINDING_REMOVED,
                project_key=request.project_key,
                story_id=request.story_id,
                run_id=run_id,
                source_component=request.source_component,
                payload={
                    "session_id": request.session_id,
                    "ownership_epoch": expected_ownership_epoch,
                },
                now=now,
            ),
            _lifecycle_event_record(
                event_type=EventType.STORY_EXECUTION_REGIME_DEACTIVATED,
                project_key=request.project_key,
                story_id=request.story_id,
                run_id=run_id,
                source_component=request.source_component,
                payload={
                    "session_id": request.session_id,
                    "ownership_epoch": expected_ownership_epoch,
                },
                now=now,
            ),
        )
        result = ControlPlaneMutationResult(
            status="committed",
            op_id=request.op_id,
            operation_kind="closure_complete",
            run_id=run_id,
            phase="closure",
            edge_bundle=bundle,
            ownership_epoch=expected_ownership_epoch,
        )
        record = _operation_record(
            op_id=request.op_id,
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=run_id,
            session_id=request.session_id,
            operation_kind="closure_complete",
            phase="closure",
            result=result,
            now=now,
            request_body_hash=_control_plane_request_body_hash(request, operation_kind="closure_complete", phase="closure"),
        )
        #: Atomic: the conditional op-row upsert (collision gate FIRST) + the
        #: INACTIVE locks, the binding deletion and the deactivation events apply in
        #: ONE transaction. A live-claim collision rolls back EVERYTHING (no orphan
        #: teardown), surfaced fail-closed by :meth:`complete_closure`.
        self._repo.commit_operation_with_side_effects(
            record,
            binding_to_save=None,
            binding_to_delete=BindingDeleteScope(
                session_id=request.session_id,
                project_key=request.project_key,
                story_id=request.story_id,
                run_id=run_id,
            ),
            locks=(lock, qa_lock),
            events=events,
            expected_ownership_epoch=expected_ownership_epoch,
        )
        return result

    def _run_matched_binding_for_teardown(
        self,
        request: ClosureCompleteRequest,
        *,
        run_id: str,
    ) -> SessionRunBindingRecord | None:
        """Resolve the CLOSING run's binding for teardown, else fail closed (#2).

        AG3-054 run-scoping sweep: tombstone-root / binding-version derivation at
        closure must read the binding that belongs to THIS run, never "whatever
        binding exists" for the session. Returns:

        * the binding when it EXACTLY matches ``(project_key, story_id, run_id)``;
        * ``None`` when no binding exists for the session (a fast / already-cleaned
          run -- a benign no-op teardown).

        Fail-closed: a binding that exists but belongs to a DIFFERENT run (the
        session was rebound to a NEW run) raises
        :class:`ControlPlaneBindingCollisionError` so a stale closure for the old run
        neither derives its tombstone from, nor tears down, the foreign run's live
        regime.

        Raises:
            ControlPlaneBindingCollisionError: When a live binding exists for the
                session but belongs to a DIFFERENT run.
        """
        binding = self._repo.load_binding(request.session_id)
        if binding is None:
            return None
        if binding.project_key == request.project_key and binding.story_id == request.story_id and binding.run_id == run_id:
            return binding
        raise ControlPlaneBindingCollisionError(
            f"closure for run {run_id!r} refused: session "
            f"{request.session_id!r} is bound to run {binding.run_id!r} "
            f"(project={binding.project_key!r}, story={binding.story_id!r}); a "
            "stale closure must not tear down a foreign run's live binding "
            "(AG3-054 run-scoping, fail-closed).",
        )

    def _mutate_phase(
        self,
        *,
        run_id: str,
        phase: str,
        request: PhaseMutationRequest,
        operation_kind: str,
        expected_ownership_epoch: int,
        phase_dispatch: PhaseDispatchResult | None = None,
    ) -> ControlPlaneMutationResult:
        existing = self._load_existing_operation(request, operation_kind=operation_kind, phase=phase)
        if existing is not None:
            return existing

        #: SOLL-054: complete/fail is a mutating control-plane operation like
        #: any other and competes for the SAME per-story object claim as
        #: start/resume/closure (FK-91 §91.1a Rule 13). A busy object returns
        #: the K4 deterministic 409 + Retry-After (IMPL-016); NO operation is
        #: stored for this attempt.
        object_conflict = self._acquire_object_claim(
            project_key=request.project_key,
            story_id=request.story_id,
            op_id=request.op_id,
        )
        if object_conflict is not None:
            return _object_claim_busy_rejection(
                op_id=request.op_id,
                operation_kind=operation_kind,
                run_id=run_id,
                phase=phase,
                conflict=object_conflict,
            )
        committed = False
        try:
            now = self._now_fn()
            #: ERROR-2 fix (#2): PLAN the side effects (pure record construction, no
            #: writes) so the op-row commit AND the binding/locks/events apply in ONE
            #: atomic transaction with the collision gate FIRST. The prior code wrote
            #: the side effects through separate transactions and THEN stored the op,
            #: so a live-claim collision left orphan side effects behind.
            if self._story_scoped_materialization_enabled(request):
                plan = _plan_story_scoped_materialization(
                    run_id=run_id,
                    phase=phase,
                    request=request,
                    now=now,
                    previous_binding_version=self._current_binding_version(request.session_id),
                    ownership_epoch=expected_ownership_epoch,
                )
            else:
                plan = _plan_fast_materialization(request=request, now=now)
            result = ControlPlaneMutationResult(
                status="committed",
                op_id=request.op_id,
                operation_kind=operation_kind,
                run_id=run_id,
                phase=phase,
                edge_bundle=plan.bundle,
                #: ERROR-2 fix: the dispatch outcome is part of the SINGLE stored
                #: result, so the persisted record == the returned result and a
                #: replay carries ``phase_dispatch`` too.
                phase_dispatch=phase_dispatch,
                #: SOLL-017 accountability: the epoch this complete/fail commits
                #: under (the active record's epoch observed at admission).
                ownership_epoch=expected_ownership_epoch,
            )
            record = _operation_record(
                op_id=request.op_id,
                project_key=request.project_key,
                story_id=request.story_id,
                run_id=run_id,
                session_id=request.session_id,
                operation_kind=operation_kind,
                phase=phase,
                result=result,
                now=now,
                request_body_hash=_control_plane_request_body_hash(request, operation_kind=operation_kind, phase=phase),
            )
            #: Atomic: the conditional op-row upsert (collision gate) + side effects in
            #: ONE transaction. A collision raises ``ControlPlaneClaimCollisionError``
            #: (handled fail-closed by the caller) with NO orphan side effect written.
            #: AG3-142 (no TOCTOU): ``expected_ownership_epoch`` re-verifies, in
            #: THIS SAME transaction, that the active record still carries the
            #: exact epoch observed at the early admission check -- a mismatch
            #: raises ``OwnershipFenceViolationError`` (caught by the caller).
            self._repo.commit_operation_with_side_effects(
                record,
                binding_to_save=plan.binding,
                binding_to_delete=None,
                locks=plan.locks,
                events=plan.events,
                expected_ownership_epoch=expected_ownership_epoch,
            )
            committed = True
            #: Codex-R1 (BLOCKER) fix: the SUCCESS-path release is NON-best-effort.
            #: The op is committed; a release failure now SURFACES (raises -> 5xx)
            #: and is NEVER swallowed while the API returns ``committed`` with a
            #: durably-held claim (the prior fail-OPEN gap: complete/fail leaves NO
            #: ``claimed`` op row, so admin_abort cannot target a swallowed stuck
            #: claim -- only a same-instance restart reconciliation would free it).
            #: A surfaced failure leaves the claim for the AG3-138 startup
            #: reconciliation to free -- no wall-clock expiry.
            self._release_object_claim(
                project_key=request.project_key,
                story_id=request.story_id,
                op_id=request.op_id,
            )
            return result
        except (
            ControlPlaneClaimCollisionError,
            ControlPlaneBindingCollisionError,
            OwnershipFenceViolationError,
        ):
            #: The whole commit transaction rolled back (collision/fence gate
            #: FIRST): NO op committed and the object claim is still held.
            #: Release it NON-best-effort (a release failure SURFACES, never
            #: returns a normal rejection while the claim stays held) before the
            #: caller maps the collision/fence violation to its fail-closed
            #: rejection (AG3-142: no TOCTOU).
            self._release_object_claim(
                project_key=request.project_key,
                story_id=request.story_id,
                op_id=request.op_id,
            )
            raise
        except BaseException:
            #: A pre-commit error (or a real process crash) BEFORE the op committed:
            #: best-effort release so the ORIGINAL error is never masked. A true
            #: crash leaves the claim held for reconcile/admin_abort only (AC1) --
            #: never a wall-clock release.
            if not committed:
                self._release_object_claim_best_effort(
                    project_key=request.project_key,
                    story_id=request.story_id,
                    op_id=request.op_id,
                )
            raise

    def _story_scoped_materialization_enabled(
        self,
        request: PhaseMutationRequest,
    ) -> bool:
        """Whether story-scoped session/locks must be materialized for this run.

        AG3-018 (FK-24 §24.3.4): a ``fast`` story does NOT activate the
        story-scoped guards and creates NO story lock-records. The mode is
        resolved AUTHORITATIVELY server-side from the state-backend
        ``StoryContext`` keyed by ``(project_key, story_id)`` -- never from an
        agent-supplied request field (which would be forgeable; AG3-018 FIX-1).

        Fail-closed: if the authoritative ``StoryContext`` cannot be resolved,
        story-scoped materialization stays ENABLED (treated as standard), so a
        code story can never silently skip its guards on a lookup gap.

        Args:
            request: The phase mutation request (carries ``project_key`` /
                ``story_id`` -- the authoritative lookup keys).

        Returns:
            ``False`` only for an authoritatively-resolved fast story; ``True``
            otherwise (standard/exploration, and the fail-closed lookup gap).
        """
        return self._story_lock_records_apply(request)

    def _story_lock_records_apply(
        self,
        request: _ModeResolutionKeys,
    ) -> bool:
        """Authoritative server-side decision: are story lock-records in play?

        The single sanctioned-surface mode resolution shared by ``_mutate_phase``
        (setup/phase mutations) and ``complete_closure`` (teardown). The operating
        mode is read from the state-backend ``StoryContext`` keyed by
        ``(project_key, story_id)`` -- NEVER from an agent-supplied request field
        (which would be forgeable; AG3-018 FIX-1).

        Fail-closed: if the authoritative ``StoryContext`` cannot be resolved, the
        run is treated as standard (story lock-records DO apply), so a code story
        can never silently skip its guards/teardown on a lookup gap.

        Args:
            request: Any request carrying the authoritative ``project_key`` /
                ``story_id`` lookup keys (phase mutation or closure completion).

        Returns:
            ``False`` only for an authoritatively-resolved fast story; ``True``
            otherwise (standard/exploration, and the fail-closed lookup gap).
        """
        ctx = self._repo.load_story_context(request.project_key, request.story_id)
        if ctx is None:
            return True
        return should_create_story_lock_records(ctx)

    def _load_existing_operation(
        self,
        request: PhaseMutationRequest | ClosureCompleteRequest,
        *,
        operation_kind: str,
        phase: str | None,
        mutating_retry: bool = True,
    ) -> ControlPlaneMutationResult | None:
        existing = self._repo.load_operation(request.op_id)
        if existing is None:
            return None
        if existing.status == "claimed":
            #: ERROR-4: a ``claimed`` placeholder is an in-flight reservation, not a
            #: committed/replayable result (its ``response_payload`` is empty). It
            #: is NOT a replay target.
            return None
        #: AG3-140: a terminal row replays ONLY when the incoming body-hash matches
        #: the stored one; a reused op_id with a DIFFERENT body raises
        #: ``IdempotencyMismatchError`` (409). The operation_kind + phase fed here
        #: are IDENTICAL to this entrypoint's terminal-write, so an honest replay
        #: never false-mismatches (a legacy null stored hash falls back to op_id-only
        #: replay, fail-open only on the pre-AG3-140 gap).
        return _replay_or_mismatch(
            request,
            existing,
            operation_kind=operation_kind,
            phase=phase,
            mutating_retry=mutating_retry,
        )
