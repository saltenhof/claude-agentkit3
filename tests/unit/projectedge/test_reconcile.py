"""Real-git tests for the AG3-151 edge takeover reconcile executor."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

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
    ProvisionWorktreeCommandPayload,
    TakeoverErrorResult,
    TakeoverReconcileCommandPayload,
    WorktreeReport,
)
from agentkit.harness_client.projectedge import reconcile as reconcile_module
from agentkit.harness_client.projectedge.client import LocalEdgePublisher
from agentkit.harness_client.projectedge.command_executor import (
    EdgeGitError,
    execute_provision_worktree,
)
from agentkit.harness_client.projectedge.reconcile import execute_takeover_reconcile

pytestmark = pytest.mark.requires_git


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _init_repo(root: Path) -> str:
    root.mkdir(parents=True)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "README.md").write_text("seed\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-q", "-m", "seed")
    return _git(root, "rev-parse", "HEAD")


def _config(project_root: Path) -> ProjectConfig:
    return ProjectConfig(
        project_key="test-project",
        project_name="Test Project",
        repositories=[RepositoryConfig(name="api", path=project_root / "api")],
        pipeline=PipelineConfig(
            config_version=SUPPORTED_CONFIG_VERSION,
            features=Features(multi_llm=False),
            sonarqube=SonarQubeConfig(available=False, enabled=False),
            ci=JenkinsConfig(available=False, enabled=False),
        ),
    )


def _payload(base_sha: str) -> TakeoverReconcileCommandPayload:
    return TakeoverReconcileCommandPayload(
        story_id="AG3-151",
        project_key="test-project",
        run_id="run-151",
        repo_id="api",
        takeover_base_sha=base_sha,
    )


def _provision(project_root: Path, base_sha: str) -> Path:
    execute_provision_worktree(
        ProvisionWorktreeCommandPayload(
            story_id="AG3-151",
            project_key="test-project",
            run_id="run-151",
            repo_id="api",
            branch="story/AG3-151",
            base_ref=base_sha,
        ),
        project_config=_config(project_root),
        project_root=project_root,
    )
    return project_root / "api" / "worktrees" / "AG3-151"


def test_clean_identity_reconciles_without_reprovision(tmp_path: Path) -> None:
    base_sha = _init_repo(tmp_path / "api")
    worktree = _provision(tmp_path, base_sha)

    execution = execute_takeover_reconcile(
        _payload(base_sha),
        project_config=_config(tmp_path),
        project_root=tmp_path,
    )

    assert isinstance(execution.result, WorktreeReport)
    assert execution.result.outcome == "no_op"
    assert execution.result.head_sha == base_sha
    assert execution.quarantine_detail is None
    assert worktree.is_dir()


def test_contested_same_worktree_is_atomically_quarantined_and_reprovisioned(
    tmp_path: Path,
) -> None:
    base_sha = _init_repo(tmp_path / "api")
    worktree = _provision(tmp_path, base_sha)
    (worktree / "uncommitted.txt").write_text("ex-owner write\n", encoding="utf-8")

    execution = execute_takeover_reconcile(
        _payload(base_sha),
        project_config=_config(tmp_path),
        project_root=tmp_path,
        now_provider=lambda: datetime(2026, 7, 11, 12, 0, tzinfo=UTC),
    )

    assert isinstance(execution.result, WorktreeReport)
    assert execution.result.outcome == "provisioned"
    assert execution.result.head_sha == base_sha
    assert execution.quarantine_detail is not None
    quarantine = Path(execution.quarantine_detail.quarantine_path)
    assert (quarantine / "uncommitted.txt").read_text(encoding="utf-8") == (
        "ex-owner write\n"
    )
    assert not (worktree / "uncommitted.txt").exists()
    assert _git(worktree, "rev-parse", "HEAD") == base_sha
    audit_files = list(quarantine.parent.joinpath("audit").glob("*.json"))
    assert len(audit_files) == 1
    assert json.loads(audit_files[0].read_text(encoding="utf-8"))["source_root"] == str(
        worktree.resolve()
    )


def test_crash_after_quarantine_replay_converges_and_reconciles_stale_branch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_sha = _init_repo(tmp_path / "api")
    worktree = _provision(tmp_path, base_sha)
    (worktree / "uncommitted.txt").write_text("ex-owner write\n", encoding="utf-8")
    real_quarantine = reconcile_module.quarantine_worktree

    def _crash_after_quarantine(
        *,
        source_root: Path,
        quarantine_store: Path,
        reason: str,
        now: datetime,
    ) -> None:
        real_quarantine(
            source_root=source_root,
            quarantine_store=quarantine_store,
            reason=reason,
            now=now,
        )
        raise RuntimeError("injected crash after quarantine")

    monkeypatch.setattr(reconcile_module, "quarantine_worktree", _crash_after_quarantine)
    with pytest.raises(RuntimeError, match="injected crash"):
        execute_takeover_reconcile(
            _payload(base_sha),
            project_config=_config(tmp_path),
            project_root=tmp_path,
            now_provider=lambda: datetime(2026, 7, 11, 12, 0, tzinfo=UTC),
        )

    assert not worktree.exists()
    assert _git(tmp_path / "api", "show-ref", "--verify", "refs/heads/story/AG3-151")
    monkeypatch.setattr(reconcile_module, "quarantine_worktree", real_quarantine)

    replay = execute_takeover_reconcile(
        _payload(base_sha),
        project_config=_config(tmp_path),
        project_root=tmp_path,
    )

    assert isinstance(replay.result, WorktreeReport)
    assert replay.result.outcome == "provisioned"
    assert replay.result.head_sha == base_sha
    assert replay.result.marker_present is True
    assert replay.quarantine_detail is None
    assert _git(worktree, "rev-parse", "HEAD") == base_sha
    assert _git(worktree, "branch", "--show-current") == "story/AG3-151"
    marker = json.loads((worktree / ".agentkit-story.json").read_text(encoding="utf-8"))
    assert marker["project_key"] == "test-project"
    assert marker["run_id"] == "run-151"
    assert marker["story_id"] == "AG3-151"
    audit_files = list(
        (tmp_path.parent / ".agentkit-quarantine" / tmp_path.name / "audit").glob(
            "*.json"
        )
    )
    assert len(audit_files) == 1


def test_markerless_failure_publication_remnant_replay_converges(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_sha = _init_repo(tmp_path / "api")
    worktree = _provision(tmp_path, base_sha)
    (worktree / "uncommitted.txt").write_text("ex-owner write\n", encoding="utf-8")

    with monkeypatch.context() as failure_patch:
        def _fail_provision(*args: object, **kwargs: object) -> object:
            del args, kwargs
            raise EdgeGitError("injected reprovision failure")

        failure_patch.setattr(
            "agentkit.harness_client.projectedge.command_executor.execute_provision_worktree",
            _fail_provision,
        )
        failed = execute_takeover_reconcile(
            _payload(base_sha),
            project_config=_config(tmp_path),
            project_root=tmp_path,
        )

    assert isinstance(failed.result, TakeoverErrorResult)
    assert failed.result.result_type == "contested_local_writes"
    assert not worktree.exists()
    LocalEdgePublisher(project_root=tmp_path).publish_unreadable_freeze_state(
        worktree_roots=[worktree]
    )
    assert not (worktree / ".agentkit-story.json").exists()

    replay = execute_takeover_reconcile(
        _payload(base_sha),
        project_config=_config(tmp_path),
        project_root=tmp_path,
    )

    assert isinstance(replay.result, WorktreeReport)
    assert replay.result.outcome == "provisioned"
    assert replay.result.head_sha == base_sha
    assert replay.result.marker_present is True
    assert _git(worktree, "rev-parse", "HEAD") == base_sha
    marker = json.loads((worktree / ".agentkit-story.json").read_text(encoding="utf-8"))
    assert marker["run_id"] == "run-151"


def test_registered_markerless_partial_reprovision_replay_converges(
    tmp_path: Path,
) -> None:
    base_sha = _init_repo(tmp_path / "api")
    worktree = _provision(tmp_path, base_sha)
    (worktree / ".agentkit-story.json").unlink()

    replay = execute_takeover_reconcile(
        _payload(base_sha),
        project_config=_config(tmp_path),
        project_root=tmp_path,
    )

    assert isinstance(replay.result, WorktreeReport)
    assert replay.result.outcome == "provisioned"
    assert replay.result.head_sha == base_sha
    assert replay.result.marker_present is True
    assert _git(worktree, "branch", "--show-current") == "story/AG3-151"
    marker = json.loads((worktree / ".agentkit-story.json").read_text(encoding="utf-8"))
    assert marker["run_id"] == "run-151"


def test_symlinked_reprovision_remnant_fails_closed_without_traversal(
    tmp_path: Path,
) -> None:
    base_sha = _init_repo(tmp_path / "api")
    worktree = tmp_path / "api" / "worktrees" / "AG3-151"
    target = tmp_path / "foreign-target"
    guard = target / ".agent-guard"
    guard.mkdir(parents=True)
    (guard / "freeze.json").write_text(
        json.dumps({"state_readable": False, "active_freezes": []}),
        encoding="utf-8",
    )
    worktree.parent.mkdir(parents=True)
    try:
        worktree.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        if exc.winerror == 1314:
            pytest.skip("Windows symlink privilege is unavailable")
        raise

    execution = execute_takeover_reconcile(
        _payload(base_sha),
        project_config=_config(tmp_path),
        project_root=tmp_path,
    )

    assert isinstance(execution.result, TakeoverErrorResult)
    assert execution.result.result_type == "local_stale_or_dirty_takeover_target"
    assert "symlinked partial worktree remnant" in execution.result.detail
    assert worktree.is_symlink()
    assert (guard / "freeze.json").is_file()


def test_mismatching_identity_reports_contested_without_moving_target(
    tmp_path: Path,
) -> None:
    base_sha = _init_repo(tmp_path / "api")
    worktree = _provision(tmp_path, base_sha)
    marker_path = worktree / ".agentkit-story.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["story_id"] = "FOREIGN-1"
    marker_path.write_text(json.dumps(marker), encoding="utf-8")

    execution = execute_takeover_reconcile(
        _payload(base_sha),
        project_config=_config(tmp_path),
        project_root=tmp_path,
    )

    assert isinstance(execution.result, TakeoverErrorResult)
    assert execution.result.result_type == "contested_local_writes"
    assert execution.quarantine_detail is None
    assert worktree.is_dir()


def test_stale_same_story_target_is_quarantined_reprovisioned_and_named(
    tmp_path: Path,
) -> None:
    base_sha = _init_repo(tmp_path / "api")
    worktree = _provision(tmp_path, base_sha)
    marker_path = worktree / ".agentkit-story.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["run_id"] = "run-old"
    marker_path.write_text(json.dumps(marker), encoding="utf-8")

    execution = execute_takeover_reconcile(
        _payload(base_sha),
        project_config=_config(tmp_path),
        project_root=tmp_path,
    )

    assert isinstance(execution.result, TakeoverErrorResult)
    assert execution.result.result_type == "local_stale_or_dirty_takeover_target"
    assert execution.quarantine_detail is not None
    assert _git(worktree, "rev-parse", "HEAD") == base_sha
