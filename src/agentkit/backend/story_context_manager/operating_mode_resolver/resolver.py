"""Canonical operating-mode literal + the behaviour-preserving accessor.

FK-56 §56.5 / §56.7a -- the local operating mode is a closed three-value set:

* ``"ai_augmented"``    -- free / unbound mode (no story binding): no story
  guards, NO integrity gate (FK-56 §56.7a / §56.10);
* ``"story_execution"`` -- a valid, ACTIVE story binding: full guards apply;
* ``"binding_invalid"`` -- a bound bundle whose binding is corrupt / mismatched:
  fail-closed block of mutating operations (FK-56 §56.7a).

The *classification* (which of the three a given hook context resolves to) is the
project-edge R-boundary's job (``projectedge.runtime.ProjectEdgeResolver`` reads
the persisted bundle, syncs, and decides). This A-core owner does NOT re-derive
that decision -- doing so would build a SECOND operative truth next to the edge
resolver (forbidden). Instead it owns the *type* and the ONE named accessor that
both downstream consumers (``guard_evaluation`` and the integrity-gate mode
guard) read the resolved mode through, so the mode never travels as a bare
string attribute access scattered across modules (SINGLE SOURCE OF TRUTH).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

# The canonical operating-mode literal (FK-56 §56.5 / §56.7a) has its SINGLE
# definition at the ``core_types`` ``domain_core_foundation`` boundary
# (``core_types.operating_mode``), so a Pydantic adapter-boundary read model
# (``control_plane.models``) can resolve the annotation at model-build time: the
# ``core_types`` ``domain_core_foundation`` boundary is in that adapter's
# ``may_import_boundary_modules`` allow-list (AC010), unlike ``projectedge.runtime``
# (a different boundary) or the ``story_context_manager`` A-core. This named
# ``operating_mode_resolver`` A-core is the SSOT
# *accessor* seam: it RE-EXPORTS the one literal and owns the single
# ``resolve_operating_mode`` accessor every consumer routes the resolved mode
# through. Every other module (the project-edge classifier ``projectedge.runtime``;
# the run-binding classifier ``control_plane.runtime``; the ``control_plane.models``
# read models; ``governance.guard_evaluation`` + the integrity-gate mode guard)
# RE-IMPORTS this exact literal rather than redeclaring it -- ONE definition, no
# drift. The CCAG permission-decision axis (``story_execution``/``ai_augmented``/
# ``interactive_agent``) is a DIFFERENT axis (FK-42 §42.2.5 / FK-56 §56.4: the
# ``interactive_agent`` is a PRINCIPAL, not a binding-validity state) and is
# deliberately NOT this type (see ``governance.ccag.runtime.CcagDecisionMode``).
from agentkit.backend.core_types.operating_mode import OperatingMode


@runtime_checkable
class CarriesOperatingMode(Protocol):
    """Structural port for any resolved state that carries an operating mode.

    Satisfied by ``projectedge.runtime.ResolvedEdgeState`` without an import
    coupling (the edge resolver owns the I/O classification; this A-core owns the
    mode semantics). Keeping it structural avoids a ``story_context_manager`` ->
    ``projectedge`` dependency edge while still giving both consumers ONE typed
    accessor.
    """

    @property
    def operating_mode(self) -> OperatingMode:
        """The resolved operating mode (FK-56 §56.5)."""
        ...


def resolve_operating_mode(resolved: CarriesOperatingMode) -> OperatingMode:
    """Return the canonical operating mode for a resolved project-edge state.

    The single, behaviour-preserving accessor both ``guard_evaluation`` and the
    integrity-gate mode guard route through. It does not re-classify (the edge
    resolver already did, fail-closed); it is the named SSOT seam so the mode is
    never read as an ad-hoc bare-attribute access scattered across modules
    (FIX-THE-MODEL).

    Args:
        resolved: Any resolved state carrying an ``operating_mode`` (typically a
            ``projectedge.runtime.ResolvedEdgeState``).

    Returns:
        The resolved :data:`OperatingMode`.
    """
    return resolved.operating_mode


__all__ = [
    "CarriesOperatingMode",
    "OperatingMode",
    "resolve_operating_mode",
]
