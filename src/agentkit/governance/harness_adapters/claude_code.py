"""Claude Code pre-tool hook adapter.

Official CLI entry point for Claude Code hooks:
``agentkit-hook-claude {phase} {hook_id}``

The adapter preserves the external hook contract: blocked decisions are
printed as JSON to stdout and return exit code 2; allowed decisions
return exit code 0.  Invalid arguments (unknown phase or hook_id) also
return exit code 2 with a message on stderr.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Literal

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
)
from agentkit.governance.harness_adapters.post_tool_outcome import (
    map_post_tool_outcome,
)
from agentkit.governance.runner import Governance, parse_hook_wrapper_args

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


class ClaudeCodePostToolEvent(BaseModel):
    """Claude Code post-tool hook payload."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    hook_event_name: Literal["PostToolUse", "PostToolUseFailure"]
    tool_name: str
    tool_input: dict[str, object] = {}
    cwd: str = ""
    session_id: str | None = None
    is_subagent: bool = False
    tool_response: object = None
    error: object = None

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

    @field_validator("tool_input", mode="before")
    @classmethod
    def _coerce_tool_input(cls, value: object) -> dict[str, object]:
        return value if isinstance(value, dict) else {}

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


def to_neutral_event(
    claude_event: ClaudeCodeHookEvent | ClaudeCodePostToolEvent,
) -> HookEvent:
    """Map a Claude Code hook payload to the harness-neutral event model."""
    principal_kind: PrincipalKind = "subagent" if claude_event.is_subagent else "main"
    post_tool_outcome = _post_tool_outcome(claude_event)
    if claude_event.tool_name == "Bash":
        return HookEvent(
            operation="bash_command",
            operation_args={"command": str(claude_event.tool_input.get("command", ""))},
            freshness_class="mutation",
            cwd=claude_event.cwd,
            session_id=claude_event.session_id,
            principal_kind=principal_kind,
            post_tool_outcome=post_tool_outcome,
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
            post_tool_outcome=post_tool_outcome,
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
            post_tool_outcome=post_tool_outcome,
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
            post_tool_outcome=post_tool_outcome,
        )
    # AG3-036 FIX-1: any tool without a dedicated harness-neutral operation
    # (WebFetch / WebSearch and every other unmapped tool) is emitted as
    # ``unknown_tool``, but its canonical name MUST survive the adapter via
    # ``operation_args["tool_name"]``. Discarding it (the old ``{}``) blinded
    # the runner's ``_event_tool`` so the web-call budget guard could never
    # derive WebFetch/WebSearch and silently failed OPEN (FK-68 §68.6.1).
    return HookEvent(
        operation="unknown_tool",
        operation_args={"tool_name": claude_event.tool_name},
        freshness_class="guarded_read",
        cwd=claude_event.cwd,
        session_id=claude_event.session_id,
        principal_kind=principal_kind,
        post_tool_outcome=post_tool_outcome,
    )


def _post_tool_outcome(
    claude_event: ClaudeCodeHookEvent | ClaudeCodePostToolEvent,
) -> dict[str, object] | None:
    if not isinstance(claude_event, ClaudeCodePostToolEvent):
        return None
    return map_post_tool_outcome(
        claude_event.tool_response,
        fallback_error=claude_event.error,
    )


def main(argv: list[str] | None = None) -> int:
    """Parse args, read stdin, evaluate governance hook, return exit code.

    Args:
        argv: Command-line arguments after the script name.  When ``None``,
            ``sys.argv[1:]`` is used.  Expected format:
            ``{phase} {hook_id}`` (e.g. ``pre branch_guard``).

    Returns:
        0 on ALLOW, 2 on BLOCK or invalid arguments.
    """
    args = list(sys.argv[1:]) if argv is None else list(argv)
    try:
        selector = parse_hook_wrapper_args(args, command_name="agentkit-hook-claude")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        raw = sys.stdin.read()
        claude_event = _parse_hook_event(raw, phase=selector.phase)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    event = to_neutral_event(claude_event)
    try:
        decision = Governance.run_hook(
            selector.hook_id,
            event,
            phase=selector.phase,
            project_root=Path.cwd(),
        )
    except Exception as exc:  # noqa: BLE001 — outermost fail-closed safety net.
        # AG3-032 ERROR 6 / FK-55 §55.10.5 / FK-31 §31.2.7: a governance hook
        # must NEVER let an evaluation fault escape and silently allow the tool
        # call. Any escaping exception is mapped to a fail-closed BLOCK (exit 2).
        print(
            json.dumps(
                {
                    "decision": "block",
                    "guard": "principal_capability",
                    "message": f"governance hook failed fail-closed: {exc}",
                    "detail": {"fault_class": type(exc).__name__},
                },
                sort_keys=True,
            )
        )
        return 2
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


def _parse_hook_event(
    raw: str,
    *,
    phase: str = "pre",
) -> ClaudeCodeHookEvent | ClaudeCodePostToolEvent:
    try:
        if phase == "post":
            return ClaudeCodePostToolEvent.model_validate_json(raw)
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
    "ClaudeCodePostToolEvent",
    "main",
    "to_neutral_event",
]


if __name__ == "__main__":
    sys.exit(main())
