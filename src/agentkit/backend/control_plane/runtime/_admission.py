"""Start-phase admission, dispatch, and atomic finalization."""

from __future__ import annotations

import logging
import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.backend.control_plane import (
    runtime_constants,
)
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
    OwnershipAdmission,
    OwnershipRejectionReason,
)
from agentkit.backend.control_plane.push_sync import (
    SyncPointBarrierType,
)
from agentkit.backend.control_plane.records import (
    RunOwnershipRecord,
)
from agentkit.backend.control_plane.repository import (
    ControlPlaneRuntimeRepository,
    EdgeCommandRepository,
    ObjectMutationClaimRepository,
)
from agentkit.backend.exceptions import (
    ControlPlaneBindingCollisionError,
    ControlPlaneClaimCollisionError,
    OwnershipFenceViolationError,
)
from agentkit.backend.pipeline_engine.phase_executor import PhaseName

from ._claims import _ClaimMixin
from ._di import (
    _default_di_execution_contract_digest_reader,
    _default_di_instance_identity,
    _default_di_object_claim_repository,
    _require_postgres_control_plane_backend,
    _resolve_edge_command_repository,
)
from ._materialization import _plan_fast_materialization, _plan_story_scoped_materialization
from ._models import (
    _claimed_operation_rejection_reason,
    _phase_binding_collision_reason,
    _start_binding_collision_reason,
    _StartPhaseMaterialization,
    _StartPhaseOutcome,
)
from ._operation_records import (
    _control_plane_request_body_hash,
    _object_claim_busy_rejection,
    _operation_record,
    _ownership_transferred_rejection,
    _push_barrier_rejection,
    _rejection_result,
)
from ._run_gates import _RunGateMixin

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.backend.control_plane.dispatch import PhaseDispatcher
    from agentkit.backend.control_plane.push_verification import PushBarrierEvidencePort
    from agentkit.backend.control_plane.records import BackendInstanceIdentityRecord

logger = logging.getLogger(__name__)

