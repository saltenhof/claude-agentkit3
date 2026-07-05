"""Preflight Check 8 — ``no_stale_worktree`` (FK-22 §22.3.1, AG3-145 Teilschritt C).

Check 8 is an Edge-Probe + Backend-Entscheid (FK-22 §22.3.1): the Project Edge
collects the ``preflight_probe`` worktree/marker state (pure collection) and the
BACKEND decides here with ownership context. NAMED, differentiated findings
(``foreign_worktree``, ``wrong_marker_wrong_story``,
``local_stale_or_dirty_takeover_target``, ``legitimate_takeover``,
``no_leftover_state``, ``edge_probe_missing``) replace the old collective FAIL.
A legitimate takeover of THIS run's own active ownership PASSes; a
missing/unreadable probe FAILs fail-closed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.control_plane.edge_commands import (
    PreflightOwnershipContext,
    decide_worktree_preflight,
)
from agentkit.backend.governance.setup_preflight_gate.preflight import (
    PreflightCheckId,
    PreflightCheckResult,
    PreflightStatus,
)

if TYPE_CHECKING:
    from agentkit.backend.control_plane.edge_commands import PreflightEdgeFinding
    from agentkit.backend.governance.setup_preflight_gate.preflight import PreflightContext

_CHECK_ID = PreflightCheckId.NO_STALE_WORKTREE


def check(ctx: PreflightContext) -> PreflightCheckResult:
    """Verify no stale / illegitimate worktree exists (FK-22 §22.3.1, Check 8).

    Args:
        ctx: The preflight context (``ctx.edge_probe_reports`` +
            ``ctx.edge_ownership``).

    Returns:
        ``PASS`` when no repo carries a stale foreign worktree (or when the edge
        was not consulted for a non-worktree story); ``FAIL`` with the first
        NAMED finding otherwise.
    """
    if ctx.edge_probe_reports is None:
        return PreflightCheckResult(
            check_id=_CHECK_ID,
            status=PreflightStatus.PASS,
            detail="no worktree edge consultation for this story",
        )
    ownership = ctx.edge_ownership or PreflightOwnershipContext()
    for repo_id in ctx.participating_repos:
        evidence = ctx.edge_probe_reports.get(repo_id)
        finding = decide_worktree_preflight(
            evidence, ownership, story_id=ctx.story_display_id
        )
        if not finding.passed:
            return _fail(finding)
    return PreflightCheckResult(
        check_id=_CHECK_ID,
        status=PreflightStatus.PASS,
        detail=f"no stale worktree for {ctx.story_display_id!r}",
    )


def _fail(finding: PreflightEdgeFinding) -> PreflightCheckResult:
    """Render a NAMED failing edge finding into a Check-8 result."""
    return PreflightCheckResult(
        check_id=_CHECK_ID,
        status=PreflightStatus.FAIL,
        detail=f"{finding.finding_code}: {finding.detail}",
        cleanup_hint=finding.cleanup_hint,
    )
