"""Git utility helpers -- worktree creation and removal.

Thin wrappers around ``git worktree`` sub-commands.  All operations are
deterministic: no LLM involvement, no side effects beyond the git
repository state.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from agentkit.exceptions import WorktreeError

if TYPE_CHECKING:
    from pathlib import Path


def create_worktree(repo_root: Path, worktree_path: Path, branch: str) -> None:
    """Create a git worktree at *worktree_path* on a new *branch*.

    Runs ``git -C <repo_root> worktree add <worktree_path> -b <branch>``.

    Args:
        repo_root: Root directory of the git repository.
        worktree_path: Absolute path where the worktree will be created.
        branch: Name of the new branch to create inside the worktree.

    Raises:
        WorktreeError: If *worktree_path* already exists on disk.
        WorktreeError: If the ``git worktree add`` command exits non-zero.
    """
    if worktree_path.exists():
        raise WorktreeError(
            f"Worktree path already exists: {worktree_path}",
            detail={"worktree_path": str(worktree_path)},
        )

    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "worktree",
            "add",
            str(worktree_path),
            "-b",
            branch,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise WorktreeError(
            f"git worktree add failed (exit {result.returncode}): {stderr}",
            detail={
                "repo_root": str(repo_root),
                "worktree_path": str(worktree_path),
                "branch": branch,
                "stderr": result.stderr,
                "stdout": result.stdout,
            },
        )


def remove_worktree(repo_root: Path, worktree_path: Path) -> None:
    """Remove a git worktree at *worktree_path*.

    Runs ``git -C <repo_root> worktree remove --force <worktree_path>``.
    If *worktree_path* does not exist the function returns without error
    (idempotent).

    Args:
        repo_root: Root directory of the git repository.
        worktree_path: Absolute path of the worktree to remove.

    Raises:
        WorktreeError: If the ``git worktree remove`` command exits non-zero
            for a reason other than the path not existing.
    """
    if not worktree_path.exists():
        return

    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "worktree",
            "remove",
            "--force",
            str(worktree_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise WorktreeError(
            f"git worktree remove failed (exit {result.returncode}): {stderr}",
            detail={
                "repo_root": str(repo_root),
                "worktree_path": str(worktree_path),
                "stderr": result.stderr,
                "stdout": result.stdout,
            },
        )
