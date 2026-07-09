"""Composed control-plane runtime service entrypoint."""

from __future__ import annotations

from ._admin import _AdminTransitionMixin
from ._admission import _ControlPlaneRuntimeAdmissionBase
from ._edge_commands import _EdgeCommandMixin
from ._project_edge_sync import _ProjectEdgeSyncMixin
from ._service_closure import _ControlPlaneClosureMixin
from ._service_phase_mutation import _ControlPlanePhaseMutationMixin
from ._service_resume import _ControlPlaneResumeMixin


class ControlPlaneRuntimeService(
    _AdminTransitionMixin,
    _EdgeCommandMixin,
    _ProjectEdgeSyncMixin,
    _ControlPlaneClosureMixin,
    _ControlPlaneResumeMixin,
    _ControlPlanePhaseMutationMixin,
    _ControlPlaneRuntimeAdmissionBase,
):
    """Implement control-plane mutations with idempotent op replay."""


__all__ = ["ControlPlaneRuntimeService"]
