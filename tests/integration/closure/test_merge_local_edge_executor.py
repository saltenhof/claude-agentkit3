"""Real-git integration coverage for the AG3-152 edge merge executor."""

from __future__ import annotations

import shutil
import subprocess
from datetime import UTC, datetime
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
    EdgeCommandView,
    MergeLocalCommandPayload,
    MergeLocalReport,
    MergeLocalRepository,
)
from agentkit.harness_client.projectedge import merge_local
from agentkit.harness_client.projectedge.command_executor import (
    EdgeGitError,
    _write_story_marker,
    execute_command,
)
from agentkit.harness_client.projectedge.merge_local import (
    WorktreeIdentityError,
    execute_merge_local,
)

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
    _write_story_marker(
        worktree,
        story_id=_STORY_ID,
        project_key="project-a",
        run_id="run-1",
    )
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


def test_main_push_disables_terminal_prompts_and_preserves_ambient_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded: dict[str, object] = {}
    monkeypatch.setenv("AG3_152_AMBIENT", "preserved")

    def _auth_sensitive_run(
        *args: object, **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        env = kwargs.get("env")
        recorded["env"] = env
        recorded["timeout"] = kwargs.get("timeout")
        if not isinstance(env, dict) or env.get("GIT_TERMINAL_PROMPT") != "0":
            raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout"))
        return subprocess.CompletedProcess(
            args[0], 128, "", "fatal: could not read Username"
        )

    monkeypatch.setattr(merge_local.subprocess, "run", _auth_sensitive_run)

    result = merge_local._push(
        tmp_path,
        "--force-with-lease=refs/heads/main:locked",
        "candidate:refs/heads/main",
    )

    env = recorded["env"]
    assert isinstance(env, dict)
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["AG3_152_AMBIENT"] == "preserved"
    assert recorded["timeout"] == 120
    assert result.returncode == 128


@pytest.mark.requires_git
def test_successful_push_identity_teardown_failure_returns_merged_executor_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _worktree, _pre_merge, candidate_and_tree = _repo(tmp_path)
    payload = _payload(candidate_and_tree, "api")

    def _identity_failure(*_args: object, **_kwargs: object) -> None:
        raise WorktreeIdentityError("simulated transient identity timeout")

    monkeypatch.setattr(merge_local, "_teardown_if_present", _identity_failure)
    command = EdgeCommandView(
        command_id="cmd-merge-local",
        command_kind="merge_local",
        payload=payload.model_dump(mode="json"),
        status="delivered",
        created_at=datetime(2026, 7, 13, tzinfo=UTC),
    )

    result = execute_command(
        command,
        project_config=_config(tmp_path, "api"),
        project_root=tmp_path,
    )

    candidate = candidate_and_tree.split(":", maxsplit=1)[0]
    assert isinstance(result, MergeLocalReport)
    assert result.outcome == "merged"
    assert result.escalated is False
    assert "teardown remains retryable" in result.detail
    assert _git(root, "ls-remote", "origin", "refs/heads/main").split()[0] == candidate


@pytest.mark.requires_git
def test_absent_worktree_replay_prunes_registration_and_deletes_story_branch(
    tmp_path: Path,
) -> None:
    root, worktree, _pre_merge, candidate_and_tree = _repo(tmp_path)
    candidate = candidate_and_tree.split(":", maxsplit=1)[0]
    _git(root, "push", "-q", "origin", f"{candidate}:refs/heads/main")
    shutil.rmtree(worktree)

    report = execute_merge_local(
        _payload(candidate_and_tree, "api"),
        project_config=_config(tmp_path, "api"),
        project_root=tmp_path,
    )

    story_ref = f"refs/heads/story/{_STORY_ID}"
    branch = subprocess.run(
        ["git", "-C", str(root), "show-ref", "--verify", "--quiet", story_ref],
        check=False,
    )
    assert report.outcome == "already_merged"
    assert branch.returncode == 1
    assert f"branch {story_ref}" not in _git(root, "worktree", "list", "--porcelain")


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
def test_rejected_cas_rolls_back_verified_linked_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, worktree, pre_merge_sha, candidate_and_tree = _repo(tmp_path)
    real_push = merge_local._push
    competing_shas: list[str] = []

    def _push_after_competing_main_update(
        worktree_path: Path, lease: str, refspec: str
    ) -> subprocess.CompletedProcess[str]:
        (root / "competing.txt").write_text("competing main update\n", encoding="utf-8")
        _git(root, "add", "competing.txt")
        _git(root, "commit", "-q", "-m", "competing main update")
        competing_shas.append(_git(root, "rev-parse", "HEAD"))
        _git(root, "push", "-q", "origin", "main")
        return real_push(worktree_path, lease, refspec)

    monkeypatch.setattr(merge_local, "_push", _push_after_competing_main_update)

    report = execute_merge_local(
        _payload(candidate_and_tree, "api"),
        project_config=_config(tmp_path, "api"),
        project_root=tmp_path,
    )

    assert report.outcome == "escalated"
    assert report.failure_code == "cas_contention"
    assert report.repositories[0].rolled_back is True
    assert _git(worktree, "rev-parse", "HEAD") == pre_merge_sha
    assert _git(root, "ls-remote", "origin", "refs/heads/main").split()[0] == competing_shas[0]


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


@pytest.mark.requires_git
def test_already_merged_replay_keeps_success_when_teardown_remains_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _worktree, _pre_merge, candidate_and_tree = _repo(tmp_path)
    candidate = candidate_and_tree.split(":", maxsplit=1)[0]
    _git(root, "push", "-q", "origin", f"{candidate}:refs/heads/main")

    def _teardown_failure(*_args: object, **_kwargs: object) -> None:
        raise EdgeGitError("simulated worktree removal failure")

    monkeypatch.setattr(merge_local, "_teardown_if_present", _teardown_failure)

    report = execute_merge_local(
        _payload(candidate_and_tree, "api"),
        project_config=_config(tmp_path, "api"),
        project_root=tmp_path,
    )

    assert report.outcome == "already_merged"
    assert report.escalated is False
    assert "teardown remains retryable" in report.detail


@pytest.mark.requires_git
def test_already_merged_replay_refuses_sibling_worktree_symlink(
    tmp_path: Path,
) -> None:
    root, worktree_a, _pre_merge, candidate_and_tree = _repo(tmp_path)
    candidate = candidate_and_tree.split(":", maxsplit=1)[0]
    _git(root, "push", "-q", "origin", f"{candidate}:refs/heads/main")
    worktree_b = root / "worktrees" / "AG3-OTHER"
    _git(root, "worktree", "add", "-q", str(worktree_b), "-b", "story/AG3-OTHER")
    _write_story_marker(
        worktree_b,
        story_id="AG3-OTHER",
        project_key="project-a",
        run_id="run-other",
    )
    sibling_work = worktree_b / "uncommitted.txt"
    sibling_work.write_text("must survive\n", encoding="utf-8")
    _git(root, "worktree", "remove", "--force", str(worktree_a))
    try:
        worktree_a.symlink_to(worktree_b, target_is_directory=True)
    except OSError as exc:
        junction = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(worktree_a), str(worktree_b)],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if junction.returncode != 0:
            pytest.skip(
                "directory symlink/junction unavailable on this platform: "
                f"{exc}; {junction.stderr.strip()}"
            )

    report = execute_merge_local(
        _payload(candidate_and_tree, "api"),
        project_config=_config(tmp_path, "api"),
        project_root=tmp_path,
    )

    assert report.outcome == "escalated"
    assert report.failure_code == "worktree_identity_invalid"
    assert worktree_b.is_dir()
    assert sibling_work.read_text(encoding="utf-8") == "must survive\n"
    assert _git(worktree_b, "rev-parse", "--abbrev-ref", "HEAD") == "story/AG3-OTHER"


