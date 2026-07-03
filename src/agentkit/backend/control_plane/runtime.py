"""Control-plane services for run binding and project-edge sync."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal, Protocol, cast

from agentkit.backend.control_plane.models import (
    AdminAbortRequest,
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
from agentkit.backend.control_plane.ownership import (
    INITIAL_OPERATION_EPOCH,
    MIN_BINDING_VERSION,
)
from agentkit.backend.control_plane.records import (
    BindingDeleteScope,
    ControlPlaneOperationRecord,
    SessionRunBindingRecord,
)
from agentkit.backend.control_plane.repository import ControlPlaneRuntimeRepository

# Deliberate RUNTIME re-import (not TYPE_CHECKING): this is the SSOT re-import of
# the canonical FK-56 operating-mode literal from its SINGLE foundation definition
# (``core_types.operating_mode``). It must be a runtime binding so the
# single-definition identity holds for consumers (and is assertable) -- moving it
# into a type-checking block would make ``control_plane.runtime.OperatingMode`` a
# different/absent object at runtime, defeating the AK2 SSOT consolidation.
from agentkit.backend.core_types.operating_mode import OperatingMode  # noqa: TC001
from agentkit.backend.exceptions import (
    ControlPlaneBindingCollisionError,
    ControlPlaneClaimCollisionError,
)
from agentkit.backend.governance.guard_system.records import StoryExecutionLockRecord
from agentkit.backend.governance.guard_system.story_scoped_guards import (
    should_create_story_lock_records,
)
from agentkit.backend.pipeline_engine.phase_executor import PhaseName
from agentkit.backend.telemetry.contract.records import ExecutionEventRecord
from agentkit.backend.telemetry.events import EventType

if TYPE_CHECKING:
    from collections.abc import Callable

    from agentkit.backend.control_plane.dispatch import PhaseDispatcher
    from agentkit.backend.control_plane.records import BackendInstanceIdentityRecord

logger = logging.getLogger(__name__)

# OperatingMode (FK-56 §56.5 / §56.7a) is RE-IMPORTED from its canonical SSOT
# foundation definition ``core_types.operating_mode``: this runtime CLASSIFIES
# the mode (``_resolve_operating_mode``) but does NOT redeclare the type, so there
# is exactly one definition and no drift (AK2 SSOT). The named
# ``operating_mode_resolver`` A-core remains the SSOT accessor seam.
FreshnessClass = Literal["baseline_read", "guarded_read", "mutation"]

_SYNC_AFTER_BY_CLASS = {
    "baseline_read": timedelta(minutes=5),
    "guarded_read": timedelta(minutes=2),
    "mutation": timedelta(seconds=45),
}

#: AG3-138: terminal statuses whose stored result ``GET operations/{op_id}``
#: surfaces VERBATIM (not rewritten to ``replayed``) so a client reconciling an
#: unclear mutation sees the true ``aborted`` / ``repair`` / ``failed`` outcome
#: an admin-abort or startup reconciliation produced (FK-91 §91.1a Regel 17).
_RECONCILE_PRESERVED_STATUSES = frozenset({"aborted", "repair", "failed"})


class OperationNotFoundError(LookupError):
    """Raised when an ``admin_abort`` target ``op_id`` does not exist (HTTP 404)."""

    def __init__(self, op_id: str) -> None:
        super().__init__(op_id)
        self.op_id = op_id


class OperationNotAbortableError(RuntimeError):
    """Raised when an ``admin_abort`` target is not a live claim (HTTP 409).

    The operation exists but is not currently ``claimed`` -- it is already
    terminal (committed / rejected / aborted / repair / failed / replayed) or was
    resolved concurrently between the load and the abort CAS. Fail-closed: an
    already-resolved operation is not re-aborted (no second terminal write).
    """

    def __init__(self, op_id: str, current_status: str) -> None:
        super().__init__(
            f"operation {op_id!r} is not an abortable in-flight claim "
            f"(current status: {current_status!r})",
        )
        self.op_id = op_id
        self.current_status = current_status


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
    """Outcome of the owner-scoped claim acquisition (AG3-054; AG3-139).

    Exactly one shape is valid:

    * ``won=True`` -- this caller holds the claim (a fresh insert) and proceeds
      to dispatch; ``result`` is ``None`` and ``claimed_at_raw`` is the RAW claim
      instant this caller stamped.
    * ``won=False`` -- this caller LOST; ``result`` is the fail-closed outcome to
      return (a terminal REPLAY, or an "operation in flight, retry" rejection for
      a foreign claim of ANY age); ``claimed_at_raw`` is ``None``.

    AG3-139: there is no wall-clock expiry and no CAS takeover of a foreign claim
    -- ownership never ends by wall clock / TTL / lease (FK-91 §91.1a Regel 16).
    An orphaned claim is ended ONLY via the AG3-138 startup reconciliation or an
    explicit ``admin_abort_inflight_operation``.

    WARNING-4 fix (#4): ``claimed_at_raw`` is the EXACT claim instant (raw ISO
    TEXT) this caller wrote. It is threaded to finalize/release so their
    ownership CAS matches BOTH ``claimed_by`` AND ``claimed_at`` -- a stale owner
    whose token is reused (DI/test wiring) cannot match a NEWER claim generation.

    AG3-138: ``operation_epoch`` is the fencing token stamped on the claim at
    acquisition time (``_build_claim_placeholder``), threaded to finalize so its
    CAS additionally requires the stored epoch to be unchanged
    (``operation_finalize_requires_cas_on_operation_epoch``).
    """

    won: bool
    result: ControlPlaneMutationResult | None
    claimed_at_raw: str | None = None
    operation_epoch: int | None = None

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
            "'claimed' start claim; only its owner's finalize/release may ",
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


class _ClaimMixin:
    """AG3-054 owner-scoped claim protocol (extracted mixin).

    Cohesive owner-token mint + atomic claim + ownership-scoped release methods,
    split out of :class:`_ControlPlaneRuntimeAdmissionBase` for cohesion (no
    behaviour change). AG3-139 removed the wall-clock lease-expiry / CAS-takeover
    branch: a foreign in-flight claim of ANY age is rejected, never taken over --
    an orphaned claim ends only via the AG3-138 startup reconciliation or an
    explicit ``admin_abort_inflight_operation``. The concrete runtime supplies the
    shared dependencies below.
    """

    if TYPE_CHECKING:
        _repo: ControlPlaneRuntimeRepository
        _token_factory: Callable[[], str]
        _now_fn: Callable[[], datetime]

        def _current_instance_identity(self) -> BackendInstanceIdentityRecord: ...

    def _mint_owner_token(self) -> str:
        """Mint and VALIDATE the per-call owner token at the seam (AG3-054, #5).

        WARNING-5 fix (#5): ownership scoping (release / finalize CAS) is only
        sound if the owner token is UNIQUE and well-shaped. A DI-injected
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
            from agentkit.backend.exceptions import ConfigError

            raise ConfigError(
                "control-plane owner token is invalid: the owner-scoped "
                "claim (AG3-054) requires a non-empty, UUID-shaped owner token so "
                "release / finalize are ownership-scoped and cannot "
                "cross-match a different caller's claim. The configured "
                "token_factory yielded an empty or non-UUID-shaped token; "
                "fail-closed (#5).",
            )
        return token

    def _acquire_claim(
        self,
        request: PhaseMutationRequest,
        *,
        run_id: str,
        phase: str,
        owner_token: str,
        operation_kind: str = "phase_start",
    ) -> _ClaimOutcome:
        """Acquire the owner-scoped claim before dispatch (AG3-054, #1; AG3-139).

        Protocol:

        1. CLAIM = ``INSERT ... ON CONFLICT (op_id) DO NOTHING`` with the per-call
           ``owner_token``. rowcount==1 => WON.
        2. Lost the insert => load the blocking row:

           * gone (a concurrent release) => retry the atomic claim ONCE.
           * TERMINAL (``status != 'claimed'``) => return the stored result as a
             REPLAY (a winner already finished; never re-dispatch).
           * ``claimed`` (a foreign in-flight claim, of ANY age) => LOSER: a
             fail-closed "operation in flight, retry" rejection. DO NOT steal, DO
             NOT dispatch. AG3-139: there is no wall-clock expiry and no CAS
             takeover -- an orphaned claim ends ONLY via the AG3-138 startup
             reconciliation (same-instance restart) or an explicit
             ``admin_abort_inflight_operation`` (FK-91 §91.1a Regel 16:
             ownership never ends by wall clock / TTL / lease).

        Args:
            request: The phase mutation request (op_id + lookup keys).
            run_id: The story run identifier.
            phase: The requested phase name.
            owner_token: This caller's per-call owner token.

        Returns:
            A :class:`_ClaimOutcome` carrying either the won claim or the loser's
            fail-closed result.
        """
        now = self._now_fn()
        placeholder = _build_claim_placeholder(
            request,
            run_id=run_id,
            phase=phase,
            owner_token=owner_token,
            now=now,
            operation_kind=operation_kind,
            instance_identity=self._current_instance_identity(),
        )
        #: WARNING-4 fix (#4): the RAW claim instant this caller stamps. The writer
        #: stores ``claimed_at`` as ``isoformat`` TEXT, so this is the exact raw
        #: column value the finalize/release CAS must match (alongside the owner
        #: token) to scope to THIS claim generation.
        claim_instant_raw = now.isoformat()
        #: AG3-138: the fencing epoch THIS claim was stamped with (only an
        #: admin-abort bumps it; AG3-139 removed the same-instance TTL takeover
        #: that used to also carry this epoch forward unchanged).
        claim_operation_epoch = placeholder.operation_epoch
        if self._repo.claim_operation(placeholder):
            return _ClaimOutcome(
                won=True,
                result=None,
                claimed_at_raw=claim_instant_raw,
                operation_epoch=claim_operation_epoch,
            )
        stored = self._repo.load_operation(request.op_id)
        if stored is None:
            # The blocking row vanished between the failed claim and this read
            # (a concurrent release). Retry the atomic claim once.
            if self._repo.claim_operation(placeholder):
                return _ClaimOutcome(
                    won=True,
                    result=None,
                    claimed_at_raw=claim_instant_raw,
                    operation_epoch=claim_operation_epoch,
                )
            return _ClaimOutcome(won=False, result=self._in_flight_rejection(request, operation_kind=operation_kind))
        if stored.status != "claimed":
            # A terminal result already exists -- replay, never re-dispatch. AG3-140:
            # a reused op_id whose body-hash DIFFERS is a fail-closed
            # ``409 idempotency_mismatch`` (the raise propagates out of
            # ``_acquire_claim`` up through the entrypoint to the HTTP layer -- it is
            # NOT caught here). A matching (or legacy null) hash replays as before.
            return _ClaimOutcome(
                won=False,
                result=_replay_or_mismatch(
                    request, stored, operation_kind=operation_kind, phase=phase
                ),
            )
        # AG3-139: a foreign ``claimed`` row -- of ANY age -- is a LOSER. There is
        # no wall-clock expiry and no CAS takeover; an in-flight claim never ends
        # by wall clock / TTL / lease (FK-91 §91.1a Regel 16). An orphaned claim
        # is ended ONLY via the AG3-138 startup reconciliation (same-instance
        # restart) or an explicit ``admin_abort_inflight_operation``.
        return _ClaimOutcome(won=False, result=self._in_flight_rejection(request, operation_kind=operation_kind))

    def _in_flight_rejection(
        self,
        request: PhaseMutationRequest,
        *,
        operation_kind: str = "phase_start",
    ) -> ControlPlaneMutationResult:
        """Build the fail-closed "operation in flight, retry" loser rejection.

        Returned when a foreign claim (of ANY age) holds the op_id (AG3-139: no
        wall-clock expiry, no CAS takeover). The loser NEVER steals and NEVER
        dispatches; it surfaces a ``rejected`` retry-now result (no fabricated
        bundle, no second dispatch). A retry then either replays the committed
        terminal result once the winner finalizes, or -- once the claim is ended
        via the AG3-138 startup reconciliation or an explicit
        ``admin_abort_inflight_operation`` -- reclaims a now-released op_id.
        """
        return _rejection_result(
            op_id=request.op_id,
            operation_kind=operation_kind,
            run_id=None,
            phase=None,
            reason=(
                "Operation in flight: another caller holds an active claim for "
                "this op_id and is mid-dispatch. The dispatch runs EXACTLY ONCE "
                "under the winning caller; retry to read the committed result "
                "(AG3-054 owner-scoped claim, no double dispatch)."
            ),
        )

    def _release_my_claim(
        self, op_id: str, owner_token: str, owner_claimed_at: str | None
    ) -> None:
        """Ownership-scoped release of MY claim (never a foreign / terminal row).

        WARNING-4 fix (#4): the release CAS matches BOTH the owner token AND MY
        claim instant (``owner_claimed_at``), so a stale generation (a reused token
        in DI/test wiring) cannot delete a NEWER claim generation.
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
        propagates (NO ERROR BYPASSING). The CAS is claim-instant-scoped (#4).
        """
        try:
            self._repo.release_operation(
                op_id, owner_token=owner_token, owner_claimed_at=owner_claimed_at
            )
        except Exception:  # noqa: BLE001 -- never mask the original error
            logger.warning(
                "control-plane claim release failed for op_id=%s (original error "
                "is re-raised; the orphaned claim remains until the AG3-138 "
                "startup reconciliation or an explicit "
                "admin_abort_inflight_operation ends it -- AG3-139, no wall-clock "
                "expiry)",
                op_id,
            )


class _ControlPlaneRuntimeAdmissionBase(_ClaimMixin):
    """Start-phase admission and dispatch support for the runtime service."""

    def __init__(
        self,
        *,
        repository: ControlPlaneRuntimeRepository | None = None,
        phase_dispatcher: PhaseDispatcher | None = None,
        now_fn: Callable[[], datetime] | None = None,
        token_factory: Callable[[], str] | None = None,
        instance_identity: BackendInstanceIdentityRecord | None = None,
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
        #: AG3-054 claim timestamp seams (deterministic-injectable). ``now_fn``
        #: stamps claim/audit instants (``claimed_at``, operation-record
        #: timestamps) and ``token_factory`` mints the per-call owner token; both
        #: default to the productive UTC clock / uuid but are injectable so the
        #: claim protocol is deterministically testable. AG3-139: ``now_fn`` is no
        #: longer consulted for any wall-clock expiry decision -- a claim's age is
        #: never interpreted to end it.
        self._now_fn: Callable[[], datetime] = now_fn or (lambda: datetime.now(tz=UTC))
        self._token_factory: Callable[[], str] = token_factory or (
            lambda: f"owner-{uuid.uuid4().hex}"
        )
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
        existing = self._load_existing_operation(
            request, operation_kind="phase_start", phase=phase
        )
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
        claim = self._acquire_claim(
            request, run_id=run_id, phase=phase, owner_token=owner_token
        )
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
                owner_operation_epoch=owner_operation_epoch,
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
            #: release MY claim (#1) -- ownership-scoped, so a foreign claim's row
            #: is never touched. The release failure must not mask the original
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
        if (
            dispatch_result is None
            and phase != PhaseName.SETUP.value
            and not run_admitted
        ):
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
        return _StartPhaseOutcome(rejection=None, dispatch_result=dispatch_result)

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
            request_body_hash=_control_plane_request_body_hash(
                request, operation_kind="phase_start", phase=phase
            ),
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
        ):
            return result
        #: Lost the ownership CAS: a concurrent finalize/admin-abort already
        #: applied AND the side effects were rolled back (NO loser double-write).
        #: Replay the winner's terminal row; NEVER overwrite it (or, in the narrow
        #: window where it is not yet readable, surface the in-flight retry
        #: rejection).
        existing = self._load_existing_operation(
            request, operation_kind="phase_start", phase=phase
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
    ) -> _StartPhaseMaterialization:
        """Build (NO writes) the start_phase side effects + bundle (ERROR-1, #1).

        Standard/exploration runs plan the full binding/locks/events; an
        authoritatively-resolved fast story plans the bundle only (no side effects).
        The plan is applied atomically under the ownership CAS by the caller.
        """
        now = self._now_fn()
        if self._story_scoped_materialization_enabled(request):
            return _plan_story_scoped_materialization(
                run_id=run_id,
                phase=phase,
                request=request,
                now=now,
                previous_binding_version=self._current_binding_version(
                    request.session_id
                ),
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
        is absent -- the idempotent persistence still commits, but no phase is
        dispatched (a missing context is surfaced by the dispatcher's own
        fail-closed path on the next resolvable call).

        AG3-054 ERROR-1: the fresh-setup / first-call ADMISSION decision is computed
        RUN-scoped HERE (``_run_admission_evidence`` for THIS exact ``(project,
        story, run_id)``) and threaded into the dispatcher as ``run_admitted``. The
        dispatcher no longer derives "fresh" from story-scoped phase-state, so an
        OLD run's phase-state for the SAME story (after ``reset-escalation``, which
        mints a new run id but reuses the per-story story_dir) can never make a NEW,
        un-admitted run "not fresh" and SKIP the fail-closed pre-start guard.

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
        run_admitted = self._run_admission_evidence(
            project_key=request.project_key,
            story_id=request.story_id,
            session_id=request.session_id,
            run_id=run_id,
        )
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
        existing = self._load_existing_operation(
            request, operation_kind=operation_kind, phase=phase
        )
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
            #: claim. The store refused to clobber it (only the owner's
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
        if self._repo.has_committed_story_exit_operation_for_run(
            project_key, story_id, run_id
        ):
            return False
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
        request: PhaseMutationRequest | ClosureCompleteRequest,
        *,
        operation_kind: str,
        phase: str | None,
    ) -> ControlPlaneMutationResult | None:
        del request, operation_kind, phase
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


class _AdminTransitionMixin:
    """AG3-138 ``admin_transition`` abort + repair-resolve service methods (mixin).

    Cohesive admin-abort / partial-write-repair / repair-resolve logic, split out of
    :class:`ControlPlaneRuntimeService` for cohesion (no behaviour change). The
    concrete runtime supplies the shared dependencies below.
    """

    if TYPE_CHECKING:
        _repo: ControlPlaneRuntimeRepository
        _now_fn: Callable[[], datetime]

        def _require_postgres_backend_on_first_use(self) -> None: ...

    def admin_abort_inflight_operation(
        self,
        op_id: str,
        request: AdminAbortRequest,
    ) -> ControlPlaneMutationResult:
        """Administratively abort a hanging server-owned in-flight operation (AG3-138).

        FK-91 §91.1a ``admin_abort_inflight_operation`` (FK-55 §55.5
        ``admin_transition``): the explicit manual end-way for an in-flight claim
        beside the same-instance startup reconciliation, AND the productive exit from
        the ``repair`` mutation lock (NO ERROR BYPASSING -- no back door that just
        "frees" claims or "clears" the lock). Acts on the two admin-actionable
        (non-closed) states:

        * a currently-``claimed`` operation (a server-owned in-flight claim) is
          CAS-aborted: it bumps ``operation_epoch`` so a late, physically-still-
          running executor's finalize fails the epoch fence deterministically -- at
          most a no-op abort note, never a second result or a silent state change
          (AC4/AC6; ``operation_finalize_requires_cas_on_operation_epoch``) -- and
          routes a partial write (already-persisted ``phase_states``/
          ``flow_executions``) into the explicit, auditable ``repair`` state instead
          of silently ``failed`` (IMPL-005), which then story-scoped mutation-locks
          the run (AC10);
        * an open ``repair`` operation is CAS-resolved to ``resolved``, lifting the
          story-scoped mutation lock so mutating operations are re-admitted (AC10).
          This is the productive end-way out of ``repair``, so even an
          over-conservative repair (see the partial-write detector) can never be a
          permanent story deadlock.

        Both transitions are fully audited: the actor (``session_id`` /
        ``principal_type``) and the mandatory ``reason`` are persisted on the terminal
        operation record (visible via ``GET operations/{op_id}``).

        Args:
            op_id: The target operation id (URL path segment).
            request: The audited admin-abort request (actor + reason).

        Returns:
            The terminal :class:`ControlPlaneMutationResult`: for a ``claimed``
            target ``aborted`` (no partial writes) or ``repair`` (partial writes
            detected); for a ``repair`` target ``resolved``. An unknown op is 404; a
            target in a truly closed terminal status (or resolved concurrently) is a
            fail-closed 409.

        Raises:
            OperationNotFoundError: When ``op_id`` does not exist (HTTP 404).
            OperationNotAbortableError: When the operation is neither ``claimed`` nor
                ``repair`` (already closed terminal, HTTP 409), or was resolved
                concurrently between the load and the CAS.
        """
        self._require_postgres_backend_on_first_use()
        record = self._repo.load_operation(op_id)
        if record is None:
            raise OperationNotFoundError(op_id)
        if record.status == "claimed":
            return self._abort_claimed_operation(record, request)
        if record.status == "repair":
            #: AC10 productive end-way: admin-abort of an OPEN ``repair`` state closes
            #: it out to ``resolved``, lifting the story-scoped mutation lock. This is
            #: the one manual exit from ``repair`` (NO ERROR BYPASSING -- no back door
            #: that just clears the lock); ``repair`` is not a closed terminal but an
            #: open, admin-actionable handling state.
            return self._resolve_repair_operation(record, request)
        #: Any truly closed terminal status (committed/aborted/failed/resolved/...) is
        #: not abortable (AC6, 409).
        raise OperationNotAbortableError(op_id, record.status)

    def _abort_claimed_operation(
        self,
        record: ControlPlaneOperationRecord,
        request: AdminAbortRequest,
    ) -> ControlPlaneMutationResult:
        """CAS-abort a currently-``claimed`` operation (AC6, partial write -> repair)."""
        status, admin_note = self._resolve_abort_terminal_status(record, request)
        result = ControlPlaneMutationResult(
            status=status,
            op_id=record.op_id,
            operation_kind=record.operation_kind,
            run_id=record.run_id,
            phase=record.phase,
            edge_bundle=None,
            phase_dispatch=None,
            admin_note=admin_note,
        )
        applied = self._repo.admin_abort_operation(
            op_id=record.op_id,
            status=status,
            response_payload=result.model_dump(mode="json"),
            now=self._now_fn(),
        )
        if not applied:
            #: The claim was concurrently resolved (finalized/aborted) between the
            #: load and the CAS. Fail-closed: it is no longer an abortable
            #: in-flight claim (AC6, 409). NO second/duplicate terminal write.
            raise OperationNotAbortableError(record.op_id, "resolved_concurrently")
        return result

    def _resolve_repair_operation(
        self,
        record: ControlPlaneOperationRecord,
        request: AdminAbortRequest,
    ) -> ControlPlaneMutationResult:
        """CAS-resolve an open ``repair`` operation to ``resolved`` (AC10 lock exit)."""
        actor = f"session={request.session_id!r} principal={request.principal_type!r}"
        admin_note = (
            f"repair resolved by {actor}: reason={request.reason!r}. The open "
            "reconcile/repair state was administratively closed out to 'resolved'; "
            "the story-scoped mutation lock is lifted and mutating operations are "
            "re-admitted (AC10). op-class admin_transition (FK-55 §55.5)."
        )
        result = ControlPlaneMutationResult(
            status="resolved",
            op_id=record.op_id,
            operation_kind=record.operation_kind,
            run_id=record.run_id,
            phase=record.phase,
            edge_bundle=None,
            phase_dispatch=None,
            admin_note=admin_note,
        )
        applied = self._repo.resolve_repair_operation(
            op_id=record.op_id,
            response_payload=result.model_dump(mode="json"),
            now=self._now_fn(),
        )
        if not applied:
            #: The repair row moved off ``repair`` (resolved concurrently) between the
            #: load and the CAS. Fail-closed: no second/duplicate resolve (AC6, 409).
            raise OperationNotAbortableError(record.op_id, "resolved_concurrently")
        return result

    def _resolve_abort_terminal_status(
        self,
        record: ControlPlaneOperationRecord,
        request: AdminAbortRequest,
    ) -> tuple[Literal["aborted", "repair"], str]:
        """Decide ``aborted`` vs ``repair`` for an admin-abort target (IMPL-005)."""
        since = record.claimed_at or record.created_at
        has_writes = self._repo.has_engine_writes_since(record.story_id, since)
        actor = f"session={request.session_id!r} principal={request.principal_type!r}"
        if has_writes:
            return (
                "repair",
                f"admin_abort_inflight_operation by {actor}: reason="
                f"{request.reason!r}. The aborted operation had already persisted "
                "engine writes (phase_states/flow_executions); entering an "
                "explicit, auditable reconcile/repair state instead of silently "
                "'failed' (IMPL-005). The story is mutation-locked until the state "
                "is resolved via repair (AC10).",
            )
        return (
            "aborted",
            f"admin_abort_inflight_operation by {actor}: reason={request.reason!r}. "
            "No persisted engine writes detected; the in-flight claim is aborted "
            "and its operation_epoch bumped so a late executor's finalize fails "
            "the fence deterministically (AC4).",
        )


class ControlPlaneRuntimeService(_AdminTransitionMixin, _ControlPlaneRuntimeAdmissionBase):
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
        existing = self._load_existing_operation(
            request, operation_kind="closure_complete", phase="closure"
        )
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
            #: claim; the store refused to clobber it. A closure reusing a live
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
        existing = self._load_existing_operation(
            request, operation_kind="phase_resume", phase=phase
        )
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
        if not self._run_was_admitted(request, run_id=run_id):
            return _rejection_result(
                op_id=request.op_id,
                operation_kind="phase_resume",
                run_id=run_id,
                phase=phase,
                reason=(
                    "phase_resume rejected: the run has no prior admitted start "
                    "(no committed setup phase_start and no session binding for "
                    "THIS project/story/run); fail-closed -- a resume must not "
                    "materialize story-scoped state for an unadmitted run "
                    "(FK-20 §20.8.2)."
                ),
                dispatch_phase=phase,
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
            #: Drive the deterministic dispatcher: with the persisted phase-state
            #: PAUSED for this phase it derives a resume (not a fresh start) and
            #: runs ``PipelineEngine.resume_phase`` with the trigger from
            #: ``request.detail`` -- now protected by the claim.
            dispatch_result = self._dispatch_phase(
                run_id=run_id, phase=phase, request=request
            )
            rejection = self._resume_rejection_if_unsuccessful(
                dispatch_result, run_id=run_id, phase=phase, request=request
            )
            if rejection is not None:
                #: AG3-130 (Codex M3): a resume that did NOT advance/re-pause the
                #: phase (absent ctx, not-PAUSED, invalid trigger -> EngineResult
                #: failed with ``dispatched=True``, or a failed/escalated resume)
                #: must NOT commit an operation or materialize a binding/lock/
                #: SESSION_RUN_BINDING_CREATED. Release MY claim and return the
                #: NON-stored rejection (the engine's own phase-state, if any,
                #: stands). A retry then re-evaluates.
                self._release_my_claim(
                    request.op_id, owner_token, owner_claimed_at
                )
                return rejection
            result = self._finalize_resume_phase(
                run_id=run_id,
                phase=phase,
                request=request,
                owner_token=owner_token,
                owner_claimed_at=owner_claimed_at,
                owner_operation_epoch=owner_operation_epoch,
                phase_dispatch=dispatch_result,
            )
            finalized = True
            return result
        except ControlPlaneBindingCollisionError as exc:
            #: AG3-054 run-scoping: the binding SAVE would overwrite a live binding
            #: belonging to a DIFFERENT run that rebound the same session. The store
            #: refused fail-closed and the WHOLE transaction rolled back -- a resume
            #: for an old run must never clobber a foreign run's live binding.
            self._release_my_claim_best_effort(
                request.op_id, owner_token, owner_claimed_at
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
            #: Any error before the terminal finalize MUST release MY claim (best
            #: effort, never masking the original error) so the op_id is not
            #: stranded (NO ERROR BYPASSING).
            if not finalized:
                self._release_my_claim_best_effort(
                    request.op_id, owner_token, owner_claimed_at
                )
            raise

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
            request_body_hash=_control_plane_request_body_hash(
                request, operation_kind="phase_resume", phase=phase
            ),
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
        ):
            return result
        existing = self._load_existing_operation(
            request, operation_kind="phase_resume", phase=phase
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
            return _build_fast_edge_bundle(
                project_key=request.project_key, sync_class="mutation", now=now
            )
        lock = self._repo.load_lock(
            binding.project_key, binding.story_id, binding.run_id, "story_execution"
        )
        if lock is None:
            return _build_fast_edge_bundle(
                project_key=request.project_key, sync_class="mutation", now=now
            )
        qa_lock = self._repo.load_lock(
            binding.project_key, binding.story_id, binding.run_id, "qa_artifact_write"
        )
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
            binding.binding_version
            if binding is not None
            else _next_binding_version(None)
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
            request_body_hash=_control_plane_request_body_hash(
                request, operation_kind="closure_complete", phase="closure"
            ),
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
                binding_version=_next_binding_version(
                    binding.binding_version if binding is not None else None
                ),
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
        #: AG3-138 (AC5, FK-91 §91.1a Regel 17): ``_replayed_result`` surfaces an
        #: ``aborted`` / ``repair`` / ``failed`` terminal state VERBATIM (a
        #: visible, auditable reconcile/repair state, SEVERITY-SEMANTIK) and
        #: only echoes the ordinary success statuses as ``replayed``.
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
        existing = self._load_existing_operation(
            request, operation_kind=operation_kind, phase=phase
        )
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
                run_id=run_id,
                phase=phase,
                request=request,
                now=now,
                previous_binding_version=self._current_binding_version(
                    request.session_id
                ),
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
            request_body_hash=_control_plane_request_body_hash(
                request, operation_kind=operation_kind, phase=phase
            ),
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
        request: PhaseMutationRequest | ClosureCompleteRequest,
        *,
        operation_kind: str,
        phase: str | None,
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
            request, existing, operation_kind=operation_kind, phase=phase
        )


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
        request_body_hash=_control_plane_request_body_hash(
            request, operation_kind="closure_complete", phase="closure"
        ),
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
    previous_binding_version: str | None,
) -> _StartPhaseMaterialization:
    """Build (NO writes) the full story-scoped binding + locks + events (#1).

    Pure record construction for a standard/exploration run: the records and the
    edge bundle are built but NOT persisted, so the claimed start_phase finalize can
    write them atomically under the ownership CAS (ERROR-1). The complete/fail
    commit (``_mutate_phase``) reuses this planner too, applying the records under
    the atomic collision-gated commit (ERROR-2).

    Args:
        previous_binding_version: The session's currently persisted
            ``binding_version`` (read at the persistence boundary by the caller),
            or ``None`` when the session has no binding yet. The next version is
            derived DB-monotone from it (``+ 1``), not from a wall clock.
    """
    binding_version = _next_binding_version(previous_binding_version)
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


def _control_plane_request_body_hash(
    request: PhaseMutationRequest | ClosureCompleteRequest,
    *,
    operation_kind: str,
    phase: str | None,
) -> str:
    """Canonical body-hash of a phase/closure request (AG3-140, FK-91 §91.1a Regel 5).

    SHA-256 of the canonical request body (``op_id`` excluded by
    :func:`compute_body_hash`). ``operation_kind`` and ``phase`` are folded in so a
    reused ``op_id`` that carries the SAME :class:`PhaseMutationRequest` for a
    DIFFERENT action (start vs complete vs fail vs resume) or a DIFFERENT phase
    hashes differently -- a claim/terminal write stamps this and a claim-loser /
    replay compares it (hash match -> replay; hash differs -> ``409
    idempotency_mismatch``).

    The ``operation_kind`` + ``phase`` fed here on the CLAIM / terminal WRITE for a
    given entrypoint MUST equal the ones fed on its REPLAY check, otherwise a
    legitimate replay would false-mismatch (see the per-entrypoint call sites).

    Args:
        request: The phase or closure mutation request.
        operation_kind: The operation kind of THIS entrypoint (``phase_start`` /
            ``phase_complete`` / ``phase_fail`` / ``phase_resume`` /
            ``closure_complete``).
        phase: The requested phase (``None``/``""`` for a closure carries the same
            ``"closure"`` value at every site).

    Returns:
        A lowercase hex SHA-256 digest string.
    """
    from agentkit.backend.state_backend.store.inflight_idempotency_guard import (
        compute_body_hash,
    )

    payload = dict(request.model_dump(mode="json"))
    #: Distinguish start/complete/fail/resume reusing the SAME PhaseMutationRequest,
    #: and setup vs closure vs any other phase, under one op_id.
    payload["__operation_kind"] = operation_kind
    payload["__phase"] = phase or ""
    #: ``compute_body_hash`` excludes the ``op_id`` key -> a pure function of the
    #: mutation data (a replay of the same mutation hashes equal).
    return compute_body_hash(payload)


def _replay_or_mismatch(
    request: PhaseMutationRequest | ClosureCompleteRequest,
    stored: ControlPlaneOperationRecord,
    *,
    operation_kind: str,
    phase: str | None,
) -> ControlPlaneMutationResult:
    """Replay a terminal row, or fail closed with ``409 idempotency_mismatch`` (AG3-140).

    A claim-loser / replay classifies a stored TERMINAL row by comparing the
    incoming request's body-hash against the one stamped on the row:

    * hash MATCHES -> a legitimate replay of the SAME mutation: return the stored
      result (``_replayed_result``).
    * hash DIFFERS -> the ``op_id`` is being reused for a DIFFERENT phase/action/
      body: fail closed with :class:`IdempotencyMismatchError` (mapped to HTTP
      ``409 idempotency_mismatch`` at the adapter, FK-91 §91.1a Regel 5).

    Fail-closed note: a ``None`` stored hash is a legacy / pre-AG3-140 row that was
    written before the body-hash was populated on this path -- it falls back to
    op_id-only replay (NEVER raises on a null stored hash), so an in-flight rollout
    can never turn an honest replay into a spurious mismatch.

    Args:
        request: The incoming phase or closure mutation request.
        stored: The stored TERMINAL operation record.
        operation_kind: This entrypoint's operation kind (MUST match the write).
        phase: This entrypoint's phase (MUST match the write).

    Returns:
        The stored result as a ``replayed`` (or verbatim reconcile-preserved)
        result on a hash match / legacy null hash.

    Raises:
        IdempotencyMismatchError: When the stored row carries a body-hash that
            differs from the incoming request's (409 idempotency_mismatch).
    """
    stored_hash = stored.request_body_hash
    if stored_hash is not None:
        incoming = _control_plane_request_body_hash(
            request, operation_kind=operation_kind, phase=phase
        )
        if incoming != stored_hash:
            from agentkit.backend.story_context_manager.errors import (
                IdempotencyMismatchError,
            )

            raise IdempotencyMismatchError(
                f"op_id {request.op_id!r} was previously used with a different "
                "request body; use a new op_id for a different mutation",
                detail={"op_id": request.op_id, "conflict": "body_hash_mismatch"},
            )
    return _replayed_result(stored.response_payload)


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
    request_body_hash: str | None = None,
) -> ControlPlaneOperationRecord:
    """Build the terminal operation record (no live claim -- a terminal row).

    AG3-140: ``request_body_hash`` is the canonical body-hash of the originating
    request (op_id excluded), stamped so a later replay of the SAME op_id can
    distinguish a legitimate replay (hash match) from a ``409 idempotency_mismatch``
    (hash differs). Fed by :func:`_control_plane_request_body_hash` at every call
    site with THAT site's ``operation_kind`` + ``phase`` (consistent with its
    replay check).
    """
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
        request_body_hash=request_body_hash,
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
    from agentkit.backend.exceptions import ConfigError
    from agentkit.backend.state_backend.store import control_plane_backend_available

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


