"""Start-phase admission and finalization flow."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from agentkit.backend.control_plane.execution_contract_assembly import (
    ExecutionContractDigestOutcome,
    build_execution_contract_digest,
)
from agentkit.backend.control_plane.models import (
    ClosureCompleteRequest,
    ControlPlaneMutationResult,
    PhaseDispatchResult,
    PhaseMutationRequest,
)
from agentkit.backend.control_plane.ownership import (
    INITIAL_OWNERSHIP_EPOCH,
    OwnershipAcquisition,
    OwnershipStatus,
)
from agentkit.backend.control_plane.ownership_fence import (
    OwnershipRejectionReason,
)
from agentkit.backend.control_plane.records import (
    RunOwnershipRecord,
)
from agentkit.backend.exceptions import (
    ControlPlaneBindingCollisionError,
    OwnershipFenceViolationError,
)
from agentkit.backend.pipeline_engine.phase_executor import PhaseName

from ._materialization import _plan_fast_materialization, _plan_story_scoped_materialization
from ._models import (
    _start_binding_collision_reason,
    _StartPhaseMaterialization,
    _StartPhaseOutcome,
)
from ._operation_records import (
    _control_plane_request_body_hash,
    _object_claim_busy_rejection,
    _operation_record,
    _rejection_result,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from agentkit.backend.control_plane import object_claims
    from agentkit.backend.control_plane.dispatch import PhaseDispatcher
    from agentkit.backend.control_plane.ownership_fence import OwnershipAdmission
    from agentkit.backend.control_plane.repository import ControlPlaneRuntimeRepository

    from ._models import _ClaimOutcome


logger = logging.getLogger(__name__)


class _StartPhaseAdmissionMixin:
    """Claim, dispatch, and finalize freshly-started phase operations."""

    if TYPE_CHECKING:
        _repo: ControlPlaneRuntimeRepository
        _now_fn: Callable[[], datetime]
        _phase_dispatcher: PhaseDispatcher | None
        _execution_contract_digest_reader: Callable[[PhaseMutationRequest, str], ExecutionContractDigestOutcome] | None

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

        def _evaluate_run_admission(
            self,
            *,
            project_key: str,
            story_id: str,
            session_id: str,
            run_id: str,
            command_id: str,
        ) -> OwnershipAdmission: ...

        def _ownership_admission_rejection(
            self,
            admission: OwnershipAdmission,
            *,
            op_id: str,
            operation_kind: str,
            run_id: str | None,
            phase: str | None,
            session_id: str,
        ) -> ControlPlaneMutationResult: ...

        def _ownership_fence_violation_rejection(
            self,
            exc: OwnershipFenceViolationError,
            *,
            op_id: str,
            operation_kind: str,
            run_id: str | None,
            phase: str | None,
        ) -> ControlPlaneMutationResult: ...

        def _fail_closed_setup_rejection(
            self, *, run_id: str, phase: str, op_id: str, reason: str
        ) -> ControlPlaneMutationResult: ...

        def _dispatch_phase(
            self,
            *,
            run_id: str,
            phase: str,
            request: PhaseMutationRequest,
            run_admitted: bool,
        ) -> PhaseDispatchResult | None: ...

        def _in_flight_rejection(
            self, request: PhaseMutationRequest, *, operation_kind: str = "phase_start"
        ) -> ControlPlaneMutationResult: ...

        def _story_scoped_materialization_enabled(self, request: PhaseMutationRequest) -> bool: ...

    def start_phase(
        self,
        *,
        run_id: str,
        phase: str,
        request: PhaseMutationRequest,
    ) -> ControlPlaneMutationResult:
        """Dispatch exactly ONE phase and persist the idempotent mutation (AG3-054).

        The existing idempotent operation / lifecycle / edge-bundle persistence
        (``_mutate_phase``) is preserved unchanged -- it is the ONE state-write
        truth. The single-phase dispatch AUGMENTS it: on a fresh (non-replayed)
        operation the requested phase is run through the deterministic engine
        (FK-45 §45.1.2), and the normalized phase result is carried back on the
        SAME ``ControlPlaneMutationResult`` (no second response path). A replayed
        operation returns its stored result without re-dispatching (idempotency).

        Args:
            run_id: The story run identifier.
            phase: The requested phase name.
            request: The phase mutation request.

        Returns:
            The committed (or replayed) :class:`ControlPlaneMutationResult`,
            carrying the normalized ``phase_dispatch`` outcome on a fresh commit.
        """
        self._require_postgres_backend_on_first_use()
        existing = self._load_existing_operation(request, operation_kind="phase_start", phase=phase)
        if existing is not None:
            return existing
        locked = self._repair_locked_rejection(
            project_key=request.project_key,
            story_id=request.story_id,
            operation_kind="phase_start",
            op_id=request.op_id,
            run_id=run_id,
            phase=phase,
        )
        if locked is not None:
            return locked

        #: AG3-054 owner-scoped claim. Mint a per-call owner token and atomically
        #: CLAIM the op_id BEFORE the dispatch side effects. Exactly ONE concurrent
        #: caller wins; a loser is handed back a fail-closed result: a REPLAY of a
        #: terminal row, or an "operation in flight, retry" rejection for a foreign
        #: claim of ANY age (it NEVER steals, NEVER dispatches). AG3-139: there is
        #: no wall-clock expiry and no CAS takeover -- an orphaned claim is ended
        #: ONLY via the AG3-138 startup reconciliation or an explicit
        #: ``admin_abort_inflight_operation`` (#1).
        owner_token = self._mint_owner_token()
        claim = self._acquire_claim(request, run_id=run_id, phase=phase, owner_token=owner_token)
        if not claim.won:
            #: ``claim.result`` is the loser's fail-closed result (replay or
            #: in-flight rejection); it is always present when ``won`` is False.
            return claim.result_or_raise()
        #: WARNING-4 fix (#4): MY exact claim instant (raw ISO TEXT). Threaded to
        #: finalize/release so their ownership CAS matches BOTH owner token AND
        #: claim instant -- a stale generation (a reused token in DI/test wiring)
        #: cannot match the newer claim generation. A won claim always carries it.
        owner_claimed_at = claim.claimed_at_raw
        #: AG3-138: MY observed fencing epoch, threaded to finalize so its CAS
        #: additionally requires it unchanged
        #: (``operation_finalize_requires_cas_on_operation_epoch``).
        owner_operation_epoch = claim.operation_epoch

        #: ERROR-1 fix (#1): the ENTIRE post-claim path is wrapped so MY claim (and
        #: only mine) is never stranded. A rejection path releases MY claim and
        #: returns; ANY exception before the terminal op is durably finalized
        #: releases MY claim and re-raises. The claim is converted to a terminal
        #: row ONLY by the ownership-scoped CAS finalize.
        finalized = False
        try:
            #: SOLL-054 (FK-91 §91.1a Rule 13; FK-10 §10.5.4): acquire the
            #: durable object-mutation claim BEFORE the dispatch side effects
            #: (engine writes run in a SEPARATE transaction from the
            #: control-plane finalize below). A busy object releases MY op_id
            #: claim (never dispatched) and returns the K4 deterministic
            #: 409 + Retry-After (IMPL-016) -- NO operation is stored.
            object_conflict = self._acquire_object_claim(
                project_key=request.project_key,
                story_id=request.story_id,
                op_id=request.op_id,
            )
            if object_conflict is not None:
                self._release_my_claim(request.op_id, owner_token, owner_claimed_at)
                return _object_claim_busy_rejection(
                    op_id=request.op_id,
                    operation_kind="phase_start",
                    run_id=run_id,
                    phase=phase,
                    conflict=object_conflict,
                )
            outcome = self._start_phase_after_claim(run_id=run_id, phase=phase, request=request)
            if outcome.rejection is not None:
                # Fail-closed rejection: release MY claims so NO committed op
                # survives and a later retry (once admitted) re-evaluates.
                self._release_my_claim(request.op_id, owner_token, owner_claimed_at)
                self._release_object_claim(
                    project_key=request.project_key,
                    story_id=request.story_id,
                    op_id=request.op_id,
                )
                return outcome.rejection
            result = self._finalize_start_phase(
                run_id=run_id,
                phase=phase,
                request=request,
                owner_token=owner_token,
                owner_claimed_at=owner_claimed_at,
                owner_operation_epoch=owner_operation_epoch,
                phase_dispatch=outcome.dispatch_result,
                mints_ownership_record=outcome.mints_ownership_record,
                observed_ownership_epoch=outcome.observed_ownership_epoch,
                execution_contract_digest=outcome.execution_contract_digest,
            )
            #: Finalize DONE (won or lost the ownership CAS): the op is terminal, so
            #: mark ``finalized`` BEFORE releasing the object claim -- a release
            #: failure below then surfaces cleanly WITHOUT the ``except`` path also
            #: trying to release MY (now terminal) op_id claim.
            finalized = True
            #: Codex-R1 (BLOCKER): NON-best-effort release on the success path -- a
            #: release failure SURFACES (raises -> 5xx), never swallowed while the
            #: API returns ``committed`` with a durably-held claim. (A CAS loss to a
            #: concurrent admin-abort already released it; this is then an idempotent
            #: no-op.)
            self._release_object_claim(
                project_key=request.project_key,
                story_id=request.story_id,
                op_id=request.op_id,
            )
            return result
        except OwnershipFenceViolationError as exc:
            #: AG3-142 (no TOCTOU): the ownership fence re-check at commit time
            #: failed -- a takeover landed between the early admission check
            #: (``_start_phase_after_claim``) and this commit. The whole finalize
            #: rolled back (no side effect, no stored op). Release MY claims and
            #: surface the rich ex-owner rejection.
            self._release_my_claim_best_effort(request.op_id, owner_token, owner_claimed_at)
            self._release_object_claim(
                project_key=request.project_key,
                story_id=request.story_id,
                op_id=request.op_id,
            )
            return self._ownership_fence_violation_rejection(
                exc,
                op_id=request.op_id,
                operation_kind="phase_start",
                run_id=run_id,
                phase=phase,
            )
        except ControlPlaneBindingCollisionError as exc:
            #: AG3-054 run-scoping sweep: this fresh start would materialize a
            #: binding for THIS run, but the session is already bound to a DIFFERENT
            #: run (it was rebound). The run-scoped store insert refused fail-closed
            #: and the WHOLE finalize rolled back -- the foreign run's binding is
            #: intact and NO terminal op survives. Release MY claims and surface a
            #: fail-closed rejection (a later retry, once the foreign run releases the
            #: session, re-evaluates). The claim is not yet a terminal row, so the
            #: release is ownership-scoped and safe.
            self._release_my_claim_best_effort(request.op_id, owner_token, owner_claimed_at)
            #: Codex-R1 (BLOCKER): the object-claim release on this handled-return
            #: rejection is NON-best-effort -- a release failure SURFACES (raises ->
            #: 5xx), never swallowed while a normal rejection is returned with the
            #: object still held.
            self._release_object_claim(
                project_key=request.project_key,
                story_id=request.story_id,
                op_id=request.op_id,
            )
            reason = _start_binding_collision_reason(phase, exc)
            return _rejection_result(
                op_id=request.op_id,
                operation_kind="phase_start",
                run_id=run_id,
                phase=phase,
                reason=reason,
                dispatch_phase=phase,
            )
        except BaseException:
            #: An exception after the claim and before the terminal finalize MUST
            #: release MY claims (#1; SOLL-054) -- ownership-scoped, so a foreign
            #: claim's row is never touched. The release failure must not mask the
            #: original error, so it is best-effort. Re-raise so NO ERROR BYPASSING
            #: holds. A crash here (not merely a Python exception) leaves BOTH
            #: claims durably held -- ended ONLY via the AG3-138 startup
            #: reconciliation or an explicit admin_abort_inflight_operation
            #: (AC1, Scope item 7).
            if not finalized:
                self._release_my_claim_best_effort(request.op_id, owner_token, owner_claimed_at)
                self._release_object_claim_best_effort(
                    project_key=request.project_key,
                    story_id=request.story_id,
                    op_id=request.op_id,
                )
            raise

    def _start_phase_after_claim(
        self,
        *,
        run_id: str,
        phase: str,
        request: PhaseMutationRequest,
    ) -> _StartPhaseOutcome:
        """Dispatch the claimed phase; return the outcome (rejection or commit-ok).

        Runs the deterministic single-phase dispatch and applies the fail-closed
        run-admission short-circuits. Returns a :class:`_StartPhaseOutcome`
        carrying either a fail-closed ``rejected`` result (the caller releases the
        claim and returns it) or the admitted ``dispatch_result`` for the caller
        to commit in ONE place (ERROR-2). No instance state is mutated.

        ERROR-1 fix (#1): the run-scoped first-call (run-admission) enforcement is
        computed HERE, in the runtime, INDEPENDENT of ``_dispatch_phase``'s
        ctx-resolvability short-circuit. ``_dispatch_phase`` returns ``None`` when
        the run ``StoryContext`` is ABSENT (AG3-123: decoupled from
        ``project_root`` resolvability -- the Backend resolves the workspace anchor
        inside the dispatcher) BEFORE the dispatcher's own run-scoped first-call
        gate runs. Without this gate, a fresh, UN-ADMITTED, NON-setup start with an
        absent ctx would fall through to the admitted path and materialize
        binding/locks/events out of thin air. The invariant holds on ALL paths: an
        un-admitted run can NEVER materialize state via a non-setup start,
        regardless of ctx resolvability.
        """
        #: ERROR-1 fix (#1): run-admission evidence for THIS exact run, computed
        #: BEFORE/independent of the ctx-resolvability short-circuit. A fresh setup
        #: start is run-admitted only when there is run-matched evidence; a
        #: non-setup start requires the run to already have been admitted.
        admission = self._evaluate_run_admission(
            project_key=request.project_key,
            story_id=request.story_id,
            session_id=request.session_id,
            run_id=run_id,
            command_id="phase_start",
        )
        #: AG3-142 (SOLL-015, FK-56 §56.8a): a run whose active ownership record
        #: belongs to a DIFFERENT run or a DIFFERENT session is fenced OUT of
        #: ``start_phase`` entirely -- it never reaches the pre-start guard or the
        #: engine (unlike the ``NO_ACTIVE_RECORD``/``STORY_EXITED`` "not yet /
        #: no longer admitted" cases below, whose existing dispatch-then-check
        #: handling is unchanged). An ex-owner gets the rich
        #: ``ownership_transferred`` rejection (FK-91 §91.1a Rule 18).
        if admission.rejection_reason in (
            OwnershipRejectionReason.RUN_MISMATCH,
            OwnershipRejectionReason.OWNERSHIP_TRANSFERRED,
            OwnershipRejectionReason.FREEZE_ACTIVE,
        ):
            return _StartPhaseOutcome(
                rejection=self._ownership_admission_rejection(
                    admission,
                    op_id=request.op_id,
                    operation_kind="phase_start",
                    run_id=run_id,
                    phase=phase,
                    session_id=request.session_id,
                ),
                dispatch_result=None,
            )
        run_admitted = admission.admitted
        #: AG3-142 (SOLL-015): a genuinely fresh setup start (no active record
        #: existed for this run) MINTS the new active record atomically at
        #: finalize; every other commit (a non-setup phase start, or a
        #: re-entry into an already-owned setup) fences against the EXISTING
        #: record. Computed HERE (before dispatch) so the AG3-143 digest build
        #: below runs -- and can reject -- BEFORE the engine ever dispatches.
        mints_ownership_record = (
            phase == PhaseName.SETUP.value and admission.rejection_reason is OwnershipRejectionReason.NO_ACTIVE_RECORD
        )
        execution_contract_digest: str | None = None
        if mints_ownership_record:
            #: AG3-143 (FK-44 §44.3a, SOLL-095, AC2): form the run's
            #: execution_contract_digest BEFORE the engine dispatch. A
            #: component that cannot be resolved (missing project
            #: registration/config, missing story specification, an
            #: unresolvable run-prompt-pin) fails the fresh setup start
            #: CLEANLY here -- no engine writes are produced, so a retry (once
            #: the missing component is fixed) re-evaluates cleanly instead of
            #: landing in the AG3-138 partial-write "repair" state.
            digest_outcome = self._resolve_execution_contract_digest_reader()(
                request,
                run_id,
            )
            if digest_outcome.rejection_reason is not None:
                return _StartPhaseOutcome(
                    rejection=self._fail_closed_setup_rejection(
                        run_id=run_id,
                        phase=phase,
                        op_id=request.op_id,
                        reason=digest_outcome.rejection_reason,
                    ),
                    dispatch_result=None,
                )
            execution_contract_digest = digest_outcome.digest
        dispatch_result = self._dispatch_phase(run_id=run_id, phase=phase, request=request, run_admitted=run_admitted)
        if dispatch_result is None and phase == PhaseName.SETUP.value and not run_admitted:
            #: Fail-closed run admission (FK-20 §20.8.2): a FRESH SETUP START whose
            #: ``StoryContext`` is ABSENT (AG3-123: no longer "no project_root")
            #: could not have its Approved+READY run-admission evaluated. Active
            #: write-guards do NOT satisfy the run-admission invariant -- a run
            #: never Approved/READY must not start. We REJECT fail-closed so NO
            #: session binding, NO lock-records, NO ``phase_start`` edge bundle and
            #: NO lifecycle events are materialized, and NO operation is stored (a
            #: later retry with a resolvable, Approved+READY context re-evaluates).
            return _StartPhaseOutcome(
                rejection=self._fail_closed_setup_rejection(
                    run_id=run_id,
                    phase=phase,
                    op_id=request.op_id,
                    reason=(
                        "Fresh setup start rejected: the run's StoryContext is "
                        "absent, so Approved + READY run-admission cannot be "
                        "evaluated; fail-closed (FK-20 §20.8.2)."
                    ),
                ),
                dispatch_result=None,
            )
        if dispatch_result is None and phase != PhaseName.SETUP.value and not run_admitted:
            #: ERROR-1 fix (#1): a FRESH, UN-ADMITTED, NON-setup start whose run
            #: ``StoryContext`` is ABSENT (AG3-123). ``_dispatch_phase`` returned
            #: ``None`` BEFORE the dispatcher's run-scoped first-call gate could run,
            #: so the run-admission invariant must be enforced HERE. A non-setup
            #: phase may only start once the run was admitted by a prior committed
            #: setup start (or a run-matched binding). With no such evidence the run
            #: was never admitted -> REJECT fail-closed: NO binding / lock / event /
            #: edge bundle is materialized and NO operation is stored (a later retry,
            #: once the run is properly admitted, re-evaluates and can succeed).
            return _StartPhaseOutcome(
                rejection=_rejection_result(
                    op_id=request.op_id,
                    operation_kind="phase_start",
                    run_id=run_id,
                    phase=phase,
                    reason=(
                        f"phase_start({phase}) rejected: the run is NOT admitted "
                        "(no committed setup phase_start and no session binding for "
                        "THIS project/story/run) and its StoryContext is absent, so "
                        "run-admission cannot be evaluated. A non-setup start must "
                        "never materialize story-scoped state for an unadmitted run; "
                        "fail-closed (FK-20 §20.8.2)."
                    ),
                    dispatch_phase=phase,
                ),
                dispatch_result=None,
            )
        if dispatch_result is not None and not dispatch_result.dispatched:
            #: Fail-closed run admission (FK-20 §20.8.2): a REJECTED dispatch
            #: (pre-start-guard denial, invalid first-call, illegal transition)
            #: must NOT materialize the run's story-scoped guard regime. No
            #: session binding, no lock-records and no ``phase_start`` edge bundle
            #: are written, and NO committed operation is persisted -- a later
            #: retry (once Approved+READY) re-evaluates and can succeed.
            return _StartPhaseOutcome(
                rejection=ControlPlaneMutationResult(
                    status="rejected",
                    op_id=request.op_id,
                    operation_kind="phase_start",
                    run_id=run_id,
                    phase=phase,
                    edge_bundle=None,
                    # The dispatcher already produced the normalized rejection.
                    phase_dispatch=dispatch_result,
                ),
                dispatch_result=None,
            )
        #: ERROR-2 fix (AC7 "same result, no second path"): admitted -- the caller
        #: builds and stores the FINAL result (incl. ``phase_dispatch``) in ONE
        #: place, so a replay of the same op_id returns an identical record.
        return _StartPhaseOutcome(
            rejection=None,
            dispatch_result=dispatch_result,
            mints_ownership_record=mints_ownership_record,
            observed_ownership_epoch=(admission.active_record.ownership_epoch if admission.active_record is not None else None),
            execution_contract_digest=execution_contract_digest,
        )

    def _resolve_execution_contract_digest_reader(
        self,
    ) -> Callable[[PhaseMutationRequest, str], ExecutionContractDigestOutcome]:
        """Return the injected/DI-defaulted reader, lazily binding the productive one.

        Mirrors :meth:`_resolve_dispatcher`: ``None`` (the productive
        default-store path -- see ``__init__``) is resolved and memoized on
        first use to :meth:`_build_execution_contract_digest`, never
        self-built eagerly (non-setup flows pay no wiring cost).
        """
        if self._execution_contract_digest_reader is None:
            self._execution_contract_digest_reader = lambda request, run_id: self._build_execution_contract_digest(
                request=request,
                run_id=run_id,
            )
        return self._execution_contract_digest_reader

    def _build_execution_contract_digest(
        self,
        *,
        request: PhaseMutationRequest,
        run_id: str,
    ) -> ExecutionContractDigestOutcome:
        """Resolve + form the execution_contract_digest for a fresh setup (AG3-143).

        Thin delegation (Sonar build #988, ``PY_CLASS_MAX_LOC_800`` cleanup):
        the actual gathering + fail-closed validation of the digest's raw
        inputs (story spec, project registration/config, skill bindings,
        run-prompt-pin, FK-44 §44.3a) lives in
        :func:`~agentkit.backend.control_plane.execution_contract_assembly.build_execution_contract_digest`
        -- this admission class keeps only its setup/finalize control flow.
        Behavior is unchanged: same repository port, same fail-closed
        rejection-before-dispatch semantics (AC2).
        """
        return build_execution_contract_digest(
            repo=self._repo,
            request=request,
            run_id=run_id,
        )

    def _finalize_start_phase(
        self,
        *,
        run_id: str,
        phase: str,
        request: PhaseMutationRequest,
        owner_token: str,
        owner_claimed_at: str | None,
        owner_operation_epoch: int | None = None,
        phase_dispatch: PhaseDispatchResult | None,
        mints_ownership_record: bool = False,
        observed_ownership_epoch: int | None = None,
        execution_contract_digest: str | None = None,
    ) -> ControlPlaneMutationResult:
        """Atomically CAS-finalize the claim AND materialize side effects (#1).

        ERROR-1 fix (#1): the side effects (binding/locks/events) are PLANNED here
        (no writes) and applied by the store in ONE transaction with the ownership
        CAS finalize (status->terminal WHERE op_id=? AND claimed_by=mytoken), gated
        on STILL owning the claim:

        * CAS affects 1 row -> I still own the claim: the terminal row AND the
          binding/locks/events are written atomically; the committed result stands.
        * CAS affects 0 rows -> my claim was concurrently finalized or
          admin-aborted (AG3-138) by a concurrent owner/operator: NOTHING is
          materialized (the store rolls back), so I (the loser) write NO
          duplicate/conflicting binding / lock / event. I then surface the
          winner's terminal row as a REPLAY (never overwriting it), or -- in the
          narrow window before it is readable -- the in-flight retry rejection.

        The loser therefore never writes canonical side effects (the EXACT defect
        this fix closes).

        AG3-142 (SOLL-015): ``mints_ownership_record`` -- a genuinely fresh setup
        start -- atomically INSERTS the new active ``RunOwnershipRecord``
        (``ownership_epoch=1``, ``acquired_via=setup``) in this SAME transaction;
        every other commit (non-setup phase start, or a setup re-entry) instead
        re-verifies the EXISTING active record at commit time (no TOCTOU) and
        raises :class:`OwnershipFenceViolationError` on a mismatch.
        ``observed_ownership_epoch`` is the epoch of that existing record as
        observed at the early admission check (:class:`_StartPhaseOutcome`);
        threaded verbatim so the commit-time re-check fences on THIS EXACT
        epoch (mirrors ``owner_operation_epoch``), not merely "some" epoch.

        AG3-143 (FK-44 §44.3a, SOLL-095): ``execution_contract_digest`` -- the
        digest :meth:`_build_execution_contract_digest` formed for a
        genuinely fresh setup start -- is persisted (run-scoped, read-only
        after insert) in this SAME transaction as ``ownership_record_to_insert``,
        mirroring its atomicity exactly: a claim-CAS loser writes neither.
        """
        now = self._now_fn()
        #: SOLL-017 accountability: the epoch this commit applies under. A fresh
        #: setup mints epoch 1; every other commit stamps the EXISTING record's
        #: observed epoch. Fail-closed (defensive): a non-minting commit MUST
        #: have observed an active record's epoch at the early admission check
        #: (the only way to reach here without one would be an un-admitted run,
        #: which the dispatcher's own pre-start guard/transition graph already
        #: rejects before a committing dispatch result exists) -- never silently
        #: skip the fence.
        if mints_ownership_record:
            ownership_epoch_for_commit = INITIAL_OWNERSHIP_EPOCH
        elif observed_ownership_epoch is not None:
            ownership_epoch_for_commit = observed_ownership_epoch
        else:
            raise OwnershipFenceViolationError(
                f"internal invariant violated: start_phase finalize for run "
                f"{run_id!r} (project={request.project_key!r}, "
                f"story={request.story_id!r}) is not minting a new ownership "
                "record but observed no active-record epoch at admission time; "
                "fail-closed (AG3-142, no silent fence skip).",
                detail={},
            )
        plan = self._plan_start_phase_materialization(
            run_id=run_id,
            phase=phase,
            request=request,
            now=now,
            ownership_epoch=ownership_epoch_for_commit,
        )
        result = ControlPlaneMutationResult(
            status="committed",
            op_id=request.op_id,
            operation_kind="phase_start",
            run_id=run_id,
            phase=phase,
            edge_bundle=plan.bundle,
            #: ERROR-2 fix: the dispatch outcome is part of the SINGLE stored
            #: result, so the persisted record == the returned result and a
            #: replay carries ``phase_dispatch`` too.
            phase_dispatch=phase_dispatch,
            ownership_epoch=ownership_epoch_for_commit,
        )
        record = _operation_record(
            op_id=request.op_id,
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=run_id,
            session_id=request.session_id,
            operation_kind="phase_start",
            phase=phase,
            result=result,
            now=now,
            request_body_hash=_control_plane_request_body_hash(request, operation_kind="phase_start", phase=phase),
        )
        ownership_record_to_insert = (
            RunOwnershipRecord(
                project_key=request.project_key,
                story_id=request.story_id,
                run_id=run_id,
                owner_session_id=request.session_id,
                ownership_epoch=INITIAL_OWNERSHIP_EPOCH,
                status=OwnershipStatus.ACTIVE,
                acquired_via=OwnershipAcquisition.SETUP,
                acquired_at=now,
                audit_ref=request.op_id,
            )
            if mints_ownership_record
            else None
        )
        execution_contract_digest_to_insert = None
        if mints_ownership_record:
            #: Fail-closed (defensive, mirrors the epoch invariant above): a
            #: minting commit MUST have a digest -- the only way to reach here
            #: without one would be ``_start_phase_after_claim`` skipping its
            #: OWN digest-build gate, which never returns an admitted outcome
            #: without either a digest or a rejection (AG3-143, no silent
            #: fence skip).
            if execution_contract_digest is None:
                raise OwnershipFenceViolationError(
                    f"internal invariant violated: start_phase finalize for run "
                    f"{run_id!r} (project={request.project_key!r}, "
                    f"story={request.story_id!r}) mints a new ownership record "
                    "but carries no execution_contract_digest; fail-closed "
                    "(AG3-143, no silent digest skip).",
                    detail={},
                )
            from agentkit.backend.prompt_runtime.execution_contract import (
                DIGEST_FORMAT_VERSION,
                ExecutionContractDigestRecord,
            )

            execution_contract_digest_to_insert = ExecutionContractDigestRecord(
                project_key=request.project_key,
                story_id=request.story_id,
                run_id=run_id,
                execution_contract_digest=execution_contract_digest,
                digest_format_version=DIGEST_FORMAT_VERSION,
                formed_at=now,
            )
        if self._repo.finalize_start_phase(
            record,
            owner_token=owner_token,
            #: WARNING-4: the CAS scopes to BOTH owner token AND claim instant.
            owner_claimed_at=owner_claimed_at,
            #: AG3-138: additionally fences on the unchanged operation_epoch.
            owner_operation_epoch=owner_operation_epoch,
            binding=plan.binding,
            locks=plan.locks,
            events=plan.events,
            ownership_record_to_insert=ownership_record_to_insert,
            execution_contract_digest_to_insert=execution_contract_digest_to_insert,
            expected_ownership_epoch=(None if mints_ownership_record else ownership_epoch_for_commit),
        ):
            return result
        #: Lost the ownership CAS: a concurrent finalize/admin-abort already
        #: applied AND the side effects were rolled back (NO loser double-write).
        #: Replay the winner's terminal row; NEVER overwrite it (or, in the narrow
        #: window where it is not yet readable, surface the in-flight retry
        #: rejection). This is the LATE-OWNER path: I originally held the claim, so
        #: I see my own now-aborted/committed row VERBATIM (legitimate late-owner
        #: visibility, ``mutating_retry=False``) -- NOT the fresh-retry conflict
        #: classification that a DIFFERENT caller reusing this op_id would get.
        existing = self._load_existing_operation(
            request,
            operation_kind="phase_start",
            phase=phase,
            mutating_retry=False,
        )
        if existing is not None:
            return existing
        return self._in_flight_rejection(request)

    def _plan_start_phase_materialization(
        self,
        *,
        run_id: str,
        phase: str,
        request: PhaseMutationRequest,
        now: datetime,
        ownership_epoch: int,
    ) -> _StartPhaseMaterialization:
        """Build (NO writes) the start_phase side effects + bundle (ERROR-1, #1).

        Standard/exploration runs plan the full binding/locks/events; an
        authoritatively-resolved fast story plans the bundle only (no side effects).
        The plan is applied atomically under the ownership CAS by the caller.
        """
        if self._story_scoped_materialization_enabled(request):
            return _plan_story_scoped_materialization(
                run_id=run_id,
                phase=phase,
                request=request,
                now=now,
                previous_binding_version=self._current_binding_version(request.session_id),
                ownership_epoch=ownership_epoch,
            )
        return _plan_fast_materialization(request=request, now=now)

    def _current_binding_version(self, session_id: str) -> str | None:
        """Read the session's currently persisted ``binding_version`` (DB-monotone).

        Returns the affected binding's version so the mint can derive the next
        monotone value (``+ 1``) from persisted DB state rather than a wall clock
        (FK-56 §56.13a). ``None`` when the session has no binding yet (first
        bind -> :data:`MIN_BINDING_VERSION`). The read is a plain load at the
        persistence boundary of the enclosing mutation; the atomic commit that
        applies the plan (ownership CAS / run-scoped upsert) serialises the
        write, so no new fence is introduced (AG3-137 value-domain change only).
        """
        binding = self._repo.load_binding(session_id)
        return binding.binding_version if binding is not None else None


__all__ = ["_StartPhaseAdmissionMixin"]
