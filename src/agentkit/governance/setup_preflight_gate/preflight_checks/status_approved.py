"""Preflight Check 3 — ``status_approved`` (FK-22 §22.3.1).

The story status in the AK3 story backend is ``Approved``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.governance.setup_preflight_gate.preflight import (
    PreflightCheckId,
    PreflightCheckResult,
    PreflightStatus,
)
from agentkit.story_context_manager.story_model import StoryStatus

if TYPE_CHECKING:
    from agentkit.governance.setup_preflight_gate.preflight import PreflightContext

_CHECK_ID = PreflightCheckId.STATUS_APPROVED


def check(ctx: PreflightContext) -> PreflightCheckResult:
    """Verify the story is in ``Approved`` status (FK-22 §22.3.1, Check 3).

    Args:
        ctx: The preflight context.

    Returns:
        ``PASS`` when the status is ``Approved``; ``FAIL`` otherwise.
    """
    story = ctx.story
    if story is None:
        return PreflightCheckResult(
            check_id=_CHECK_ID,
            status=PreflightStatus.FAIL,
            detail="Cannot check status: story could not be fetched",
            cleanup_hint=(
                "The story could not be fetched; resolve the story_exists "
                "failure first, then restart the story."
            ),
        )
    if story.status is StoryStatus.APPROVED:
        return PreflightCheckResult(
            check_id=_CHECK_ID,
            status=PreflightStatus.PASS,
            detail=f"Story {story.story_display_id!r} is Approved",
        )
    return PreflightCheckResult(
        check_id=_CHECK_ID,
        status=PreflightStatus.FAIL,
        detail=f"Story {story.story_display_id!r} is {story.status.value!r}",
        cleanup_hint=(
            f"Approve story {story.story_display_id!r} (currently "
            f"{story.status.value!r}) before starting it."
        ),
    )
