"""Codex hook event mapping to the harness-neutral guard model."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from agentkit.governance.guard_evaluation import (
    HookEvent,
    Operation,
    PrincipalKind,
)

if TYPE_CHECKING:
    from agentkit.projectedge.runtime import FreshnessClass

CodexToolName = Literal[
    "shell_command",
    "apply_patch",
    "write_file",
    "edit_file",
    "read_file",
    "list_files",
    "search_files",
    "view_image",
]

_BASH_TOOLS = frozenset({"shell_command", "exec_command", "exec", "bash", "command"})
_FILE_WRITE_TOOLS = frozenset({"write_file", "create_file"})
_FILE_EDIT_TOOLS = frozenset({"apply_patch", "edit_file", "patch_file"})
_FILE_READ_TOOLS = frozenset(
    {
        "read_file",
        "open_file",
        "list_files",
        "search_files",
        "view_image",
        "read",
        "grep",
        "glob",
        "rg",
    },
)
_TOOL_CLASSIFICATIONS = (
    (_BASH_TOOLS, "bash_command", "mutation", "command", ("command", "cmd", "script")),
    (
        _FILE_WRITE_TOOLS,
        "file_write",
        "mutation",
        "file_path",
        ("file_path", "path", "filename"),
    ),
    (
        _FILE_EDIT_TOOLS,
        "file_edit",
        "mutation",
        "file_path",
        ("file_path", "path", "filename"),
    ),
    (
        _FILE_READ_TOOLS,
        "file_read",
        "baseline_read",
        "file_path",
        ("file_path", "path", "filename"),
    ),
)
_ALIASES: dict[str, tuple[str, ...]] = {
    "tool_name": ("tool", "toolName", "name"),
    "tool_input": ("arguments", "input", "toolInput"),
    "cwd": ("current_working_directory", "working_dir"),
    "session_id": ("sessionId", "conversation_id", "conversationId"),
    "is_subagent": ("subagent", "isSubagent", "is_subagent_session"),
}


class CodexHookEvent(BaseModel):
    """Codex pre-tool hook payload accepted by the AK3 adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    tool_name: str
    tool_input: dict[str, object] = {}
    cwd: str = ""
    session_id: str | None = None
    is_subagent: bool = False
    principal_kind: PrincipalKind | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_aliases(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        updated = dict(value)
        for canonical, aliases in _ALIASES.items():
            _copy_first_alias(updated, canonical, aliases)
        updated.setdefault("cwd", str(Path.cwd()))
        return updated

    @field_validator("tool_name")
    @classmethod
    def _validate_tool_name(cls, value: str) -> str:
        if not value:
            raise ValueError("tool_name must be a non-empty string")
        return value

    @field_validator("tool_input", mode="before")
    @classmethod
    def _validate_tool_input(cls, value: object) -> dict[str, object]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        raise ValueError("tool_input must be a JSON object")

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


def to_neutral_event(codex_event: CodexHookEvent) -> HookEvent:
    """Map a Codex hook payload to the harness-neutral event model."""
    operation, freshness_class, operation_args = _classify_tool(
        codex_event.tool_name,
        codex_event.tool_input,
    )
    return HookEvent(
        operation=operation,
        operation_args=operation_args,
        freshness_class=freshness_class,
        cwd=codex_event.cwd,
        session_id=codex_event.session_id,
        principal_kind=_principal_kind(codex_event),
    )


def _classify_tool(
    tool_name: str,
    tool_input: dict[str, object],
) -> tuple[Operation, FreshnessClass, dict[str, object]]:
    normalized_tool = _normalize_tool_name(tool_name)
    for tools, operation, freshness_class, arg_name, arg_keys in _TOOL_CLASSIFICATIONS:
        if normalized_tool in tools:
            return (
                cast("Operation", operation),
                cast("FreshnessClass", freshness_class),
                {arg_name: _string_arg(tool_input, *arg_keys)},
            )
    # AG3-036 FIX-2: any tool without a dedicated harness-neutral operation is
    # emitted as ``unknown_tool``, but its ORIGINAL name MUST survive the adapter
    # via ``operation_args["tool_name"]`` (the runner's ``_event_tool``
    # convention, mirroring the Claude adapter). FK-76 §76.5.2: Codex exposes no
    # WebSearch/WebFetch surface, so the settings writer registers no web matcher
    # for Codex (documented, not silent). This preserve-the-name branch is the
    # fail-closed backstop: if a WebFetch/WebSearch name EVER reaches the Codex
    # governance runner, ``budget_event_emitter`` can still derive the web tool
    # and DENY a research over-budget / unresolved call rather than letting it
    # slip through unenforced (defence in depth, no silent drop of enforcement).
    return "unknown_tool", "guarded_read", {"tool_name": tool_name}


def _normalize_tool_name(tool_name: str) -> str:
    normalized_tool = tool_name.strip().replace("-", "_")
    normalized_tool = normalized_tool.removeprefix("functions.")
    return normalized_tool.lower()


def _copy_first_alias(
    value: dict[str, object],
    canonical: str,
    aliases: tuple[str, ...],
) -> None:
    if canonical in value:
        return
    alias = next((candidate for candidate in aliases if candidate in value), None)
    if alias is not None:
        value[canonical] = value.pop(alias)


def _principal_kind(codex_event: CodexHookEvent) -> PrincipalKind:
    if codex_event.principal_kind is not None:
        return codex_event.principal_kind
    return "subagent" if codex_event.is_subagent else "main"


def _string_arg(tool_input: dict[str, object], *keys: str) -> str:
    for key in keys:
        value = tool_input.get(key)
        if isinstance(value, str):
            return value
    return ""


__all__ = [
    "CodexHookEvent",
    "to_neutral_event",
]
