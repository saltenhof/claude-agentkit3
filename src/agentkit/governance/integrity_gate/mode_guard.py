"""Integrity-gate operating-mode exclusion guard (FK-56 §56.7a / §56.10).

FK-56 §56.7a / §56.10: in the ``ai_augmented`` (free / unbound) operating mode
there is NO integrity gate -- no ``integrity_gate_started`` / ``integrity_gate_result``
telemetry, no closure FAIL-codes. Before AG3-097 this negative abgrenzung was
only IMPLICIT (the gate simply was not invoked in that mode). AG3-097 makes it
EXPLICIT and fail-closed: an accidental ``IntegrityGate.evaluate`` call in
``ai_augmented`` mode is a typed programming error that aborts BEFORE any
integrity work begins (before any event is emitted), so no half-run gate can
leak an ``integrity_gate_started`` event or a closure FAIL-code.

The mode itself comes from the named
``story_context_manager.operating_mode_resolver`` owner (sub-part 2): both this
guard and ``governance.guard_evaluation`` read the resolved
:data:`~agentkit.story_context_manager.operating_mode_resolver.OperatingMode`
through that single seam.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentkit.story_context_manager.operating_mode_resolver import (
        OperatingMode,
    )


class IntegrityGateNotApplicableError(RuntimeError):
    """The integrity gate was invoked in a mode where it must not run.

    FK-56 §56.7a / §56.10: the ``ai_augmented`` (free / unbound) operating mode
    has NO integrity gate. Raising this typed error BEFORE any integrity work
    (before ``integrity_gate_started``) guarantees the gate cannot emit a single
    integrity-gate event or produce a closure FAIL-code in that mode -- the
    exclusion is explicit and fail-closed, never a silent no-op that might still
    have partially run (ZERO DEBT / FAIL-CLOSED).
    """


def guard_integrity_gate_mode(operating_mode: OperatingMode) -> None:
    """Reject an integrity-gate invocation in the ``ai_augmented`` mode.

    Called at the very top of :meth:`IntegrityGate.evaluate`, before any
    dimension work, scope resolution, or telemetry. ``story_execution`` and
    ``binding_invalid`` proceed normally (the gate is applicable for a bound run;
    a ``binding_invalid`` run never reaches a productive closure gate anyway, but
    the integrity gate itself is not the place to re-decide that). Only
    ``ai_augmented`` is hard-excluded.

    Args:
        operating_mode: The resolved operating mode (FK-56 §56.5), obtained from
            the named ``operating_mode_resolver`` owner.

    Raises:
        IntegrityGateNotApplicableError: If ``operating_mode == "ai_augmented"``
            (FK-56 §56.7a / §56.10) -- raised before any integrity work.
    """
    if operating_mode == "ai_augmented":
        msg = (
            "IntegrityGate is not applicable in the ai_augmented operating mode "
            "(FK-56 §56.7a / §56.10): the free / unbound mode has no integrity "
            "gate -- no integrity_gate_started/integrity_gate_result events and "
            "no closure FAIL-codes. Aborting before any integrity work "
            "(fail-closed, ZERO DEBT)."
        )
        raise IntegrityGateNotApplicableError(msg)


__all__ = [
    "IntegrityGateNotApplicableError",
    "guard_integrity_gate_mode",
]
