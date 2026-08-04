"""AG3-206 transcript visibility and fail-closed hook process proofs."""

from __future__ import annotations

import builtins
import io
import json
import re
import subprocess
import sys
import textwrap
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agentkit.backend.cli.main import main as cli_main
from agentkit.harness_client.harness_adapters.claude_code import (
    main as claude_main,
)
from agentkit.harness_client.harness_adapters.claude_code import (
    main_project_edge,
)
from agentkit.harness_client.harness_adapters.codex.cli import main as codex_main
from agentkit.harness_client.harness_adapters.hook_error_report import (
    TranscriptFormatError,
    aggregate_hook_errors,
)

_CLAUDE_EVENT = json.dumps(
    {"tool_name": "Read", "tool_input": {"file_path": "a.py"}, "cwd": "."}
)
_CODEX_EVENT = json.dumps(
    {"tool": "read_file", "arguments": {"path": "a.py"}, "cwd": "."}
)


def _attachment(
    *,
    hook: str,
    stderr: str,
    command: str | None = None,
    timestamp: str = "2026-08-03T10:00:00Z",
) -> str:
    return json.dumps(
        {
            "type": "attachment",
            "timestamp": timestamp,
            "attachment": {
                "type": "hook_non_blocking_error",
                "hookName": hook,
                "stderr": stderr,
                "stdout": "",
                "exitCode": 1,
                "command": command or "agentkit-hook-claude pre branch_guard",
            },
        }
    )


def test_transcript_errors_are_grouped_by_command_and_text_deduplicated(
    tmp_path: Path,
) -> None:
    transcript = tmp_path / "incident.jsonl"
    toml_error = "Traceback\r\nModuleNotFoundError: No module named 'tomlkit'"
    colored_toml_error = (
        "Failed with non-blocking status code: "
        "\x1b[31mTraceback\x1b[0m\nModuleNotFoundError: No module named 'tomlkit'"
    )
    governance_error = "ModuleNotFoundError: No module named 'agentkit.governance'"
    lines = [
        _attachment(
            hook="PreToolUse:Bash",
            command="agentkit-hook-claude pre commit_hook",
            stderr=toml_error,
        ),
        _attachment(
            hook="PreToolUse:Bash",
            command="agentkit-hook-claude pre commit_hook",
            stderr=colored_toml_error,
        ),
        _attachment(
            hook="PreToolUse:Bash",
            command="agentkit-hook-claude pre skill_usage_check",
            stderr=governance_error,
        ),
        _attachment(
            hook="PostToolUse:Bash",
            command="agentkit-hook-claude post health_monitor",
            stderr=toml_error,
        ),
        json.dumps({"type": "assistant", "message": {"content": "ignored"}}),
    ]
    transcript.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = aggregate_hook_errors(transcript)

    assert report.total_errors == 4
    assert [group.hook for group in report.hooks] == [
        "agentkit-hook-claude post health_monitor",
        "agentkit-hook-claude pre commit_hook",
        "agentkit-hook-claude pre skill_usage_check",
    ]
    pre = report.hooks[1]
    assert pre.total == 2
    assert [(error.count, error.text) for error in pre.errors] == [
        (2, "Traceback\nModuleNotFoundError: No module named 'tomlkit'"),
    ]


