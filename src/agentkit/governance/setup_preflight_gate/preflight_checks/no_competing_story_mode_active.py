"""Preflight Check 10 — ``no_competing_story_mode_active`` (FK-22 §22.3.1).

No conflicting project-wide story mode is active (FK-24 §24.3.3).  Fast and
Standard are fachlich mutually exclusive: while any Standard story is active
no Fast story may start, and vice versa.  This check reads the project
``mode_lock`` (read path established by AG3-034 §2.1.2); the atomic set is a
follow-up story.

The comparison runs on the DECOUPLED fast/standard ``mode`` axis
(``WireStoryMode`` / ``StoryContext.mode``, FK-24 §24.3.3) — NOT the
``execution_route`` axis.  The candidate's mode is read from ``story.mode``
and the lock's ``active_mode`` is one of ``WireStoryMode`` wire values
(``standard``/``fast``); a missing/idle lock means standard==fast both allowed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.governance.setup_preflight_gate.preflight import (
    PreflightCheckId,
    PreflightCheckResult,
    PreflightStatus,
)
from agentkit.story_context_manager.story_model import WireStoryMode

if TYPE_CHECKING:
    from agentkit.governance.setup_preflight_gate.preflight import PreflightContext
    from agentkit.state_backend.store.mode_lock_repository import ModeLockRecord

_CHECK_ID = PreflightCheckId.NO_COMPETING_STORY_MODE_ACTIVE


def _resolve_lock(ctx: PreflightContext) -> ModeLockRecord | None:
    """Resolve the mode-lock fail-closed (E-E fix).

    When a ``mode_lock_reader`` is wired it is authoritative: a read error
    propagates (caught by ``_run_one`` -> fail-closed ``FAIL``), never masked
    as idle.  Otherwise the pre-resolved ``ctx.mode_lock`` is used.
    """
    if ctx.mode_lock_reader is not None:
        return ctx.mode_lock_reader(ctx.project_key)
    return ctx.mode_lock


def _desired_mode(ctx: PreflightContext) -> WireStoryMode:
    """Return the candidate story's fast/standard ``mode`` (FK-24 §24.3.3)."""
    story = ctx.story
    if story is not None and story.mode is WireStoryMode.FAST:
        return WireStoryMode.FAST
    return WireStoryMode.STANDARD


def check(ctx: PreflightContext) -> PreflightCheckResult:
    """Verify no competing story mode is active (FK-22 §22.3.1, Check 10).

    Allowed: ``mode_lock`` is idle (absent / ``holder_count == 0`` /
    ``active_mode is None``), or the active ``mode`` equals the candidate
    story's ``mode`` on the decoupled fast/standard axis (FK-24 §24.3.3).
    FAIL when the lock holds the opposite mode.

    FAIL-CLOSED (E-E fix): when a ``mode_lock_reader`` is wired it is the
    authoritative source and is read here.  A read error is NOT caught — it
    propagates so :func:`run_preflight._run_one` converts it into a fail-closed
    ``FAIL`` (a real mode conflict must never be masked as idle).

    Args:
        ctx: The preflight context (``ctx.mode_lock_reader`` is the read path;
            ``ctx.mode_lock`` is the pre-resolved fallback).

    Returns:
        ``PASS`` when no competing mode is active; ``FAIL`` otherwise.
    """
    lock = _resolve_lock(ctx)
    if lock is None or lock.holder_count <= 0 or lock.active_mode is None:
        return PreflightCheckResult(
            check_id=_CHECK_ID,
            status=PreflightStatus.PASS,
            detail="Project mode-lock is idle; no competing mode active",
        )

    active_mode = (
        WireStoryMode.FAST
        if lock.active_mode == WireStoryMode.FAST.value
        else WireStoryMode.STANDARD
    )
    desired_mode = _desired_mode(ctx)
    active_route = active_mode.value
    desired_route = desired_mode.value
    if active_mode is not desired_mode:
        return PreflightCheckResult(
            check_id=_CHECK_ID,
            status=PreflightStatus.FAIL,
            detail=(
                f"Competing story mode active: lock holds {active_route!r} "
                f"({lock.holder_count} holder(s)), story wants {desired_route!r}"
            ),
            cleanup_hint=(
                f"Wait until all active {active_route!r}-mode stories reach "
                "Done/Cancelled; Fast and Standard are mutually exclusive "
                "(FK-24 §24.3.3)."
            ),
        )
    return PreflightCheckResult(
        check_id=_CHECK_ID,
        status=PreflightStatus.PASS,
        detail=f"Project mode-lock holds compatible mode {active_route!r}",
    )
