"""Owner-scoped operation and object-mutation claim lifecycle."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from agentkit.backend.control_plane import (
    object_claims,
)

# Deliberate RUNTIME re-import (not TYPE_CHECKING): this is the SSOT re-import of
# the canonical FK-56 operating-mode literal from its SINGLE foundation definition
# (``core_types.operating_mode``). It must be a runtime binding so the
# single-definition identity holds for consumers (and is assertable) -- moving it
# into a type-checking block would make ``control_plane.runtime.OperatingMode`` a
# different/absent object at runtime, defeating the AK2 SSOT consolidation.
from ._models import _ClaimOutcome, _is_valid_owner_token
from ._operation_records import _build_claim_placeholder, _rejection_result, _replay_or_mismatch

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from agentkit.backend.control_plane.models import (
        ControlPlaneMutationResult,
        PhaseMutationRequest,
    )
    from agentkit.backend.control_plane.records import BackendInstanceIdentityRecord
    from agentkit.backend.control_plane.repository import (
        ControlPlaneRuntimeRepository,
        ObjectMutationClaimRepository,
    )

logger = logging.getLogger(__name__)

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
        _object_claim_repo: ObjectMutationClaimRepository

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
             ``admin_abort_inflight_operation`` (FK-91 §91.1a Rule 16:
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
                result=_replay_or_mismatch(request, stored, operation_kind=operation_kind, phase=phase),
            )
        # AG3-139: a foreign ``claimed`` row -- of ANY age -- is a LOSER. There is
        # no wall-clock expiry and no CAS takeover; an in-flight claim never ends
        # by wall clock / TTL / lease (FK-91 §91.1a Rule 16). An orphaned claim
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

    def _release_my_claim(self, op_id: str, owner_token: str, owner_claimed_at: str | None) -> None:
        """Ownership-scoped release of MY claim (never a foreign / terminal row).

        WARNING-4 fix (#4): the release CAS matches BOTH the owner token AND MY
        claim instant (``owner_claimed_at``), so a stale generation (a reused token
        in DI/test wiring) cannot delete a NEWER claim generation.
        """
        self._repo.release_operation(op_id, owner_token=owner_token, owner_claimed_at=owner_claimed_at)

    def _release_my_claim_best_effort(self, op_id: str, owner_token: str, owner_claimed_at: str | None) -> None:
        """Release MY claim without masking an in-flight original error (#1).

        Used on the exception path: a release failure must NOT replace the original
        exception (it is logged and swallowed), so the real error always
        propagates (NO ERROR BYPASSING). The CAS is claim-instant-scoped (#4).
        """
        try:
            self._repo.release_operation(op_id, owner_token=owner_token, owner_claimed_at=owner_claimed_at)
        except Exception:  # noqa: BLE001 -- never mask the original error
            logger.warning(
                "control-plane claim release failed for op_id=%s (original error "
                "is re-raised; the orphaned claim remains until the AG3-138 "
                "startup reconciliation or an explicit "
                "admin_abort_inflight_operation ends it -- AG3-139, no wall-clock "
                "expiry)",
                op_id,
            )

    def _acquire_object_claim(
        self,
        *,
        project_key: str,
        story_id: str,
        op_id: str,
    ) -> object_claims.ObjectClaimConflict | None:
        """Acquire the default per-story object-mutation claim BEFORE dispatch.

        SOLL-054/SOLL-048 (FK-91 §91.1a Rule 13; FK-10 §10.5.4): every
        mutating control-plane operation acquires a durable claim on its
        declared serialization object -- default ``(project_key, story_id)``
        -- BEFORE any dispatch/commit side effect and holds it until
        finalize/abort. Bound to the OBJECT, never the caller.

        Returns:
            ``None`` on success (the claim is held); an
            :class:`~agentkit.backend.control_plane.object_claims.ObjectClaimConflict`
            when the object is busy -- the caller surfaces the K4
            deterministic 409 + Retry-After (IMPL-016) and stores NO
            operation for this attempt (a retry re-evaluates from scratch).
        """
        key = object_claims.story_claim_key(project_key, story_id)
        identity = self._current_instance_identity()
        return object_claims.acquire_story_claim(
            self._object_claim_repo,
            key,
            op_id=op_id,
            backend_instance_id=identity.backend_instance_id,
            instance_incarnation=identity.instance_incarnation,
            now=self._now_fn(),
        )

    def _release_claim_key(self, key: object_claims.ObjectClaimKey, *, op_id: str) -> None:
        """Release ONE object-mutation claim by its identity (ownership-scoped)."""
        self._object_claim_repo.release_claim(key.project_key, key.serialization_scope, key.scope_key, op_id)

    def _release_claim_key_best_effort(self, key: object_claims.ObjectClaimKey, *, op_id: str) -> None:
        """Release an object-mutation claim without masking an original error."""
        try:
            self._release_claim_key(key, op_id=op_id)
        except Exception:  # noqa: BLE001 -- never mask the original error
            logger.warning(
                "control-plane object-claim release failed for op_id=%s "
                "object=%s:%s (original error is re-raised; the orphaned "
                "claim remains until the AG3-138 startup reconciliation or an "
                "explicit admin_abort_inflight_operation ends it -- no "
                "wall-clock expiry)",
                op_id,
                key.serialization_scope,
                key.scope_key,
            )

    def _release_object_claim(self, *, project_key: str, story_id: str, op_id: str) -> None:
        """Release the default per-story object-mutation claim (finalize/abort)."""
        self._release_claim_key(object_claims.story_claim_key(project_key, story_id), op_id=op_id)

    def _release_object_claim_best_effort(self, *, project_key: str, story_id: str, op_id: str) -> None:
        """Release the per-story object claim without masking an original error."""
        self._release_claim_key_best_effort(object_claims.story_claim_key(project_key, story_id), op_id=op_id)
