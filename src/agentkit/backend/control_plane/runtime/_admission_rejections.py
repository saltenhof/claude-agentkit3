"""Admission rejection and repair-lock result builders."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from agentkit.backend.control_plane.ownership import (
    canonical_binding_revocation_reason,
)
from agentkit.backend.control_plane.ownership_fence import (
    ERROR_CODE_STORY_FROZEN,
    OwnershipAdmission,
    OwnershipRejectionReason,
)
from agentkit.backend.core_types.freeze import (
    FreezeKind,
    active_freeze_state_from_record,
    freeze_error_code,
)

from ._operation_records import (
    _ownership_transferred_rejection,
    _rejection_result,
)

if TYPE_CHECKING:
    from agentkit.backend.control_plane.models import (
        ControlPlaneMutationResult,
    )
    from agentkit.backend.control_plane.repository import ControlPlaneRuntimeRepository
    from agentkit.backend.exceptions import (
        OwnershipFenceViolationError,
    )

logger = logging.getLogger(__name__)


class _AdmissionRejectionMixin:
    """Build fail-closed admission and repair-lock rejection results."""

    if TYPE_CHECKING:
        _repo: ControlPlaneRuntimeRepository

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
            freeze_states = tuple(
                active_freeze_state_from_record(record)
                for record in self._repo.load_active_freezes(story_id)
            )
            contested = next(
                (
                    state
                    for state in freeze_states
                    if state.kind is FreezeKind.CONTESTED_LOCAL_WRITES
                ),
                None,
            )
            if contested is not None:
                from agentkit.backend.control_plane.models import FreezeConflictDetail

                result = _rejection_result(
                    op_id=op_id,
                    operation_kind=operation_kind,
                    run_id=run_id,
                    phase=phase,
                    reason=(
                        f"{operation_kind} rejected: contested local writes "
                        "freeze blocks mutation while ownership remains active."
                    ),
                    dispatch_phase=phase,
                    error_code="contested_local_writes",
                )
                return result.model_copy(
                    update={
                        "freeze_conflict": FreezeConflictDetail(
                            kind="contested_local_writes",
                            freeze_reason=contested.freeze_reason,
                            freeze_epoch=contested.freeze_epoch,
                            state_readable=contested.readable,
                        )
                    }
                )
            if not self._repo.has_unreconciled_takeover_for_story(project_key, story_id):
                return None
            result = _rejection_result(
                op_id=op_id,
                operation_kind=operation_kind,
                run_id=run_id,
                phase=phase,
                reason=(
                    f"{operation_kind} rejected: story {story_id!r} has an "
                    "unreconciled takeover transfer in the active ownership "
                    "epoch; no new mutating operation is admitted until the "
                    "takeover reconcile obligation is cleared (fail-closed, "
                    "FK-56 §56.13f)."
                ),
                dispatch_phase=phase,
            )
            return result.model_copy(update={"error_code": "takeover_reconcile_required"})
        result = _rejection_result(
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
        return result.model_copy(update={"error_code": "repair_lock_required"})

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
        session_id: str,
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
        if admission.rejection_reason is OwnershipRejectionReason.FREEZE_ACTIVE:
            from agentkit.backend.control_plane.models import FreezeConflictDetail

            freeze = admission.blocking_freeze
            assert freeze is not None  # noqa: S101 -- freeze rejection carries its state
            kind = freeze.kind.value if freeze.kind is not None else None
            result = _rejection_result(
                op_id=op_id,
                operation_kind=operation_kind,
                run_id=run_id,
                phase=phase,
                reason=(
                    f"{operation_kind} rejected: story freeze blocks mutation; "
                    f"kind={kind!r}, freeze_epoch={freeze.freeze_epoch!r}; "
                    "ownership remains active (FK-56 §56.13f, fail-closed)."
                ),
                error_code=freeze_error_code(freeze.kind),
            )
            return result.model_copy(
                update={
                    "freeze_conflict": FreezeConflictDetail(
                        kind=kind,
                        freeze_reason=freeze.freeze_reason,
                        freeze_epoch=freeze.freeze_epoch,
                        state_readable=freeze.readable,
                    )
                }
            )
        if admission.rejection_reason is not OwnershipRejectionReason.OWNERSHIP_TRANSFERRED:
            binding = self._repo.load_binding(session_id)
            if (
                binding is not None
                and binding.status == "revoked"
                and (run_id is None or binding.run_id == run_id)
            ):
                reason = (
                    canonical_binding_revocation_reason(binding.revocation_reason)
                    or "session_binding_mismatch"
                )
                return _rejection_result(
                    op_id=op_id,
                    operation_kind=operation_kind,
                    run_id=run_id,
                    phase=phase,
                    reason=(
                        f"{operation_kind} rejected: session disowned; reason={reason}; "
                        "new_owner_ref=none"
                    ),
                    error_code=reason,
                )
            return _rejection_result(
                op_id=op_id,
                operation_kind=operation_kind,
                run_id=run_id,
                phase=phase,
                reason=(
                    f"{operation_kind} rejected: no prior admitted start; the "
                    "active run-ownership record "
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
        if exc.detail.get("error_code") == ERROR_CODE_STORY_FROZEN:
            from agentkit.backend.control_plane.models import FreezeConflictDetail

            result = _rejection_result(
                op_id=op_id,
                operation_kind=operation_kind,
                run_id=run_id,
                phase=phase,
                reason=(
                    f"{operation_kind} rejected: a story freeze entered before "
                    "commit; no state was written (FK-56 §56.13f, no TOCTOU)."
                ),
                error_code=freeze_error_code(
                    _optional_str(exc.detail.get("freeze_kind"))
                ),
            )
            return result.model_copy(
                update={
                    "freeze_conflict": FreezeConflictDetail(
                        kind=_optional_str(exc.detail.get("freeze_kind")),
                        freeze_reason=_optional_str(exc.detail.get("freeze_reason")),
                        freeze_epoch=_optional_str(exc.detail.get("freeze_epoch")),
                        state_readable=bool(exc.detail.get("freeze_state_readable", True)),
                    )
                }
            )
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


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


__all__ = ["_AdmissionRejectionMixin"]
