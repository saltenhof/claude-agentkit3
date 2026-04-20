"""Git utility helpers -- worktree creation and removal.

Thin wrappers around ``git worktree`` sub-commands.  All operations are
deterministic: no LLM involvement, no side effects beyond the git
repository state.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from agentkit.exceptions import WorktreeError


def _ensure_repo_root(repo_root: Path) -> None:
    """Validate that ``repo_root`` is itself a Git repository root."""

    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "rev-parse",
            "--show-toplevel",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise WorktreeError(
            "git repository root validation failed",
            detail={
                "repo_root": str(repo_root),
                "stderr": result.stderr,
                "stdout": result.stdout,
            },
        )

    top_level = result.stdout.strip()
    if not top_level:
        raise WorktreeError(
            "git repository root validation returned an empty path",
            detail={"repo_root": str(repo_root)},
        )

    if Path(top_level).resolve() != repo_root.resolve():
        raise WorktreeError(
            "repo_root must point at the repository root",
            detail={
                "repo_root": str(repo_root),
                "resolved_repo_root": str(repo_root.resolve()),
                "git_top_level": str(Path(top_level).resolve()),
            },
        )


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
    _ensure_repo_root(repo_root)

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

    If *worktree_path* exists on disk, runs
    ``git -C <repo_root> worktree remove --force <worktree_path>``.

    If *worktree_path* does not exist (e.g. deleted externally without going
    through git), the directory removal is skipped but
    ``git worktree prune`` is still executed so that any dangling git
    metadata is cleaned up.  This makes the function fully idempotent.

    Args:
        repo_root: Root directory of the git repository.
        worktree_path: Absolute path of the worktree to remove.

    Raises:
        WorktreeError: If the ``git worktree remove`` command exits non-zero.
    """
    _ensure_repo_root(repo_root)

    if worktree_path.exists():
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
        return

    # Path absent on disk: git metadata may still be registered.
    # ``git worktree prune`` removes metadata for all missing worktrees.
    subprocess.run(
        ["git", "-C", str(repo_root), "worktree", "prune"],
        capture_output=True,
        text=True,
    )
