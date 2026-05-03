from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from agentkit.control_plane.models import (
    EdgeBundle,
    EdgePointer,
    SessionRunBindingView,
    StoryExecutionLockView,
)
from agentkit.governance.guard_evaluation import (
    HookEvent,
    _normalize_event,
    evaluate_pre_tool_use,
)
from agentkit.projectedge.client import LocalEdgePublisher

if TYPE_CHECKING:
    from pathlib import Path


def _bundle(
    *,
    worktree_root: str,
    operating_mode: Literal[
        "ai_augmented",
        "story_execution",
        "binding_invalid",
    ] = "story_execution",
    lock_status: Literal["ACTIVE", "INACTIVE", "INVALID"] = "ACTIVE",
    qa_lock_status: Literal["ACTIVE", "INACTIVE", "INVALID"] | None = "ACTIVE",
) -> EdgeBundle:
    now = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
    return EdgeBundle(
        current=EdgePointer(
            project_key="tenant-a",
            export_version="edge-001",
            operating_mode=operating_mode,
            bundle_dir="_temp/governance/bundles/edge-001",
            sync_after=now + timedelta(minutes=5),
            freshness_class="guarded_read",
            generated_at=now,
        ),
        session=SessionRunBindingView(
            session_id="sess-001",
            project_key="tenant-a",
            story_id="AG3-100",
            run_id="run-100",
            principal_type="orchestrator",
            worktree_roots=[worktree_root],
            binding_version="bind-001",
            operating_mode=operating_mode,
        ),
        lock=StoryExecutionLockView(
            project_key="tenant-a",
            story_id="AG3-100",
            run_id="run-100",
            lock_type="story_execution",
            status=lock_status,
            worktree_roots=[worktree_root],
            binding_version="bind-001",
            activated_at=now,
            updated_at=now,
        ),
        qa_lock=(
            StoryExecutionLockView(
                project_key="tenant-a",
                story_id="AG3-100",
                run_id="run-100",
                lock_type="qa_artifact_write",
                status=qa_lock_status,
                worktree_roots=[worktree_root],
                binding_version="bind-001",
                activated_at=now,
                updated_at=now,
            )
            if qa_lock_status is not None
            else None
        ),
    )


def test_guard_evaluation_blocks_force_push_without_story_execution(
    tmp_path: Path,
) -> None:
    verdict = evaluate_pre_tool_use(
        HookEvent(
            operation="bash_command",
            operation_args={"command": "git push --force origin feature"},
            freshness_class="mutation",
            cwd=str(tmp_path),
            session_id=None,
        ),
        project_root=tmp_path,
    )

    assert verdict.allowed is False
    assert verdict.guard_name == "branch_guard"


def test_guard_evaluation_blocks_write_outside_story_worktree(
    tmp_path: Path,
) -> None:
    worktree = tmp_path / "worktree"
    LocalEdgePublisher(project_root=tmp_path).publish(_bundle(worktree_root=str(worktree)))

    verdict = evaluate_pre_tool_use(
        HookEvent(
            operation="file_write",
            operation_args={"file_path": str(tmp_path / "outside.py")},
            freshness_class="mutation",
            cwd=str(worktree),
            session_id="sess-001",
        ),
        project_root=tmp_path,
    )

    assert verdict.allowed is False
    assert verdict.guard_name == "scope_guard"


def test_guard_evaluation_blocks_qa_artifact_tampering_in_story_execution(
    tmp_path: Path,
) -> None:
    worktree = tmp_path / "worktree"
    LocalEdgePublisher(project_root=tmp_path).publish(_bundle(worktree_root=str(worktree)))

    verdict = evaluate_pre_tool_use(
        HookEvent(
            operation="file_write",
            operation_args={
                "file_path": str(
                    tmp_path / "_temp" / "qa" / "AG3-100" / "verify-decision.json",
                ),
            },
            freshness_class="mutation",
            cwd=str(worktree),
            session_id="sess-001",
            principal_kind="subagent",
        ),
        project_root=tmp_path,
    )

    assert verdict.allowed is False
    assert verdict.guard_name == "artifact_guard"


