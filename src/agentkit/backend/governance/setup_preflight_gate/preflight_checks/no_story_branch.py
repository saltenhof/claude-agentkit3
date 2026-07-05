"""Preflight Check 7 — ``no_story_branch`` (FK-22 §22.3.1, AG3-145 Teilschritt C).

Checks 7/8 are an Edge-Probe + Backend-Entscheid (FK-22 §22.3.1): the Project
Edge collects the ``preflight_probe`` evidence (branch class + head SHA, local
worktree/marker state -- pure collection), and the BACKEND decides here with
ownership context (active ``run_ownership_records`` row + ``takeover_base_sha``)
and the remote story-branch head SHA from the AG3-146 provider-adapter
``ls-remote`` ref-read -- never a backend worktree git subprocess.

The decision emits NAMED, differentiated findings (``stale_foreign_branch``,
``locally_ahead``, ``remote_branch_diverged_after_takeover``,
``local_stale_or_dirty_takeover_target``, ``legitimate_takeover``,
``no_leftover_state``, ``edge_probe_missing``) instead of one collective FAIL:
``stale foreign`` FAILs (a human decides); a ``legitimate takeover`` (active
own-session ownership PLUS alignment to ``takeover_base_sha``) PASSes. A
missing/unreadable probe FAILs fail-closed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.control_plane.edge_commands import (
    PreflightOwnershipContext,
    decide_branch_preflight,
)
from agentkit.backend.governance.setup_preflight_gate.preflight import (
    PreflightCheckId,
    PreflightCheckResult,
    PreflightStatus,
)

if TYPE_CHECKING:
    from agentkit.backend.control_plane.edge_commands import PreflightEdgeFinding
    from agentkit.backend.governance.setup_preflight_gate.preflight import PreflightContext

_CHECK_ID = PreflightCheckId.NO_STORY_BRANCH


def check(ctx: PreflightContext) -> PreflightCheckResult:
    """Verify no leftover / illegitimate story branch exists (FK-22 §22.3.1, Check 7).

    Args:
        ctx: The preflight context (``ctx.edge_probe_reports`` +
            ``ctx.edge_ownership``).

    Returns:
        ``PASS`` when no repo carries a leftover foreign branch (or when the
        edge was not consulted for a non-worktree story); ``FAIL`` with the
        first NAMED finding otherwise.
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
        finding = decide_branch_preflight(evidence, ownership)
        if not finding.passed:
            return _fail(finding)
    return PreflightCheckResult(
        check_id=_CHECK_ID,
        status=PreflightStatus.PASS,
        detail=f"no leftover story branch story/{ctx.story_display_id}",
    )


def _fail(finding: PreflightEdgeFinding) -> PreflightCheckResult:
    """Render a NAMED failing edge finding into a Check-7 result."""
    return PreflightCheckResult(
        check_id=_CHECK_ID,
        status=PreflightStatus.FAIL,
        detail=f"{finding.finding_code}: {finding.detail}",
        cleanup_hint=finding.cleanup_hint,
    )
