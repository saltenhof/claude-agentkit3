"""Preflight Check 2 — ``story_attributes_consistent`` (FK-22 §22.3.1).

The story attributes (story_type, size, mode, participating_repos) are
present and consistent with the registered :data:`PROFILES` for the story
type (story_context_manager ``types.PROFILES``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.governance.setup_preflight_gate.preflight import (
    PreflightCheckId,
    PreflightCheckResult,
    PreflightStatus,
)
from agentkit.story_context_manager.types import StoryType, get_profile

if TYPE_CHECKING:
    from agentkit.governance.setup_preflight_gate.preflight import PreflightContext

_CHECK_ID = PreflightCheckId.STORY_ATTRIBUTES_CONSISTENT
_HINT = (
    "Correct the story attributes (story_type / size / mode / repos) so they "
    "match a registered story-type profile before restarting the story."
)


def _fail(detail: str) -> PreflightCheckResult:
    return PreflightCheckResult(
        check_id=_CHECK_ID,
        status=PreflightStatus.FAIL,
        detail=detail,
        cleanup_hint=_HINT,
    )


def check(ctx: PreflightContext) -> PreflightCheckResult:
    """Validate story attribute consistency (FK-22 §22.3.1, Check 2).

    Checks (against the story-type profile, story_context_manager ``PROFILES``):
        - the story was fetched,
        - the story type maps to a registered profile,
        - ``participating_repos`` is non-empty,
        - code stories (implementation/bugfix) declare a profile that uses a
          worktree, non-code stories (concept/research) do not.

    Args:
        ctx: The preflight context.

    Returns:
        ``PASS`` when all attribute invariants hold; ``FAIL`` otherwise.
    """
    story = ctx.story
    if story is None:
        return _fail("Cannot check attributes: story could not be fetched")

    try:
        story_type = StoryType(str(story.story_type))
    except ValueError:
        return _fail(f"Unknown story_type {story.story_type!r}")

    try:
        profile = get_profile(story_type)
    except Exception as exc:  # noqa: BLE001 -- surface as a consistency FAIL
        return _fail(f"No profile for story_type {story_type.value!r}: {exc}")

    repos = list(getattr(story, "participating_repos", []) or [])
    if not repos:
        return _fail(
            f"Story {story.story_display_id!r} has no participating_repos"
        )

    is_code = story_type in (StoryType.IMPLEMENTATION, StoryType.BUGFIX)
    if is_code != profile.uses_worktree:
        return _fail(
            f"story_type {story_type.value!r} is inconsistent with its "
            f"profile (uses_worktree={profile.uses_worktree})"
        )

    return PreflightCheckResult(
        check_id=_CHECK_ID,
        status=PreflightStatus.PASS,
        detail=(
            f"Attributes consistent for {story.story_display_id!r}: "
            f"type={story_type.value}, size={story.size.value}, "
            f"repos={len(repos)}"
        ),
    )