@pytest.mark.requires_git
def test_failed_checkout_does_not_rewrite_or_report_rollback_of_story_branch(
    tmp_path: Path,
) -> None:
    root, worktree, _pre_merge, candidate_and_tree = _repo(tmp_path)
    candidate = candidate_and_tree.split(":", maxsplit=1)[0]
    (worktree / "README.md").write_text("uncommitted story work\n", encoding="utf-8")

    report = execute_merge_local(
        _payload(candidate_and_tree, "api"),
        project_config=_config(tmp_path, "api"),
        project_root=tmp_path,
    )

    assert report.outcome == "escalated"
    assert report.failure_code == "local_merge_failed"
    assert report.repositories[0].rolled_back is False
    assert report.repositories[0].outcome == "failed"
    assert _git(root, "rev-parse", f"refs/heads/story/{_STORY_ID}") == candidate
    assert _git(worktree, "rev-parse", "--abbrev-ref", "HEAD") == f"story/{_STORY_ID}"


@pytest.mark.requires_git
def test_applied_push_with_lost_response_reconciles_to_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, worktree, _pre_merge, candidate_and_tree = _repo(tmp_path)
    real_push = merge_local._push

    def _applied_but_response_lost(
        worktree_path: Path, lease: str, refspec: str
    ) -> subprocess.CompletedProcess[str]:
        applied = real_push(worktree_path, lease, refspec)
        assert applied.returncode == 0
        return subprocess.CompletedProcess(applied.args, 124, "", "push timed out")

    monkeypatch.setattr(merge_local, "_push", _applied_but_response_lost)

    report = execute_merge_local(
        _payload(candidate_and_tree, "api"),
        project_config=_config(tmp_path, "api"),
        project_root=tmp_path,
    )

    candidate = candidate_and_tree.split(":", maxsplit=1)[0]
    assert report.outcome in {"merged", "already_merged"}
    assert report.escalated is False
    assert report.repositories[0].rolled_back is False
    assert _git(root, "ls-remote", "origin", "refs/heads/main").split()[0] == candidate
    assert not worktree.exists()


