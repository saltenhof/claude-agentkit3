"""Build StoryContext from a GitHub issue."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.integrations.github.issues import get_issue
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.sizing import estimate_size
from agentkit.story_context_manager.story_model import WireStoryMode
from agentkit.story_context_manager.types import StoryMode, StoryType, get_profile

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


def _extract_mode(labels: tuple[str, ...]) -> WireStoryMode:
    """Extract the fast/standard mode from issue labels (FK-24 §24.3.3).

    The fast/standard ``mode`` is a SEPARATE axis from the
    ``execution_route`` (EXECUTION/EXPLORATION) path. A ``fast`` label
    (AG3-018) opts the run into fast mode; everything else is ``standard``.

    Args:
        labels: Tuple of label names from the issue.

    Returns:
        :attr:`WireStoryMode.FAST` if a ``fast`` label is present, else
        :attr:`WireStoryMode.STANDARD`.
    """
    for label in labels:
        if label.strip().lower() == "fast":
            return WireStoryMode.FAST
    return WireStoryMode.STANDARD


def build_story_context(
    owner: str,
    repo: str,
    issue_nr: int,
    project_root: Path,
    project_key: str,
    story_id: str | None = None,
) -> StoryContext:
    """Build a ``StoryContext`` by reading a GitHub issue.

    Steps:
        1. Fetch the issue via :func:`~agentkit.integrations.github.issues.get_issue`.
        2. Extract ``story_type`` from labels.
        3. Determine execution route from the story-type profile's default.
        3a. Extract the fast/standard ``mode`` axis (FK-24 §24.3.3) from
            labels (default ``standard``).
        4. Estimate size from labels and title.
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
    mode: StoryMode | None = profile.default_mode
    story_mode = _extract_mode(issue.labels)

    resolved_story_id = story_id if story_id is not None else f"STORY-{issue_nr}"
    story_number = _story_number_from_id(resolved_story_id) or issue.number

    return StoryContext(
        project_key=project_key,
        story_number=story_number,
        story_id=resolved_story_id,
        story_type=story_type,
        execution_route=mode,
        mode=story_mode,
        issue_nr=issue.number,
        title=issue.title,
        story_size=estimate_size(list(issue.labels), issue.title),
        project_root=project_root,
        participating_repos=[repo],
        labels=list(issue.labels),
        created_at=datetime.now(tz=UTC),
    )


def _story_number_from_id(story_id: str) -> int | None:
    suffix = story_id.rsplit("-", maxsplit=1)[-1]
    if not suffix.isdigit():
        return None
    return int(suffix)
