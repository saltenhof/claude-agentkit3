"""Build StoryContext from a GitHub issue."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.integrations.github.issues import get_issue
from agentkit.story.models import StoryContext
from agentkit.story.types import StoryMode, StoryType, get_profile

if TYPE_CHECKING:
    from pathlib import Path


def _extract_story_type(labels: tuple[str, ...]) -> StoryType:
    """Extract story type from issue labels.

    Searches labels for a recognised story-type name (case-insensitive).
    ``"bug"`` and ``"bugfix"`` both map to :attr:`StoryType.BUGFIX`.

    Args:
        labels: Tuple of label names from the issue.

    Returns:
        The matched ``StoryType``, or ``IMPLEMENTATION`` as default.
    """
    for label in labels:
        normalized = label.strip().lower()
        if normalized in ("bug", "bugfix"):
            return StoryType.BUGFIX
        if normalized == "concept":
            return StoryType.CONCEPT
        if normalized == "research":
            return StoryType.RESEARCH
    return StoryType.IMPLEMENTATION


def build_story_context(
    owner: str,
    repo: str,
    issue_nr: int,
    project_root: Path,
    story_id: str | None = None,
) -> StoryContext:
    """Build a ``StoryContext`` by reading a GitHub issue.

    Steps:
        1. Fetch the issue via :func:`~agentkit.integrations.github.issues.get_issue`.
        2. Extract ``story_type`` from labels.
        3. Determine execution mode from the story-type profile's default.
        4. Estimate size from labels and title (informational, not stored).
        5. Generate ``story_id`` if not provided.
        6. Build and return the ``StoryContext``.

    Args:
        owner: GitHub repository owner.
        repo: GitHub repository name.
        issue_nr: Issue number to read.
        project_root: Path to the target project root.
        story_id: Optional explicit story ID.  If ``None``, derived
            as ``"STORY-{issue_nr}"``.

    Returns:
        Populated ``StoryContext`` with all fields from the issue.
    """
    issue = get_issue(owner, repo, issue_nr)

    story_type = _extract_story_type(issue.labels)
    profile = get_profile(story_type)
    mode: StoryMode = profile.default_mode

    resolved_story_id = story_id if story_id is not None else f"STORY-{issue_nr}"

    return StoryContext(
        story_id=resolved_story_id,
        story_type=story_type,
        mode=mode,
        issue_nr=issue.number,
        title=issue.title,
        project_root=project_root,
        participating_repos=[f"{owner}/{repo}"],
        labels=list(issue.labels),
        created_at=datetime.now(tz=UTC),
    )
