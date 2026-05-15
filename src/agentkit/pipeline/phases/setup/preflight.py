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
    from agentkit.story_context_manager.story_model import StoryStatus

    checks: list[PreflightCheck] = []
    story: Story | None = None

    # --- Check 1: story exists ---
    story = service.get_story(story_display_id)
    if story is not None:
        checks.append(PreflightCheck(
            name="story_exists",
            passed=True,
            message=f"Story {story_display_id!r} found: {story.title!r}",
        ))
    else:
        checks.append(PreflightCheck(
            name="story_exists",
            passed=False,
            message=f"Story {story_display_id!r} not found in StoryService",
        ))

    # --- Check 2: status_approved ---
    if story is not None:
        is_approved = story.status is StoryStatus.APPROVED
        checks.append(PreflightCheck(
            name="status_approved",
            passed=is_approved,
            message=(
                f"Story {story_display_id!r} is {story.status.value!r}"
                if not is_approved
                else f"Story {story_display_id!r} is Approved"
            ),
        ))
    else:
        checks.append(PreflightCheck(
            name="status_approved",
            passed=False,
            message="Cannot check status: story could not be fetched",
        ))

    # --- Check 3: dependencies_closed ---
    if story is not None:
        # Load dependency IDs from authoritative repository if available (Befund 8)
        if dependency_repository is not None:
            dep_edges = dependency_repository.list_for_story(story_display_id)
            dep_ids = [edge.depends_on_story_id for edge in dep_edges]
        else:
            # Legacy fallback: story.dependencies (may be [] for DB-loaded stories
            # that don't have the join populated)
            dep_ids = list(story.dependencies)

        open_deps: list[str] = []
        for dep_id in dep_ids:
            dep = service.get_story(dep_id)
            if dep is None or dep.status is not StoryStatus.DONE:
                dep_status = dep.status.value if dep is not None else "missing"
                open_deps.append(f"{dep_id} ({dep_status})")

        if open_deps:
            checks.append(PreflightCheck(
                name="dependencies_closed",
                passed=False,
                message=f"Open dependencies: {', '.join(open_deps)}",
            ))
        else:
            dep_count = len(dep_ids)
            checks.append(PreflightCheck(
                name="dependencies_closed",
                passed=True,
                message=(
                    "No dependencies"
                    if dep_count == 0
                    else f"All {dep_count} dependenc{'y' if dep_count == 1 else 'ies'} done"
                ),
            ))
    else:
        checks.append(PreflightCheck(
            name="dependencies_closed",
            passed=False,
            message="Cannot check dependencies: story could not be fetched",
        ))

    all_passed = all(c.passed for c in checks)
    return PreflightResult(
        passed=all_passed,
        checks=tuple(checks),
        story=story,
    )
