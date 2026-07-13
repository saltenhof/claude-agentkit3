"""Edge-command executors against a REAL dev-local git fixture repo (AG3-145 B).

MOCKS/STUBS rule: the edge executor runs REAL git subprocesses against a REAL
temp repo -- no git mocking. Covers provision (worktree + marker + head SHA),
teardown idempotency (double teardown = reported no-op), preflight probe (pure
collection), and the deterministic error result for an edge-unknown command
kind (Scope item 4).
"""

from __future__ import annotations

import inspect
import json
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
    CommandErrorResult,
    EdgeCommandView,
    PreflightProbeReport,
    WorktreeReport,
)
from agentkit.harness_client.projectedge.command_executor import (
    _EDGE_GIT_TIMEOUT_S,
    EdgeGitError,
    _run_git,
    execute_command,
    execute_preflight_probe,
    execute_provision_worktree,
    execute_reset_worktree,
)

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

pytestmark = pytest.mark.requires_git

_STORY_ID = "AG3-700"
_BRANCH = "story/AG3-700"


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True)


def _init_repo(root: Path) -> None:
    """Init a real git repo with one commit so ``worktree add`` succeeds."""
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "README.md").write_text("seed\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-q", "-m", "seed")


def _project_config(project_root: Path, repo_names: list[str]) -> ProjectConfig:
    return ProjectConfig(
        project_key="test-project",
        project_name="Test Project",
        repositories=[
            RepositoryConfig(name=name, path=project_root / name) for name in repo_names
        ],
        pipeline=PipelineConfig(
            config_version=SUPPORTED_CONFIG_VERSION,
            features=Features(multi_llm=False),
            sonarqube=SonarQubeConfig(available=False, enabled=False),
            ci=JenkinsConfig(available=False, enabled=False),
        ),
    )


def _now() -> datetime:
    from datetime import UTC, datetime

    return datetime(2026, 7, 5, 12, 0, tzinfo=UTC)


def _command(kind: str, payload: dict[str, object]) -> EdgeCommandView:
    return EdgeCommandView(
        command_id=f"cmd-{kind}",
        command_kind=kind,
        payload=payload,
        status="delivered",
        created_at=_now(),
    )


# ---------------------------------------------------------------------------
# provision_worktree
# ---------------------------------------------------------------------------


def test_provision_creates_worktree_marker_and_reports_head_sha(tmp_path: Path) -> None:
    repo_root = tmp_path / "api"
    _init_repo(repo_root)
    config = _project_config(tmp_path, ["api"])
    command = _command(
        "provision_worktree",
        {
            "story_id": _STORY_ID,
            "project_key": "test-project",
            "run_id": "run-1",
            "repo_id": "api",
            "branch": _BRANCH,
            "base_ref": "main",
        },
    )

    result = execute_command(command, project_config=config, project_root=tmp_path)

    assert isinstance(result, WorktreeReport)
    assert result.outcome == "provisioned"
    assert result.marker_present is True
    assert result.head_sha is not None and len(result.head_sha) >= 7
    worktree_path = repo_root / "worktrees" / _STORY_ID
    assert worktree_path.is_dir()
    assert result.worktree_root == str(worktree_path)
    marker = json.loads((worktree_path / ".agentkit-story.json").read_text(encoding="utf-8"))
    assert marker["story_id"] == _STORY_ID
    assert marker["run_id"] == "run-1"
    assert marker["project_key"] == "test-project"
    # The branch was really created dev-locally.
    branches = subprocess.run(
        ["git", "-C", str(repo_root), "branch", "--list", _BRANCH],
        capture_output=True, text=True, check=True,
    )
    assert _BRANCH in branches.stdout


# ---------------------------------------------------------------------------
# teardown_worktree (idempotent -- FK-10 §10.5.3)
# ---------------------------------------------------------------------------


