"""Preflight Check 7 — ``no_story_branch`` (FK-22 §22.3.1).

No unaufgeraeumter ``story/{story_id}`` branch exists.  The default probe does
a real read-only ``git show-ref`` on the project repo (FAIL-CLOSED, Finding B);
a git error fails the check closed via ``run_preflight`` (AK4).  A custom probe
may be injected via :class:`PreflightContext`.  Branch cleanup CLI logic is out
of scope (story.md §2.2).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.governance.setup_preflight_gate.preflight import (
    PreflightCheckId,
    PreflightCheckResult,
    PreflightStatus,
)

if TYPE_CHECKING:
    from agentkit.backend.governance.setup_preflight_gate.preflight import PreflightContext

_CHECK_ID = PreflightCheckId.NO_STORY_BRANCH


def check(ctx: PreflightContext) -> PreflightCheckResult:
    """Verify no leftover story branch exists (FK-22 §22.3.1, Check 7).

    Args:
        ctx: The preflight context (``ctx.branch_exists`` is the probe).

    Returns:
        ``PASS`` when no ``story/{story_id}`` branch exists; ``FAIL`` otherwise.
    """
    branch = f"story/{ctx.story_display_id}"
    if ctx.branch_exists(ctx.project_root, ctx.story_display_id):
        return PreflightCheckResult(
            check_id=_CHECK_ID,
            status=PreflightStatus.FAIL,
            detail=f"Branch {branch!r} of an unfinished prior run exists",
            cleanup_hint=(
                f"Delete the leftover branch with `git branch -d {branch}` "
                "(or recover the prior run) before restarting."
            ),
        )
    return PreflightCheckResult(
        check_id=_CHECK_ID,
        status=PreflightStatus.PASS,
        detail=f"No leftover branch {branch!r}",
    )