def test_timestamp_window_reproduces_incident_slice(tmp_path: Path) -> None:
    transcript = tmp_path / "growing-session.jsonl"
    transcript.write_text(
        "\n".join(
            [
                _attachment(
                    hook="PreToolUse:Read",
                    stderr="first",
                    timestamp="2026-08-03T09:59:59Z",
                ),
                _attachment(
                    hook="PreToolUse:Read",
                    stderr="second",
                    timestamp="2026-08-03T10:00:00Z",
                ),
                _attachment(
                    hook="PreToolUse:Read",
                    stderr="later",
                    timestamp="2026-08-03T10:00:01Z",
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    report = aggregate_hook_errors(
        transcript,
        since=datetime(2026, 8, 3, 10, 0, tzinfo=UTC),
        until=datetime(2026, 8, 3, 10, 0, tzinfo=UTC),
    )

    assert report.total_errors == 1
    assert report.hooks[0].errors[0].text == "second"


def test_hook_errors_cli_outputs_machine_readable_report(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        _attachment(hook="PreToolUse:Read", stderr="broken") + "\n",
        encoding="utf-8",
    )

    assert cli_main(["hook-errors", str(transcript)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["total_errors"] == 1
    assert payload["hooks"][0]["hook"] == "agentkit-hook-claude pre branch_guard"
    assert payload["hooks"][0]["errors"] == [{"count": 1, "text": "broken"}]


def test_malformed_transcript_fails_closed(tmp_path: Path) -> None:
    transcript = tmp_path / "broken.jsonl"
    transcript.write_text("{not-json}\n", encoding="utf-8")

    with pytest.raises(TranscriptFormatError, match="invalid JSON"):
        aggregate_hook_errors(transcript)


def test_malformed_attachment_record_fails_closed(tmp_path: Path) -> None:
    transcript = tmp_path / "broken-attachment.jsonl"
    transcript.write_text(
        json.dumps({"type": "attachment", "attachment": []}) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(TranscriptFormatError, match="attachment must be an object"):
        aggregate_hook_errors(transcript)


@pytest.mark.parametrize("attachment_type", [None, "", 7])
def test_attachment_without_valid_type_fails_closed(
    tmp_path: Path,
    attachment_type: object,
) -> None:
    transcript = tmp_path / "invalid-attachment-type.jsonl"
    record = {
        "type": "attachment",
        "attachment": {"type": attachment_type},
    }
    transcript.write_text(json.dumps(record) + "\n", encoding="utf-8")

    with pytest.raises(TranscriptFormatError, match="attachment has no non-empty type"):
        aggregate_hook_errors(transcript)


@pytest.mark.parametrize(
    "stderr",
    ["\x1b[31m\x1b[0m", "Failed with non-blocking status code:"],
)
def test_hook_error_text_must_remain_non_empty_after_normalization(
    tmp_path: Path,
    stderr: str,
) -> None:
    transcript = tmp_path / "empty-normalized-error.jsonl"
    transcript.write_text(
        _attachment(hook="PreToolUse:Read", stderr=stderr) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(TranscriptFormatError, match="after normalization"):
        aggregate_hook_errors(transcript)


@pytest.mark.parametrize("timestamp", [None, "not-a-timestamp", "2026-08-03T10:00:00"])
def test_hook_error_timestamp_is_validated_without_bounds(
    tmp_path: Path,
    timestamp: str | None,
) -> None:
    transcript = tmp_path / "invalid-timestamp.jsonl"
    record = json.loads(_attachment(hook="PreToolUse:Read", stderr="broken"))
    if timestamp is None:
        del record["timestamp"]
    else:
        record["timestamp"] = timestamp
    transcript.write_text(json.dumps(record) + "\n", encoding="utf-8")

    with pytest.raises(TranscriptFormatError, match="timestamp|Timestamp"):
        aggregate_hook_errors(transcript)


@pytest.mark.parametrize(
    ("entrypoint", "event", "blocked_import"),
    [
        (claude_main, _CLAUDE_EVENT, "agentkit.backend.governance.runner"),
        (codex_main, _CODEX_EVENT, "agentkit.backend.governance.runner"),
        (main_project_edge, _CLAUDE_EVENT, "agentkit.backend.governance.guard_evaluation"),
    ],
)
def test_hook_runtime_import_failure_blocks_instead_of_appearing_successful(
    entrypoint: object,
    event: str,
    blocked_import: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC 4: even a startup import fault becomes the harness BLOCK code 2."""
    real_import = builtins.__import__

    def _failing_import(
        name: str,
        globals_: dict[str, object] | None = None,
        locals_: dict[str, object] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        if name == blocked_import:
            raise ModuleNotFoundError("No module named 'tomlkit'")
        return real_import(name, globals_, locals_, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _failing_import)
    monkeypatch.setattr("sys.stdin", io.StringIO(event))
    arguments = [] if entrypoint is main_project_edge else ["pre", "branch_guard"]

    assert callable(entrypoint)
    assert entrypoint(arguments) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["decision"] == "block"
    assert payload["detail"]["fault_class"] == "ModuleNotFoundError"


@pytest.mark.parametrize(
    ("module_name", "event"),
    [
        (
            "agentkit.harness_client.harness_adapters.claude_code",
            _CLAUDE_EVENT,
        ),
        (
            "agentkit.harness_client.harness_adapters.codex.cli",
            _CODEX_EVENT,
        ),
    ],
)
def test_hook_entrypoint_imports_without_pydantic_and_blocks_fail_closed(
    module_name: str,
    event: str,
) -> None:
    """B2: each shipped hook boundary survives a missing top-level package."""
    source = f"""
        import importlib
        import importlib.abc
        import io
        import json
        import sys

        class BlockPydantic(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "pydantic" or fullname.startswith("pydantic."):
                    raise ModuleNotFoundError("No module named 'pydantic'")
                return None

        sys.meta_path.insert(0, BlockPydantic())
        module = importlib.import_module({module_name!r})
        sys.stdin = io.StringIO({event!r})
        exit_code = module.main(["pre", "branch_guard"])
        print(json.dumps({{"exit_code": exit_code}}))
    """
    result = subprocess.run(  # noqa: S603 - fixed current-interpreter invocation
        [sys.executable, "-c", textwrap.dedent(source)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    payload = json.loads(lines[0])
    assert payload["decision"] == "block"
    assert payload["detail"]["fault_class"] == "ModuleNotFoundError"
    assert json.loads(lines[1]) == {"exit_code": 2}


@pytest.mark.parametrize(
    ("entrypoint", "event", "mapper_target"),
    [
        (
            claude_main,
            _CLAUDE_EVENT,
            "agentkit.harness_client.harness_adapters.claude_code.to_neutral_event",
        ),
        (
            codex_main,
            _CODEX_EVENT,
            "agentkit.harness_client.harness_adapters.codex.event_mapping.to_neutral_event",
        ),
    ],
)
def test_hook_event_mapping_failure_blocks_instead_of_escaping(
    entrypoint: object,
    event: str,
    mapper_target: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC 4: mapper faults remain inside the outer fail-closed boundary."""

    def _fail_mapping(_event: object) -> None:
        raise RuntimeError("mapper failed")

    monkeypatch.setattr(mapper_target, _fail_mapping)
    monkeypatch.setattr("sys.stdin", io.StringIO(event))

    assert callable(entrypoint)
    assert entrypoint(["pre", "branch_guard"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["decision"] == "block"
    assert payload["detail"]["fault_class"] == "RuntimeError"


def test_shipped_hook_surfaces_contain_no_unconditional_success_shell_guard() -> None:
    """AC 4: no shipped hook command masks failure with ``|| true``."""
    roots = (
        Path("src/agentkit/harness_client/harness_adapters"),
        Path("src/agentkit/bundles/target_project"),
    )
    offenders: list[str] = []
    for root in roots:
        for path in root.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            if path.suffix not in {".json", ".py", ".sh", ".toml", ".j2"}:
                continue
            text = path.read_text(encoding="utf-8")
            if re.search(r"\|\|\s*true\b", text):
                offenders.append(str(path))
    assert not offenders, f"hook failure is masked in: {offenders}"
