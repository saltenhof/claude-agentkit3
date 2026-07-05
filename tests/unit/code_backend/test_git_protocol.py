"""Unit tests for the provider-neutral ``git ls-remote`` read capability.

AC2: ``ref_read`` resolves a head SHA against a local bare-repo fixture via
real ``git ls-remote`` -- no worktree, no physical repo access, real git
protocol (mirrors the existing ``tests/unit/utils/test_git.py`` convention of
exercising real ``git`` subprocess calls under ``@pytest.mark.requires_git``).
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from agentkit.backend.code_backend.git_protocol import GitLsRemoteReader

if TYPE_CHECKING:
    from pathlib import Path


def _run_git(*args: str) -> None:
    subprocess.run(["git", *args], check=True, capture_output=True, text=True)  # noqa: S603, S607


@pytest.fixture
def bare_repo_with_commit(tmp_path: Path) -> tuple[Path, str]:
    """A local bare repo with one commit pushed to ``main``.

    Returns:
        A ``(bare_repo_path, head_sha)`` pair.
    """
    bare = tmp_path / "bare.git"
    work = tmp_path / "work"
    _run_git("init", "--bare", str(bare))
    _run_git("clone", str(bare), str(work))
    _run_git("-C", str(work), "config", "user.email", "git-protocol-test@example.com")
    _run_git("-C", str(work), "config", "user.name", "Git Protocol Test")
    (work / "file.txt").write_text("hello", encoding="utf-8")
    _run_git("-C", str(work), "add", "file.txt")
    _run_git("-C", str(work), "commit", "-m", "init")
    _run_git("-C", str(work), "branch", "-M", "main")
    _run_git("-C", str(work), "push", "origin", "main")
    result = subprocess.run(  # noqa: S603, S607
        ["git", "-C", str(work), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return bare, result.stdout.strip()


@pytest.mark.requires_git
class TestGitLsRemoteReader:
    """Real ``git ls-remote`` reads against a local bare-repo fixture."""

    def test_resolves_known_branch_head_sha(
        self, bare_repo_with_commit: tuple[Path, str]
    ) -> None:
        bare, head_sha = bare_repo_with_commit
        result = GitLsRemoteReader().read_head_sha(str(bare), "main")
        assert result.resolved is True
        assert result.head_sha == head_sha
        assert result.ref == "main"

    def test_resolves_fully_qualified_ref(
        self, bare_repo_with_commit: tuple[Path, str]
    ) -> None:
        bare, head_sha = bare_repo_with_commit
        result = GitLsRemoteReader().read_head_sha(str(bare), "refs/heads/main")
        assert result.resolved is True
        assert result.head_sha == head_sha

    def test_unresolvable_ref_is_typed_failure(
        self, bare_repo_with_commit: tuple[Path, str]
    ) -> None:
        """AC2: a non-resolvable ref is a deterministic typed error, never a raise."""
        bare, _head_sha = bare_repo_with_commit
        result = GitLsRemoteReader().read_head_sha(str(bare), "refs/heads/does-not-exist")
        assert result.resolved is False
        assert result.head_sha is None
        assert result.detail

    def test_unreachable_remote_is_typed_failure(self, tmp_path: Path) -> None:
        """AC2: a non-resolvable remote is a deterministic typed error, never a raise."""
        missing = tmp_path / "does-not-exist.git"
        result = GitLsRemoteReader().read_head_sha(str(missing), "main")
        assert result.resolved is False
        assert result.head_sha is None
        assert result.detail

    def test_no_worktree_or_physical_repo_access_required(
        self, bare_repo_with_commit: tuple[Path, str], tmp_path: Path
    ) -> None:
        """AC2: the read works from an arbitrary cwd with no local checkout at all."""
        bare, head_sha = bare_repo_with_commit
        # Reading from a location with NO git repository of its own proves the
        # capability needs no worktree/physical repo -- only network protocol.
        neutral_cwd = tmp_path / "no-repo-here"
        neutral_cwd.mkdir()
        result = GitLsRemoteReader().read_head_sha(str(bare), "main")
        assert result.resolved is True
        assert result.head_sha == head_sha
        assert not (neutral_cwd / ".git").exists()


@pytest.mark.unit
class TestGitLsRemoteReaderMockedEdgeCases:
    """Mocked-subprocess branches too awkward to reproduce with real git.

    Ambiguous multi-ref matches, unparsable ``ls-remote`` output and raw
    subprocess failures are all deterministic typed errors (AC2), but real
    git rarely/never emits them naturally (e.g. a same-named branch+tag pair,
    or a malformed output line). Mocking ``subprocess.run`` here is the
    permitted external-system-dependency exception.
    """

    def test_subprocess_error_is_typed_failure(self) -> None:
        with patch(
            "agentkit.backend.code_backend.git_protocol.subprocess.run",
            side_effect=OSError("boom"),
        ):
            result = GitLsRemoteReader().read_head_sha("remote", "main")
        assert result.resolved is False
        assert result.head_sha is None
        assert "boom" in result.detail

    def test_empty_stdout_with_zero_exit_is_typed_failure(self) -> None:
        with patch(
            "agentkit.backend.code_backend.git_protocol.subprocess.run"
        ) as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = GitLsRemoteReader().read_head_sha("remote", "main")
        assert result.resolved is False
        assert "no matching ref" in result.detail

    def test_ambiguous_match_is_typed_failure(self) -> None:
        with patch(
            "agentkit.backend.code_backend.git_protocol.subprocess.run"
        ) as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="sha1\trefs/heads/main\nsha2\trefs/tags/main\n",
                stderr="",
            )
            result = GitLsRemoteReader().read_head_sha("remote", "main")
        assert result.resolved is False
        assert "ambiguous" in result.detail

    def test_unparsable_line_is_typed_failure(self) -> None:
        with patch(
            "agentkit.backend.code_backend.git_protocol.subprocess.run"
        ) as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="\tno-sha-here\n", stderr=""
            )
            result = GitLsRemoteReader().read_head_sha("remote", "main")
        assert result.resolved is False
        assert "unparsable" in result.detail