def test_guard_evaluation_allows_main_agent_write_to_qa_directory(
    tmp_path: Path,
) -> None:
    worktree = tmp_path / "worktree"
    LocalEdgePublisher(project_root=tmp_path).publish(_bundle(worktree_root=str(worktree)))

    verdict = evaluate_pre_tool_use(
        HookEvent(
            operation="file_write",
            operation_args={
                "file_path": str(
                    tmp_path / "_temp" / "qa" / "AG3-100" / "structural.json",
                ),
            },
            freshness_class="mutation",
            cwd=str(worktree),
            session_id="sess-001",
            principal_kind="main",
        ),
        project_root=tmp_path,
    )

    assert verdict.allowed is True


def test_guard_evaluation_blocks_subagent_write_when_qa_lock_missing(
    tmp_path: Path,
) -> None:
    worktree = tmp_path / "worktree"
    LocalEdgePublisher(project_root=tmp_path).publish(
        _bundle(worktree_root=str(worktree), qa_lock_status=None),
    )

    verdict = evaluate_pre_tool_use(
        HookEvent(
            operation="file_write",
            operation_args={
                "file_path": str(
                    tmp_path / "_temp" / "qa" / "AG3-100" / "structural.json",
                ),
            },
            freshness_class="mutation",
            cwd=str(worktree),
            session_id="sess-001",
            principal_kind="subagent",
        ),
        project_root=tmp_path,
    )

    assert verdict.allowed is False
    assert verdict.guard_name == "artifact_guard"


def test_guard_evaluation_blocks_mutation_for_binding_invalid(
    tmp_path: Path,
) -> None:
    worktree = tmp_path / "worktree"
    LocalEdgePublisher(project_root=tmp_path).publish(
        _bundle(worktree_root=str(worktree), lock_status="INVALID"),
    )

    verdict = evaluate_pre_tool_use(
        HookEvent(
            operation="file_write",
            operation_args={"file_path": str(worktree / "src" / "main.py")},
            freshness_class="mutation",
            cwd=str(worktree),
            session_id="sess-001",
        ),
        project_root=tmp_path,
    )

    assert verdict.allowed is False
    assert verdict.guard_name == "operating_mode_guard"


def test_guard_evaluation_blocks_non_story_branch_push_in_story_execution(
    tmp_path: Path,
) -> None:
    worktree = tmp_path / "worktree"
    LocalEdgePublisher(project_root=tmp_path).publish(_bundle(worktree_root=str(worktree)))

    verdict = evaluate_pre_tool_use(
        HookEvent(
            operation="bash_command",
            operation_args={"command": "git push origin feature/AG3-100"},
            freshness_class="mutation",
            cwd=str(worktree),
            session_id="sess-001",
        ),
        project_root=tmp_path,
    )

    assert verdict.allowed is False
    assert verdict.guard_name == "branch_guard"


def test_guard_evaluation_blocks_bash_git_internal_mutation(tmp_path: Path) -> None:
    verdict = evaluate_pre_tool_use(
        HookEvent(
            operation="bash_command",
            operation_args={"command": "Remove-Item .git/refs/heads/main"},
            freshness_class="mutation",
            cwd=str(tmp_path),
            session_id=None,
        ),
        project_root=tmp_path,
    )

    assert verdict.allowed is False
    assert verdict.guard_name == "branch_guard"


def test_normalize_event_uses_neutral_operation_contract() -> None:
    assert _normalize_event(
        HookEvent(
            operation="file_edit",
            operation_args={"file_path": "a.py"},
            freshness_class="mutation",
            cwd=".",
            session_id=None,
        ),
    ) == ("file_edit", {"file_path": "a.py"}, "mutation")
    assert _normalize_event(
        HookEvent(
            operation="file_read",
            operation_args={"file_path": "a.py"},
            freshness_class="baseline_read",
            cwd=".",
            session_id=None,
        ),
    ) == ("file_read", {"file_path": "a.py"}, "baseline_read")
    assert _normalize_event(
        HookEvent(
            operation="unknown_tool",
            operation_args={},
            freshness_class="guarded_read",
            cwd=".",
            session_id=None,
        ),
    ) == ("unknown_tool", {}, "guarded_read")
