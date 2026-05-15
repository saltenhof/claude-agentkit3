from __future__ import annotations

import io
import json
from typing import TYPE_CHECKING

from agentkit.governance.harness_adapters.codex.cli import main
from agentkit.governance.protocols import GuardVerdict, ViolationType

if TYPE_CHECKING:
    import pytest


def test_main_returns_allow_exit_code_and_stdout_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(json.dumps({"tool": "read_file", "arguments": {"path": "a.py"}, "cwd": "."})),
    )
    monkeypatch.setattr(
        "agentkit.governance.runner.Governance.run_hook",
        staticmethod(lambda hook_id, event, phase="pre", project_root=None: GuardVerdict.allow("guard_evaluation")),
    )

    assert main(["pre", "branch_guard"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"decision": "allow", "guard": "guard_evaluation"}


def test_main_returns_block_exit_code_and_stdout_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(json.dumps({"tool": "shell_command", "arguments": {"command": "git push --force"}, "cwd": "."})),
    )
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
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "decision": "block",
        "detail": {"command": "git push --force"},
        "guard": "branch_guard",
        "message": "blocked",
    }
