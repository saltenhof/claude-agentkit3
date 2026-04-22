from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta

from agentkit.control_plane.models import (
    EdgeBundle,
    EdgePointer,
    SessionRunBindingView,
    StoryExecutionLockView,
)
from agentkit.governance.hookruntime import (
    HookEvent,
    _normalize_event,
    _parse_hook_event,
    evaluate_pre_tool_use,
    main,
)
from agentkit.governance.protocols import GuardVerdict, ViolationType
from agentkit.projectedge.client import LocalEdgePublisher


def _bundle(
    *,
    worktree_root: str,
    operating_mode: str = "story_execution",
    lock_status: str = "ACTIVE",
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
    )


def test_hookruntime_blocks_force_push_even_without_story_execution(tmp_path) -> None:
    verdict = evaluate_pre_tool_use(
        HookEvent(
            tool_name="Bash",
            tool_input={"command": "git push --force origin feature"},
            cwd=str(tmp_path),
            session_id=None,
        ),
        project_root=tmp_path,
    )

    assert verdict.allowed is False
    assert verdict.guard_name == "branch_guard"


def test_hookruntime_blocks_write_outside_story_worktree(tmp_path) -> None:
    worktree = tmp_path / "worktree"
    LocalEdgePublisher(project_root=tmp_path).publish(_bundle(worktree_root=str(worktree)))

    verdict = evaluate_pre_tool_use(
        HookEvent(
            tool_name="Write",
            tool_input={"file_path": str(tmp_path / "outside.py")},
            cwd=str(worktree),
            session_id="sess-001",
        ),
        project_root=tmp_path,
    )

    assert verdict.allowed is False
    assert verdict.guard_name == "scope_guard"


def test_hookruntime_blocks_qa_artifact_tampering_in_story_execution(tmp_path) -> None:
    worktree = tmp_path / "worktree"
    LocalEdgePublisher(project_root=tmp_path).publish(_bundle(worktree_root=str(worktree)))

    verdict = evaluate_pre_tool_use(
        HookEvent(
            tool_name="Write",
            tool_input={
                "file_path": str(
                    tmp_path / "_temp" / "qa" / "AG3-100" / "verify-decision.json",
                ),
            },
            cwd=str(worktree),
            session_id="sess-001",
            is_subagent=True,
        ),
        project_root=tmp_path,
    )

    assert verdict.allowed is False
    assert verdict.guard_name == "artifact_guard"


def test_hookruntime_allows_main_agent_write_to_qa_directory(tmp_path) -> None:
    worktree = tmp_path / "worktree"
    LocalEdgePublisher(project_root=tmp_path).publish(_bundle(worktree_root=str(worktree)))

    verdict = evaluate_pre_tool_use(
        HookEvent(
            tool_name="Write",
            tool_input={
                "file_path": str(
                    tmp_path / "_temp" / "qa" / "AG3-100" / "structural.json",
                ),
            },
            cwd=str(worktree),
            session_id="sess-001",
            is_subagent=False,
        ),
        project_root=tmp_path,
    )

    assert verdict.allowed is True


def test_hookruntime_blocks_mutation_for_binding_invalid(tmp_path) -> None:
    worktree = tmp_path / "worktree"
    LocalEdgePublisher(project_root=tmp_path).publish(
        _bundle(worktree_root=str(worktree), lock_status="INVALID"),
    )

    verdict = evaluate_pre_tool_use(
        HookEvent(
            tool_name="Write",
            tool_input={"file_path": str(worktree / "src" / "main.py")},
            cwd=str(worktree),
            session_id="sess-001",
        ),
        project_root=tmp_path,
    )

    assert verdict.allowed is False
    assert verdict.guard_name == "operating_mode_guard"


def test_hookruntime_blocks_non_story_branch_push_in_story_execution(tmp_path) -> None:
    worktree = tmp_path / "worktree"
    LocalEdgePublisher(project_root=tmp_path).publish(_bundle(worktree_root=str(worktree)))

    verdict = evaluate_pre_tool_use(
        HookEvent(
            tool_name="Bash",
            tool_input={"command": "git push origin feature/AG3-100"},
            cwd=str(worktree),
            session_id="sess-001",
        ),
        project_root=tmp_path,
    )

    assert verdict.allowed is False
    assert verdict.guard_name == "branch_guard"


def test_hookruntime_blocks_bash_git_internal_mutation(tmp_path) -> None:
    verdict = evaluate_pre_tool_use(
        HookEvent(
            tool_name="Bash",
            tool_input={"command": "Remove-Item .git/refs/heads/main"},
            cwd=str(tmp_path),
            session_id=None,
        ),
        project_root=tmp_path,
    )

    assert verdict.allowed is False
    assert verdict.guard_name == "branch_guard"


def test_parse_hook_event_defaults_cwd_and_discards_invalid_session(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.chdir(tmp_path)

    event = _parse_hook_event(
        json.dumps(
            {
                "tool_name": "Write",
                "tool_input": {"file_path": "x.py"},
                "session_id": 123,
            },
        ),
    )

    assert event.cwd == str(tmp_path)
    assert event.session_id is None


def test_parse_hook_event_rejects_invalid_payload_shapes() -> None:
    try:
        _parse_hook_event("[]")
    except RuntimeError as exc:
        assert "JSON object" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected RuntimeError")

    try:
        _parse_hook_event(json.dumps({"tool_name": "Write", "tool_input": []}))
    except RuntimeError as exc:
        assert "tool_input" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected RuntimeError")


def test_normalize_event_covers_edit_read_and_unknown_tool() -> None:
    assert _normalize_event(
        HookEvent(
            tool_name="Edit",
            tool_input={"file_path": "a.py"},
            cwd=".",
            session_id=None,
        ),
    ) == ("file_edit", {"file_path": "a.py"}, "mutation")
    assert _normalize_event(
        HookEvent(
            tool_name="Read",
            tool_input={"file_path": "a.py"},
            cwd=".",
            session_id=None,
        ),
    ) == ("file_read", {"file_path": "a.py"}, "baseline_read")
    assert _normalize_event(
        HookEvent(tool_name="Task", tool_input={}, cwd=".", session_id=None),
    ) == ("unknown_tool", {}, "guarded_read")


def test_main_returns_allow_and_block_exit_codes(monkeypatch, capsys) -> None:
    allow_event = json.dumps({"tool_name": "Task", "tool_input": {}, "cwd": "."})
    monkeypatch.setattr("sys.stdin", io.StringIO(allow_event))
    monkeypatch.setattr(
        "agentkit.governance.hookruntime.evaluate_pre_tool_use",
        lambda event, project_root: GuardVerdict.allow("hook_runtime"),
    )
    assert main() == 0

    block_event = json.dumps({"tool_name": "Task", "tool_input": {}, "cwd": "."})
    monkeypatch.setattr("sys.stdin", io.StringIO(block_event))
    monkeypatch.setattr(
        "agentkit.governance.hookruntime.evaluate_pre_tool_use",
        lambda event, project_root: GuardVerdict.block(
            "branch_guard",
            ViolationType.BRANCH_VIOLATION,
            "blocked",
            detail={"command": "git push --force"},
        ),
    )

    assert main() == 2
    out = capsys.readouterr().out
    assert "\"decision\": \"block\"" in out
