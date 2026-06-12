"""OperatingModeResolver named-namespace equivalence (AG3-097 AK2, FK-56 §56.5).

The canonical ``OperatingMode`` literal has its SINGLE definition at the
blood-type-0 foundation (``core_types.operating_mode``); the named
``operating_mode_resolver`` owner RE-EXPORTS it and owns the single
``resolve_operating_mode`` accessor that both ``guard_evaluation`` and the
integrity-gate mode guard route the resolved mode through. The accessor is
behaviour-PRESERVING: it returns exactly the mode the project-edge resolver
already classified (ai_augmented / story_execution / binding_invalid), with no
re-classification.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from agentkit.control_plane.models import EdgePointer, SessionRunBindingView
from agentkit.control_plane.runtime import OperatingMode as ControlPlaneOperatingMode
from agentkit.core_types.operating_mode import OperatingMode as CoreTypesOperatingMode
from agentkit.projectedge.runtime import OperatingMode as RuntimeOperatingMode
from agentkit.story_context_manager.operating_mode_resolver import (
    OperatingMode,
    resolve_operating_mode,
)
from agentkit.story_context_manager.operating_mode_resolver.resolver import (
    CarriesOperatingMode,
)


@dataclass(frozen=True)
class _Resolved:
    """First-class carrier of an operating mode (the ResolvedEdgeState analogue)."""

    operating_mode: OperatingMode


@pytest.mark.parametrize(
    "mode",
    ["ai_augmented", "story_execution", "binding_invalid"],
)
def test_resolve_returns_the_classified_mode_unchanged(mode: OperatingMode) -> None:
    """Equivalence: the accessor returns the already-classified mode verbatim."""
    resolved = _Resolved(operating_mode=mode)

    assert resolve_operating_mode(resolved) == mode


def test_all_real_consumers_reimport_the_one_literal() -> None:
    """SINGLE DEFINITION: every real consumer re-imports the ONE foundation literal.

    AK2 SSOT (AG3-097 review remediation): the canonical ``OperatingMode`` has
    exactly ONE definition -- ``core_types.operating_mode`` (blood-type-0
    foundation) -- and EVERY real consumer re-imports that exact object:

    * the project-edge classifier ``projectedge.runtime``,
    * the run-binding classifier ``control_plane.runtime``,
    * the named ``operating_mode_resolver`` A-core accessor seam,
    * the control-plane PRODUCTION read models ``EdgePointer`` and
      ``SessionRunBindingView`` (the residual Codex finding: these no longer
      redeclare the inline ``Literal[...]`` -- their Pydantic field annotation IS
      the canonical object).

    Identity (``is``) proves there is no second, drifting copy anywhere.
    """
    assert OperatingMode is CoreTypesOperatingMode
    assert RuntimeOperatingMode is CoreTypesOperatingMode
    assert ControlPlaneOperatingMode is CoreTypesOperatingMode
    assert (
        EdgePointer.model_fields["operating_mode"].annotation is CoreTypesOperatingMode
    )
    assert (
        SessionRunBindingView.model_fields["operating_mode"].annotation
        is CoreTypesOperatingMode
    )


def test_ccag_decision_mode_is_a_different_axis_not_the_operating_mode() -> None:
    """CCAG's permission-decision axis is NOT conflated with OperatingMode.

    FK-42 §42.2.5 / FK-56 §56.4: CCAG keys on whether a host-prompt is admissible
    (a PRINCIPAL property: ``interactive_agent``), NOT on binding validity. Its
    literal is a genuinely different axis -- it must carry its own name
    (``CcagDecisionMode``), have NO ``binding_invalid`` member, and must NOT be
    the SSOT ``OperatingMode`` (no second operating-mode truth, FIX-THE-MODEL).
    """
    from typing import get_args

    from agentkit.governance.ccag.runtime import CcagDecisionMode

    assert CcagDecisionMode is not OperatingMode
    ccag_values = set(get_args(CcagDecisionMode))
    operating_values = set(get_args(OperatingMode))
    assert ccag_values != operating_values
    # The CCAG axis has the host-dialog principal but NOT the FK-56 binding state.
    assert "interactive_agent" in ccag_values
    assert "binding_invalid" not in ccag_values
    assert "binding_invalid" in operating_values


def test_real_resolved_edge_state_satisfies_the_port() -> None:
    """The real ResolvedEdgeState structurally satisfies CarriesOperatingMode.

    Proves the named accessor consumes the SAME object the edge resolver
    produces (no parallel truth) -- ai_augmented is the bundle-less default.
    """
    from agentkit.projectedge.runtime import ResolvedEdgeState

    resolved = ResolvedEdgeState(operating_mode="ai_augmented", bundle=None)

    assert isinstance(resolved, CarriesOperatingMode)
    assert resolve_operating_mode(resolved) == "ai_augmented"


def test_guard_evaluation_consumes_the_resolver() -> None:
    """guard_evaluation imports + uses the named resolver (AK2 consumer proof)."""
    import agentkit.governance.guard_evaluation as guard_eval

    assert guard_eval.resolve_operating_mode is resolve_operating_mode


def test_integrity_gate_mode_guard_consumes_the_resolver_literal() -> None:
    """The integrity-gate mode guard is typed on the resolver's OperatingMode.

    The guard rejects exactly the ai_augmented value the resolver classifies;
    the two share one literal owner (no drift).
    """
    from agentkit.governance.integrity_gate.mode_guard import (
        IntegrityGateNotApplicableError,
        guard_integrity_gate_mode,
    )

    resolved = _Resolved(operating_mode="ai_augmented")
    with pytest.raises(IntegrityGateNotApplicableError):
        guard_integrity_gate_mode(resolve_operating_mode(resolved))
