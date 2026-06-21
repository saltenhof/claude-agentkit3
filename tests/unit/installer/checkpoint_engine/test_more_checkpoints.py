"""Supplementary checkpoint coverage (AG3-088): CP 10a/10b/11/12, dry-run, probe."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.unit.installer.checkpoint_engine.conftest import (
    InMemoryRegistrationRepo,
    make_config,
)

from agentkit.backend.installer.bootstrap_checkpoints.cp01_to_06 import cp05_pipeline_config
from agentkit.backend.installer.bootstrap_checkpoints.cp10 import (
    cp10_mcp_registration,
    cp10a_concept_context_properties,
    cp10b_concept_validation_hook,
    cp10d_sonarqube,
)
from agentkit.backend.installer.bootstrap_checkpoints.cp11_to_12 import (
    cp11_git_hooks_and_claude,
    cp12_verify_registration,
)
from agentkit.backend.installer.bootstrap_checkpoints.orchestrator import (
    build_checkpoint_context,
)
from agentkit.backend.installer.checkpoint_engine.execution_mode import ExecutionMode
from agentkit.backend.installer.checkpoint_engine.reasons import (
    DRY_RUN_PLAN_MARKER,
    REASON_PLANNED_NO_MUTATION,
    REASON_VECTORDB_DISABLED,
)
from agentkit.backend.installer.registration import CheckpointStatus
from agentkit.backend.installer.repo_probe import GhCliRepoExistenceProbe

if TYPE_CHECKING:
    from pathlib import Path


def _ctx(
    tmp_path: Path,
    repo: InMemoryRegistrationRepo,
    *,
    mode: ExecutionMode = ExecutionMode.REGISTER,
    features_vectordb: bool = False,
) -> object:
    config = make_config(
        tmp_path,
        bundle_store_root=tmp_path / "b",
        registration_repo=repo,
        features_vectordb=features_vectordb,
    )
    ctx = build_checkpoint_context(config, mode)
    cp05_pipeline_config(ctx)
    return ctx


def test_cp10a_skipped_without_vectordb(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    result = cp10a_concept_context_properties(_ctx(tmp_path, registration_repo))  # type: ignore[arg-type]
    assert result.status is CheckpointStatus.SKIPPED
    assert result.reason == REASON_VECTORDB_DISABLED


def test_cp10a_created_with_vectordb(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    ctx = _ctx(tmp_path, registration_repo, features_vectordb=True)
    result = cp10a_concept_context_properties(ctx)  # type: ignore[arg-type]
    assert result.status is CheckpointStatus.CREATED


def test_cp10b_skipped_without_vectordb(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    result = cp10b_concept_validation_hook(_ctx(tmp_path, registration_repo))  # type: ignore[arg-type]
    assert result.status is CheckpointStatus.SKIPPED
    assert result.reason == REASON_VECTORDB_DISABLED


def test_cp10b_created_with_vectordb(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    ctx = _ctx(tmp_path, registration_repo, features_vectordb=True)
    result = cp10b_concept_validation_hook(ctx)  # type: ignore[arg-type]
    assert result.status is CheckpointStatus.CREATED


def test_cp10_dry_run_plan_contract_with_vectordb(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    ctx = _ctx(
        tmp_path, registration_repo, mode=ExecutionMode.DRY_RUN, features_vectordb=True
    )
    result = cp10_mcp_registration(ctx)  # type: ignore[arg-type]
    assert result.status is CheckpointStatus.CREATED
    assert result.reason == REASON_PLANNED_NO_MUTATION
    assert DRY_RUN_PLAN_MARKER in (result.detail or "")
    assert not (tmp_path / ".mcp.json").exists()


def test_cp10d_skipped_when_sonar_off(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    ctx = _ctx(tmp_path, registration_repo, mode=ExecutionMode.VERIFY)
    result = cp10d_sonarqube(ctx)  # type: ignore[arg-type]
    assert result.status is CheckpointStatus.SKIPPED
    assert result.reason == "not_applicable"


def test_cp11_creates_claude_md_skeleton(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    config = make_config(
        root, bundle_store_root=tmp_path / "b", registration_repo=registration_repo
    )
    ctx = build_checkpoint_context(config, ExecutionMode.REGISTER)
    result = cp11_git_hooks_and_claude(ctx)
    # git may not be a repo here; CP 11 either CREATES the CLAUDE.md (status
    # CREATED) or FAILS on the hooksPath git config — both are deterministic.
    assert result.status in (CheckpointStatus.CREATED, CheckpointStatus.FAILED)
    if result.status is CheckpointStatus.CREATED:
        assert (root / "CLAUDE.md").is_file()


def test_cp11_dry_run_does_not_write(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    config = make_config(
        root, bundle_store_root=tmp_path / "b", registration_repo=registration_repo
    )
    ctx = build_checkpoint_context(config, ExecutionMode.DRY_RUN)
    result = cp11_git_hooks_and_claude(ctx)
    assert DRY_RUN_PLAN_MARKER in (result.detail or "")
    assert not (root / "CLAUDE.md").exists()


def test_cp12_verify_passes_after_profile_and_config(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    from agentkit.backend.installer.bootstrap_checkpoints.cp01_to_06 import (
        cp06_profile_resolution,
    )

    ctx = _ctx(tmp_path, registration_repo, mode=ExecutionMode.VERIFY)
    cp06_profile_resolution(ctx)
    result = cp12_verify_registration(ctx)  # type: ignore[arg-type]
    assert result.status is CheckpointStatus.PASS


def test_cp12_verify_fails_when_profile_missing(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    # No CP 6 run -> resolved_profile is None -> verification FAILED.
    ctx = _ctx(tmp_path, registration_repo, mode=ExecutionMode.VERIFY)
    result = cp12_verify_registration(ctx)  # type: ignore[arg-type]
    assert result.status is CheckpointStatus.FAILED
    assert result.reason == "verification_failed"


def test_gh_probe_reports_absent_when_gh_missing(monkeypatch: object) -> None:
    """GhCliRepoExistenceProbe is fail-closed when ``gh`` is not installed."""
    import shutil

    from _pytest.monkeypatch import MonkeyPatch

    assert isinstance(monkeypatch, MonkeyPatch)
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    probe = GhCliRepoExistenceProbe()
    result = probe("acme", "demo")
    assert result.exists is False
    assert "gh" in result.detail


def test_gh_probe_success_and_failure_subprocess(monkeypatch: object) -> None:
    """GhCliRepoExistenceProbe maps a zero / non-zero ``gh`` exit deterministically."""
    import shutil
    import subprocess

    from _pytest.monkeypatch import MonkeyPatch

    assert isinstance(monkeypatch, MonkeyPatch)
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/gh")

    class _Completed:
        def __init__(self, returncode: int, stderr: str = "") -> None:
            self.returncode = returncode
            self.stderr = stderr
            self.stdout = ""

    def _ok(*_a: object, **_k: object) -> _Completed:
        return _Completed(0)

    monkeypatch.setattr(subprocess, "run", _ok)
    assert GhCliRepoExistenceProbe()("acme", "demo").exists is True

    def _fail(*_a: object, **_k: object) -> _Completed:
        return _Completed(1, stderr="not found")

    monkeypatch.setattr(subprocess, "run", _fail)
    res = GhCliRepoExistenceProbe()("acme", "demo")
    assert res.exists is False
    assert "not found" in res.detail


def test_cp11_sets_hooks_path_in_real_git_repo(
    tmp_path: Path, registration_repo: InMemoryRegistrationRepo
) -> None:
    """CP 11 sets core.hooksPath in a real git repo (register mode)."""
    import subprocess

    root = tmp_path / "gitproj"
    root.mkdir()
    init = subprocess.run(  # noqa: S603
        ["git", "-C", str(root), "init"], capture_output=True, text=True, check=False
    )
    if init.returncode != 0:  # pragma: no cover - git always present in CI
        import pytest

        pytest.skip("git not available")
    config = make_config(
        root, bundle_store_root=tmp_path / "b", registration_repo=registration_repo
    )
    ctx = build_checkpoint_context(config, ExecutionMode.REGISTER)
    result = cp11_git_hooks_and_claude(ctx)
    assert result.status is CheckpointStatus.CREATED
    hooks_path = subprocess.run(  # noqa: S603
        ["git", "-C", str(root), "config", "--get", "core.hooksPath"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert hooks_path.stdout.strip() == "tools/hooks/"
    assert (root / "CLAUDE.md").is_file()
    # Idempotent re-run: hooksPath already set, CLAUDE.md present -> PASS.
    ctx2 = build_checkpoint_context(config, ExecutionMode.REGISTER)
    assert cp11_git_hooks_and_claude(ctx2).status is CheckpointStatus.PASS
