"""Preflight Check 6 — ``no_active_runtime_residue`` (FK-22 §22.3.1).

No active runtime residue of a *prior* run.  ``execution_events`` telemetry is
explicitly NOT a start gate (FK-22 §22.3.1, Check 6).

FAIL-CLOSED (Finding B fix): the canonical residue read lives in the state
backend (open/non-terminal phase-states for the story).  ``governance`` is a
truth-boundary-protected module and must NOT call the state-backend loader
directly (TB003); the run-id-aware residue probe is therefore INJECTED by the
orchestrator (``SetupPhaseHandler``, composition-wired via
``build_phase_state_residue_probe``) through
:class:`PreflightContext.active_runtime_residue`.  When NO probe is wired the
default fails the check CLOSED — it never silently passes a precondition it
cannot evaluate (the earlier fail-open default-PASS is removed).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.governance.setup_preflight_gate.preflight import (
    PreflightCheckId,
    PreflightCheckResult,
    PreflightStatus,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.governance.setup_preflight_gate.preflight import PreflightContext

_CHECK_ID = PreflightCheckId.NO_ACTIVE_RUNTIME_RESIDUE


def _default_probe(project_root: Path, story_display_id: str) -> bool:
    """Raise when no run-aware residue probe is wired (FAIL-CLOSED, Finding B).

    The canonical residue read is a state-backend read the orchestrator owns
    (``governance`` may not call the loader directly, TB003).  Refusing to
    answer here makes ``run_preflight`` record a fail-closed FAIL (AK4) instead
    of an optimistic PASS — the unwired standalone path never green-lights a
    precondition it cannot evaluate.
    """
    msg = (
        f"no_active_runtime_residue probe is not wired for {story_display_id!r} "
        f"(project_root={project_root}); the orchestrator must inject the "
        "run-aware state-backend residue probe (FK-22 §22.3.1, fail-closed)."
    )
    raise RuntimeError(msg)


def check(ctx: PreflightContext) -> PreflightCheckResult:
    """Verify no active runtime residue exists (FK-22 §22.3.1, Check 6).

    Args:
        ctx: The preflight context.

    Returns:
        ``PASS`` when no active runtime residue exists; ``FAIL`` otherwise.
    """
    probe = ctx.active_runtime_residue or _default_probe
    if probe(ctx.project_root, ctx.story_display_id):
        return PreflightCheckResult(
            check_id=_CHECK_ID,
            status=PreflightStatus.FAIL,
            detail=(
                f"Active or inconsistent runtime state of a prior run found "
                f"for {ctx.story_display_id!r}"
            ),
            cleanup_hint=(
                f"Reset the prior run for {ctx.story_display_id!r} via the "
                "official story-reset path before restarting."
            ),
        )
    return PreflightCheckResult(
        check_id=_CHECK_ID,
        status=PreflightStatus.PASS,
        detail=f"No active runtime residue for {ctx.story_display_id!r}",
    )