def _default_di_instance_identity() -> BackendInstanceIdentityRecord:
    """Build the deterministic DI-seam backend instance identity (AG3-138).

    Bound automatically when a repository is DI-injected without an explicit
    identity (test / alternative wiring). A stable, well-formed value keeps the
    claim stamp and the ownership fencing sound; it is NEVER used on the
    productive default-store path (which requires the startup hook).
    """
    from agentkit.backend.control_plane.records import BackendInstanceIdentityRecord

    return BackendInstanceIdentityRecord(
        backend_instance_id="di-wiring-instance",
        instance_incarnation=1,
        updated_at=datetime.now(tz=UTC),
    )


def _build_claim_placeholder(
    request: PhaseMutationRequest,
    *,
    run_id: str,
    phase: str,
    owner_token: str,
    now: datetime,
    instance_identity: BackendInstanceIdentityRecord,
    operation_kind: str = "phase_start",
) -> ControlPlaneOperationRecord:
    """Build the in-flight ``claimed`` placeholder op record (AG3-054).

    The ``claimed`` status marks an in-flight reservation, distinct from the
    terminal ``committed`` / ``rejected`` the winning caller writes next; its
    ``response_payload`` is empty (not a replayable result). ``claimed_by`` is the
    per-call owner token and ``claimed_at`` is the claim instant -- an audit
    instant only (AG3-139: its age is never interpreted to end the claim); the
    ownership-scoped finalize/release CAS keys off this exact value (WARNING-4).

    AG3-130: ``operation_kind`` parametrizes the claim reservation so ``resume``
    reserves its op_id under ``phase_resume`` through the SAME claim-before-dispatch
    protocol as ``start`` (no double-resume: the side-effecting engine resume runs
    only after the reservation).

    AG3-138 (``inflight-operation-record``, FK-91 §91.1a rules 13/16): every
    freshly-acquired claim is stamped with the CALLING instance's identity
    (``backend_instance_id`` + ``instance_incarnation``), an initial fencing
    ``operation_epoch`` (bumped only by an explicit admin-abort, never by wall
    clock) and its ``declared_serialization_scope`` (the default
    ``(project_key, story_id)`` object-serialization scope, Regel 13).
    """
    return ControlPlaneOperationRecord(
        op_id=request.op_id,
        project_key=request.project_key,
        story_id=request.story_id,
        run_id=run_id,
        session_id=request.session_id,
        operation_kind=operation_kind,
        phase=phase,
        status="claimed",
        response_payload={},
        created_at=now,
        updated_at=now,
        claimed_by=owner_token,
        claimed_at=now,
        operation_epoch=INITIAL_OPERATION_EPOCH,
        backend_instance_id=instance_identity.backend_instance_id,
        instance_incarnation=instance_identity.instance_incarnation,
        declared_serialization_scope=f"{request.project_key}:{request.story_id}",
        #: AG3-140: stamp the canonical body-hash on the claim so a claim-loser
        #: (``_acquire_claim`` terminal-replay branch) can classify a reused op_id
        #: as a legitimate replay (hash match) vs ``409 idempotency_mismatch`` (hash
        #: differs). Fed with THIS claim's operation_kind + phase, identical to the
        #: terminal-write/replay pair of the same entrypoint (no false-mismatch).
        request_body_hash=_control_plane_request_body_hash(
            request, operation_kind=operation_kind, phase=phase
        ),
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
    only for a non-materializing status) is re-enforced on every replay: a
    tampered stored payload that violates it raises at the boundary instead of
    silently passing.

    AG3-138: an ``aborted`` / ``repair`` / ``failed`` terminal result (which
    carries NO ``edge_bundle``) is surfaced VERBATIM -- rewriting its status to
    ``replayed`` would both hide the true terminal state from an idempotent
    retry AND violate the model invariant (``replayed`` requires an
    ``edge_bundle``). Only the ordinary success statuses are echoed as
    ``replayed``.

    Args:
        stored_payload: The JSON payload of the persisted operation.

    Returns:
        A validated :class:`ControlPlaneMutationResult`: verbatim for a
        preserved terminal status, else a ``replayed`` echo.
    """
    stored_status = stored_payload.get("status")
    if stored_status in _RECONCILE_PRESERVED_STATUSES:
        return ControlPlaneMutationResult.model_validate(stored_payload)
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


def _next_binding_version(previous_version: str | None) -> str:
    """Mint the next binding version (FK-17 §17.3a.16: monotone Integer >= 1).

    DB-monotone, process-independent (CAS-capable, FK-56 §56.13a): the value is
    derived from the affected binding's PREVIOUSLY PERSISTED version (``previous
    + 1``), or the initial :data:`MIN_BINDING_VERSION` when no binding exists
    yet. There is deliberately NO wall clock and NO process-local counter — the
    former ``bind-<uuid4>`` token was non-monotone, and a clock-derived token
    both leaks a wall-clock dependency into ownership/takeover challenge material
    and is only process-local monotone, neither of which is a sound CAS
    foundation.

    The caller reads ``previous_version`` from the store at the persistence
    boundary of the SAME mutation whose atomic commit (ownership CAS at
    start-phase finalize / run-scoped binding upsert) serialises the write, so no
    NEW fencing/lock is introduced (AG3-137 is a pure value-domain change; the
    fence lives in AG3-142).

    Representation note (AG3-137 scope §5): the returned value is a canonical
    decimal ``str`` because it flows verbatim into the derived
    ``StoryExecutionLockRecord`` / edge-bundle projections whose column lives in
    ``sqlite_store`` (K5: not migrated here); a literal numeric-column migration
    is deferred to AG3-142. Only the value DOMAIN is a monotone positive integer.

    Args:
        previous_version: The affected binding's currently persisted
            ``binding_version`` (a canonical integer string), or ``None`` when no
            binding exists yet for the target session.

    Returns:
        The next canonical decimal version string.
    """
    if previous_version is None:
        return str(MIN_BINDING_VERSION)
    return str(int(previous_version) + 1)
