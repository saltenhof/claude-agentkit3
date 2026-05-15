from __future__ import annotations

import json
from typing import TYPE_CHECKING

from agentkit.governance.harness_adapters.codex.cli import _parse_hook_event
from agentkit.governance.harness_adapters.codex.event_mapping import (
    CodexHookEvent,
    to_neutral_event,
)

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_parse_hook_event_accepts_codex_aliases_and_defaults_cwd(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)

    event = _parse_hook_event(
        json.dumps(
            {
                "tool": "shell_command",
                "arguments": {"command": "git status"},
                "sessionId": "session-1",
                "subagent": True,
            },
        ),
    )

    assert event.tool_name == "shell_command"
    assert event.tool_input == {"command": "git status"}
    assert event.cwd == str(tmp_path)
    assert event.session_id == "session-1"
    assert event.is_subagent is True


def test_parse_hook_event_rejects_invalid_payload_shapes() -> None:
    try:
        _parse_hook_event("[]")
    except RuntimeError as exc:
        assert "JSON object" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected RuntimeError")

    try:
        _parse_hook_event(json.dumps({"tool": "shell_command", "arguments": []}))
    except RuntimeError as exc:
        assert "tool_input" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected RuntimeError")


def test_to_neutral_event_maps_mutating_codex_tools() -> None:
    bash = to_neutral_event(
        CodexHookEvent(
            tool_name="shell_command",
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
        CodexHookEvent(
            tool_name="write_file",
            tool_input={"path": "a.py"},
            cwd=".",
        ),
    )
    assert write.operation == "file_write"
    assert write.operation_args == {"file_path": "a.py"}
    assert write.freshness_class == "mutation"

    edit = to_neutral_event(
        CodexHookEvent(
            tool_name="functions.apply_patch",
            tool_input={"file_path": "b.py"},
            cwd=".",
        ),
    )
    assert edit.operation == "file_edit"
    assert edit.operation_args == {"file_path": "b.py"}
    assert edit.freshness_class == "mutation"


def test_to_neutral_event_maps_read_and_unknown_codex_tools() -> None:
    read = to_neutral_event(
        CodexHookEvent(
            tool_name="read_file",
            tool_input={"path": "a.py"},
            cwd=".",
        ),
    )
    assert read.operation == "file_read"
    assert read.operation_args == {"file_path": "a.py"}
    assert read.freshness_class == "baseline_read"

    unknown = to_neutral_event(
        CodexHookEvent(tool_name="spawn_agent", tool_input={}, cwd="."),
    )
    assert unknown.operation == "unknown_tool"
    assert unknown.operation_args == {}
    assert unknown.freshness_class == "guarded_read"


def test_principal_kind_field_overrides_subagent_bool() -> None:
    event = to_neutral_event(
        CodexHookEvent(
            tool_name="read_file",
            tool_input={},
            cwd=".",
            is_subagent=True,
            principal_kind="main",
        ),
    )

    assert event.principal_kind == "main"
