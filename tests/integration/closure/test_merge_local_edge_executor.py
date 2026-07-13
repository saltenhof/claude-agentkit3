"""Real-git integration coverage for the AG3-152 edge merge executor."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.config.models import (
    SUPPORTED_CONFIG_VERSION,
    Features,
    JenkinsConfig,
    PipelineConfig,
    ProjectConfig,
    RepositoryConfig,
    SonarQubeConfig,
)
from agentkit.backend.control_plane.models import (
    MergeLocalCommandPayload,
    MergeLocalRepository,
)
from agentkit.harness_client.projectedge.merge_local import execute_merge_local

if TYPE_CHECKING:
    from pathlib import Path

_STORY_ID = "AG3-152"


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _config(project_root: Path, *repo_ids: str) -> ProjectConfig:
    return ProjectConfig(
        project_key="project-a",
        project_name="Project A",
        repositories=[
            RepositoryConfig(name=repo_id, path=project_root / repo_id)
            for repo_id in repo_ids
        ],
        pipeline=PipelineConfig(
            config_version=SUPPORTED_CONFIG_VERSION,
            features=Features(multi_llm=False),
            ci=JenkinsConfig(available=False, enabled=False),
            sonarqube=SonarQubeConfig(available=False, enabled=False),
        ),
    )


def _repo(project_root: Path) -> tuple[Path, Path, str, str]:
    remote = project_root / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    root = project_root / "api"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "README.md").write_text("main\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-q", "-m", "initial main")
    _git(root, "remote", "add", "origin", str(remote))
    _git(root, "push", "-q", "-u", "origin", "main")
    pre_merge_sha = _git(root, "rev-parse", "HEAD")
    worktree = root / "worktrees" / _STORY_ID
    _git(root, "worktree", "add", "-q", str(worktree), "-b", f"story/{_STORY_ID}")
    _git(worktree, "config", "user.email", "test@example.com")
    _git(worktree, "config", "user.name", "Test")
    (worktree / "README.md").write_text("story\n", encoding="utf-8")
    _git(worktree, "add", "README.md")
    _git(worktree, "commit", "-q", "-m", "story change")
    candidate = _git(worktree, "rev-parse", "HEAD")
    tree_hash = _git(worktree, "rev-parse", "HEAD^{tree}")
    _git(worktree, "push", "-q", "-u", "origin", f"story/{_STORY_ID}")
    return root, worktree, pre_merge_sha, candidate + ":" + tree_hash


def _payload(candidate_and_tree: str, *repo_ids: str) -> MergeLocalCommandPayload:
    candidate, tree_hash = candidate_and_tree.split(":", maxsplit=1)
    return MergeLocalCommandPayload(
        story_id=_STORY_ID,
        project_key="project-a",
        run_id="run-1",
        repositories=[MergeLocalRepository(repo_id=repo_id) for repo_id in repo_ids],
        mode="standard",
        expected_candidate_commit=candidate,
        expected_candidate_tree_hash=tree_hash,
    )


@pytest.mark.requires_git
def test_atomic_merge_and_lost_result_replay_converge(tmp_path: Path) -> None:
    root, worktree, _pre_merge, candidate_and_tree = _repo(tmp_path)
    payload = _payload(candidate_and_tree, "api")

    first = execute_merge_local(
        payload, project_config=_config(tmp_path, "api"), project_root=tmp_path
    )

    candidate = candidate_and_tree.split(":", maxsplit=1)[0]
    assert first.outcome == "merged"
    assert _git(root, "ls-remote", "origin", "refs/heads/main").split()[0] == candidate
    assert not worktree.exists()

    replay = execute_merge_local(
        payload, project_config=_config(tmp_path, "api"), project_root=tmp_path
    )

    assert replay.outcome == "already_merged"
    assert replay.escalated is False
    assert _git(root, "ls-remote", "origin", "refs/heads/main").split()[0] == candidate


@pytest.mark.requires_git
def test_rejected_cas_rolls_back_verified_linked_worktree(tmp_path: Path) -> None:
    root, worktree, pre_merge_sha, candidate_and_tree = _repo(tmp_path)
    hook = tmp_path / "remote.git" / "hooks" / "pre-receive"
    hook.write_text(
        "#!/bin/sh\nwhile read old new ref; do\n"
        "  if [ \"$ref\" = \"refs/heads/main\" ]; then exit 1; fi\n"
        "done\nexit 0\n",
        encoding="utf-8",
    )
    hook.chmod(0o755)

    report = execute_merge_local(
        _payload(candidate_and_tree, "api"),
        project_config=_config(tmp_path, "api"),
        project_root=tmp_path,
    )

    assert report.outcome == "escalated"
    assert report.failure_code == "cas_contention"
    assert report.repositories[0].rolled_back is True
    assert _git(worktree, "rev-parse", "HEAD") == pre_merge_sha
    assert _git(root, "ls-remote", "origin", "refs/heads/main").split()[0] == pre_merge_sha


@pytest.mark.requires_git
def test_two_repositories_escalate_before_any_git_side_effect(tmp_path: Path) -> None:
    root, worktree, pre_merge_sha, candidate_and_tree = _repo(tmp_path)

    report = execute_merge_local(
        _payload(candidate_and_tree, "api", "worker"),
        project_config=_config(tmp_path, "api", "worker"),
        project_root=tmp_path,
    )

    assert report.failure_code == "multi_repo_not_supported"
    assert _git(worktree, "rev-parse", "HEAD") != pre_merge_sha
    assert _git(root, "ls-remote", "origin", "refs/heads/main").split()[0] == pre_merge_sha
