"""SOLL-079 contract: story exit preserves worktrees and branches."""

from __future__ import annotations

import ast
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from agentkit.backend.control_plane.ownership import OwnershipStatus
from agentkit.backend.control_plane.records import (
    BindingDeleteScope,
    ControlPlaneOperationRecord,
    SessionRunBindingRecord,
)
from agentkit.backend.control_plane.repository import ControlPlaneRuntimeRepository
from agentkit.backend.governance.principal_capabilities.principals import Principal
from agentkit.backend.story_exit import (
    ExitReason,
    ExitRunState,
    StoryExitRequest,
    StoryExitService,
)

if TYPE_CHECKING:
    from agentkit.backend.governance.guard_system.records import StoryExecutionLockRecord
    from agentkit.backend.telemetry.contract.records import ExecutionEventRecord


_NOW = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)


@dataclass
class _ExitState:
    operations: dict[str, ControlPlaneOperationRecord]
    bindings: dict[str, SessionRunBindingRecord]
    locks: dict[tuple[str, str, str, str], StoryExecutionLockRecord]


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _exit_repository(state: _ExitState) -> ControlPlaneRuntimeRepository:
    def _commit(
        record: ControlPlaneOperationRecord,
        *,
        binding_to_save: SessionRunBindingRecord | None,
        binding_to_delete: BindingDeleteScope | None,
        locks: tuple[StoryExecutionLockRecord, ...],
        events: tuple[ExecutionEventRecord, ...],
        ownership_status_target: OwnershipStatus | None = None,
    ) -> None:
        del events, binding_to_delete
        assert ownership_status_target is OwnershipStatus.ENDED
        state.operations[record.op_id] = record
        if binding_to_save is not None:
            state.bindings[binding_to_save.session_id] = binding_to_save
        for lock in locks:
            state.locks[(lock.project_key, lock.story_id, lock.run_id, lock.lock_type)] = (
                lock
            )

    return ControlPlaneRuntimeRepository(
        load_operation=state.operations.get,
        commit_operation_with_side_effects=_commit,
        has_committed_story_exit_operation_for_run=lambda project_key, story_id, run_id: any(
            operation.operation_kind == "story_exit"
            and operation.project_key == project_key
            and operation.story_id == story_id
            and operation.run_id == run_id
            for operation in state.operations.values()
        ),
        load_binding=state.bindings.get,
        load_lock=lambda project_key, story_id, run_id, lock_type: state.locks.get(
            (project_key, story_id, run_id, lock_type)
        ),
    )


@pytest.mark.requires_git
def test_story_exit_preserves_worktree_branch_and_commissions_no_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    worktree = tmp_path / "worktree"
    repo_root.mkdir()
    _git(repo_root, "init", "-q", "-b", "main")
    _git(repo_root, "config", "user.email", "t@example.com")
    _git(repo_root, "config", "user.name", "T")
    _git(repo_root, "config", "commit.gpgsign", "false")
    (repo_root / "README.md").write_text("seed\n", encoding="utf-8")
    _git(repo_root, "add", "README.md")
    _git(repo_root, "commit", "-q", "-m", "seed")
    _git(repo_root, "worktree", "add", "-q", "-b", "story/AG3-079", str(worktree))
    (worktree / "preserve.txt").write_text("must survive exit\n", encoding="utf-8")

    cleanup_calls: list[str] = []

    def _record_cleanup(*args: object, **kwargs: object) -> None:
        del args, kwargs
        cleanup_calls.append("cleanup")

    monkeypatch.setattr(
        "agentkit.backend.bootstrap.edge_provisioning_adapter.commission_teardown_worktree",
        _record_cleanup,
    )
    monkeypatch.setattr(
        "agentkit.backend.state_backend.harness_edge_command_store.commission_edge_command_record_global",
        _record_cleanup,
    )
    monkeypatch.setattr(
        "agentkit.backend.state_backend.harness_edge_command_store.insert_edge_command_record_global",
        _record_cleanup,
    )

    binding = SessionRunBindingRecord(
        session_id="sess-079",
        project_key="ak3",
        story_id="AG3-079",
        run_id="run-079",
        principal_type="orchestrator",
        worktree_roots=(str(worktree),),
        binding_version="1",
        updated_at=_NOW,
    )
    state = _ExitState(operations={}, bindings={binding.session_id: binding}, locks={})
    service = StoryExitService(
        control_plane_repository=_exit_repository(state),
        story_service=SimpleNamespace(
            administratively_cancel_for_story_exit=lambda *args, **kwargs: SimpleNamespace(
                status="Cancelled"
            )
        ),
        governance=SimpleNamespace(
            deactivate_locks=lambda _story_id: SimpleNamespace(
                restored_to_ai_augmented=True
            )
        ),
        artifact_root=tmp_path / "artifacts",
        run_state_loader=lambda _request: ExitRunState(
            project_key="ak3",
            story_id="AG3-079",
            run_id="run-079",
            session_id="sess-079",
            human_design_required=True,
            remediation_exhausted=True,
            architecture_blockers=("human architecture decision required",),
        ),
        now_fn=lambda: _NOW,
    )

    result = service.exit_story(
        StoryExitRequest(
            project_key="ak3",
            story_id="AG3-079",
            run_id="run-079",
            session_id="sess-079",
            reason=ExitReason.SOLUTION_VIABILITY_REQUIRES_HUMAN_DESIGN,
            principal=Principal.HUMAN_CLI,
            exit_id="exit-079",
        )
    )

    assert result.exit_finalized is True
    assert cleanup_calls == []
    assert set(state.operations) == {"exit-079"}
    assert state.operations["exit-079"].operation_kind == "story_exit"
    assert worktree.is_dir()
    assert (worktree / "preserve.txt").read_text(encoding="utf-8") == (
        "must survive exit\n"
    )
    assert _git(repo_root, "show-ref", "--verify", "refs/heads/story/AG3-079")


def test_deployed_projectedge_reuses_shared_takeover_executor_without_copy() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    deployed = (
        repo_root
        / "src"
        / "agentkit"
        / "bundles"
        / "target_project"
        / "tools"
        / "agentkit"
        / "projectedge.py"
    ).read_text(encoding="utf-8")

    assert "process_open_commands" in deployed
    assert "takeover_reconcile" in deployed
    assert "def execute_takeover_reconcile" not in deployed
    assert "quarantine_worktree" not in deployed


def test_takeover_executor_has_no_stash_or_salvage_command_path() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    source = (
        repo_root
        / "src"
        / "agentkit"
        / "harness_client"
        / "projectedge"
        / "reconcile.py"
    ).read_text(encoding="utf-8")
    string_literals = {
        node.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }

    assert "stash" not in string_literals
    assert "salvage" not in string_literals
