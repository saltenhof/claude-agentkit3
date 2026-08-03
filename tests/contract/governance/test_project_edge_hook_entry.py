"""The scaffold's pre-tool wrapper must actually run, and must not block blindly.

AK3 rolls `.agentkit/hooks/pre_tool_use.py` into every installed project on the
matcher `Bash|Write|Edit|Read|Grep|Glob`. It pointed at `agentkit.governance.…`,
a module the deployment-unit restructure removed, and called an entry point that
requires `{phase} {hook_id}` with no arguments at all. Measured in one session:
74 failures, and NO guard ran for Write, Edit, Read, Grep or Glob.

Repairing only the import turns 74 silent failures into 74 refused tool calls,
because the argument parser returns 2 and 2 means BLOCK here. These tests hold
both halves together.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import TYPE_CHECKING

from agentkit.harness_client.harness_adapters import claude_code

if TYPE_CHECKING:
    import pytest

SCAFFOLD_WRAPPER = (
    Path(__file__).resolve().parents[3]
    / "src/agentkit/bundles/target_project/.agentkit/hooks/pre_tool_use.py"
)

REAL_PAYLOAD = {
    "session_id": "probe",
    "cwd": "T:/codebase/intima",
    "tool_name": "Read",
    "tool_input": {"file_path": "README.md"},
    "hook_event_name": "PreToolUse",
    "tool_use_id": "toolu_probe",
    "permission_mode": "bypassPermissions",
    "effort": {"level": "high"},
}


def test_the_scaffold_wrapper_imports_a_module_that_exists() -> None:
    """The wrapper is deployed verbatim -- its import must resolve TODAY."""
    source = SCAFFOLD_WRAPPER.read_text(encoding="utf-8")

    assert "agentkit.governance." not in source, "points at a module the restructure removed"
    assert "main_project_edge" in source, "must call the argumentless collective entry"

    namespace: dict[str, object] = {}
    exec(compile(source, str(SCAFFOLD_WRAPPER), "exec"), namespace)  # noqa: S102
    assert callable(namespace["main_project_edge"])


def test_the_collective_entry_allows_a_harmless_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(REAL_PAYLOAD)))
    monkeypatch.setattr(
        "agentkit.backend.governance.guard_evaluation.evaluate_pre_tool_use",
        lambda _event, **_kwargs: _Allow(),
    )

    assert claude_code.main_project_edge([]) == 0


def test_an_argument_is_rejected_without_pretending_to_be_a_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wrapper takes no arguments; a caller that passes one must be told."""
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(REAL_PAYLOAD)))

    assert claude_code.main_project_edge(["pre", "branch_guard"]) == 2


def test_an_evaluation_fault_blocks_rather_than_allowing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _explode(_event: object, **_kwargs: object) -> object:
        raise RuntimeError("guard registry unavailable")

    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(REAL_PAYLOAD)))
    monkeypatch.setattr(
        "agentkit.backend.governance.guard_evaluation.evaluate_pre_tool_use",
        _explode,
    )

    assert claude_code.main_project_edge([]) == 2


class _Allow:
    allowed = True
    guard_name = "guard_evaluation"
    message = ""
    detail: dict[str, object] = {}
    warning = None
