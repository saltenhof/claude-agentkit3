"""Preflight Check 4 — ``dependencies_done`` (FK-22 §22.3.1).

All ``StoryDependency`` predecessors of the story are in status ``Done``.
Dependency IDs come from the authoritative
:class:`StoryDependencyRepository` when provided, else from the Story's
in-memory ``dependencies`` join.
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
    from agentkit.backend.execution_planning.repository import StoryDependencyRepository
    from agentkit.backend.governance.setup_preflight_gate.preflight import PreflightContext
    from agentkit.backend.story_context_manager.service import StoryService
    from agentkit.backend.story_context_manager.story_model import Story

_CHECK_ID = PreflightCheckId.DEPENDENCIES_DONE


def check(ctx: PreflightContext) -> PreflightCheckResult:
    """Verify all dependencies are ``Done`` (FK-22 §22.3.1, Check 4).

    Args:
        ctx: The preflight context.

    Returns:
        ``PASS`` when every dependency story is ``Done``; ``FAIL`` when at
        least one is open or missing.
    """
    story = ctx.story
    if story is None:
        return PreflightCheckResult(
            check_id=_CHECK_ID,
            status=PreflightStatus.FAIL,
            detail="Cannot check dependencies: story could not be fetched",
            cleanup_hint=(
                "The story could not be fetched; resolve the story_exists "
                "failure first, then restart the story."
            ),
        )

    dep_ids = _resolve_dependency_ids(story, ctx.dependency_repository)
    open_deps = _open_dependencies(dep_ids, ctx.service)
    if open_deps:
        joined = ", ".join(open_deps)
        return PreflightCheckResult(
            check_id=_CHECK_ID,
            status=PreflightStatus.FAIL,
            detail=f"Open dependencies: {joined}",
            cleanup_hint=(
                f"Bring the open dependencies to Done before starting: {joined}"
            ),
        )
    return PreflightCheckResult(
        check_id=_CHECK_ID,
        status=PreflightStatus.PASS,
        detail=_passed_message(len(dep_ids)),
    )


def _resolve_dependency_ids(
    story: Story,
    dependency_repository: StoryDependencyRepository | None,
) -> list[str]:
    """Resolve dependency IDs from the authoritative repo or the story join."""
    if dependency_repository is not None:
        return [
            edge.depends_on_story_id
            for edge in dependency_repository.list_for_story(story.story_display_id)
        ]
    return list(story.dependencies)


def _open_dependencies(dep_ids: list[str], service: StoryService) -> list[str]:
    """Return ``["dep_id (status)"]`` for every unfinished dependency."""
    open_deps: list[str] = []
    for dep_id in dep_ids:
        dep = service.get_story(dep_id)
        if dep is None:
            open_deps.append(f"{dep_id} (missing)")
        elif dep.status is not StoryStatus.DONE:
            open_deps.append(f"{dep_id} ({dep.status.value})")
    return open_deps


def _passed_message(dep_count: int) -> str:
    """Build the PASS message for the dependencies_done check."""
    if dep_count == 0:
        return "No dependencies"
    noun = "dependency" if dep_count == 1 else "dependencies"
    return f"All {dep_count} {noun} done"