def test_teardown_removes_worktree_then_double_teardown_is_no_op(tmp_path: Path) -> None:
    repo_root = tmp_path / "api"
    _init_repo(repo_root)
    config = _project_config(tmp_path, ["api"])
    from agentkit.backend.control_plane.models import ProvisionWorktreeCommandPayload

    execute_provision_worktree(
        ProvisionWorktreeCommandPayload(
            story_id=_STORY_ID, project_key="test-project", run_id="run-1",
            repo_id="api", branch=_BRANCH, base_ref="main",
        ),
        project_config=config,
        project_root=tmp_path,
    )

    teardown_cmd = _command(
        "teardown_worktree",
        {"story_id": _STORY_ID, "repo_id": "api", "branch": _BRANCH},
    )
    first = execute_command(teardown_cmd, project_config=config, project_root=tmp_path)
    assert isinstance(first, WorktreeReport)
    assert first.outcome == "torn_down"
    assert not (repo_root / "worktrees" / _STORY_ID).exists()

    # AC7 / FK-10 §10.5.3: a double teardown is a reported no-op, never an error.
    second = execute_command(teardown_cmd, project_config=config, project_root=tmp_path)
    assert isinstance(second, WorktreeReport)
    assert second.outcome == "no_op"


def test_reset_worktree_keeps_local_head_and_discards_uncommitted_changes(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "api"
    _init_repo(repo_root)
    config = _project_config(tmp_path, ["api"])
    from agentkit.backend.control_plane.models import (
        ProvisionWorktreeCommandPayload,
        ResetWorktreeCommandPayload,
    )

    execute_provision_worktree(
        ProvisionWorktreeCommandPayload(
            story_id=_STORY_ID, project_key="test-project", run_id="run-old",
            repo_id="api", branch=_BRANCH, base_ref="main",
        ),
        project_config=config,
        project_root=tmp_path,
    )
    worktree = repo_root / "worktrees" / _STORY_ID
    (worktree / "local-commit.txt").write_text("kept\n", encoding="utf-8")
    (worktree / ".gitignore").write_text("ignored-local.txt\n", encoding="utf-8")
    _git(worktree, "add", "local-commit.txt")
    _git(worktree, "add", ".gitignore")
    _git(worktree, "commit", "-q", "-m", "local story commit")
    head_before = subprocess.run(
        ["git", "-C", str(worktree), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    (worktree / "local-commit.txt").write_text("dirty\n", encoding="utf-8")
    (worktree / "untracked").mkdir()
    (worktree / "untracked" / "drop.txt").write_text("drop\n", encoding="utf-8")
    ignored = worktree / "ignored-local.txt"
    ignored.write_text("keep ignored state\n", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "keep.txt"
    sentinel.write_text("keep\n", encoding="utf-8")
    link = worktree / "outside-link"
    symlink_created = True
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        symlink_created = False

    result = execute_reset_worktree(
        ResetWorktreeCommandPayload(
            story_id=_STORY_ID,
            project_key="test-project",
            run_id="run-recovered",
            repo_id="api",
        ),
        project_config=config,
        project_root=tmp_path,
    )

    assert result.outcome == "reset"
    assert result.head_sha == head_before
    assert (worktree / "local-commit.txt").read_text(encoding="utf-8") == "kept\n"
    assert not (worktree / "untracked").exists()
    assert ignored.read_text(encoding="utf-8") == "keep ignored state\n"
    if symlink_created:
        assert not link.exists()
    assert sentinel.read_text(encoding="utf-8") == "keep\n"
    marker = json.loads(
        (worktree / ".agentkit-story.json").read_text(encoding="utf-8")
    )
    assert marker["run_id"] == "run-recovered"


def test_reset_worktree_plain_directory_fails_without_resetting_primary_checkout(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "api"
    _init_repo(repo_root)
    config = _project_config(tmp_path, ["api"])
    from agentkit.backend.control_plane.models import ResetWorktreeCommandPayload

    (repo_root / "README.md").write_text("unrelated primary edit\n", encoding="utf-8")
    worktree = repo_root / "worktrees" / _STORY_ID
    worktree.mkdir(parents=True)
    (worktree / "corrupt-remnant.txt").write_text("keep\n", encoding="utf-8")

    with pytest.raises(EdgeGitError, match="not its own git worktree root"):
        execute_reset_worktree(
            ResetWorktreeCommandPayload(
                story_id=_STORY_ID,
                project_key="test-project",
                run_id="run-recovered",
                repo_id="api",
            ),
            project_config=config,
            project_root=tmp_path,
        )

    assert (repo_root / "README.md").read_text(encoding="utf-8") == (
        "unrelated primary edit\n"
    )
    assert (worktree / "corrupt-remnant.txt").read_text(encoding="utf-8") == "keep\n"


def test_reset_worktree_refuses_when_resolved_toplevel_differs_from_target(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "api"
    _init_repo(repo_root)
    config = _project_config(tmp_path, ["api"])
    from agentkit.backend.control_plane.models import ResetWorktreeCommandPayload

    nested_repo = repo_root / "worktrees"
    _init_repo(nested_repo)
    (nested_repo / _STORY_ID).mkdir()

    with pytest.raises(EdgeGitError, match="not its own git worktree root"):
        execute_reset_worktree(
            ResetWorktreeCommandPayload(
                story_id=_STORY_ID,
                project_key="test-project",
                run_id="run-recovered",
                repo_id="api",
            ),
            project_config=config,
            project_root=tmp_path,
        )


def test_reset_worktree_refuses_unregistered_foreign_checkout(tmp_path: Path) -> None:
    repo_root = tmp_path / "api"
    _init_repo(repo_root)
    config = _project_config(tmp_path, ["api"])
    from agentkit.backend.control_plane.models import ResetWorktreeCommandPayload

    foreign_checkout = repo_root / "worktrees" / _STORY_ID
    _init_repo(foreign_checkout)

    with pytest.raises(EdgeGitError, match="not a registered worktree"):
        execute_reset_worktree(
            ResetWorktreeCommandPayload(
                story_id=_STORY_ID,
                project_key="test-project",
                run_id="run-recovered",
                repo_id="api",
            ),
            project_config=config,
            project_root=tmp_path,
        )


def test_reset_worktree_refuses_a_symlinked_target_before_git(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "api"
    _init_repo(repo_root)
    config = _project_config(tmp_path, ["api"])
    from pathlib import Path as ConcretePath

    from agentkit.backend.control_plane.models import ResetWorktreeCommandPayload

    worktree = repo_root / "worktrees" / _STORY_ID
    original_is_symlink = ConcretePath.is_symlink

    def report_target_symlink(path: Path) -> bool:
        return path == worktree or original_is_symlink(path)

    monkeypatch.setattr(ConcretePath, "is_symlink", report_target_symlink)
    with pytest.raises(EdgeGitError, match="refuses to follow"):
        execute_reset_worktree(
            ResetWorktreeCommandPayload(
                story_id=_STORY_ID,
                project_key="test-project",
                run_id="run-recovered",
                repo_id="api",
            ),
            project_config=config,
            project_root=tmp_path,
        )


def test_reset_worktree_has_no_stash_salvage_or_quarantine_path() -> None:
    source = inspect.getsource(execute_reset_worktree)

    assert '"reset", "--hard", "HEAD"' in source
    assert '"clean", "-fd"' in source
    assert not {"stash", "salvage", "quarantine"} & set(source.lower().split())


# ---------------------------------------------------------------------------
# preflight_probe (pure collection -- FK-22 §22.3.1)
# ---------------------------------------------------------------------------


def test_preflight_probe_on_clean_repo_reports_no_branch_no_worktree(tmp_path: Path) -> None:
    repo_root = tmp_path / "api"
    _init_repo(repo_root)
    config = _project_config(tmp_path, ["api"])

    from agentkit.backend.control_plane.models import PreflightProbeCommandPayload

    result = execute_preflight_probe(
        PreflightProbeCommandPayload(story_id=_STORY_ID, repo_id="api", branch=_BRANCH),
        project_config=config,
        project_root=tmp_path,
    )

    assert isinstance(result, PreflightProbeReport)
    assert result.branch_present is False
    assert result.head_sha is None
    assert result.worktree_present is False
    assert result.marker_present is False


def test_preflight_probe_after_provision_reports_branch_and_marker(tmp_path: Path) -> None:
    repo_root = tmp_path / "api"
    _init_repo(repo_root)
    config = _project_config(tmp_path, ["api"])
    from agentkit.backend.control_plane.models import (
        PreflightProbeCommandPayload,
        ProvisionWorktreeCommandPayload,
    )

    execute_provision_worktree(
        ProvisionWorktreeCommandPayload(
            story_id=_STORY_ID, project_key="test-project", run_id="run-9",
            repo_id="api", branch=_BRANCH, base_ref="main",
        ),
        project_config=config,
        project_root=tmp_path,
    )

    result = execute_preflight_probe(
        PreflightProbeCommandPayload(story_id=_STORY_ID, repo_id="api", branch=_BRANCH),
        project_config=config,
        project_root=tmp_path,
    )

    assert result.branch_present is True
    assert result.head_sha is not None
    assert result.worktree_present is True
    assert result.marker_present is True
    assert result.marker_story_id == _STORY_ID
    assert result.marker_run_id == "run-9"


# ---------------------------------------------------------------------------
# Scope item 4: an edge-unknown command kind is a deterministic error result
# ---------------------------------------------------------------------------


def test_merge_local_bad_payload_yields_error_result(tmp_path: Path) -> None:
    config = _project_config(tmp_path, ["api"])
    command = _command("merge_local", {"repo_id": "api"})

    result = execute_command(command, project_config=config, project_root=tmp_path)

    assert isinstance(result, CommandErrorResult)
    assert result.error_code == "command_execution_failed"


def test_execution_failure_yields_error_result_not_exception(tmp_path: Path) -> None:
    """A bad payload / git error surfaces as a terminal CommandErrorResult."""
    config = _project_config(tmp_path, ["api"])
    # repo 'api' is configured but never git-init'd -> provision raises EdgeGitError,
    # which the dispatcher converts to a deterministic error result.
    command = _command(
        "provision_worktree",
        {
            "story_id": _STORY_ID, "project_key": "test-project", "run_id": "run-1",
            "repo_id": "api", "branch": _BRANCH, "base_ref": "main",
        },
    )

    result = execute_command(command, project_config=config, project_root=tmp_path)

    assert isinstance(result, CommandErrorResult)
    assert result.error_code == "command_execution_failed"


def test_run_git_uses_bounded_subprocess_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Local git operations cannot hang the edge executor indefinitely."""
    from agentkit.harness_client.projectedge import command_executor

    recorded: dict[str, object] = {}

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        recorded["timeout"] = kwargs.get("timeout")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(command_executor.subprocess, "run", fake_run)

    result = _run_git(tmp_path, "status")

    assert result.returncode == 0
    assert recorded["timeout"] == _EDGE_GIT_TIMEOUT_S


def test_run_git_timeout_raises_edge_git_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agentkit.harness_client.projectedge import command_executor

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd="git status", timeout=kwargs.get("timeout"))

    monkeypatch.setattr(command_executor.subprocess, "run", fake_run)

    with pytest.raises(EdgeGitError, match="timed out"):
        _run_git(tmp_path, "status")


def test_unknown_repo_id_raises_edge_git_error(tmp_path: Path) -> None:
    from agentkit.backend.control_plane.models import PreflightProbeCommandPayload

    config = _project_config(tmp_path, ["api"])
    with pytest.raises(EdgeGitError, match="not configured"):
        execute_preflight_probe(
            PreflightProbeCommandPayload(story_id=_STORY_ID, repo_id="ghost", branch=_BRANCH),
            project_config=config,
            project_root=tmp_path,
        )
