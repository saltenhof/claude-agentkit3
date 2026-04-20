"""Unit tests for agentkit.utils.git -- worktree creation and removal."""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from agentkit.exceptions import WorktreeError
from agentkit.utils.git import create_worktree, remove_worktree


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
class TestCreateWorktree:
    """Tests for create_worktree."""

    def test_creates_directory(self, git_repo: Path, tmp_path: Path) -> None:
        """create_worktree produces a directory at the requested path."""
        worktree_path = tmp_path / "wt" / "my-worktree"
        create_worktree(git_repo, worktree_path, "story/AG3-001")
        assert worktree_path.is_dir()

    def test_creates_branch(self, git_repo: Path, tmp_path: Path) -> None:
        """create_worktree creates the specified branch in the repository."""
        worktree_path = tmp_path / "wt-branch"
        create_worktree(git_repo, worktree_path, "story/AG3-002")
        result = subprocess.run(
            ["git", "-C", str(git_repo), "branch", "--list", "story/AG3-002"],
            capture_output=True,
            text=True,
        )
        assert "story/AG3-002" in result.stdout

    def test_existing_path_raises_worktree_error(
        self, git_repo: Path, tmp_path: Path
    ) -> None:
        """create_worktree raises WorktreeError when the path already exists."""
        existing = tmp_path / "already-there"
        existing.mkdir()
        with pytest.raises(WorktreeError, match="already exists"):
            create_worktree(git_repo, existing, "story/AG3-003")

    def test_invalid_repo_raises_worktree_error(self, tmp_path: Path) -> None:
        """create_worktree raises WorktreeError when git command fails."""
        not_a_repo = tmp_path / "not-a-repo"
        not_a_repo.mkdir()
        worktree_path = tmp_path / "wt-fail"
        with pytest.raises(WorktreeError):
            create_worktree(not_a_repo, worktree_path, "story/AG3-004")

    def test_nested_repo_path_is_rejected(self, git_repo: Path, tmp_path: Path) -> None:
        """create_worktree requires the actual repo root, not a nested path."""
        nested = git_repo / "nested"
        nested.mkdir()

        with pytest.raises(WorktreeError, match="repository root"):
            create_worktree(nested, tmp_path / "wt-nested", "story/AG3-005")

    def test_git_worktree_add_failure_is_wrapped(
        self, git_repo: Path, tmp_path: Path
    ) -> None:
        """create_worktree wraps git failures after root validation succeeds."""
        create_worktree(git_repo, tmp_path / "wt-existing-branch", "story/AG3-006")

        with pytest.raises(WorktreeError, match="git worktree add failed"):
            create_worktree(git_repo, tmp_path / "wt-duplicate-branch", "story/AG3-006")


@pytest.mark.requires_git
class TestRemoveWorktree:
    """Tests for remove_worktree."""

    def test_removes_existing_worktree(self, git_repo: Path, tmp_path: Path) -> None:
        """remove_worktree removes a previously created worktree."""
        worktree_path = tmp_path / "wt-to-remove"
        create_worktree(git_repo, worktree_path, "story/AG3-010")
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
        create_worktree(git_repo, worktree_path, "story/AG3-011")
        assert worktree_path.exists()

        # Simulate external deletion — bypass git entirely.
        shutil.rmtree(str(worktree_path))
        assert not worktree_path.exists()

        # Must not raise even though path is absent.
        remove_worktree(git_repo, worktree_path)

        # Verify metadata was pruned: the same path can now host a new worktree.
        create_worktree(git_repo, worktree_path, "story/AG3-011b")
        assert worktree_path.exists()

    def test_remove_worktree_requires_repo_root(
        self, git_repo: Path, tmp_path: Path
    ) -> None:
        """remove_worktree rejects nested repo paths the same way as create."""
        worktree_path = tmp_path / "wt-remove-root-check"
        create_worktree(git_repo, worktree_path, "story/AG3-012")
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
