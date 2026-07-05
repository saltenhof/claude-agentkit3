"""Unit tests for agentkit.backend.utils.git -- worktree creation and removal."""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from agentkit.backend.exceptions import WorktreeError
from agentkit.backend.utils.git import (
    remove_worktree,
    tree_hash_of_commit,
)


def _add_worktree(repo_root: Path, worktree_path: Path, branch: str) -> None:
    """Create a worktree via a raw ``git worktree add`` (test setup helper).

    AG3-145 Teilschritt E: ``utils.git.create_worktree`` was removed (worktree
    provisioning is an edge command now), so ``remove_worktree`` tests seed their
    fixture worktree with a bare git subprocess instead of the deleted helper.
    """
    subprocess.run(
        ["git", "-C", str(repo_root), "worktree", "add", str(worktree_path), "-b", branch],
        check=True,
        capture_output=True,
    )


@pytest.mark.requires_git
class TestTreeHashOfCommit:
    """Tests for tree_hash_of_commit (AG3-056 FIX-4)."""

    def test_returns_tree_hash_of_head(self, git_repo: Path) -> None:
        head = subprocess.run(
            ["git", "-C", str(git_repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        expected = subprocess.run(
            ["git", "-C", str(git_repo), "rev-parse", "HEAD^{tree}"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert tree_hash_of_commit(git_repo, head) == expected

    def test_unknown_commit_fails_closed(self, git_repo: Path) -> None:
        with pytest.raises(WorktreeError, match="rev-parse"):
            tree_hash_of_commit(git_repo, "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef")


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Minimal git repo with an initial commit for worktree tests."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "test@test.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "Test"],
        check=True,
        capture_output=True,
    )
    # An initial commit is required before `git worktree add -b` works.
    (tmp_path / "README.md").write_text("init", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "."],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-m", "init"],
        check=True,
        capture_output=True,
    )
    return tmp_path


@pytest.mark.requires_git
class TestRemoveWorktree:
    """Tests for remove_worktree."""

    def test_removes_existing_worktree(self, git_repo: Path, tmp_path: Path) -> None:
        """remove_worktree removes a previously created worktree."""
        worktree_path = tmp_path / "wt-to-remove"
        _add_worktree(git_repo, worktree_path, "story/AG3-010")
        assert worktree_path.exists()
        remove_worktree(git_repo, worktree_path)
        assert not worktree_path.exists()

    def test_nonexistent_path_is_idempotent(
        self, git_repo: Path, tmp_path: Path
    ) -> None:
        """remove_worktree does not raise when the path does not exist."""
        nonexistent = tmp_path / "does-not-exist"
        # Must not raise
        remove_worktree(git_repo, nonexistent)

    def test_externally_deleted_path_cleans_git_metadata(
        self, git_repo: Path, tmp_path: Path
    ) -> None:
        """remove_worktree prunes git metadata when directory was deleted externally.

        Simulates the scenario where a worktree directory is removed without
        going through git (e.g. ``rm -rf``).  The git worktree metadata still
        refers to the old path.  ``remove_worktree`` must clean up that
        metadata so the path can be reused.
        """
        worktree_path = tmp_path / "wt-external-delete"
        _add_worktree(git_repo, worktree_path, "story/AG3-011")
        assert worktree_path.exists()

        # Simulate external deletion — bypass git entirely.
        shutil.rmtree(str(worktree_path))
        assert not worktree_path.exists()

        # Must not raise even though path is absent.
        remove_worktree(git_repo, worktree_path)

        # Verify metadata was pruned: the same path can now host a new worktree.
        _add_worktree(git_repo, worktree_path, "story/AG3-011b")
        assert worktree_path.exists()

    def test_remove_worktree_requires_repo_root(
        self, git_repo: Path, tmp_path: Path
    ) -> None:
        """remove_worktree rejects nested repo paths the same way as create."""
        worktree_path = tmp_path / "wt-remove-root-check"
        _add_worktree(git_repo, worktree_path, "story/AG3-012")
        nested = git_repo / "nested-remove"
        nested.mkdir()

        with pytest.raises(WorktreeError, match="repository root"):
            remove_worktree(nested, worktree_path)

    def test_git_worktree_remove_failure_is_wrapped(
        self, git_repo: Path, tmp_path: Path
    ) -> None:
        """remove_worktree wraps git failures for non-worktree directories."""
        not_a_worktree = tmp_path / "not-a-worktree"
        not_a_worktree.mkdir()

        with pytest.raises(WorktreeError, match="git worktree remove failed"):
            remove_worktree(git_repo, not_a_worktree)
