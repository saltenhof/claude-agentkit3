from __future__ import annotations

import io
import json
from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.governance.harness_adapters.codex.cli import _parse_hook_event
from agentkit.governance.harness_adapters.codex.event_mapping import (
    CodexHookEvent,
    to_neutral_event,
)
from agentkit.governance.protocols import GuardVerdict
from agentkit.implementation.worker_health import PostToolOutcome, apply_post_tool_use
from agentkit.state_backend.store.worker_health_repository import (
    StateBackendWorkerHealthRepository,
)

if TYPE_CHECKING:
    import pytest

    from agentkit.governance.guard_evaluation import HookEvent

_FIXTURE_DIR = Path(__file__).parents[4] / "fixtures" / "harness_post_tool"


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


def test_codex_post_tool_use_fixture_matches_schema_and_maps_contract() -> None:
    payload = json.loads(
        (_FIXTURE_DIR / "codex_post_tool_use_success.json").read_text(
            encoding="utf-8",
        )
    )
    schema = json.loads(
        (
            _FIXTURE_DIR / "codex_post_tool_use.command.input.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert schema["properties"]["hook_event_name"]["const"] == "PostToolUse"
    assert set(schema["required"]).issubset(payload)
    assert payload["hook_event_name"] == "PostToolUse"

    event = to_neutral_event(
        _parse_hook_event(json.dumps(payload), phase="post"),
    )

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


def test_codex_post_tool_use_failure_fixture_maps_contract() -> None:
    raw = (_FIXTURE_DIR / "codex_post_tool_use_failure.json").read_text(
        encoding="utf-8",
    )
    event = to_neutral_event(_parse_hook_event(raw, phase="post"))

    assert event.operation == "bash_command"
    assert event.operation_args == {"command": "git commit -m change"}
    assert event.post_tool_outcome == {
        "exit_code": 1,
        "stdout": "",
        "stderr": "policy violation: commit blocked",
        "tool_result": {
            "exit_code": 1,
            "stdout": "",
            "stderr": "policy violation: commit blocked",
        },
    }
    PostToolOutcome.model_validate(event.post_tool_outcome)


def test_codex_partial_post_payload_defaults_and_string_response() -> None:
    event = to_neutral_event(
        _parse_hook_event(
            json.dumps(
                {
                    "hook_event_name": "PostToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": "git status"},
                    "tool_response": "plain output",
                },
            ),
            phase="post",
        )
    )

    assert event.post_tool_outcome == {
        "exit_code": None,
        "stdout": "plain output",
        "stderr": "",
        "tool_result": None,
    }
    PostToolOutcome.model_validate(event.post_tool_outcome)


def test_codex_phase_aware_cli_sends_post_outcome_to_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agentkit.governance.harness_adapters.codex.cli import main

    raw = (_FIXTURE_DIR / "codex_post_tool_use_success.json").read_text(
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


def test_codex_post_tool_input_malformed_fails_closed_without_runner_or_health_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from agentkit.governance.harness_adapters.codex.cli import main

    captured: list[HookEvent] = []
    malformed = json.dumps(
        {
            "hook_event_name": "PostToolUse",
            "tool_name": "shell_command",
            "tool_input": "git commit -m change",
            "tool_response": {"exit_code": 1},
            "cwd": str(tmp_path),
        }
    )

    def _spy(
        hook_id: str,
        event: HookEvent,
        phase: str = "pre",
        project_root: object = None,
    ) -> GuardVerdict:
        _ = hook_id, phase, project_root
        captured.append(event)
        return GuardVerdict.allow("health_monitor")

    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    monkeypatch.setenv("AGENTKIT_STORY_ID", "AG3-106")
    monkeypatch.setenv("AGENTKIT_WORKER_ID", "worker-1")
    monkeypatch.setattr("sys.stdin", io.StringIO(malformed))
    monkeypatch.setattr(
        "agentkit.governance.runner.Governance.run_hook",
        staticmethod(_spy),
    )

    assert main(["post", "health_monitor"]) == 2
    assert captured == []
    repository = StateBackendWorkerHealthRepository(tmp_path)
    assert repository.load(story_id="AG3-106", worker_id="worker-1") is None
    assert not (tmp_path / "_temp" / "qa" / "AG3-106").exists()


def test_codex_well_formed_failed_git_commit_post_updates_hook_conflict(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("AGENTKIT_STATE_BACKEND", "sqlite")
    monkeypatch.setenv("AGENTKIT_ALLOW_SQLITE", "1")
    repository = StateBackendWorkerHealthRepository(tmp_path)
    raw = (_FIXTURE_DIR / "codex_post_tool_use_failure.json").read_text(
        encoding="utf-8",
    )
    event = to_neutral_event(_parse_hook_event(raw, phase="post")).model_copy(
        update={
            "operation_args": {
                "story_id": "AG3-106",
                "worker_id": "worker-1",
                "command": "git commit -m change",
            }
        }
    )
    assert event.post_tool_outcome is not None

    state = apply_post_tool_use(
        event=event,
        outcome=PostToolOutcome.model_validate(event.post_tool_outcome),
        repository=repository,
        project_root=tmp_path,
    )

    assert state.score_components.hook_conflict > 0
    persisted = repository.load(story_id="AG3-106", worker_id="worker-1")
    assert persisted is not None
    assert persisted.score_components.hook_conflict > 0


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
    # AG3-036 FIX-2: the original tool name MUST survive the adapter so the
    # runner's ``_event_tool`` can still derive it (fail-closed backstop).
    assert unknown.operation_args == {"tool_name": "spawn_agent"}
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
