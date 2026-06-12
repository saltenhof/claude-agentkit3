"""OperatingModeResolver -- the named operating-mode resolution owner.

PROJECT_STRUCTURE.md:120 prescribes a named
``story_context_manager/operating_mode_resolver/`` namespace for resolving the
local operating mode (FK-56 §56.5 / §56.7a). Before AG3-097 that resolution was
scattered: the ``OperatingMode`` literal lived in ``projectedge.runtime`` and the
``binding_invalid`` block decision plus the integrity-gate exclusion read it
ad-hoc. This namespace consolidates the *mode semantics* onto ONE named owner
(FIX-THE-MODEL / SINGLE SOURCE OF TRUTH) WITHOUT changing behaviour:

* the canonical :data:`OperatingMode` literal has its SINGLE definition at the
  blood-type-0/A-core foundation module ``agentkit.core_types.operating_mode``
  (modelled as the ``domain_core_foundation`` boundary ``core_types``, importable
  by everyone, importing nothing AK3-specific). It lives there -- not in this
  A-core and not in ``projectedge.runtime`` -- because the ``control_plane.models``
  R-adapter must resolve the annotation at model-build time and an adapter
  boundary may only outbound-import the foundation layer, never another boundary
  (AC010), so a foundation home is the only cycle-free SSOT. This A-core RE-EXPORTS
  that literal as the SSOT *accessor* seam. Every other module RE-IMPORTS this
  exact literal -- the run-binding classifier ``control_plane.runtime``, the
  project-edge classifier ``projectedge.runtime``, the ``control_plane.models``
  read models, and the ``governance`` consumers (guard_evaluation + the
  integrity-gate mode guard). No module redeclares the literal, so AK2's SSOT
  claim is literal, not aspirational;
* :func:`resolve_operating_mode` is the single, behaviour-preserving accessor
  that turns a resolved project-edge state into its :data:`OperatingMode` --
  consumed by ``governance.guard_evaluation`` (the pre-tool guard) AND by the
  integrity-gate mode guard (``governance.integrity_gate.mode_guard``).

The R-boundary FS reads + the project-edge sync live in ``projectedge.runtime``
(the I/O boundary) and the run-binding classification in ``control_plane.runtime``;
this A-core namespace owns the *mode-semantic seam* (the re-exported literal + the
one accessor). The CCAG permission-decision axis (``CcagDecisionMode``:
``story_execution``/``ai_augmented``/``interactive_agent``) is a DIFFERENT axis
(FK-42 §42.2.5 / FK-56 §56.4 -- ``interactive_agent`` is a PRINCIPAL, not a
binding-validity state) and is deliberately NOT this type.

The FK-56 namespace concept-prose nachzug (PROJECT_STRUCTURE / BC-registry doc)
is AG3-102; AG3-097 owns only this code namespace.
"""

from __future__ import annotations

from agentkit.story_context_manager.operating_mode_resolver.resolver import (
    OperatingMode,
    resolve_operating_mode,
)

__all__ = [
    "OperatingMode",
    "resolve_operating_mode",
]
