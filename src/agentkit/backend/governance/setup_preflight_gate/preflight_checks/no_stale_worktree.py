"""Preflight Check 8 — ``no_stale_worktree`` (FK-22 §22.3.1).

No stale worktree directory for the story exists.  The default probe checks
for a ``_worktrees/{story_id}`` directory under the project root (story.md
§2.1.1); a custom probe may be injected via :class:`PreflightContext`.
Worktree recovery mechanics are out of scope (story.md §2.2).
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

_CHECK_ID = PreflightCheckId.NO_STALE_WORKTREE


def _default_probe(project_root: Path, story_display_id: str) -> bool:
    """Return ``True`` when a ``_worktrees/{story_id}`` directory exists."""
    worktree_dir = project_root / "_worktrees" / story_display_id
    return worktree_dir.is_dir()


def check(ctx: PreflightContext) -> PreflightCheckResult:
    """Verify no stale worktree exists (FK-22 §22.3.1, Check 8).

    Args:
        ctx: The preflight context.

    Returns:
        ``PASS`` when no stale worktree exists; ``FAIL`` otherwise.
    """
    probe = ctx.stale_worktree_present or _default_probe
    if probe(ctx.project_root, ctx.story_display_id):
        return PreflightCheckResult(
            check_id=_CHECK_ID,
            status=PreflightStatus.FAIL,
            detail=(
                f"Stale worktree of an unfinished prior run found for "
                f"{ctx.story_display_id!r}"
            ),
            cleanup_hint=(
                f"Run `agentkit cleanup-worktree --story {ctx.story_display_id}` "
                "to remove the stale worktree before restarting."
            ),
        )
    return PreflightCheckResult(
        check_id=_CHECK_ID,
        status=PreflightStatus.PASS,
        detail=f"No stale worktree for {ctx.story_display_id!r}",
    )
