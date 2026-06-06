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


def create_worktree(
    repo_root: Path,
    worktree_path: Path,
    branch: str,
    base_ref: str | None = None,
) -> None:
    """Create a git worktree at *worktree_path* on a new *branch*.

    Runs ``git -C <repo_root> worktree add <worktree_path> -b <branch>``
    and appends ``base_ref`` when supplied.

    Args:
        repo_root: Root directory of the git repository.
        worktree_path: Absolute path where the worktree will be created.
        branch: Name of the new branch to create inside the worktree.
        base_ref: Optional base reference for the new branch.

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

    command = [
        "git",
        "-C",
        str(repo_root),
        "worktree",
        "add",
        str(worktree_path),
        "-b",
        branch,
    ]
    if base_ref is not None:
        command.append(base_ref)

    result = subprocess.run(
        command,
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
                "base_ref": base_ref,
                "stderr": result.stderr,
                "stdout": result.stdout,
            },
        )


def branch_exists(repo_root: Path, branch: str) -> bool:
    """Return whether a local branch exists in a repository.

    Args:
        repo_root: Root directory of the git repository.
        branch: Branch name to check.

    Raises:
        WorktreeError: If ``repo_root`` is not a git repository root.
    """
    _ensure_repo_root(repo_root)
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/heads/{branch}",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise WorktreeError(
        f"git branch existence check failed (exit {result.returncode})",
        detail={
            "repo_root": str(repo_root),
            "branch": branch,
            "stderr": result.stderr,
            "stdout": result.stdout,
        },
    )


def tree_hash_of_commit(repo_root: Path, commit_sha: str) -> str:
    """Return the git tree hash of a commit (``rev-parse <commit>^{tree}``).

    Used by the pre-merge scan runner (AG3-056 FIX-4) to derive the
    ``tree_hash`` of the PROVEN candidate commit for the commit-bound
    attestation — never from a local ``HEAD``. The consumer asserts
    ``tree_hash(scan) == tree_hash(merge)`` (FK-29 §29.1a.3).

    Args:
        repo_root: Root directory of the git repository.
        commit_sha: The commit whose tree hash is requested.

    Returns:
        The 40-char (or longer, for SHA-256 repos) tree object id.

    Raises:
        WorktreeError: When the commit is unknown or git exits non-zero
            (fail-closed — the caller must not stamp an empty tree hash).
    """
    result = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", f"{commit_sha}^{{tree}}"],
        capture_output=True,
        text=True,
    )
    tree = result.stdout.strip()
    if result.returncode != 0 or not tree:
        raise WorktreeError(
            f"git rev-parse {commit_sha}^{{tree}} failed (exit {result.returncode})",
            detail={
                "repo_root": str(repo_root),
                "commit_sha": commit_sha,
                "stderr": result.stderr,
                "stdout": result.stdout,
            },
        )
    return tree


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
