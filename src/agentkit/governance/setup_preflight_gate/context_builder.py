"""Build StoryContext from a GitHub issue."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentkit.governance.errors import StoryModeResolutionError
from agentkit.integrations.github.issues import get_issue
from agentkit.story_context_manager.models import StoryContext
from agentkit.story_context_manager.sizing import estimate_size
from agentkit.story_context_manager.story_model import WireStoryMode
from agentkit.story_context_manager.types import StoryMode, StoryType, get_profile

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.story_context_manager.service import StoryService


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
    """Extract the fast/standard mode from issue labels (legacy/standalone only).

    The fast/standard ``mode`` is a SEPARATE axis from the
    ``execution_route`` (EXECUTION/EXPLORATION) path. A ``fast`` label
    (AG3-018) opts the run into fast mode; everything else is ``standard``.

    FIX-1 (FK-24 §24.3.3, CLAUDE.md SINGLE SOURCE OF TRUTH): GitHub fields are
    setup INPUT, NOT operative truth. The authoritative ``mode`` is the one
    persisted by ``StoryService`` (``Story.mode``); :func:`build_story_context`
    reads it from there. This label-based extractor remains ONLY for the
    standalone/legacy path where no ``StoryService`` record is available.

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


def _resolve_authoritative_mode(
    story_service: StoryService | None,
    story_display_id: str,
    labels: tuple[str, ...],
) -> WireStoryMode:
    """Resolve the operative fast/standard ``mode`` (FIX-1, FK-24 §24.3.3).

    The AUTHORITATIVE source is the ``StoryService`` record (``Story.mode``); the
    GitHub label is only the legacy/standalone fallback when no service is wired.
    Fail-closed (CLAUDE.md FAIL-CLOSED): a wired service that does not know the
    story raises :class:`StoryModeResolutionError` rather than silently defaulting
    to a label-derived or ``standard`` mode (an unverifiable mode would let an
    invalid Fast/Standard run proceed).

    Args:
        story_service: The authoritative ``StoryService`` (``None`` =>
            standalone/legacy; the label fallback then applies).
        story_display_id: The story display ID used to look the record up.
        labels: Issue labels (the legacy fallback source only).

    Returns:
        The authoritative :class:`WireStoryMode`.

    Raises:
        StoryModeResolutionError: When a service is wired but the story record
            is missing.
    """
    if story_service is None:
        return _extract_mode(labels)
    story = story_service.get_story(story_display_id)
    if story is None:
        raise StoryModeResolutionError(
            f"cannot resolve the authoritative mode: story {story_display_id!r} "
            "is not in the StoryService store (FIX-1, fail-closed -- the GitHub "
            "label is not operative truth, FK-24 §24.3.3)",
            detail={"story_display_id": story_display_id},
        )
    # ``Story.mode`` is ``WireStoryMode | None``; ``None`` (an older record
    # created before the mode field) is the standard default.
    return story.mode if story.mode is not None else WireStoryMode.STANDARD


def build_story_context(
    owner: str,
    repo: str,
    issue_nr: int,
    project_root: Path,
    project_key: str,
    story_id: str | None = None,
    *,
    story_service: StoryService | None = None,
) -> StoryContext:
    """Build a ``StoryContext`` by reading a GitHub issue.

    Steps:
        1. Fetch the issue via :func:`~agentkit.integrations.github.issues.get_issue`.
        2. Extract ``story_type`` from labels.
        3. Determine execution route from the story-type profile's default.
        3a. Resolve the fast/standard ``mode`` axis (FK-24 §24.3.3) from the
            AUTHORITATIVE ``StoryService`` record (FIX-1) -- NOT from labels;
            GitHub fields are setup INPUT, not operative truth (CLAUDE.md). The
            label is the standalone/legacy fallback only.
        4. Estimate size from labels and title.
        5. Generate ``story_id`` if not provided.
        6. Build and return the ``StoryContext`` (the model enforces fast-only-
           for-impl/bugfix fail-closed, AC7).

    Args:
        owner: GitHub repository owner.
        repo: GitHub repository name.
        issue_nr: Issue number to read.
        project_root: Path to the target project root.
        story_id: Optional explicit story ID.  If ``None``, derived
            as ``"STORY-{issue_nr}"``.
        story_service: The authoritative ``StoryService`` (FIX-1). When wired the
            operative ``mode`` is read from its record; when ``None`` the
            standalone/legacy label fallback applies.

    Returns:
        Populated ``StoryContext`` with all fields from the issue.
    """
    issue = get_issue(owner, repo, issue_nr)

    story_type = _extract_story_type(issue.labels)
    profile = get_profile(story_type)
    mode: StoryMode | None = profile.default_mode

    resolved_story_id = story_id if story_id is not None else f"STORY-{issue_nr}"
    story_mode = _resolve_authoritative_mode(
        story_service, resolved_story_id, issue.labels
    )
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