@pytest.mark.requires_git
@pytest.mark.parametrize(
    ("returncode", "stderr", "expected_code"),
    [
        (128, "fatal: Authentication failed", "push_auth_failed"),
        (124, "push timed out", "push_timeout"),
    ],
)
def test_unapplied_push_failure_has_distinct_classification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
    stderr: str,
    expected_code: str,
) -> None:
    root, worktree, pre_merge_sha, candidate_and_tree = _repo(tmp_path)

    def _failed_push(
        worktree_path: Path, lease: str, refspec: str
    ) -> subprocess.CompletedProcess[str]:
        del worktree_path, lease, refspec
        return subprocess.CompletedProcess(["git", "push"], returncode, "", stderr)

    monkeypatch.setattr(merge_local, "_push", _failed_push)

    report = execute_merge_local(
        _payload(candidate_and_tree, "api"),
        project_config=_config(tmp_path, "api"),
        project_root=tmp_path,
    )

    assert report.outcome == "escalated"
    assert report.failure_code == expected_code
    assert report.repositories[0].rolled_back is True
    assert _git(worktree, "rev-parse", "HEAD") == pre_merge_sha
    assert _git(root, "ls-remote", "origin", "refs/heads/main").split()[0] == pre_merge_sha


@pytest.mark.requires_git
def test_candidate_fetch_failure_has_own_failure_code(tmp_path: Path) -> None:
    root, _worktree, _pre_merge, candidate_and_tree = _repo(tmp_path)
    _git(root, "remote", "set-url", "origin", str(tmp_path / "missing-remote.git"))

    report = execute_merge_local(
        _payload(candidate_and_tree, "api"),
        project_config=_config(tmp_path, "api"),
        project_root=tmp_path,
    )

    assert report.outcome == "escalated"
    assert report.failure_code == "candidate_fetch_failed"
