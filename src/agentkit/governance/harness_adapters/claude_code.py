"""Claude Code pre-tool hook adapter.

Official CLI entry point for Claude Code hooks:
``python -m agentkit.governance.harness_adapters.claude_code``.
The adapter preserves the external hook contract: blocked decisions are
printed as JSON to stdout and return exit code 2; allowed decisions
return exit code 0.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationError,
    field_validator,
    model_validator,
)

from agentkit.governance.guard_evaluation import (
    HookEvent,
    PrincipalKind,
    evaluate_pre_tool_use,
)

_READ_ONLY_TOOLS = frozenset({"Glob", "Grep", "Read"})


class ClaudeCodeHookEvent(BaseModel):
    """Claude Code pre-tool hook payload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_name: str
    tool_input: dict[str, object] = {}
    cwd: str = ""
    session_id: str | None = None
    is_subagent: bool = False

    @model_validator(mode="before")
    @classmethod
    def _apply_defaults(cls, value: object) -> object:
        if isinstance(value, dict) and "cwd" not in value:
            updated = dict(value)
            updated["cwd"] = str(Path.cwd())
            return updated
        return value

    @field_validator("tool_name")
    @classmethod
    def _validate_tool_name(cls, value: str) -> str:
        if not value:
            raise ValueError("tool_name must be a non-empty string")
        return value

    @field_validator("cwd", mode="before")
    @classmethod
    def _default_cwd(cls, value: object) -> str:
        if isinstance(value, str) and value:
            return value
        return str(Path.cwd())

    @field_validator("session_id", mode="before")
    @classmethod
    def _coerce_session_id(cls, value: object) -> str | None:
        return value if isinstance(value, str) else None


def to_neutral_event(claude_event: ClaudeCodeHookEvent) -> HookEvent:
    """Map a Claude Code hook payload to the harness-neutral event model."""
    principal_kind: PrincipalKind = "subagent" if claude_event.is_subagent else "main"
    if claude_event.tool_name == "Bash":
        return HookEvent(
            operation="bash_command",
            operation_args={"command": str(claude_event.tool_input.get("command", ""))},
            freshness_class="mutation",
            cwd=claude_event.cwd,
            session_id=claude_event.session_id,
            principal_kind=principal_kind,
        )
    if claude_event.tool_name == "Write":
        return HookEvent(
            operation="file_write",
            operation_args={
                "file_path": str(claude_event.tool_input.get("file_path", "")),
            },
            freshness_class="mutation",
            cwd=claude_event.cwd,
            session_id=claude_event.session_id,
            principal_kind=principal_kind,
        )
    if claude_event.tool_name == "Edit":
        return HookEvent(
            operation="file_edit",
            operation_args={
                "file_path": str(claude_event.tool_input.get("file_path", "")),
            },
            freshness_class="mutation",
            cwd=claude_event.cwd,
            session_id=claude_event.session_id,
            principal_kind=principal_kind,
        )
    if claude_event.tool_name in _READ_ONLY_TOOLS:
        return HookEvent(
            operation="file_read",
            operation_args={
                "file_path": str(claude_event.tool_input.get("file_path", "")),
            },
            freshness_class="baseline_read",
            cwd=claude_event.cwd,
            session_id=claude_event.session_id,
            principal_kind=principal_kind,
        )
    return HookEvent(
        operation="unknown_tool",
        operation_args={},
        freshness_class="guarded_read",
        cwd=claude_event.cwd,
        session_id=claude_event.session_id,
        principal_kind=principal_kind,
    )


def main(argv: list[str] | None = None) -> int:
    """Read one Claude Code hook event from stdin and return hook exit code."""
    del argv
    raw = sys.stdin.read()
    claude_event = _parse_hook_event(raw)
    event = to_neutral_event(claude_event)
    decision = evaluate_pre_tool_use(event, project_root=Path.cwd())
    if not decision.allowed:
        payload = {
            "decision": "block",
            "guard": decision.guard_name,
            "message": decision.message,
            "detail": decision.detail,
        }
        print(json.dumps(payload, sort_keys=True))
        return 2
    return 0


def _parse_hook_event(raw: str) -> ClaudeCodeHookEvent:
    try:
        return ClaudeCodeHookEvent.model_validate_json(raw)
    except ValidationError as exc:
        message = str(exc)
        if "tool_input" in message and "object" in message:
            raise RuntimeError("tool_input must be a JSON object") from exc
        if "Input should be an object" in message:
            raise RuntimeError("Hook payload must be a JSON object") from exc
        raise RuntimeError(str(exc)) from exc


__all__ = [
    "ClaudeCodeHookEvent",
    "main",
    "to_neutral_event",
]


if __name__ == "__main__":
    sys.exit(main())
