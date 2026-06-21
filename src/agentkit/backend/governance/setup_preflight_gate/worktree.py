"""Worktree setup for the setup phase.

Implements the multi-repository setup contract from FK-22 §22.6.2:
one equal worktree per participating repository, all using branch
``story/{story_id}``.
"""

from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.backend.boundary.shared.time import now_iso
from agentkit.backend.exceptions import WorktreeError
from agentkit.backend.utils.git import branch_exists, create_worktree, remove_worktree
from agentkit.backend.utils.io import atomic_write_text

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.backend.config.models import ProjectConfig, RepositoryConfig
    from agentkit.backend.story_context_manager.models import StoryContext


class RepoNotFoundError(WorktreeError):
    """Raised when a participating repo is absent from project config."""


@dataclass(frozen=True)
class WorktreeResult:
    """Result of a successful repo-specific worktree setup."""

    success: bool
    worktree_path: Path
    repo_name: str
    branch: str


def setup_worktrees(
    story_id: str,
    context: StoryContext,
    project: ProjectConfig,
    *,
    project_root: Path,
    base_ref: str = "main",
) -> list[WorktreeResult]:
    """Create one worktree per participating repo.

    Repo names are resolved against ``project.repositories[].name``.
    If any repo fails after earlier worktrees were created, those
    worktrees are removed best-effort before the original failure is
    re-raised.

    Args:
        story_id: Story display identifier.
        context: Story context containing ``participating_repos``.
        project: Target project configuration.
        project_root: Root directory used to resolve relative repo paths.
        base_ref: Base reference for the new branch.

    Returns:
        Successful worktree setup results in the same order as
        ``context.participating_repos``.

    Raises:
        RepoNotFoundError: If a participating repo name is not configured.
        WorktreeError: If a git worktree operation fails.
    """
    repo_lookup = {repo.name: repo for repo in project.repositories}
    created: list[tuple[Path, WorktreeResult]] = []

    try:
        for repo_name in context.participating_repos:
            repo = repo_lookup.get(repo_name)
            if repo is None:
                raise RepoNotFoundError(
                    f"Participating repo {repo_name!r} is not configured",
                    detail={
                        "repo_name": repo_name,
                        "configured_repos": sorted(repo_lookup),
                    },
                )
            repo_root = _resolve_repo_root(project_root, repo)
            result = setup_worktree(
                story_id,
                repo,
                repo_root=repo_root,
                base_ref=base_ref,
            )
            created.append((repo_root, result))
            write_story_marker(
                result.worktree_path,
                story_id=story_id,
                project_key=context.project_key,
                run_id=result.worktree_path.name,
            )
    except WorktreeError:
        for repo_root, result in reversed(created):
            with contextlib.suppress(WorktreeError):
                remove_worktree(repo_root, result.worktree_path)
        raise

    return [result for _, result in created]


def write_story_marker(
    worktree_path: Path,
    *,
    story_id: str,
    project_key: str,
    run_id: str,
) -> Path:
    """Write the FK-36 story marker used by PostCompact epoch scoping."""
    marker_path = worktree_path / ".agentkit-story.json"
    payload = {
        "story_id": story_id,
        "project_key": project_key,
        "run_id": run_id,
        "created_at": now_iso(),
    }
    atomic_write_text(
        marker_path,
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        newline="",
    )
    return marker_path


def setup_worktree(
    story_id: str,
    repo: RepositoryConfig,
    *,
    repo_root: Path,
    base_ref: str = "main",
) -> WorktreeResult:
    """Create the story branch worktree for one repository.

    Args:
        story_id: Story display identifier.
        repo: Repository entry from ``project.repositories``.
        repo_root: Resolved repository root.
        base_ref: Base reference for the new branch.

    Returns:
        A successful worktree result.

    Raises:
        WorktreeError: If the story branch already exists or the worktree
            cannot be created.
    """
    branch = f"story/{story_id}"
    if branch_exists(repo_root, branch):
        raise WorktreeError(
            f"Story branch already exists in repo {repo.name!r}: {branch}",
            detail={"repo_name": repo.name, "repo_root": str(repo_root), "branch": branch},
        )

    worktree_path = repo_root / "worktrees" / story_id
    create_worktree(
        repo_root=repo_root,
        worktree_path=worktree_path,
        branch=branch,
        base_ref=base_ref,
    )
    return WorktreeResult(
        success=True,
        worktree_path=worktree_path,
        repo_name=repo.name,
        branch=branch,
    )


def _resolve_repo_root(project_root: Path, repo: RepositoryConfig) -> Path:
    """Resolve a configured repo path relative to the target project root."""
    if repo.path.is_absolute():
        return repo.path
    return project_root / repo.path
