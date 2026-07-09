"""Start-phase admission, dispatch, and atomic finalization."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from ._admission_dispatch import _AdmissionDispatchMixin as _AdmissionDispatchMixin
from ._admission_identity import _AdmissionIdentityMixin as _AdmissionIdentityMixin
from ._admission_phase_mutation import (
    _AdmittedPhaseMutationMixin as _AdmittedPhaseMutationMixin,
)
from ._admission_rejections import _AdmissionRejectionMixin as _AdmissionRejectionMixin
from ._admission_start_phase import _StartPhaseAdmissionMixin as _StartPhaseAdmissionMixin
from ._claims import _ClaimMixin
from ._run_gates import _RunGateMixin

if TYPE_CHECKING:
    from agentkit.backend.control_plane.models import (
        ClosureCompleteRequest,
        ControlPlaneMutationResult,
        PhaseDispatchResult,
        PhaseMutationRequest,
    )


class _ControlPlaneRuntimeAdmissionBase(
    _RunGateMixin,
    _ClaimMixin,
    _AdmissionIdentityMixin,
    _AdmissionRejectionMixin,
    _AdmissionDispatchMixin,
    _StartPhaseAdmissionMixin,
    _AdmittedPhaseMutationMixin,
    ABC,
):
    """Abstract admission-algorithm base for the runtime service.

    The concrete ``ControlPlaneRuntimeService`` supplies the template-method
    hooks below. Those hooks orchestrate collaborators assembled only by the full
    service, including ``_AdminTransitionMixin``, ``_EdgeCommandMixin``, and
    ``_ProjectEdgeSyncMixin``.
    """

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


__all__ = ["_ControlPlaneRuntimeAdmissionBase"]
