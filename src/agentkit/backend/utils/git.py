"""Git utility helpers -- worktree removal + commit tree-hash reads.

Thin wrappers around ``git`` sub-commands. All operations are deterministic:
no LLM involvement, no side effects beyond the git repository state.

AG3-145 sub-step E (SOLL-136, FK-10 §10.2.4a): the setup-side worktree
provisioning primitives (``create_worktree`` / ``branch_exists``) were removed
-- physical worktree provisioning is an edge command now
(``harness_client.projectedge.command_executor``). This module retains ONLY the
primitives the AG3-152 closure/merge block still consumes on the backend:
``remove_worktree`` (``closure.multi_repo_saga``) and ``tree_hash_of_commit``
(``verify_system.pre_merge_runner.scan_runner``).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from agentkit.backend.exceptions import WorktreeError


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
