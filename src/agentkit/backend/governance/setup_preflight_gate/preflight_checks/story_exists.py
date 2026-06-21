"""Preflight Check 1 — ``story_exists`` (FK-22 §22.3.1).

The story ID exists in the AK3 story backend and is retrievable.
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


def check(ctx: PreflightContext) -> PreflightCheckResult:
    """Verify the story exists in the StoryService (FK-22 §22.3.1, Check 1).

    Args:
        ctx: The preflight context (``ctx.story`` is the resolved Story).

    Returns:
        ``PASS`` when the story was found; ``FAIL`` (with a cleanup hint)
        otherwise.
    """
    if ctx.story is None:
        return PreflightCheckResult(
            check_id=PreflightCheckId.STORY_EXISTS,
            status=PreflightStatus.FAIL,
            detail=f"Story {ctx.story_display_id!r} not found in StoryService",
            cleanup_hint=(
                f"Verify the story ID {ctx.story_display_id!r} is correct and "
                "the story exists (not deleted) in the AK3 story backend."
            ),
        )
    return PreflightCheckResult(
        check_id=PreflightCheckId.STORY_EXISTS,
        status=PreflightStatus.PASS,
        detail=f"Story {ctx.story_display_id!r} found: {ctx.story.title!r}",
    )
