"""Unit tests for :class:`CommitHook` (AG3-036 AC3)."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.telemetry.emitters import MemoryEmitter
from agentkit.backend.telemetry.events import EventType
from agentkit.backend.telemetry.hooks.base import HookContext, HookTrigger
from agentkit.backend.telemetry.hooks.commit_hook import (
    CommitHook,
    command_may_create_commit,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def _context(**overrides: object) -> HookContext:
    base: dict[str, object] = {
        "trigger": HookTrigger.POST_TOOL_USE,
        "story_id": "AG3-001",
        "run_id": "run-1",
        "project_key": "demo",
        "worker_id": "worker-1",
        "tool": "Bash",
        "command": "git commit -m 'work'",
    }
    base.update(overrides)
    return HookContext(**base)  # type: ignore[arg-type]


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _write_commit(repo: Path, filename: str, content: str, message: str) -> str:
    (repo / filename).write_text(content, encoding="utf-8")
    _git(repo, "add", filename)
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-b", "main"], check=True)
    _git(repo, "config", "user.email", "worker@example.test")
    _git(repo, "config", "user.name", "Worker")
    _write_commit(repo, "base.txt", "base\n", "base")
    return repo


def test_increment_commit_emitted_on_git_commit() -> None:
    emitter = MemoryEmitter()
    hook = CommitHook(emitter)

    result = hook.evaluate(
        _context(
            payload={
                "commit_sha": "abc123",
                "repo_name": "demo-repo",
                "files_changed": 3,
            }
        )
    )
    hook.emit(result)

    assert result.triggered is True
    event = result.events[0]
    assert event.event_type is EventType.INCREMENT_COMMIT
    # Mandatory fields (AC3).
    assert event.payload["commit_sha"] == "abc123"
    assert event.payload["repo_name"] == "demo-repo"
    assert event.payload["story_id"] == "AG3-001"
    assert event.payload["worker_id"] == "worker-1"
    assert event.payload["files_changed"] == 3
    assert emitter.all_events[0].event_type is EventType.INCREMENT_COMMIT


@pytest.mark.parametrize(
    "command",
    [
        "git cherry-pick abc123",
        "git revert --no-edit abc123",
        "git merge feature/ag3-147",
        "git rebase origin/main",
    ],
)
def test_increment_commit_emitted_on_commit_producing_git_commands(
    command: str,
) -> None:
    hook = CommitHook(MemoryEmitter())

    result = hook.evaluate(
        _context(
            command=command,
            payload={
                "commit_sha": "abc123",
                "repo_name": "demo-repo",
                "files_changed": 1,
            },
        )
    )

    assert result.triggered is True
    assert result.events[0].event_type is EventType.INCREMENT_COMMIT


def test_increment_commit_emitted_on_mechanical_head_delta_without_git_regex() -> None:
    hook = CommitHook(MemoryEmitter())

    result = hook.evaluate(
        _context(
            command="invoke-local-wrapper-that-commits",
            payload={
                "head_before": "a" * 40,
                "head_after": "b" * 40,
                "repo_name": "demo-repo",
            },
        )
    )

    assert result.triggered is True
    assert result.events[0].payload["commit_sha"] == "b" * 40
    assert result.events[0].payload["repo_name"] == "demo-repo"


@pytest.mark.parametrize(
    ("command", "prepare"),
    [
        (
            "git commit -m work",
            lambda repo: _write_commit(repo, "plain.txt", "plain\n", "plain"),
        ),
        (
            "git cherry-pick side",
            lambda repo: _prepare_cherry_pick(repo),
        ),
        (
            "git am change.patch",
            lambda repo: _prepare_am(repo),
        ),
        (
            "git merge --no-ff side",
            lambda repo: _prepare_merge(repo),
        ),
    ],
)
def test_increment_commit_emitted_from_durable_head_delta_for_commit_paths(
    git_repo: Path,
    tmp_path: Path,
    command: str,
    prepare: Callable[[Path], str],
) -> None:
    """PRE/POST HEAD deltas catch commit-producing paths without regex reliance."""

    snapshot_dir = tmp_path / "snapshots"
    emitter = MemoryEmitter()
    pre_hook = CommitHook(emitter, snapshot_dir=snapshot_dir)
    post_hook = CommitHook(emitter, snapshot_dir=snapshot_dir)
    pre_hook.evaluate(
        _context(
            trigger=HookTrigger.PRE_TOOL_USE,
            command=command,
            payload={"cwd": str(git_repo)},
        )
    )

    prepare(git_repo)

    result = post_hook.evaluate(
        _context(
            command=command,
            payload={"cwd": str(git_repo)},
        )
    )
    post_hook.emit(result)

    assert result.triggered is True
    assert result.events[0].event_type is EventType.INCREMENT_COMMIT
    assert result.events[0].payload["commit_sha"] == _git(git_repo, "rev-parse", "HEAD")
    assert result.events[0].payload["repo_name"] == "repo"


def _prepare_cherry_pick(repo: Path) -> str:
    _git(repo, "checkout", "-b", "side")
    side_sha = _write_commit(repo, "cherry.txt", "cherry\n", "cherry")
    _git(repo, "checkout", "main")
    _git(repo, "cherry-pick", side_sha)
    return side_sha


def _prepare_am(repo: Path) -> str:
    _git(repo, "checkout", "-b", "patch-source")
    patch_sha = _write_commit(repo, "patch.txt", "patch\n", "patch")
    patch = _git(repo, "format-patch", "-1", patch_sha, "--stdout")
    _git(repo, "checkout", "main")
    patch_path = repo / "change.patch"
    patch_path.write_text(patch, encoding="utf-8")
    _git(repo, "am", str(patch_path))
    return patch_sha


def _prepare_merge(repo: Path) -> str:
    _git(repo, "checkout", "-b", "side")
    side_sha = _write_commit(repo, "merge.txt", "merge\n", "merge")
    _git(repo, "checkout", "main")
    _git(repo, "merge", "--no-ff", "side", "-m", "merge side")
    return side_sha


def test_increment_commit_skips_unchanged_mechanical_head() -> None:
    hook = CommitHook(MemoryEmitter())

    result = hook.evaluate(
        _context(
            command="git am patch.mbox",
            payload={
                "head_before": "a" * 40,
                "head_after": "a" * 40,
                "repo_name": "demo-repo",
            },
        )
    )

    assert result.triggered is False


@pytest.mark.parametrize(
    "command",
    [
        "git -C repo cherry-pick abc123",
        "git -c user.name=bot commit -m work",
        "git --work-tree=repo merge feature/ag3-147",
        "git am patch.mbox",
        "git pull --rebase",
    ],
)
def test_command_may_create_commit_handles_git_global_options(command: str) -> None:
    assert command_may_create_commit(command) is True


def test_non_commit_bash_is_skipped() -> None:
    hook = CommitHook(MemoryEmitter())
    result = hook.evaluate(_context(command="git status"))
    assert result.triggered is False


def test_non_bash_tool_is_skipped() -> None:
    hook = CommitHook(MemoryEmitter())
    result = hook.evaluate(_context(tool="Write", command="git commit"))
    assert result.triggered is False


def test_files_changed_defaults_to_zero_for_bad_value() -> None:
    hook = CommitHook(MemoryEmitter())
    result = hook.evaluate(
        _context(payload={"commit_sha": "abc123", "files_changed": "not-a-number"})
    )
    assert result.events[0].payload["files_changed"] == 0
