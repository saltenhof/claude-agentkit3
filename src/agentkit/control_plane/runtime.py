"""Control-plane services for run binding and project-edge sync."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal, Protocol, cast

from agentkit.control_plane.models import (
    ClosureCompleteRequest,
    ControlPlaneMutationResult,
    EdgeBundle,
    EdgePointer,
    PhaseDispatchResult,
    PhaseMutationRequest,
    ProjectEdgeSyncRequest,
    SessionRunBindingView,
    StoryExecutionLockView,
)
from agentkit.control_plane.records import (
    BindingDeleteScope,
    ControlPlaneOperationRecord,
    SessionRunBindingRecord,
)
from agentkit.control_plane.repository import ControlPlaneRuntimeRepository
from agentkit.exceptions import (
    ControlPlaneBindingCollisionError,
    ControlPlaneClaimCollisionError,
)
from agentkit.governance.guard_system.records import StoryExecutionLockRecord
from agentkit.governance.guard_system.story_scoped_guards import (
    should_create_story_lock_records,
)
from agentkit.story_context_manager.models import PhaseName
from agentkit.telemetry.contract.records import ExecutionEventRecord
from agentkit.telemetry.events import EventType

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.control_plane.dispatch import PhaseDispatcher

logger = logging.getLogger(__name__)

OperatingMode = Literal["ai_augmented", "story_execution", "binding_invalid"]
FreshnessClass = Literal["baseline_read", "guarded_read", "mutation"]

_SYNC_AFTER_BY_CLASS = {
    "baseline_read": timedelta(minutes=5),
    "guarded_read": timedelta(minutes=2),
    "mutation": timedelta(seconds=45),
}

#: AG3-054 leased claim TTL. A ``claimed`` placeholder older than this is treated
#: as a CRASHED owner and is reclaimable via an atomic CAS takeover; a younger
#: claim is an ACTIVE dispatch and is NEVER stolen (the loser gets an in-flight
#: rejection and retries). The value is the trade-off between the two hazards:
#:
#: * Too SHORT and a genuinely-live dispatch (engine + pre-start guard + the QA
#:   subflow's outermost reach) could exceed it and be stolen -> double dispatch,
#:   the exact ERROR this story closes. A control-plane ``start_phase`` only
#:   drives the deterministic single-phase dispatch + idempotent persistence
#:   (seconds), so a few minutes is comfortably above any non-crashed run.
#: * Too LONG and a crashed claim poisons the op_id for that long before a retry
#:   can reclaim it.
#:
#: Five minutes is well above the realistic dispatch wall-time and short enough
#: that a crashed claim is reclaimable within one operator/retry cycle.
_CLAIM_LEASE_TTL = timedelta(minutes=5)


class _ModeResolutionKeys(Protocol):
    """The authoritative ``(project_key, story_id)`` lookup keys for mode resolution.

    Both :class:`PhaseMutationRequest` and :class:`ClosureCompleteRequest` satisfy
    this structurally, so the single sanctioned-surface mode resolution
    (``_story_lock_records_apply``) is shared across setup and closure without
    coupling to a concrete request type.
    """

    @property
    def project_key(self) -> str: ...

    @property
    def story_id(self) -> str: ...


@dataclass(frozen=True)
class _StartPhaseOutcome:
    """Outcome of the post-claim dispatch for a ``start_phase`` (#1, ERROR-2).

    Carries EITHER a fail-closed ``rejection`` (the caller releases the claim and
    returns it) OR the admitted ``dispatch_result`` for the caller to commit in
    ONE place. Exactly one is non-``None``; both ``None`` means "admitted with no
    dispatch outcome" (a non-setup fail-closed-to-standard materialization).
    """

    rejection: ControlPlaneMutationResult | None
    dispatch_result: PhaseDispatchResult | None


@dataclass(frozen=True)
class _StartPhaseMaterialization:
    """The PLANNED start_phase side effects + edge bundle (no writes) (#1).

    ERROR-1 fix (#1): the start_phase side effects are PLANNED here (pure record
    construction, no store writes) so the ownership-scoped CAS finalize can apply
    them atomically in ONE transaction, gated on still owning the claim. A fast
    story carries an empty ``binding`` / ``locks`` / ``events`` (it materializes no
    story-scoped state) but still a valid ``bundle`` (ai_augmented).
    """

    bundle: EdgeBundle
    binding: SessionRunBindingRecord | None
    locks: tuple[StoryExecutionLockRecord, ...]
    events: tuple[ExecutionEventRecord, ...]


@dataclass(frozen=True)
class _ClaimOutcome:
    """Outcome of the leased, owner-scoped claim acquisition (AG3-054).

    Exactly one shape is valid:

    * ``won=True`` -- this caller holds the lease (fresh claim or CAS takeover of
      an expired one) and proceeds to dispatch; ``result`` is ``None`` and
      ``claimed_at_raw`` is the RAW lease instant this caller stamped.
    * ``won=False`` -- this caller LOST; ``result`` is the fail-closed outcome to
      return (a terminal REPLAY, or an "operation in flight, retry" rejection);
      ``claimed_at_raw`` is ``None``.

    WARNING-4 fix (#4): ``claimed_at_raw`` is the EXACT lease epoch (raw ISO TEXT)
    this caller wrote at claim/takeover time. It is threaded to finalize/release so
    their ownership CAS matches BOTH ``claimed_by`` AND ``claimed_at`` -- a stale
    owner whose token is reused (DI/test) or after an expiry-takeover cannot match a
    NEWER lease generation.
    """

    won: bool
    result: ControlPlaneMutationResult | None
    claimed_at_raw: str | None = None

    def result_or_raise(self) -> ControlPlaneMutationResult:
        """Return the loser's result; guard the won-but-no-result invariant."""
        if self.result is None:
            msg = "a lost claim must always carry a fail-closed result"
            raise RuntimeError(msg)
        return self.result


def _start_binding_collision_reason(
    phase: str, exc: ControlPlaneBindingCollisionError
) -> str:
    return "".join(
        (
            f"phase_start({phase}) rejected: {exc}. A start for this run ",
            "must not overwrite a foreign run's live binding (AG3-054 ",
            "run-scoping, fail-closed).",
        )
    )


def _claimed_operation_rejection_reason(
    operation_kind: str, op_id: str, operation_label: str
) -> str:
    suffix = (
        "A complete/fail reusing a live start's op_id must not clobber the claim "
        if operation_label == "complete/fail"
        else ""
    )
    return "".join(
        (
            f"{operation_kind} rejected: op_id {op_id!r} is held by a LIVE ",
            "'claimed' start lease; only its owner's finalize/release may ",
            f"transition it. {suffix}(AG3-054 ERROR-3, fail-closed).",
        )
    )


def _phase_binding_collision_reason(
    operation_kind: str, exc: ControlPlaneBindingCollisionError
) -> str:
    return "".join(
        (
            f"{operation_kind} rejected: {exc}. A {operation_kind} for an ",
            "old run must not overwrite a foreign run's live binding ",
            "(AG3-054 run-scoping, fail-closed).",
        )
    )


def _closure_binding_collision_reason(exc: ControlPlaneBindingCollisionError) -> str:
    return "".join(
        (
            f"closure_complete rejected: {exc}. A closure for an old run ",
            "must not tear down a foreign run's live binding (AG3-054 ",
            "run-scoping, fail-closed).",
        )
    )


class _ControlPlaneRuntimeAdmissionBase:
    """Start-phase admission and dispatch support for the runtime service."""

    def __init__(
        self,
        *,
        repository: ControlPlaneRuntimeRepository | None = None,
        phase_dispatcher: PhaseDispatcher | None = None,
        now_fn: Callable[[], datetime] | None = None,
        token_factory: Callable[[], str] | None = None,
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
        #: AG3-054: the deterministic single-phase dispatcher (FK-45 §45.1.2). DI:
        #: the engine/registry + pre-start guard are injected, never self-built by
        #: this service. ``None`` is lazily resolved to the productive composition
        #: on first ``start_phase`` (so non-dispatch flows pay no wiring cost).
        self._phase_dispatcher = phase_dispatcher
        #: AG3-054 leased claim seams (deterministic-injectable). ``now_fn`` is the
        #: lease-clock and ``token_factory`` mints the per-call owner token; both
        #: default to the productive UTC clock / uuid but are injectable so the
        #: claim/lease protocol is deterministically testable (no wall-clock,
        #: no random token inside the claim path).
        self._now_fn: Callable[[], datetime] = now_fn or (lambda: datetime.now(tz=UTC))
        self._token_factory: Callable[[], str] = token_factory or (
            lambda: f"owner-{uuid.uuid4().hex}"
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

    def _mint_owner_token(self) -> str:
        """Mint and VALIDATE the per-call owner token at the seam (AG3-054, #5).

        WARNING-5 fix (#5): ownership scoping (release / finalize / takeover CAS) is
        only sound if the owner token is UNIQUE and well-shaped. A DI-injected
        ``token_factory`` (tests / alternative wiring) that yields an empty or
        non-UUID-shaped token would let owner A's stale release/finalize CAS match
        owner B's claim (cross-ownership). The token is therefore validated here at
        the mint seam: it MUST be a non-empty string carrying a parseable UUID
        (the productive factory mints ``owner-<uuid4hex>``). An invalid token is
        rejected fail-closed with a clear error instead of silently eroding the
        ownership scope. The token stays injectable for deterministic tests --
        only its SHAPE is enforced, never a specific value.

        Returns:
            The validated owner token.

        Raises:
            ConfigError: When the configured ``token_factory`` yields an
                empty / non-UUID-shaped token.
        """
        token = self._token_factory()
        if not _is_valid_owner_token(token):
            from agentkit.exceptions import ConfigError

            raise ConfigError(
                "control-plane owner token is invalid: the leased owner-scoped "
                "claim (AG3-054) requires a non-empty, UUID-shaped owner token so "
                "release / finalize / takeover are ownership-scoped and cannot "
                "cross-match a different caller's claim. The configured "
                "token_factory yielded an empty or non-UUID-shaped token; "
                "fail-closed (#5).",
            )
        return token

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
        existing = self._load_existing_operation(request.op_id)
        if existing is not None:
            return existing

        #: AG3-054 leased, owner-scoped claim. Mint a per-call owner token and
        #: atomically CLAIM the op_id BEFORE the dispatch side effects. Exactly ONE
        #: concurrent caller wins; a loser is handed back a fail-closed result:
        #: a REPLAY of a terminal row, or an "operation in flight, retry" rejection
        #: for a still-live foreign claim (it NEVER steals, NEVER dispatches). An
        #: EXPIRED foreign claim (crashed owner) is taken over via an atomic CAS so
        #: the op_id is never permanently poisoned (#1).
        owner_token = self._mint_owner_token()
        claim = self._acquire_claim(
            request, run_id=run_id, phase=phase, owner_token=owner_token
        )
        if not claim.won:
            #: ``claim.result`` is the loser's fail-closed result (replay or
            #: in-flight rejection); it is always present when ``won`` is False.
            return claim.result_or_raise()
        #: WARNING-4 fix (#4): MY exact lease epoch (raw ISO TEXT). Threaded to
        #: finalize/release so their ownership CAS matches BOTH owner token AND
        #: lease epoch -- a stale generation (reused token / post-takeover) cannot
        #: match the newer lease. A won claim always carries it.
        owner_claimed_at = claim.claimed_at_raw

        #: ERROR-1 fix (#1): the ENTIRE post-claim path is wrapped so MY claim (and
        #: only mine) is never stranded. A rejection path releases MY claim and
        #: returns; ANY exception before the terminal op is durably finalized
        #: releases MY claim and re-raises. The claim is converted to a terminal
        #: row ONLY by the ownership-scoped CAS finalize.
        finalized = False
        try:
            outcome = self._start_phase_after_claim(
                run_id=run_id, phase=phase, request=request
            )
            if outcome.rejection is not None:
                # Fail-closed rejection: release MY claim so NO committed op
                # survives and a later retry (once admitted) re-evaluates.
                self._release_my_claim(
                    request.op_id, owner_token, owner_claimed_at
                )
                return outcome.rejection
            result = self._finalize_start_phase(
                run_id=run_id,
                phase=phase,
                request=request,
                owner_token=owner_token,
                owner_claimed_at=owner_claimed_at,
                phase_dispatch=outcome.dispatch_result,
            )
            finalized = True
            return result
        except ControlPlaneBindingCollisionError as exc:
            #: AG3-054 run-scoping sweep: this fresh start would materialize a
            #: binding for THIS run, but the session is already bound to a DIFFERENT
            #: run (it was rebound). The run-scoped store insert refused fail-closed
            #: and the WHOLE finalize rolled back -- the foreign run's binding is
            #: intact and NO terminal op survives. Release MY claim and surface a
            #: fail-closed rejection (a later retry, once the foreign run releases the
            #: session, re-evaluates). The claim is not yet a terminal row, so the
            #: release is ownership-scoped and safe.
            self._release_my_claim_best_effort(
                request.op_id, owner_token, owner_claimed_at
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
            #: release MY claim (#1) -- ownership-scoped, so a concurrent takeover's
            #: row is never touched. The release failure must not mask the original
            #: error, so it is best-effort. Re-raise so NO ERROR BYPASSING holds.
            if not finalized:
                self._release_my_claim_best_effort(
                    request.op_id, owner_token, owner_claimed_at
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
        the ``StoryContext`` is unresolvable (no ctx / no ``project_root``) BEFORE
        the dispatcher's own run-scoped first-call gate runs. Without this gate, a
        fresh, UN-ADMITTED, NON-setup start with an unresolvable ctx would fall
        through to the admitted path and materialize binding/locks/events out of
        thin air. The invariant held on ALL paths: an un-admitted run can NEVER
        materialize state via a non-setup start, regardless of ctx resolvability.
        """
        #: ERROR-1 fix (#1): run-admission evidence for THIS exact run, computed
        #: BEFORE/independent of the ctx-resolvability short-circuit. A fresh setup
        #: start is run-admitted only when there is run-matched evidence; a
        #: non-setup start requires the run to already have been admitted.
        run_admitted = self._run_admission_evidence(
            project_key=request.project_key,
            story_id=request.story_id,
            session_id=request.session_id,
            run_id=run_id,
        )
        dispatch_result = self._dispatch_phase(
            run_id=run_id, phase=phase, request=request
        )
        if dispatch_result is None and phase == PhaseName.SETUP.value and not run_admitted:
            #: Fail-closed run admission (FK-20 §20.8.2): a FRESH SETUP START whose
            #: ``StoryContext`` is unresolvable (no ctx / no project_root) could not
            #: have its Approved+READY run-admission evaluated. Active write-guards
            #: do NOT satisfy the run-admission invariant -- a run never
            #: Approved/READY must not start. We REJECT fail-closed so NO session
            #: binding, NO lock-records, NO ``phase_start`` edge bundle and NO
            #: lifecycle events are materialized, and NO operation is stored (a
            #: later retry with a resolvable, Approved+READY context re-evaluates).
            return _StartPhaseOutcome(
                rejection=self._fail_closed_setup_rejection(
                    run_id=run_id,
                    phase=phase,
                    op_id=request.op_id,
                    reason=(
                        "Fresh setup start rejected: the run's StoryContext is "
                        "unresolvable, so Approved + READY run-admission cannot "
                        "be evaluated; fail-closed (FK-20 §20.8.2)."
                    ),
                ),
                dispatch_result=None,
            )
        if (
            dispatch_result is None
            and phase != PhaseName.SETUP.value
            and not run_admitted
        ):
            #: ERROR-1 fix (#1): a FRESH, UN-ADMITTED, NON-setup start whose
            #: ``StoryContext`` is unresolvable. ``_dispatch_phase`` returned ``None``
            #: BEFORE the dispatcher's run-scoped first-call gate could run, so the
            #: run-admission invariant must be enforced HERE. A non-setup phase may
            #: only start once the run was admitted by a prior committed setup start
            #: (or a run-matched binding). With no such evidence the run was never
            #: admitted -> REJECT fail-closed: NO binding / lock / event / edge
            #: bundle is materialized and NO operation is stored (a later retry,
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
                        "THIS project/story/run) and its StoryContext is "
                        "unresolvable, so run-admission cannot be evaluated. A "
                        "non-setup start must never materialize story-scoped state "
                        "for an unadmitted run; fail-closed (FK-20 §20.8.2)."
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
        return _StartPhaseOutcome(rejection=None, dispatch_result=dispatch_result)

    def _acquire_claim(
        self,
        request: PhaseMutationRequest,
        *,
        run_id: str,
        phase: str,
        owner_token: str,
    ) -> _ClaimOutcome:
        """Acquire the leased, owner-scoped claim before dispatch (AG3-054, #1).

        Protocol:

        1. CLAIM = ``INSERT ... ON CONFLICT (op_id) DO NOTHING`` with the per-call
           ``owner_token`` lease. rowcount==1 => WON.
        2. Lost the insert => load the blocking row:

           * gone (a concurrent release) => retry the atomic claim ONCE.
           * TERMINAL (``status != 'claimed'``) => return the stored result as a
             REPLAY (a winner already finished; never re-dispatch).
           * LIVE ``claimed`` (now - claimed_at < TTL) => LOSER: a fail-closed
             "operation in flight, retry" rejection. DO NOT steal, DO NOT dispatch.
           * EXPIRED ``claimed`` (now - claimed_at >= TTL) => atomic CAS takeover
             of the crashed owner's lease; rowcount==1 => took over (WON), else a
             concurrent winner changed the row => LOSER (in-flight rejection).

        Args:
            request: The phase mutation request (op_id + lookup keys).
            run_id: The story run identifier.
            phase: The requested phase name.
            owner_token: This caller's per-call lease owner token.

        Returns:
            A :class:`_ClaimOutcome` carrying either the won lease or the loser's
            fail-closed result.
        """
        now = self._now_fn()
        placeholder = _build_claim_placeholder(
            request, run_id=run_id, phase=phase, owner_token=owner_token, now=now
        )
        #: WARNING-4 fix (#4): the RAW lease epoch this caller stamps. The writer
        #: stores ``claimed_at`` as ``isoformat`` TEXT, so this is the exact raw
        #: column value the finalize/release CAS must match (alongside the owner
        #: token) to scope to THIS lease generation.
        claim_instant_raw = now.isoformat()
        if self._repo.claim_operation(placeholder):
            return _ClaimOutcome(
                won=True, result=None, claimed_at_raw=claim_instant_raw
            )
        stored = self._repo.load_operation(request.op_id)
        if stored is None:
            # The blocking row vanished between the failed claim and this read
            # (a concurrent release). Retry the atomic claim once.
            if self._repo.claim_operation(placeholder):
                return _ClaimOutcome(
                    won=True, result=None, claimed_at_raw=claim_instant_raw
                )
            return _ClaimOutcome(won=False, result=self._in_flight_rejection(request))
        if stored.status != "claimed":
            # A terminal result already exists -- replay, never re-dispatch.
            return _ClaimOutcome(
                won=False,
                result=_replayed_result(stored.response_payload),
            )
        if not self._claim_is_expired(stored, now=now):
            # A LIVE foreign claim -- a winner is mid-dispatch. Never steal.
            return _ClaimOutcome(won=False, result=self._in_flight_rejection(request))
        # EXPIRED claim (crashed owner): atomic CAS takeover of the exact observed
        # lease. A concurrent winner that finalized/took over changed the row, so
        # the CAS affects zero rows and this caller loses the takeover race.
        #
        # ERROR-2 fix (AG3-054): the observed ``claimed_at`` is the RAW stored
        # column value (``claimed_at_raw``), NOT the normalized aware instant used
        # to JUDGE expiry above. The CAS compares against the raw TEXT column, so a
        # naive/legacy/malformed row (judged EXPIRED here) must be matched by its
        # raw value -- matching the normalized value would never hit the raw column
        # and would poison the op_id forever (rowcount 0 on every retry).
        if self._repo.takeover_operation(
            placeholder,
            observed_claimed_by=stored.claimed_by,
            observed_claimed_at=stored.claimed_at_raw,
        ):
            #: WARNING-4: the takeover re-stamped the lease to MY ``now``, so MY
            #: lease epoch is the same ``claim_instant_raw`` -- threaded to
            #: finalize/release so their CAS scopes to THIS (new) generation.
            return _ClaimOutcome(
                won=True, result=None, claimed_at_raw=claim_instant_raw
            )
        return _ClaimOutcome(won=False, result=self._in_flight_rejection(request))

    def _claim_is_expired(
        self,
        stored: ControlPlaneOperationRecord,
        *,
        now: datetime,
    ) -> bool:
        """Whether a ``claimed`` row's lease has expired (AG3-054, #4).

        Fail-closed: a ``claimed`` row with NO ``claimed_at`` (a legacy / malformed
        placeholder that carries no lease) is treated as EXPIRED so the op_id can
        never be poisoned permanently by an un-leased claim.

        WARNING-4 fix (#4): the mapper boundary normalizes ``claimed_at`` to aware
        UTC, but a naive ``claimed_at`` (e.g. injected via a fake repo) or a naive
        ``now`` (an injected ``now_fn``) would still make ``now - claimed_at`` raise
        ``TypeError`` and crash the retry BEFORE any takeover. Both operands are
        therefore coerced to aware UTC here, and a value that cannot be coerced is
        treated as EXPIRED (reclaimable) rather than crashing the takeover path.
        """
        if stored.claimed_at is None:
            return True
        claimed_at = _as_aware_utc(stored.claimed_at)
        if claimed_at is None:
            # An unusable lease instant is fail-closed reclaimable (EXPIRED),
            # never a crash (NO ERROR BYPASSING -- the op_id stays recoverable).
            return True
        return (_as_aware_utc(now) or now) - claimed_at >= _CLAIM_LEASE_TTL

    def _in_flight_rejection(
        self,
        request: PhaseMutationRequest,
    ) -> ControlPlaneMutationResult:
        """Build the fail-closed "operation in flight, retry" loser rejection.

        Returned when a LIVE foreign claim holds the op_id (or the CAS takeover of
        an expired claim was lost to a concurrent winner). The loser NEVER steals
        and NEVER dispatches; it surfaces a ``rejected`` retry-now result (no
        fabricated bundle, no second dispatch). A single retry then either replays
        the committed terminal result or reclaims a now-expired/released claim.
        """
        return _rejection_result(
            op_id=request.op_id,
            operation_kind="phase_start",
            run_id=None,
            phase=None,
            reason=(
                "Operation in flight: another caller holds an active claim for "
                "this op_id and is mid-dispatch. The dispatch runs EXACTLY ONCE "
                "under the winning caller; retry to read the committed result "
                "(AG3-054 leased owner-scoped claim, no double dispatch)."
            ),
        )

    def _finalize_start_phase(
        self,
        *,
        run_id: str,
        phase: str,
        request: PhaseMutationRequest,
        owner_token: str,
        owner_claimed_at: str | None,
        phase_dispatch: PhaseDispatchResult | None,
    ) -> ControlPlaneMutationResult:
        """Atomically CAS-finalize the claim AND materialize side effects (#1).

        ERROR-1 fix (#1): the side effects (binding/locks/events) are PLANNED here
        (no writes) and applied by the store in ONE transaction with the ownership
        CAS finalize (status->terminal WHERE op_id=? AND claimed_by=mytoken), gated
        on STILL owning the claim:

        * CAS affects 1 row -> I still own the claim: the terminal row AND the
          binding/locks/events are written atomically; the committed result stands.
        * CAS affects 0 rows -> my lease was taken over and finalized by a
          concurrent owner B: NOTHING is materialized (the store rolls back), so I
          (the loser) write NO duplicate/conflicting binding / lock / event. I then
          surface B's terminal row as a REPLAY (never overwriting it), or -- in the
          narrow window before it is readable -- the in-flight retry rejection.

        The loser therefore never writes canonical side effects (the EXACT defect
        this fix closes).
        """
        plan = self._plan_start_phase_materialization(
            run_id=run_id, phase=phase, request=request
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
            now=self._now_fn(),
        )
        if self._repo.finalize_start_phase(
            record,
            owner_token=owner_token,
            #: WARNING-4: the CAS scopes to BOTH owner token AND lease epoch.
            owner_claimed_at=owner_claimed_at,
            binding=plan.binding,
            locks=plan.locks,
            events=plan.events,
        ):
            return result
        #: Lost the ownership CAS: a concurrent takeover already finalized AND the
        #: side effects were rolled back (NO loser double-write). Replay the
        #: winner's terminal row; NEVER overwrite it (or, in the narrow window
        #: where it is not yet readable, surface the in-flight retry rejection).
        existing = self._load_existing_operation(request.op_id)
        if existing is not None:
            return existing
        return self._in_flight_rejection(request)

    def _plan_start_phase_materialization(
        self,
        *,
        run_id: str,
        phase: str,
        request: PhaseMutationRequest,
    ) -> _StartPhaseMaterialization:
        """Build (NO writes) the start_phase side effects + bundle (ERROR-1, #1).

        Standard/exploration runs plan the full binding/locks/events; an
        authoritatively-resolved fast story plans the bundle only (no side effects).
        The plan is applied atomically under the ownership CAS by the caller.
        """
        now = self._now_fn()
        if self._story_scoped_materialization_enabled(request):
            return _plan_story_scoped_materialization(
                run_id=run_id, phase=phase, request=request, now=now
            )
        return _plan_fast_materialization(request=request, now=now)

    def _release_my_claim(
        self, op_id: str, owner_token: str, owner_claimed_at: str | None
    ) -> None:
        """Ownership-scoped release of MY claim (never a foreign / terminal row).

        WARNING-4 fix (#4): the release CAS matches BOTH the owner token AND MY
        lease epoch (``owner_claimed_at``), so a stale generation (reused token /
        post-takeover) cannot delete a NEWER lease.
        """
        self._repo.release_operation(
            op_id, owner_token=owner_token, owner_claimed_at=owner_claimed_at
        )

    def _release_my_claim_best_effort(
        self, op_id: str, owner_token: str, owner_claimed_at: str | None
    ) -> None:
        """Release MY claim without masking an in-flight original error (#1).

        Used on the exception path: a release failure must NOT replace the original
        exception (it is logged and swallowed), so the real error always
        propagates (NO ERROR BYPASSING). The CAS is lease-epoch-scoped (#4).
        """
        try:
            self._repo.release_operation(
                op_id, owner_token=owner_token, owner_claimed_at=owner_claimed_at
            )
        except Exception:  # noqa: BLE001 -- never mask the original error
            logger.warning(
                "control-plane claim release failed for op_id=%s (original error "
                "is re-raised; the claim lease will expire and become reclaimable)",
                op_id,
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

    def _dispatch_phase(
        self,
        *,
        run_id: str,
        phase: str,
        request: PhaseMutationRequest,
    ) -> PhaseDispatchResult | None:
        """Run the deterministic single-phase dispatch for a fresh start_phase.

        Resolves the run's :class:`StoryContext` through the sanctioned story read
        surface (same surface the mode resolution already uses) and drives the
        injected :class:`PhaseDispatcher`. Returns ``None`` when the story context
        is unresolvable -- the idempotent persistence still commits, but no phase
        is dispatched (a missing context is surfaced by the dispatcher's own
        fail-closed path on the next resolvable call).

        AG3-054 ERROR-1: the fresh-setup / first-call ADMISSION decision is computed
        RUN-scoped HERE (``_run_admission_evidence`` for THIS exact ``(project,
        story, run_id)``) and threaded into the dispatcher as ``run_admitted``. The
        dispatcher no longer derives "fresh" from story-scoped phase-state, so an
        OLD run's phase-state for the SAME story (after ``reset-escalation``, which
        mints a new run id but reuses the per-story story_dir) can never make a NEW,
        un-admitted run "not fresh" and SKIP the fail-closed pre-start guard.
        """
        from agentkit.installer.paths import story_dir as resolve_story_dir

        ctx = self._repo.load_story_context(request.project_key, request.story_id)
        if ctx is None or ctx.project_root is None:
            return None
        dispatcher = self._resolve_dispatcher()
        s_dir = resolve_story_dir(ctx.project_root, ctx.story_id)
        run_admitted = self._run_admission_evidence(
            project_key=request.project_key,
            story_id=request.story_id,
            session_id=request.session_id,
            run_id=run_id,
        )
        return dispatcher.dispatch(
            ctx=ctx,
            phase=phase,
            story_dir=s_dir,
            run_id=run_id,
            run_admitted=run_admitted,
            detail=request.detail,
        )

    def _resolve_dispatcher(self) -> PhaseDispatcher:
        """Return the injected dispatcher, lazily building the productive one."""
        if self._phase_dispatcher is None:
            from agentkit.control_plane.dispatch import build_phase_dispatcher

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
        existing = self._load_existing_operation(request.op_id)
        if existing is not None:
            return existing
        if not self._run_was_admitted(request, run_id=run_id):
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
        try:
            return self._mutate_phase(
                run_id=run_id,
                phase=phase,
                request=request,
                operation_kind=operation_kind,
            )
        except ControlPlaneClaimCollisionError:
            #: ERROR-3 fix (#3): the op_id is held by a LIVE ``claimed`` start
            #: lease. The store refused to clobber it (only the owner's
            #: finalize/release may transition a claimed row), so this
            #: complete/fail reusing a live start's op_id is rejected fail-closed
            #: -- it never steals/destroys the start's ownership.
            reason = _claimed_operation_rejection_reason(
                operation_kind, request.op_id, "complete/fail"
            )
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

    def _run_was_admitted(
        self,
        request: PhaseMutationRequest,
        *,
        run_id: str,
    ) -> bool:
        """Whether a prior committed start admitted THIS exact run (E3 / #2).

        Admission evidence (either is sufficient, both RUN-matched): a committed
        setup ``phase_start`` for THIS exact ``(project_key, story_id, run_id)``,
        or a session binding that EXACTLY matches this run on ``(project_key,
        story_id, run_id)`` (a standard start materialized one). ERROR-2 fix (#2):
        a binding is admission evidence ONLY when it belongs to the SAME
        project/story/run -- a stale binding that merely reuses the same
        ``session_id`` for a DIFFERENT project/story/run must NOT admit this
        completion/failure. Fail-closed: when no run-matched evidence is present
        the run was never admitted.

        Args:
            request: The phase mutation request (lookup keys + session id).
            run_id: The authoritative path run id of the completion/failure.

        Returns:
            Whether THIS run was admitted by a prior committed start.
        """
        return self._run_admission_evidence(
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
    ) -> bool:
        """Whether a prior committed start admitted THIS run for closure (#6).

        Same run-matched admission evidence as :meth:`_run_was_admitted`: a
        committed setup ``phase_start`` for THIS run, or a session binding matching
        ``(project_key, story_id, run_id)``. Closure shares the complete/fail
        admission rule so the entrypoint is consistent (no unexplained asymmetry).
        """
        return self._run_admission_evidence(
            project_key=request.project_key,
            story_id=request.story_id,
            session_id=request.session_id,
            run_id=run_id,
        )

    def _run_admission_evidence(
        self,
        *,
        project_key: str,
        story_id: str,
        session_id: str,
        run_id: str,
    ) -> bool:
        """Shared RUN-scoped admission probe for complete/fail/closure (#2 / #3 / #6).

        ERROR-3 fix (#3): admission evidence is RUN-scoped, never story-scoped. The
        prior implementation also accepted a persisted phase-state, but
        ``PhaseState`` has NO ``run_id`` (it is keyed by story/phase), so a NEW run
        was wrongly admitted by an OLD run's phase-state of the SAME story. That
        story-scoped evidence is DROPPED. Admission now requires run-matched
        evidence, either of:

        * a session binding that EXACTLY matches ``(project_key, story_id,
          run_id)`` -- a standard start materialized one for THIS run (#2: a
          binding reusing the same ``session_id`` for a DIFFERENT run does NOT
          admit); or
        * a prior COMMITTED control-plane operation carrying THIS exact
          ``(project_key, story_id, run_id)`` -- a fast start (which materializes
          no binding) leaves a committed start op for the run.

        Fail-closed: no run-matched evidence => the run was never admitted.
        """
        binding = self._repo.load_binding(session_id)
        if (
            binding is not None
            and binding.project_key == project_key
            and binding.story_id == story_id
            and binding.run_id == run_id
        ):
            return True
        return self._repo.has_committed_operation_for_run(
            project_key, story_id, run_id
        )

    def _load_existing_operation(
        self,
        op_id: str,
    ) -> ControlPlaneMutationResult | None:
        del op_id
        raise NotImplementedError

    def _story_scoped_materialization_enabled(
        self, request: PhaseMutationRequest
    ) -> bool:
        del request
        raise NotImplementedError

    def _mutate_phase(
        self,
        *,
        run_id: str,
        phase: str,
        request: PhaseMutationRequest,
        operation_kind: str,
        phase_dispatch: PhaseDispatchResult | None = None,
    ) -> ControlPlaneMutationResult:
        del run_id, phase, request, operation_kind, phase_dispatch
        raise NotImplementedError


class ControlPlaneRuntimeService(_ControlPlaneRuntimeAdmissionBase):
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
        existing = self._load_existing_operation(request.op_id)
        if existing is not None:
            return existing

        if not self._closure_run_was_admitted(request, run_id=run_id):
            #: ERROR-6 fix (#6): closure is consistent with complete/fail admission
            #: -- a closure for a run with NO prior admitted start must NOT commit
            #: (no committed setup phase_start, no run-matched session binding).
            #: Fail-closed: an unadmitted closure never tears down (or fabricates)
            #: a guard regime. The AG3-018 fast-story no-op is PRESERVED when there
            #: WAS a prior admitted run (the fast story's admitted setup left a
            #: committed setup phase_start), so a legitimate fast closure still
            #: no-ops below.
            return _rejection_result(
                op_id=request.op_id,
                operation_kind="closure_complete",
                run_id=run_id,
                phase="closure",
                reason=(
                    "closure_complete rejected: the run has no prior admitted "
                    "start (no committed setup phase_start and no session binding "
                    "for THIS project/story/run); fail-closed -- closure must not "
                    "commit for an unadmitted run (FK-20 §20.8.2)."
                ),
                dispatch_phase="closure",
            )

        now = datetime.now(tz=UTC)
        try:
            if not self._story_lock_records_apply(request):
                return _complete_fast_closure(
                    self._repo,
                    run_id=run_id,
                    request=request,
                    now=now,
                )
            return self._complete_standard_closure(
                run_id=run_id, request=request, now=now
            )
        except ControlPlaneClaimCollisionError:
            #: ERROR-3 fix (#3): the op_id is held by a LIVE ``claimed`` start
            #: lease; the store refused to clobber it. A closure reusing a live
            #: start's op_id is rejected fail-closed (consistent with
            #: complete/fail), never stealing the start's ownership.
            reason = _claimed_operation_rejection_reason(
                "closure_complete", request.op_id, "closure"
            )
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
            #: regime.
            reason = _closure_binding_collision_reason(exc)
            return _rejection_result(
                op_id=request.op_id,
                operation_kind="closure_complete",
                run_id=run_id,
                phase="closure",
                reason=reason,
                dispatch_phase="closure",
            )

    def _complete_standard_closure(
        self,
        *,
        run_id: str,
        request: ClosureCompleteRequest,
        now: datetime,
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
        binding_version = (
            binding.binding_version if binding is not None else _next_binding_version()
        )
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
                payload={"session_id": request.session_id},
                now=now,
            ),
            _lifecycle_event_record(
                event_type=EventType.STORY_EXECUTION_REGIME_DEACTIVATED,
                project_key=request.project_key,
                story_id=request.story_id,
                run_id=run_id,
                source_component=request.source_component,
                payload={"session_id": request.session_id},
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
        if (
            binding.project_key == request.project_key
            and binding.story_id == request.story_id
            and binding.run_id == run_id
        ):
            return binding
        raise ControlPlaneBindingCollisionError(
            f"closure for run {run_id!r} refused: session "
            f"{request.session_id!r} is bound to run {binding.run_id!r} "
            f"(project={binding.project_key!r}, story={binding.story_id!r}); a "
            "stale closure must not tear down a foreign run's live binding "
            "(AG3-054 run-scoping, fail-closed).",
        )

    def sync_project_edge(
        self,
        request: ProjectEdgeSyncRequest,
    ) -> ControlPlaneMutationResult:
        self._require_postgres_backend_on_first_use()
        now = datetime.now(tz=UTC)
        binding = self._repo.load_binding(request.session_id)
        if binding is None or binding.project_key != request.project_key:
            lock = StoryExecutionLockRecord(
                project_key=request.project_key,
                story_id="",
                run_id="",
                lock_type="story_execution",
                status="INACTIVE",
                worktree_roots=(),
                binding_version=_next_binding_version(),
                activated_at=now,
                updated_at=now,
                deactivated_at=now,
            )
            bundle = _build_edge_bundle(
                binding=None,
                lock=lock,
                sync_class=request.freshness_class,
                now=now,
            )
            return ControlPlaneMutationResult(
                status="synced",
                op_id=request.op_id,
                operation_kind="project_edge_sync",
                edge_bundle=bundle,
            )

        lock_record = self._repo.load_lock(
            binding.project_key,
            binding.story_id,
            binding.run_id,
            "story_execution",
        )
        qa_lock_record = self._repo.load_lock(
            binding.project_key,
            binding.story_id,
            binding.run_id,
            "qa_artifact_write",
        )
        if lock_record is None:
            lock = StoryExecutionLockRecord(
                project_key=binding.project_key,
                story_id=binding.story_id,
                run_id=binding.run_id,
                lock_type="story_execution",
                status="INVALID",
                worktree_roots=binding.worktree_roots,
                binding_version=binding.binding_version,
                activated_at=now,
                updated_at=now,
            )
        else:
            lock = lock_record
        bundle = _build_edge_bundle(
            binding=binding,
            lock=lock,
            qa_lock=qa_lock_record,
            sync_class=request.freshness_class,
            now=now,
        )
        return ControlPlaneMutationResult(
            status="synced",
            op_id=request.op_id,
            operation_kind="project_edge_sync",
            run_id=binding.run_id,
            edge_bundle=bundle,
        )

    def get_operation(self, op_id: str) -> ControlPlaneMutationResult | None:
        self._require_postgres_backend_on_first_use()
        record = self._repo.load_operation(op_id)
        if record is None:
            return None
        if record.status == "claimed":
            #: ERROR-4: an in-flight claim placeholder is not a reconcilable op yet.
            return None
        return _replayed_result(record.response_payload)

    def _mutate_phase(
        self,
        *,
        run_id: str,
        phase: str,
        request: PhaseMutationRequest,
        operation_kind: str,
        phase_dispatch: PhaseDispatchResult | None = None,
    ) -> ControlPlaneMutationResult:
        existing = self._load_existing_operation(request.op_id)
        if existing is not None:
            return existing

        now = self._now_fn()
        #: ERROR-2 fix (#2): PLAN the side effects (pure record construction, no
        #: writes) so the op-row commit AND the binding/locks/events apply in ONE
        #: atomic transaction with the collision gate FIRST. The prior code wrote
        #: the side effects through separate transactions and THEN stored the op,
        #: so a live-claim collision left orphan side effects behind.
        if self._story_scoped_materialization_enabled(request):
            plan = _plan_story_scoped_materialization(
                run_id=run_id, phase=phase, request=request, now=now
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
        )
        #: Atomic: the conditional op-row upsert (collision gate) + side effects in
        #: ONE transaction. A collision raises ``ControlPlaneClaimCollisionError``
        #: (handled fail-closed by the caller) with NO orphan side effect written.
        self._repo.commit_operation_with_side_effects(
            record,
            binding_to_save=plan.binding,
            binding_to_delete=None,
            locks=plan.locks,
            events=plan.events,
        )
        return result

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
        op_id: str,
    ) -> ControlPlaneMutationResult | None:
        existing = self._repo.load_operation(op_id)
        if existing is None:
            return None
        if existing.status == "claimed":
            #: ERROR-4: a ``claimed`` placeholder is an in-flight reservation, not a
            #: committed/replayable result (its ``response_payload`` is empty). It
            #: is NOT a replay target.
            return None
        return _replayed_result(existing.response_payload)


def _complete_fast_closure(
    repo: ControlPlaneRuntimeRepository,
    *,
    run_id: str,
    request: ClosureCompleteRequest,
    now: datetime,
) -> ControlPlaneMutationResult:
    """No-op closure for a fast story (FK-24 §24.3.4; ``no_locks_active``).

    A fast story never created a session binding or story/QA lock-records at
    setup, so closure deactivates NOTHING: it creates no ``story_execution`` /
    ``qa_artifact_write`` lock-records and emits NO story-execution deactivation
    events. It returns an ``ai_augmented`` bundle with no session and no locks.
    Any session binding that may exist is still cleaned up, but a fast run holds
    none, so this is a pure no-op for the guard regime.

    ERROR-2 fix (#2): the op-row commit and the (best-effort) binding deletion run
    in ONE atomic transaction with the collision gate FIRST, so a closure reusing a
    LIVE ``claimed`` start's op_id raises :class:`ControlPlaneClaimCollisionError`
    (handled fail-closed by :meth:`complete_closure`) with the binding deletion
    rolled back too -- no orphan teardown even on the fast path.
    """
    bundle = _build_fast_edge_bundle(
        project_key=request.project_key,
        sync_class="mutation",
        now=now,
    )
    result = ControlPlaneMutationResult(
        status="committed",
        op_id=request.op_id,
        operation_kind="closure_complete",
        run_id=run_id,
        phase="closure",
        edge_bundle=bundle,
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
    )
    repo.commit_operation_with_side_effects(
        record,
        binding_to_save=None,
        #: AG3-054 run-scoping: a fast run holds no binding, so this delete is a
        #: benign no-op for THIS run. But it stays run-scoped so a session that a
        #: DIFFERENT (standard) run has since rebound is NEVER torn down by this
        #: fast closure -- a foreign binding fails closed at the store and rolls back.
        binding_to_delete=BindingDeleteScope(
            session_id=request.session_id,
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=run_id,
        ),
        locks=(),
        events=(),
    )
    return result


def _plan_story_scoped_materialization(
    *,
    run_id: str,
    phase: str,
    request: PhaseMutationRequest,
    now: datetime,
) -> _StartPhaseMaterialization:
    """Build (NO writes) the full story-scoped binding + locks + events (#1).

    Pure record construction for a standard/exploration run: the records and the
    edge bundle are built but NOT persisted, so the leased start_phase finalize can
    write them atomically under the ownership CAS (ERROR-1). The complete/fail
    commit (``_mutate_phase``) reuses this planner too, applying the records under
    the atomic collision-gated commit (ERROR-2).
    """
    binding_version = _next_binding_version()
    binding = SessionRunBindingRecord(
        session_id=request.session_id,
        project_key=request.project_key,
        story_id=request.story_id,
        run_id=run_id,
        principal_type=request.principal_type,
        worktree_roots=tuple(request.worktree_roots),
        binding_version=binding_version,
        updated_at=now,
    )
    lock = StoryExecutionLockRecord(
        project_key=request.project_key,
        story_id=request.story_id,
        run_id=run_id,
        lock_type="story_execution",
        status="ACTIVE",
        worktree_roots=tuple(request.worktree_roots),
        binding_version=binding_version,
        activated_at=now,
        updated_at=now,
    )
    qa_lock = StoryExecutionLockRecord(
        project_key=request.project_key,
        story_id=request.story_id,
        run_id=run_id,
        lock_type="qa_artifact_write",
        status="ACTIVE",
        worktree_roots=tuple(request.worktree_roots),
        binding_version=binding_version,
        activated_at=now,
        updated_at=now,
    )
    bundle = _build_edge_bundle(
        binding=binding,
        lock=lock,
        qa_lock=qa_lock,
        sync_class="mutation",
        now=now,
    )
    events = (
        _lifecycle_event_record(
            event_type=EventType.SESSION_RUN_BINDING_CREATED,
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=run_id,
            source_component=request.source_component,
            payload={
                "session_id": request.session_id,
                "principal_type": request.principal_type,
                "worktree_roots": list(request.worktree_roots),
            },
            now=now,
            phase=phase,
        ),
        _lifecycle_event_record(
            event_type=EventType.STORY_EXECUTION_REGIME_ACTIVATED,
            project_key=request.project_key,
            story_id=request.story_id,
            run_id=run_id,
            source_component=request.source_component,
            payload={"session_id": request.session_id},
            now=now,
            phase=phase,
        ),
    )
    return _StartPhaseMaterialization(
        bundle=bundle,
        binding=binding,
        locks=(lock, qa_lock),
        events=events,
    )


def _plan_fast_materialization(
    *,
    request: PhaseMutationRequest,
    now: datetime,
) -> _StartPhaseMaterialization:
    """Build (NO writes) the fast-story plan: bundle only, no side effects (#1).

    A fast story materializes NO session binding, NO ``story_execution`` lock and
    NO ``qa_artifact_write`` lock, so the plan carries an empty binding / locks /
    events but a valid ``ai_augmented`` bundle. The story-scoped guards never
    activate; the baseline guards (BranchGuard et al.) stay active in every mode.
    """
    bundle = _build_fast_edge_bundle(
        project_key=request.project_key,
        sync_class="mutation",
        now=now,
    )
    return _StartPhaseMaterialization(
        bundle=bundle, binding=None, locks=(), events=()
    )


def _operation_record(
    *,
    op_id: str,
    project_key: str,
    story_id: str,
    run_id: str | None,
    session_id: str | None,
    operation_kind: str,
    phase: str | None,
    result: ControlPlaneMutationResult,
    now: datetime,
) -> ControlPlaneOperationRecord:
    """Build the terminal operation record (no claim lease -- a terminal row)."""
    return ControlPlaneOperationRecord(
        op_id=op_id,
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
        session_id=session_id,
        operation_kind=operation_kind,
        phase=phase,
        status=result.status,
        response_payload=result.model_dump(mode="json"),
        created_at=now,
        updated_at=now,
    )


def _lifecycle_event_record(
    *,
    event_type: EventType,
    project_key: str,
    story_id: str,
    run_id: str,
    source_component: str,
    payload: dict[str, object],
    now: datetime,
    phase: str | None = None,
) -> ExecutionEventRecord:
    """Build (NO write) one canonical control-plane lifecycle execution event (#1)."""
    return ExecutionEventRecord(
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
        event_id=f"evt-{uuid.uuid4().hex}",
        event_type=event_type.value,
        occurred_at=now,
        source_component=source_component,
        severity="info",
        phase=phase,
        payload=payload,
    )


def _require_postgres_control_plane_backend() -> None:
    """Fail closed unless the active state backend supports the control plane (#3).

    The control-plane runtime store (session bindings, story-execution locks and
    the idempotent operation/claim records) lives ONLY in the canonical central
    PostgreSQL runtime persistence (FK-22 §22.9). The SQLite backend is a narrow,
    gated unit-test backend that does not provide the global control-plane tables,
    so a productive ``ControlPlaneRuntimeService`` on SQLite would raise an opaque
    ``RuntimeError`` mid-call inside ``start_phase`` (the atomic claim). This
    surfaces that as an explicit, early ``ConfigError`` at construction instead.

    Raises:
        ConfigError: When the active backend lacks the control-plane store.
    """
    from agentkit.exceptions import ConfigError
    from agentkit.state_backend.store import control_plane_backend_available

    # Resolve the backend support through the sanctioned ``state_backend.store``
    # surface (architecture conformance AC010/AC011: the control plane must not
    # import the raw ``state_backend.config`` driver module directly).
    if not control_plane_backend_available():
        raise ConfigError(
            "The control-plane runtime requires the Postgres state backend: the "
            "control-plane operation/claim, session-binding and lock records are "
            "part of the canonical central PostgreSQL runtime persistence (FK-22 "
            "§22.9) and have no SQLite implementation. Set "
            "AGENTKIT_STATE_BACKEND=postgres for any productive / control-plane "
            "path; fail-closed (#3).",
        )


def _build_claim_placeholder(
    request: PhaseMutationRequest,
    *,
    run_id: str,
    phase: str,
    owner_token: str,
    now: datetime,
) -> ControlPlaneOperationRecord:
    """Build the in-flight leased ``claimed`` placeholder op record (AG3-054).

    The ``claimed`` status marks an in-flight reservation, distinct from the
    terminal ``committed`` / ``rejected`` the winning caller writes next; its
    ``response_payload`` is empty (not a replayable result). ``claimed_by`` is the
    per-call owner token and ``claimed_at`` is the lease start instant -- the
    expiry compare and the CAS takeover both key off this exact lease.
    """
    return ControlPlaneOperationRecord(
        op_id=request.op_id,
        project_key=request.project_key,
        story_id=request.story_id,
        run_id=run_id,
        session_id=request.session_id,
        operation_kind="phase_start",
        phase=phase,
        status="claimed",
        response_payload={},
        created_at=now,
        updated_at=now,
        claimed_by=owner_token,
        claimed_at=now,
    )


def _rejection_result(
    *,
    op_id: str,
    operation_kind: str,
    run_id: str | None,
    phase: str | None,
    reason: str,
    dispatch_phase: str = "setup",
) -> ControlPlaneMutationResult:
    """Build a fail-closed REJECTED mutation result (no bundle, no committed op).

    The single shared shape for every control-plane rejection (fresh-setup
    unresolvable ctx / pre-start-guard / unadmitted complete-fail / in-flight
    claim loss): ``status='rejected'``, no ``edge_bundle`` (it materialized none),
    and the reason carried on a ``rejected`` :class:`PhaseDispatchResult`.

    Args:
        op_id: The operation id.
        operation_kind: ``phase_start`` / ``phase_complete`` / ``phase_fail``.
        run_id: The run id (``None`` when unknown, e.g. a claim-loss replay).
        phase: The requested phase (``None`` when unknown).
        reason: The human-readable rejection reason.
        dispatch_phase: The phase name carried on the inner ``PhaseDispatchResult``
            (defaults to ``setup``; the outer ``phase`` may be ``None``).

    Returns:
        The fail-closed ``rejected`` :class:`ControlPlaneMutationResult`.
    """
    return ControlPlaneMutationResult(
        status="rejected",
        op_id=op_id,
        operation_kind=operation_kind,
        run_id=run_id,
        phase=phase,
        edge_bundle=None,
        phase_dispatch=PhaseDispatchResult(
            phase=phase or dispatch_phase,
            status="rejected",
            reaction="rejected",
            dispatched=False,
            rejection_reason=reason,
        ),
    )


def _replayed_result(
    stored_payload: dict[str, object],
) -> ControlPlaneMutationResult:
    """Rebuild a stored result as a ``replayed`` result, RE-RUNNING validators (E6).

    The status rewrite to ``replayed`` is done by re-constructing the model via
    ``model_validate`` over the stored payload with ``status`` overridden -- NOT
    via ``model_copy(update=...)`` (which pydantic does NOT re-validate). So the
    model's ``edge_bundle``-optionality invariant (``edge_bundle`` may be ``None``
    only for ``rejected``) is re-enforced on every replay: a tampered stored
    payload that violates it raises at the boundary instead of silently passing.

    Args:
        stored_payload: The JSON payload of the persisted operation.

    Returns:
        A validated ``replayed`` :class:`ControlPlaneMutationResult`.
    """
    return ControlPlaneMutationResult.model_validate(
        {**stored_payload, "status": "replayed"},
    )


def _build_fast_edge_bundle(
    *,
    project_key: str,
    sync_class: FreshnessClass,
    now: datetime,
) -> EdgeBundle:
    """Build an ``ai_augmented`` bundle for a fast story (AG3-018 AC3/AC5).

    A fast story carries no story-scoped session binding and no
    ``story_execution`` / ``qa_artifact_write`` lock. The resulting bundle has
    ``session is None`` and ``lock is None``, so the local edge resolves to
    ``ai_augmented`` and only the baseline guards run.

    Args:
        project_key: The project key for the edge pointer.
        sync_class: Freshness class driving the pointer ``sync_after``.
        now: The mutation timestamp.

    Returns:
        An ``EdgeBundle`` with no session and no locks.
    """
    export_version = f"edge-{uuid.uuid4().hex}"
    pointer = EdgePointer(
        project_key=project_key,
        export_version=export_version,
        operating_mode="ai_augmented",
        bundle_dir=f"_temp/governance/bundles/{export_version}",
        sync_after=now + _SYNC_AFTER_BY_CLASS[sync_class],
        freshness_class=sync_class,
        generated_at=now,
    )
    return EdgeBundle(
        current=pointer,
        session=None,
        lock=None,
        qa_lock=None,
        tombstone_worktree_roots=[],
    )


def _build_edge_bundle(
    *,
    binding: SessionRunBindingRecord | None,
    lock: StoryExecutionLockRecord,
    qa_lock: StoryExecutionLockRecord | None = None,
    sync_class: FreshnessClass,
    now: datetime,
    tombstone_worktree_roots: tuple[str, ...] = (),
) -> EdgeBundle:
    operating_mode = _resolve_operating_mode(binding=binding, lock=lock)
    export_version = f"edge-{uuid.uuid4().hex}"
    pointer = EdgePointer(
        project_key=lock.project_key or (binding.project_key if binding else ""),
        export_version=export_version,
        operating_mode=operating_mode,
        bundle_dir=f"_temp/governance/bundles/{export_version}",
        sync_after=now + _SYNC_AFTER_BY_CLASS[sync_class],
        freshness_class=sync_class,
        generated_at=now,
    )
    binding_view = (
        SessionRunBindingView(
            session_id=binding.session_id,
            project_key=binding.project_key,
            story_id=binding.story_id,
            run_id=binding.run_id,
            principal_type=binding.principal_type,
            worktree_roots=list(binding.worktree_roots),
            binding_version=binding.binding_version,
            operating_mode=operating_mode,
        )
        if binding is not None
        else None
    )
    lock_view = StoryExecutionLockView(
        project_key=lock.project_key,
        story_id=lock.story_id,
        run_id=lock.run_id,
        lock_type=lock.lock_type,
        status=cast("Literal['ACTIVE', 'INACTIVE', 'INVALID']", lock.status),
        worktree_roots=list(lock.worktree_roots),
        binding_version=lock.binding_version,
        activated_at=lock.activated_at,
        updated_at=lock.updated_at,
        deactivated_at=lock.deactivated_at,
    )
    qa_lock_view = (
        StoryExecutionLockView(
            project_key=qa_lock.project_key,
            story_id=qa_lock.story_id,
            run_id=qa_lock.run_id,
            lock_type=qa_lock.lock_type,
            status=cast("Literal['ACTIVE', 'INACTIVE', 'INVALID']", qa_lock.status),
            worktree_roots=list(qa_lock.worktree_roots),
            binding_version=qa_lock.binding_version,
            activated_at=qa_lock.activated_at,
            updated_at=qa_lock.updated_at,
            deactivated_at=qa_lock.deactivated_at,
        )
        if qa_lock is not None
        else None
    )
    return EdgeBundle(
        current=pointer,
        session=binding_view,
        lock=lock_view,
        qa_lock=qa_lock_view,
        tombstone_worktree_roots=list(tombstone_worktree_roots),
    )


def _resolve_operating_mode(
    *,
    binding: SessionRunBindingRecord | None,
    lock: StoryExecutionLockRecord,
) -> OperatingMode:
    if binding is None:
        return "ai_augmented"
    if lock.status == "ACTIVE":
        return "story_execution"
    return "binding_invalid"


def _is_valid_owner_token(token: object) -> bool:
    """Whether an owner token is non-empty and UUID-shaped (AG3-054, #5).

    Accepts either a bare UUID (``uuid4`` hex or canonical form) or the productive
    ``owner-<uuid4hex>`` shape (the ``owner-`` prefix is stripped before the UUID
    check). An empty / whitespace-only / non-UUID token is rejected so two distinct
    claims can never cross-match. Validation is purely structural -- any unique
    UUID-shaped token (including a test-injected one) is accepted.

    Args:
        token: The candidate owner token (validated structurally).

    Returns:
        ``True`` iff the token carries a parseable UUID.
    """
    if not isinstance(token, str) or not token.strip():
        return False
    candidate = token.strip()
    if candidate.startswith("owner-"):
        candidate = candidate[len("owner-") :]
    try:
        uuid.UUID(candidate)
    except ValueError:
        return False
    return True


def _as_aware_utc(value: datetime) -> datetime | None:
    """Coerce a datetime to aware UTC for the lease-expiry compare (#4).

    A naive value is assumed UTC; an aware value is converted to UTC. Returns
    ``None`` only if the value is not a usable datetime (defensive: the caller
    then treats the lease as EXPIRED rather than crashing).
    """
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _next_binding_version() -> str:
    return f"bind-{uuid.uuid4().hex}"
