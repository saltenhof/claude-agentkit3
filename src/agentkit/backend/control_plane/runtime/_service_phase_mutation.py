"""Control-plane runtime phase materialization responsibilities."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from agentkit.backend.control_plane.models import (
    ClosureCompleteRequest,
    ControlPlaneMutationResult,
    PhaseDispatchResult,
    PhaseMutationRequest,
)
from agentkit.backend.exceptions import (
    ControlPlaneBindingCollisionError,
    ControlPlaneClaimCollisionError,
    OwnershipFenceViolationError,
)
from agentkit.backend.governance.guard_system.story_scoped_guards import should_create_story_lock_records

from ._materialization import _plan_fast_materialization, _plan_story_scoped_materialization
from ._operation_records import (
    _control_plane_request_body_hash,
    _object_claim_busy_rejection,
    _operation_record,
    _replay_or_mismatch,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from agentkit.backend.control_plane import object_claims
    from agentkit.backend.control_plane.repository import ControlPlaneRuntimeRepository

    from ._models import (
        _ModeResolutionKeys,
    )

logger = logging.getLogger(__name__)


class _ControlPlanePhaseMutationMixin:
    """Commit phase mutations and resolve story-scoped materialization."""

    if TYPE_CHECKING:
        _repo: ControlPlaneRuntimeRepository
        _now_fn: Callable[[], datetime]

        def _acquire_object_claim(
            self, *, project_key: str, story_id: str, op_id: str
        ) -> object_claims.ObjectClaimConflict | None: ...

        def _release_object_claim(self, *, project_key: str, story_id: str, op_id: str) -> None: ...

        def _release_object_claim_best_effort(self, *, project_key: str, story_id: str, op_id: str) -> None: ...

        def _current_binding_version(self, session_id: str) -> str | None: ...

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


__all__ = ["_ControlPlanePhaseMutationMixin"]
