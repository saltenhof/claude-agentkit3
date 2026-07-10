"""Admission-gated complete/fail phase mutations."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from agentkit.backend.control_plane import (
    runtime_constants,
)
from agentkit.backend.control_plane.push_sync import (
    SyncPointBarrierType,
)
from agentkit.backend.exceptions import (
    ControlPlaneBindingCollisionError,
    ControlPlaneClaimCollisionError,
    OwnershipFenceViolationError,
)

from ._models import (
    _claimed_operation_rejection_reason,
    _phase_binding_collision_reason,
)
from ._operation_records import (
    _push_barrier_rejection,
    _rejection_result,
)

if TYPE_CHECKING:
    from agentkit.backend.control_plane.models import (
        ClosureCompleteRequest,
        ControlPlaneMutationResult,
        PhaseDispatchResult,
        PhaseMutationRequest,
    )
    from agentkit.backend.control_plane.ownership_fence import OwnershipAdmission
    from agentkit.backend.control_plane.push_sync import BarrierVerdict

logger = logging.getLogger(__name__)


class _AdmittedPhaseMutationMixin:
    """Complete/fail mutations that require an already admitted run."""

    if TYPE_CHECKING:

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

        def _push_barrier_block(
            self,
            barrier_type: SyncPointBarrierType,
            *,
            project_key: str,
            story_id: str,
            run_id: str,
            sync_point_id: str,
        ) -> BarrierVerdict | None: ...

        def _mutate_phase(
            self,
            *,
            run_id: str,
            phase: str,
            request: PhaseMutationRequest,
            operation_kind: str,
            expected_ownership_epoch: int,
            phase_dispatch: PhaseDispatchResult | None = None,
        ) -> ControlPlaneMutationResult: ...

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
        admission = self._run_was_admitted(
            request,
            run_id=run_id,
            command_id=operation_kind,
        )
        if not admission.admitted:
            return self._ownership_admission_rejection(
                admission,
                op_id=request.op_id,
                operation_kind=operation_kind,
                run_id=run_id,
                phase=phase,
                session_id=request.session_id,
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


__all__ = ["_AdmittedPhaseMutationMixin"]
