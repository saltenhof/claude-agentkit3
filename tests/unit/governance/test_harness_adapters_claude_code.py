from __future__ import annotations

import io
import json
from typing import TYPE_CHECKING

from agentkit.governance.harness_adapters.claude_code import (
    ClaudeCodeHookEvent,
    _parse_hook_event,
    main,
    to_neutral_event,
)
from agentkit.governance.protocols import GuardVerdict, ViolationType

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_parse_hook_event_defaults_cwd_and_discards_invalid_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
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


def test_to_neutral_event_maps_mutating_tools() -> None:
    bash = to_neutral_event(
        ClaudeCodeHookEvent(
            tool_name="Bash",
            tool_input={"command": "git status"},
            cwd=".",
            is_subagent=True,
        ),
    )
    assert bash.operation == "bash_command"
    assert bash.operation_args == {"command": "git status"}
    assert bash.freshness_class == "mutation"
    assert bash.principal_kind == "subagent"

    write = to_neutral_event(
        ClaudeCodeHookEvent(
            tool_name="Write",
            tool_input={"file_path": "a.py"},
            cwd=".",
        ),
    )
    assert write.operation == "file_write"
    assert write.operation_args == {"file_path": "a.py"}
    assert write.freshness_class == "mutation"

    edit = to_neutral_event(
        ClaudeCodeHookEvent(
            tool_name="Edit",
            tool_input={"file_path": "b.py"},
            cwd=".",
        ),
    )
    assert edit.operation == "file_edit"
    assert edit.operation_args == {"file_path": "b.py"}
    assert edit.freshness_class == "mutation"


def test_to_neutral_event_maps_read_and_unknown_tools() -> None:
    read = to_neutral_event(
        ClaudeCodeHookEvent(
            tool_name="Read",
            tool_input={"file_path": "a.py"},
            cwd=".",
        ),
    )
    assert read.operation == "file_read"
    assert read.operation_args == {"file_path": "a.py"}
    assert read.freshness_class == "baseline_read"

    unknown = to_neutral_event(
        ClaudeCodeHookEvent(tool_name="Task", tool_input={}, cwd="."),
    )
    assert unknown.operation == "unknown_tool"
    assert unknown.operation_args == {}
    assert unknown.freshness_class == "guarded_read"


def test_main_returns_allow_and_block_exit_codes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    allow_event = json.dumps({"tool_name": "Task", "tool_input": {}, "cwd": "."})
    monkeypatch.setattr("sys.stdin", io.StringIO(allow_event))
    monkeypatch.setattr(
        "agentkit.governance.harness_adapters.claude_code.evaluate_pre_tool_use",
        lambda event, project_root: GuardVerdict.allow("guard_evaluation"),
    )
    assert main() == 0

    block_event = json.dumps({"tool_name": "Task", "tool_input": {}, "cwd": "."})
    monkeypatch.setattr("sys.stdin", io.StringIO(block_event))
    monkeypatch.setattr(
        "agentkit.governance.harness_adapters.claude_code.evaluate_pre_tool_use",
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
