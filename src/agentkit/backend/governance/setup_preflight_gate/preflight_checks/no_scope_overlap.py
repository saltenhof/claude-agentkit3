"""Preflight Check 9 — ``no_scope_overlap`` (FK-22 §22.3.1).

No other active (``In Progress``) story works on overlapping
``participating_repos``.  An overlap means a merge conflict is
pre-programmed (FK-22 §22.3.1, Check 9).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.governance.setup_preflight_gate.preflight import (
    PreflightCheckId,
    PreflightCheckResult,
    PreflightStatus,
)
from agentkit.backend.story_context_manager.story_model import StoryStatus

if TYPE_CHECKING:
    from agentkit.backend.governance.setup_preflight_gate.preflight import PreflightContext

_CHECK_ID = PreflightCheckId.NO_SCOPE_OVERLAP


def check(ctx: PreflightContext) -> PreflightCheckResult:
    """Verify no scope overlap with an active story (FK-22 §22.3.1, Check 9).

    Reads all stories of the project via the StoryService and compares the
    candidate story's ``participating_repos`` against every other
    ``In Progress`` story's repos.

    Args:
        ctx: The preflight context.

    Returns:
        ``PASS`` when no active story shares a repo; ``FAIL`` otherwise.
    """
    story = ctx.story
    if story is None:
        return PreflightCheckResult(
            check_id=_CHECK_ID,
            status=PreflightStatus.FAIL,
            detail="Cannot check scope overlap: story could not be fetched",
            cleanup_hint=(
                "The story could not be fetched; resolve the story_exists "
                "failure first, then restart the story."
            ),
        )

    own_repos = set(getattr(story, "participating_repos", []) or [])
    overlaps = _overlapping_stories(ctx, own_repos)
    if overlaps:
        joined = ", ".join(sorted(overlaps))
        return PreflightCheckResult(
            check_id=_CHECK_ID,
            status=PreflightStatus.FAIL,
            detail=f"Scope overlap with active stories: {joined}",
            cleanup_hint=(
                "Wait until the overlapping active stories reach Done/Cancelled "
                f"before starting (overlap with: {joined})."
            ),
        )
    return PreflightCheckResult(
        check_id=_CHECK_ID,
        status=PreflightStatus.PASS,
        detail=f"No scope overlap for {story.story_display_id!r}",
    )


def _overlapping_stories(ctx: PreflightContext, own_repos: set[str]) -> set[str]:
    """Return the display IDs of active stories sharing a repo with the candidate."""
    if not own_repos:
        return set()
    overlaps: set[str] = set()
    for other in ctx.service.list_stories(ctx.project_key):
        if other.story_display_id == ctx.story_display_id:
            continue
        if other.status is not StoryStatus.IN_PROGRESS:
            continue
        if own_repos & set(other.participating_repos):
            overlaps.add(other.story_display_id)
    return overlaps
