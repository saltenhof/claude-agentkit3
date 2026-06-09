from __future__ import annotations

import io
import json
from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.governance.harness_adapters.claude_code import (
    ClaudeCodeHookEvent,
    _parse_hook_event,
    main,
    to_neutral_event,
)
from agentkit.governance.protocols import GuardVerdict, ViolationType
from agentkit.implementation.worker_health import PostToolOutcome

if TYPE_CHECKING:
    import pytest

    from agentkit.governance.guard_evaluation import HookEvent

_FIXTURE_DIR = Path(__file__).parents[2] / "fixtures" / "harness_post_tool"


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


def test_claude_post_tool_use_fixture_maps_outcome_contract() -> None:
    raw = (_FIXTURE_DIR / "claude_post_tool_use_success.json").read_text(
        encoding="utf-8",
    )
    event = to_neutral_event(_parse_hook_event(raw, phase="post"))

    assert event.operation == "bash_command"
    assert event.operation_args == {"command": "git status"}
    assert event.post_tool_outcome == {
        "exit_code": 0,
        "stdout": "On branch main\n",
        "stderr": "",
        "tool_result": {
            "exit_code": 0,
            "stdout": "On branch main\n",
            "stderr": "",
        },
    }
    PostToolOutcome.model_validate(event.post_tool_outcome)


def test_claude_failure_fixture_maps_post_tool_use_failure() -> None:
    raw = (_FIXTURE_DIR / "claude_post_tool_use_failure.json").read_text(
        encoding="utf-8",
    )
    event = to_neutral_event(_parse_hook_event(raw, phase="post"))

    assert event.operation == "bash_command"
    assert event.operation_args == {"command": "git commit -m change"}
    assert event.post_tool_outcome == {
        "exit_code": 1,
        "stdout": "",
        "stderr": "Command exited with non-zero status code 1",
        "tool_result": None,
    }
    PostToolOutcome.model_validate(event.post_tool_outcome)


def test_claude_partial_post_payload_defaults_and_discards_extras() -> None:
    event = to_neutral_event(
        _parse_hook_event(
            json.dumps(
                {
                    "hook_event_name": "PostToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": "git status"},
                    "tool_response": {
                        "stdout": {"lines": ["ok"]},
                        "stderr": ["warn"],
                        "unexpected": "discarded at outcome boundary",
                    },
                },
            ),
            phase="post",
        )
    )

    assert event.post_tool_outcome == {
        "exit_code": None,
        "stdout": "{\"lines\": [\"ok\"]}",
        "stderr": "[\"warn\"]",
        "tool_result": {
            "stdout": {"lines": ["ok"]},
            "stderr": ["warn"],
            "unexpected": "discarded at outcome boundary",
        },
    }
    PostToolOutcome.model_validate(event.post_tool_outcome)


def test_claude_phase_aware_cli_sends_post_outcome_to_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = (_FIXTURE_DIR / "claude_post_tool_use_success.json").read_text(
        encoding="utf-8",
    )
    captured: list[tuple[str, HookEvent, str]] = []

    def _spy(
        hook_id: str,
        event: HookEvent,
        phase: str = "pre",
        project_root: object = None,
    ) -> GuardVerdict:
        _ = project_root
        captured.append((hook_id, event, phase))
        return GuardVerdict.allow("health_monitor")

    monkeypatch.setattr("sys.stdin", io.StringIO(raw))
    monkeypatch.setattr(
        "agentkit.governance.runner.Governance.run_hook",
        staticmethod(_spy),
    )

    assert main(["post", "health_monitor"]) == 0
    assert captured[0][0] == "health_monitor"
    assert captured[0][2] == "post"
    assert captured[0][1].post_tool_outcome is not None


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
    # AG3-036 FIX-1: the original tool name MUST survive the adapter (the
    # runner's ``_event_tool`` derives WebFetch/WebSearch from it). Dropping it
    # (the old ``{}``) blinded the web-call budget guard -> fail-open.
    assert unknown.operation_args == {"tool_name": "Task"}
    assert unknown.freshness_class == "guarded_read"


def test_main_returns_allow_and_block_exit_codes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    allow_event = json.dumps({"tool_name": "Task", "tool_input": {}, "cwd": "."})
    monkeypatch.setattr("sys.stdin", io.StringIO(allow_event))
    monkeypatch.setattr(
        "agentkit.governance.runner.Governance.run_hook",
        staticmethod(lambda hook_id, event, phase="pre", project_root=None: GuardVerdict.allow("guard_evaluation")),
    )
    assert main(["pre", "branch_guard"]) == 0

    block_event = json.dumps({"tool_name": "Task", "tool_input": {}, "cwd": "."})
    monkeypatch.setattr("sys.stdin", io.StringIO(block_event))
    monkeypatch.setattr(
        "agentkit.governance.runner.Governance.run_hook",
        staticmethod(
            lambda hook_id, event, phase="pre", project_root=None: GuardVerdict.block(
                "branch_guard",
                ViolationType.BRANCH_VIOLATION,
                "blocked",
                detail={"command": "git push --force"},
            )
        ),
    )

    assert main(["pre", "branch_guard"]) == 2
    out = capsys.readouterr().out
    assert "\"decision\": \"block\"" in out