class _ControlPlaneRuntimeAdmissionBase(_RunGateMixin, _ClaimMixin, ABC):
    """Abstract admission-algorithm base for the runtime service.

    The concrete ``ControlPlaneRuntimeService`` supplies the template-method
    hooks below. Those hooks orchestrate collaborators assembled only by the full
    service, including ``_AdminTransitionMixin``, ``_EdgeCommandMixin``, and
    ``_ProjectEdgeSyncMixin``.
    """

    def __init__(
        self,
        *,
        repository: ControlPlaneRuntimeRepository | None = None,
        object_claim_repository: ObjectMutationClaimRepository | None = None,
        edge_command_repository: EdgeCommandRepository | None = None,
        phase_dispatcher: PhaseDispatcher | None = None,
        now_fn: Callable[[], datetime] | None = None,
        token_factory: Callable[[], str] | None = None,
        instance_identity: BackendInstanceIdentityRecord | None = None,
        execution_contract_digest_reader: (Callable[[PhaseMutationRequest, str], ExecutionContractDigestOutcome] | None) = None,
        push_barrier_evidence: PushBarrierEvidencePort | None = None,
    ) -> None:
        #: ERROR-3 fix (#3): whether this service uses the PRODUCTIVE default
        #: control-plane store (Postgres-only by design). When ``True`` every
        #: control-plane store entrypoint asserts the Postgres backend ONCE, early
        #: and CLEARLY (see :meth:`_require_postgres_backend_on_first_use`), so a
        #: SQLite/other backend fails fast with an explicit error instead of an
        #: opaque ``RuntimeError`` deep inside ``start_phase`` (the atomic claim).
        #: A DI-injected repository (tests / alternative wiring) owns its own
        #: backend and is exempt.
        self._uses_default_store = repository is None
        self._backend_checked = False
        self._repo = repository or ControlPlaneRuntimeRepository()
        #: AG3-141 (K5 Postgres-only): the object-mutation-claim persistence
        #: port ``object_claims.py`` orchestrates lock-sets over. Mirrors
        #: ``_instance_identity`` below: a DI-injected ``repository`` (test /
        #: alternative wiring, owns its own backend) that does not also inject
        #: an explicit ``object_claim_repository`` gets a self-contained
        #: in-memory fake (never the productive Postgres-backed default) --
        #: honoring the SAME cross-scope fairness contract -- so a DB-free unit
        #: test is never forced to also wire Postgres for the object claim.
        if object_claim_repository is not None:
            self._object_claim_repo = object_claim_repository
        elif repository is not None:
            self._object_claim_repo = _default_di_object_claim_repository()
        else:
            self._object_claim_repo = ObjectMutationClaimRepository()
        #: AG3-145 (K5 Postgres-only, FK-91 §91.1b): the Edge-Command-Queue DI
        #: seam -- see ``_resolve_edge_command_repository`` (mirrors
        #: ``object_claim_repository`` above; extracted to a module-level
        #: helper to keep this constructor's LOC budget, PY_CLASS_MAX_LOC_800).
        self._edge_command_repo = _resolve_edge_command_repository(edge_command_repository, repository)
        #: AG3-147 (FK-10 §10.2.4b): the two-stage push-barrier evidence DI seam
        #: (Edge freshness ∧ server ref-read). ``None`` here means "not explicitly
        #: wired": on the PRODUCTIVE default store it is lazily resolved to the
        #: real Postgres+code-backend port (:meth:`_resolve_push_barrier_evidence`)
        #: so the barrier is fail-closed enforced; a DI-injected ``repository``
        #: (test / alternative wiring) without an explicit port leaves the barrier
        #: UNWIRED (the gate no-ops) -- barrier tests inject an explicit port with
        #: prepared evidence, exactly like ``edge_command_repository``.
        self._push_barrier_evidence = push_barrier_evidence
        #: AG3-143 (K5 Postgres-only, FK-44 §44.3a): the execution-contract-
        #: digest reader for a genuinely fresh setup start. Mirrors
        #: ``object_claim_repository``: a DI-injected ``repository`` OR an
        #: injected ``phase_dispatcher`` (either one means this construction
        #: is a test / alternative wiring, never the fully productive default
        #: -- mirrors the existing pg-integration-test idiom of injecting a
        #: fake dispatcher while keeping the REAL Postgres-backed
        #: ``repository=None`` for the op/binding/ownership tables) that does
        #: not ALSO inject an explicit reader gets a trivial, always-
        #: succeeding in-memory reader (never the productive state-backend/
        #: filesystem gathering) -- so a DB-free/dispatcher-faked test
        #: exercising a fresh setup start is never forced to also wire a real
        #: project registration / story specification / skill-binding /
        #: prompt-bundle fixture. ``None`` on the FULLY productive default
        #: path (neither overridden) is lazily resolved to
        #: :meth:`_build_execution_contract_digest` on first use.
        self._execution_contract_digest_reader: Callable[[PhaseMutationRequest, str], ExecutionContractDigestOutcome] | None
        if execution_contract_digest_reader is not None:
            self._execution_contract_digest_reader = execution_contract_digest_reader
        elif repository is not None or phase_dispatcher is not None:
            self._execution_contract_digest_reader = _default_di_execution_contract_digest_reader()
        else:
            self._execution_contract_digest_reader = None
        #: AG3-142 (K5 Postgres-only): the run-ownership persistence port the
        #: admission fence reads (and the setup-start finalize inserts into) is
        #: ``self._repo.load_active_ownership`` -- the SAME
        #: ``ControlPlaneRuntimeRepository`` port every other regime mutation
        #: uses (op/binding/lock CRUD). ONE repository, ONE DI seam: a test
        #: injecting only ``repository=`` (the common case) gets ownership reads
        #: wired to the SAME fake state as everything else, never a second,
        #: silently-disconnected ownership store.
        #: AG3-054: the deterministic single-phase dispatcher (FK-45 §45.1.2). DI:
        #: the engine/registry + pre-start guard are injected, never self-built by
        #: this service. ``None`` is lazily resolved to the productive composition
        #: on first ``start_phase`` (so non-dispatch flows pay no wiring cost).
        self._phase_dispatcher = phase_dispatcher
        #: AG3-054 claim timestamp seams (deterministic-injectable). ``now_fn``
        #: stamps claim/audit instants (``claimed_at``, operation-record
        #: timestamps) and ``token_factory`` mints the per-call owner token; both
        #: default to the productive UTC clock / uuid but are injectable so the
        #: claim protocol is deterministically testable. AG3-139: ``now_fn`` is no
        #: longer consulted for any wall-clock expiry decision -- a claim's age is
        #: never interpreted to end it.
        self._now_fn: Callable[[], datetime] = now_fn or (lambda: datetime.now(tz=UTC))
        self._token_factory: Callable[[], str] = token_factory or (lambda: f"owner-{uuid.uuid4().hex}")
        #: AG3-138 (IMPL-003/IMPL-004): THIS boot's resolved instance identity.
        #: For the PRODUCTIVE default store it stays ``None`` until the pre-serve
        #: startup hook resolves and binds it (fail-closed via
        #: :meth:`_current_instance_identity`): the listener never accepts a
        #: claim-acquiring request before the hook has run
        #: (``control_plane_http.app.serve_control_plane``). A DI-injected
        #: repository is the test / alternative-wiring seam (it owns its own
        #: backend, mirroring ``_uses_default_store``): when such a caller does
        #: not inject an explicit identity, a deterministic default is bound so
        #: the claim stamp stays well-formed -- this is NOT a production
        #: fallback (production uses the default store and the startup hook).
        self._instance_identity = instance_identity
        if self._instance_identity is None and repository is not None:
            self._instance_identity = _default_di_instance_identity()

    @property
    def repository(self) -> ControlPlaneRuntimeRepository:
        """The control-plane runtime persistence port (AG3-138 startup hook wiring)."""
        return self._repo

    @property
    def object_claim_repository(self) -> ObjectMutationClaimRepository:
        """The object-mutation-claim persistence port (AG3-141 startup hook wiring)."""
        return self._object_claim_repo

    def bind_instance_identity(self, identity: BackendInstanceIdentityRecord) -> None:
        """Bind THIS boot's resolved instance identity (AG3-138 startup hook).

        Called exactly once by the pre-serve startup hook after
        :func:`~agentkit.backend.control_plane.instance_identity.resolve_backend_instance_identity`
        and :func:`~agentkit.backend.control_plane.startup_reconcile.run_startup_reconciliation`
        both succeed -- before the listener accepts its first request.
        """
        self._instance_identity = identity

    def _current_instance_identity(self) -> BackendInstanceIdentityRecord:
        """Return THIS boot's instance identity, resolving it once when needed.

        Every newly-acquired claim is stamped with the backend instance identity
        (AG3-138 AC3, FK-91 §91.1a rule 16). The identity is never invented and
        never a foreign one -- it is resolved from the authoritative persistent
        store (``backend_instance_identity``, Postgres-only, K5):

        * The **serving path** binds it up front: ``serve_control_plane`` runs the
          pre-serve startup hook (identity resolution + orphan reconciliation)
          BEFORE the listener accepts its first request (AC1/AC9), then
          :meth:`bind_instance_identity` binds it onto the service the listener
          uses -- so this method returns the already-bound value and the lazy
          branch below is never reached on the serving path.
        * A **DI-injected** repository binds a deterministic identity in
          ``__init__`` (the test / alternative-wiring seam).
        * For a **directly-constructed default-store** service the identity is
          resolved here lazily on first claim and memoized -- mirroring
          :meth:`_require_postgres_backend_on_first_use`, the default store is
          self-sufficient to resolve its OWN identity from the store. It never
          fabricates or guesses an identity (trap: own vs foreign); when the
          Postgres store is unavailable it fails CLOSED (K5) rather than stamping
          a fabricated identity onto a claim.
        """
        if self._instance_identity is not None:
            return self._instance_identity
        if self._uses_default_store:
            from agentkit.backend.control_plane.instance_identity import (
                resolve_backend_instance_identity,
            )
            from agentkit.backend.control_plane.repository import (
                BackendInstanceIdentityRepository,
            )

            self._instance_identity = resolve_backend_instance_identity(
                BackendInstanceIdentityRepository(),
            )
            return self._instance_identity
        # A DI repository without an explicit identity has one bound in __init__;
        # reaching here would be a wiring error -- fail closed rather than stamp
        # an unresolved claim.
        from agentkit.backend.exceptions import ConfigError

        raise ConfigError(
            "control-plane claim acquisition requires a resolved backend "
            "instance identity (AG3-138 IMPL-003/IMPL-004, fail-closed): no "
            "identity is bound and no default-store resolution seam is available.",
        )

    def _require_postgres_backend_on_first_use(self) -> None:
        """Assert the Postgres backend before the first default-store use (#3).

        The control-plane runtime store (operation/claim, session-binding and lock
        records) is part of the canonical central PostgreSQL runtime persistence
        (FK-22 §22.9) and has NO SQLite implementation. When this service uses the
        PRODUCTIVE default store, every store entrypoint calls this once: it fails
        CLOSED and CLEARLY with an explicit error if the active backend is not
        Postgres, instead of an opaque ``RuntimeError`` deep inside the atomic
        claim. A DI-injected repository (tests / alternative wiring) is exempt.
        """
        if not self._uses_default_store or self._backend_checked:
            return
        _require_postgres_control_plane_backend()
        self._backend_checked = True

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
        ):
            return _StartPhaseOutcome(
                rejection=self._ownership_admission_rejection(
                    admission,
                    op_id=request.op_id,
                    operation_kind="phase_start",
                    run_id=run_id,
                    phase=phase,
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

    def _repair_locked_rejection(
        self,
        *,
        project_key: str,
        story_id: str,
        operation_kind: str,
        op_id: str,
        run_id: str | None,
        phase: str,
    ) -> ControlPlaneMutationResult | None:
        """Fail-closed AC10 mutation lock: reject a mutation for a story in repair.

        A story with an open reconcile/repair state (an orphaned/aborted
        operation whose engine writes were already partially persisted, IMPL-005)
        is mutation-locked at this dispatch-/operations-layer entrypoint: no NEW
        mutating operation is admitted until the state is resolved via
        ``admin_abort``/repair (SEVERITY-SEMANTIK: a visible, auditable
        handling requirement, never silent continued work on a partial-write state).

        Returns:
            A fail-closed ``rejected`` result when the story is locked, else
            ``None`` (no NEW operation/claim/side-effect is written in either
            case -- a lock rejection stores nothing, mirroring every other
            fail-closed rejection in this module).
        """
        if not self._repo.has_open_repair_for_story(project_key, story_id):
            return None
        return _rejection_result(
            op_id=op_id,
            operation_kind=operation_kind,
            run_id=run_id,
            phase=phase,
            reason=(
                f"{operation_kind} rejected: story {story_id!r} has an open "
                "reconcile/repair state (a prior in-flight operation left "
                "partial engine writes -- phase_states/flow_executions -- after "
                "an admin-abort or startup-reconciliation orphan finalize); no "
                "new mutating operation is admitted until the state is resolved "
                "via admin_abort/repair (fail-closed, AG3-138 AC10)."
            ),
            dispatch_phase=phase,
        )

    def _fail_closed_setup_rejection(
        self,
        *,
        run_id: str,
        phase: str,
        op_id: str,
        reason: str,
    ) -> ControlPlaneMutationResult:
        """Build a fail-closed fresh-setup-start rejection (no state, no op)."""
        return _rejection_result(
            op_id=op_id,
            operation_kind="phase_start",
            run_id=run_id,
            phase=phase,
            reason=reason,
        )

    def _ownership_admission_rejection(
        self,
        admission: OwnershipAdmission,
        *,
        op_id: str,
        operation_kind: str,
        run_id: str | None,
        phase: str | None,
    ) -> ControlPlaneMutationResult:
        """Build the ex-owner rejection from a rejected :class:`OwnershipAdmission`.

        AG3-142 (SOLL-042, IMPL-019, FK-91 §91.1a Rule 18): ONLY the
        ``OWNERSHIP_TRANSFERRED`` reason carries the rich, structured
        ``ownership_transferred`` payload (mandatory: reason, new owner, transfer
        instant) -- ``admission.active_record`` is always present for THIS
        reason (an active record for THIS run with a DIFFERENT owner). Every
        other rejection reason (``NO_ACTIVE_RECORD`` / ``RUN_MISMATCH`` /
        ``STORY_EXITED``) has no "new owner" to report and falls back to the
        plain fail-closed rejection shape callers already use.
        """
        if admission.rejection_reason is not OwnershipRejectionReason.OWNERSHIP_TRANSFERRED:
            return _rejection_result(
                op_id=op_id,
                operation_kind=operation_kind,
                run_id=run_id,
                phase=phase,
                reason=(
                    f"{operation_kind} rejected: the active run-ownership record "
                    f"does not admit run {run_id!r} "
                    f"({admission.rejection_reason}); fail-closed "
                    "(FK-56 §56.8a)."
                ),
            )
        record = admission.active_record
        assert record is not None  # noqa: S101 -- OWNERSHIP_TRANSFERRED always carries one
        return _ownership_transferred_rejection(
            op_id=op_id,
            operation_kind=operation_kind,
            run_id=run_id,
            phase=phase,
            new_owner_session_id=record.owner_session_id,
            new_ownership_epoch=record.ownership_epoch,
            transferred_at=record.acquired_at,
        )

    def _ownership_fence_violation_rejection(
        self,
        exc: OwnershipFenceViolationError,
        *,
        op_id: str,
        operation_kind: str,
        run_id: str | None,
        phase: str | None,
    ) -> ControlPlaneMutationResult:
        """Build the ex-owner rejection from a commit-time fence violation (AG3-142).

        The row function's ``detail`` carries the CURRENT conflicting owner read
        within the SAME rolled-back transaction (no TOCTOU): ``None`` values mean
        the story has no active record at all (ended/reset/split/never admitted,
        never a genuine transfer) -- a plain fail-closed rejection, not the rich
        ``ownership_transferred`` payload.
        """
        new_owner = exc.detail.get("current_owner_session_id")
        new_epoch = exc.detail.get("current_ownership_epoch")
        transferred_at = exc.detail.get("transferred_at")
        if not isinstance(new_owner, str) or not isinstance(new_epoch, int) or not isinstance(transferred_at, str):
            return _rejection_result(
                op_id=op_id,
                operation_kind=operation_kind,
                run_id=run_id,
                phase=phase,
                reason=(
                    f"{operation_kind} rejected: the ownership fence failed at "
                    f"commit time for run {run_id!r} -- no active run-ownership "
                    f"record exists; fail-closed (FK-56 §56.8a, no TOCTOU). {exc}"
                ),
            )
        return _ownership_transferred_rejection(
            op_id=op_id,
            operation_kind=operation_kind,
            run_id=run_id,
            phase=phase,
            new_owner_session_id=new_owner,
            new_ownership_epoch=new_epoch,
            transferred_at=datetime.fromisoformat(transferred_at),
        )

    def _dispatch_phase(
        self,
        *,
        run_id: str,
        phase: str,
        request: PhaseMutationRequest,
        run_admitted: bool,
    ) -> PhaseDispatchResult | None:
        """Run the deterministic single-phase dispatch for a fresh start_phase.

        Resolves the run's :class:`StoryContext` through the sanctioned story read
        surface (same surface the mode resolution already uses) and drives the
        injected :class:`PhaseDispatcher`. Returns ``None`` when the story context
        is absent -- the idempotent persistence still commits, but no phase is
        dispatched (a missing context is surfaced by the dispatcher's own
        fail-closed path on the next resolvable call).

        AG3-054 ERROR-1 / AG3-142: the fresh-setup / first-call ADMISSION decision
        is computed RUN-scoped by the CALLER (``_evaluate_run_admission`` for THIS
        exact ``(project, story, run_id)`` -- since AG3-142, record-only) and
        threaded in here as ``run_admitted`` (a single admission read per call,
        never a second one). The dispatcher no longer derives "fresh" from
        story-scoped phase-state, so an OLD run's phase-state for the SAME story
        (after ``reset-escalation``, which mints a new run id but reuses the
        per-story story_dir) can never make a NEW, un-admitted run "not fresh" and
        SKIP the fail-closed pre-start guard.

        AG3-123: the Backend resolves the story-workspace filesystem anchor INSIDE
        the dispatcher via the injected ``StoryWorkspaceLocator`` (from canonical
        level-1 state, NOT ``ctx.project_root``). This method therefore no longer
        derives a ``story_dir`` from ``ctx.project_root`` -- the run-admission
        evaluation is decoupled from ``project_root`` resolvability. An unresolvable
        workspace is failed closed by the dispatcher as a structured rejection
        (``dispatched=False``); ``None`` is returned ONLY when the run
        ``StoryContext`` is absent, which the run-admission gate in
        :meth:`_start_phase_after_claim` handles fail-closed.
        """
        ctx = self._repo.load_story_context(request.project_key, request.story_id)
        if ctx is None:
            return None
        dispatcher = self._resolve_dispatcher()
        return dispatcher.dispatch(
            ctx=ctx,
            phase=phase,
            run_id=run_id,
            run_admitted=run_admitted,
            detail=request.detail,
        )

    def _resolve_dispatcher(self) -> PhaseDispatcher:
        """Return the injected dispatcher, lazily building the productive one."""
        if self._phase_dispatcher is None:
            from agentkit.backend.control_plane.dispatch import build_phase_dispatcher

            self._phase_dispatcher = build_phase_dispatcher()
        return self._phase_dispatcher

    def complete_phase(
        self,
        *,
        run_id: str,
        phase: str,
        request: PhaseMutationRequest,
    ) -> ControlPlaneMutationResult:
        return self._mutate_admitted_phase(
            run_id=run_id,
            phase=phase,
            request=request,
            operation_kind="phase_complete",
        )

    def fail_phase(
        self,
        *,
        run_id: str,
        phase: str,
        request: PhaseMutationRequest,
    ) -> ControlPlaneMutationResult:
        return self._mutate_admitted_phase(
            run_id=run_id,
            phase=phase,
            request=request,
            operation_kind="phase_fail",
        )

    def _mutate_admitted_phase(
        self,
        *,
        run_id: str,
        phase: str,
        request: PhaseMutationRequest,
        operation_kind: str,
    ) -> ControlPlaneMutationResult:
        """Mutate a phase that requires a PRIOR admitted start (E3).

        A phase complete/fail must follow a committed start: a completion or
        failure with no prior admitted run (no committed setup ``phase_start`` for
        the run AND no run-matched session binding) is fail-closed REJECTED -- it
        must NOT materialize story-scoped state out of thin air (no binding, no
        locks, no events, no stored op). Idempotent replay of the SAME op_id still
        wins first (the start/complete may legitimately replay).

        Args:
            run_id: The story run identifier.
            phase: The requested phase name.
            request: The phase mutation request.
            operation_kind: ``phase_complete`` or ``phase_fail``.

        Returns:
            The committed (or replayed) result, or a fail-closed rejection when no
            prior admitted run exists.
        """
        self._require_postgres_backend_on_first_use()
        existing = self._load_existing_operation(request, operation_kind=operation_kind, phase=phase)
        if existing is not None:
            return existing
        locked = self._repair_locked_rejection(
            project_key=request.project_key,
            story_id=request.story_id,
            operation_kind=operation_kind,
            op_id=request.op_id,
            run_id=run_id,
            phase=phase,
        )
        if locked is not None:
            return locked
        admission = self._run_was_admitted(request, run_id=run_id)
        if not admission.admitted:
            if admission.rejection_reason is OwnershipRejectionReason.OWNERSHIP_TRANSFERRED:
                return self._ownership_admission_rejection(
                    admission,
                    op_id=request.op_id,
                    operation_kind=operation_kind,
                    run_id=run_id,
                    phase=phase,
                )
            return _rejection_result(
                op_id=request.op_id,
                operation_kind=operation_kind,
                run_id=run_id,
                phase=phase,
                reason=(
                    f"{operation_kind} rejected: the run has no prior admitted "
                    "start (no committed setup phase_start and no session binding "
                    "for THIS project/story/run); fail-closed -- a "
                    "completion/failure must not materialize story-scoped state "
                    "for an unadmitted run (FK-20 §20.8.2)."
                ),
            )
        #: ``admission.admitted`` is True here, so ``active_record`` is present
        #: (``evaluate_ownership_admission``): its epoch is threaded verbatim to
        #: the commit-time re-check (no TOCTOU) and to the accountability stamp.
        assert admission.active_record is not None  # noqa: S101 -- admitted implies a record
        #: AG3-147 (FK-10 §10.2.4b, boundary type 1): the phase-completion push
        #: barrier. A code-bearing phase's completion is fail-closed BLOCKED until
        #: EVERY participating repo is server-verified-pushed -- checked AFTER
        #: admission, BEFORE the commit, so a blocked barrier writes NO state.
        if operation_kind == "phase_complete" and phase in runtime_constants.PUSH_GATED_COMPLETION_PHASES:
            blocked = self._push_barrier_block(
                SyncPointBarrierType.PHASE_COMPLETION,
                project_key=request.project_key,
                story_id=request.story_id,
                run_id=run_id,
                sync_point_id=run_id,
            )
            if blocked is not None:
                return _push_barrier_rejection(
                    blocked,
                    op_id=request.op_id,
                    operation_kind=operation_kind,
                    run_id=run_id,
                    phase=phase,
                )
        try:
            return self._mutate_phase(
                run_id=run_id,
                phase=phase,
                request=request,
                operation_kind=operation_kind,
                expected_ownership_epoch=admission.active_record.ownership_epoch,
            )
        except OwnershipFenceViolationError as exc:
            #: AG3-142 (no TOCTOU): the ownership fence re-check at commit time
            #: (in the SAME transaction as the collision-gated commit) failed --
            #: a takeover landed between the early admission check above and this
            #: commit. Nothing committed; surface the rich ex-owner rejection.
            return self._ownership_fence_violation_rejection(
                exc,
                op_id=request.op_id,
                operation_kind=operation_kind,
                run_id=run_id,
                phase=phase,
            )
        except ControlPlaneClaimCollisionError:
            #: ERROR-3 fix (#3): the op_id is held by a LIVE ``claimed`` start
            #: claim. The store refused to clobber it (only the owner's
            #: finalize/release may transition a claimed row), so this
            #: complete/fail reusing a live start's op_id is rejected fail-closed
            #: -- it never steals/destroys the start's ownership.
            reason = _claimed_operation_rejection_reason(operation_kind, request.op_id, "complete/fail")
            return _rejection_result(
                op_id=request.op_id,
                operation_kind=operation_kind,
                run_id=run_id,
                phase=phase,
                reason=reason,
            )
        except ControlPlaneBindingCollisionError as exc:
            #: AG3-054 run-scoping sweep: the binding SAVE would overwrite a live
            #: binding belonging to a DIFFERENT run that has rebound the same
            #: session. The store refused fail-closed and the WHOLE transaction
            #: rolled back -- NO binding overwrite, NO lock change, NO events, NO
            #: stored op. A complete/fail for an old run must never clobber a foreign
            #: run's live binding.
            reason = _phase_binding_collision_reason(operation_kind, exc)
            return _rejection_result(
                op_id=request.op_id,
                operation_kind=operation_kind,
                run_id=run_id,
                phase=phase,
                reason=reason,
            )

    @abstractmethod
    def _load_existing_operation(
        self,
        request: PhaseMutationRequest | ClosureCompleteRequest,
        *,
        operation_kind: str,
        phase: str | None,
        mutating_retry: bool = True,
    ) -> ControlPlaneMutationResult | None:
        del request, operation_kind, phase, mutating_retry
        raise NotImplementedError

    @abstractmethod
    def _story_scoped_materialization_enabled(self, request: PhaseMutationRequest) -> bool:
        del request
        raise NotImplementedError

    @abstractmethod
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
        del run_id, phase, request, operation_kind, expected_ownership_epoch, phase_dispatch
        raise NotImplementedError
