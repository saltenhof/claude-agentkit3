"""Preflight checks for the setup phase.

All checks run even if earlier ones fail (fail-closed, collect all errors).
Checks are performed against the StoryService (story_context_manager BC),
not GitHub — GitHub was the v2 approach, replaced in FK-22 §22.4.1.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentkit.execution_planning.repository import StoryDependencyRepository
    from agentkit.story_context_manager.service import StoryService
    from agentkit.story_context_manager.story_model import Story


@dataclass(frozen=True)
class PreflightCheck:
    """A single preflight check result.

    Attributes:
        name: Short identifier for the check (e.g. ``"story_exists"``).
        passed: Whether the check passed.
        message: Human-readable description of the outcome.
    """

    name: str
    passed: bool
    message: str


@dataclass(frozen=True)
class PreflightResult:
    """Result of all preflight checks.

    Attributes:
        passed: ``True`` only if every individual check passed.
        checks: Tuple of all check results, in execution order.
        story: The fetched Story entity, or ``None`` if the story
            could not be retrieved.
    """

    passed: bool
    checks: tuple[PreflightCheck, ...]
    story: Story | None = None


def run_preflight(
    story_display_id: str,
    service: StoryService,
    *,
    dependency_repository: StoryDependencyRepository | None = None,
) -> PreflightResult:
    """Run all preflight checks against a StoryService.

    Checks (all run regardless of earlier failures):
        1. **story_exists** -- ``StoryService.get_story`` returns a Story.
        2. **status_approved** -- story status is ``StoryStatus.APPROVED``.
        3. **dependencies_closed** -- all dependency story_display_ids
           have ``StoryStatus.DONE``. Dependencies are loaded from
           ``dependency_repository.list_for_story`` when provided, or
           fall back to ``story.dependencies`` (which may be empty if
           the Story was loaded without the join).

    Args:
        story_display_id: Story display ID to validate (e.g. ``"AK3-042"``).
        service: Authoritative StoryService instance.
        dependency_repository: Optional StoryDependencyRepository. When
            provided, dependency IDs are loaded from the repository
            (authoritative source). When ``None``, falls back to
            ``story.dependencies`` (legacy / in-memory path).

    Returns:
        A ``PreflightResult`` containing all check outcomes.
    """
    story = service.get_story(story_display_id)
    checks = (
        _check_story_exists(story_display_id, story),
        _check_status_approved(story_display_id, story),
        _check_dependencies_closed(story, service, dependency_repository),
    )
    return PreflightResult(
        passed=all(c.passed for c in checks),
        checks=checks,
        story=story,
    )


def _check_story_exists(story_display_id: str, story: Story | None) -> PreflightCheck:
    """Return the story_exists check result."""
    if story is None:
        return PreflightCheck(
            name="story_exists",
            passed=False,
            message=f"Story {story_display_id!r} not found in StoryService",
        )
    return PreflightCheck(
        name="story_exists",
        passed=True,
        message=f"Story {story_display_id!r} found: {story.title!r}",
    )


def _check_status_approved(
    story_display_id: str, story: Story | None,
) -> PreflightCheck:
    """Return the status_approved check result."""
    from agentkit.story_context_manager.story_model import StoryStatus

    if story is None:
        return PreflightCheck(
            name="status_approved",
            passed=False,
            message="Cannot check status: story could not be fetched",
        )
    if story.status is StoryStatus.APPROVED:
        return PreflightCheck(
            name="status_approved",
            passed=True,
            message=f"Story {story_display_id!r} is Approved",
        )
    return PreflightCheck(
        name="status_approved",
        passed=False,
        message=f"Story {story_display_id!r} is {story.status.value!r}",
    )


def _check_dependencies_closed(
    story: Story | None,
    service: StoryService,
    dependency_repository: StoryDependencyRepository | None,
) -> PreflightCheck:
    """Return the dependencies_closed check result."""
    if story is None:
        return PreflightCheck(
            name="dependencies_closed",
            passed=False,
            message="Cannot check dependencies: story could not be fetched",
        )

    dep_ids = _resolve_dependency_ids(story, dependency_repository)
    open_deps = _open_dependencies(dep_ids, service)
    if open_deps:
        return PreflightCheck(
            name="dependencies_closed",
            passed=False,
            message=f"Open dependencies: {', '.join(open_deps)}",
        )
    return PreflightCheck(
        name="dependencies_closed",
        passed=True,
        message=_dependencies_passed_message(len(dep_ids)),
    )


def _resolve_dependency_ids(
    story: Story,
    dependency_repository: StoryDependencyRepository | None,
) -> list[str]:
    """Resolve dependency display IDs from the authoritative repo or the story join."""
    # Befund 8: authoritative source is the dependency repository when available.
    if dependency_repository is not None:
        return [
            edge.depends_on_story_id
            for edge in dependency_repository.list_for_story(story.story_display_id)
        ]
    # Fallback for DB-loaded stories whose dependencies join is not populated.
    return list(story.dependencies)


def _open_dependencies(dep_ids: list[str], service: StoryService) -> list[str]:
    """Return ``[ "dep_id (status)" ]`` for every unfinished dependency."""
    from agentkit.story_context_manager.story_model import StoryStatus

    open_deps: list[str] = []
    for dep_id in dep_ids:
        dep = service.get_story(dep_id)
        if dep is None:
            open_deps.append(f"{dep_id} (missing)")
        elif dep.status is not StoryStatus.DONE:
            open_deps.append(f"{dep_id} ({dep.status.value})")
    return open_deps


def _dependencies_passed_message(dep_count: int) -> str:
    """Build the message for a passing dependencies_closed check."""
    if dep_count == 0:
        return "No dependencies"
    noun = "dependency" if dep_count == 1 else "dependencies"
    return f"All {dep_count} {noun} done"
