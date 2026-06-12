"""Canonical local operating-mode literal (FK-56 §56.5 / §56.7a).

Foundation (blood-type-0) home of the closed three-value local operating-mode
set. This module imports NOTHING AK3-specific (only ``typing``); it is the
SINGLE definition every consumer re-imports, so AK2's "one OperatingMode" claim
is literal, not aspirational.

The three values (FK-56 §56.5 / §56.7a):

* ``"ai_augmented"``    -- free / unbound mode (no story binding): no story
  guards, NO integrity gate (FK-56 §56.7a / §56.10);
* ``"story_execution"`` -- a valid, ACTIVE story binding: full guards apply;
* ``"binding_invalid"`` -- a bound bundle whose binding is corrupt / mismatched:
  fail-closed block of mutating operations (FK-56 §56.7a).

Why it lives in ``core_types`` and not in a boundary: ``control_plane.models``
(a Pydantic adapter-boundary read model) must resolve this annotation at
model-build time, and an adapter-boundary may only outbound-import the
shared/foundation layer -- not another boundary such as ``projectedge.runtime``
(its previous home) nor the ``story_context_manager`` A-core (AC010). Placing the
type at the blood-type-0 foundation lets EVERY consumer (the project-edge
classifier, the run-binding classifier, the A-core resolver seam, and the
control-plane read models) re-import the EXACT SAME object cycle-free -- ONE
definition, no drift, true SSOT.

The named ``story_context_manager.operating_mode_resolver`` A-core stays the
SSOT *accessor* owner: it re-exports this literal and owns the single
``resolve_operating_mode`` accessor consumers route the resolved mode through.

The CCAG permission-decision axis (``governance.ccag.runtime.CcagDecisionMode``:
``story_execution`` / ``ai_augmented`` / ``interactive_agent``) is a DIFFERENT
axis (FK-42 §42.2.5 / FK-56 §56.4 -- ``interactive_agent`` is a PRINCIPAL, not a
binding-validity state) and is deliberately NOT this type.
"""

from __future__ import annotations

from typing import Literal

#: The canonical closed three-value local operating-mode set (FK-56 §56.5 /
#: §56.7a). Defined exactly ONCE here at the blood-type-0 foundation; every other
#: module re-imports this object rather than redeclaring the literal.
OperatingMode = Literal["ai_augmented", "story_execution", "binding_invalid"]

__all__ = ["OperatingMode"]
