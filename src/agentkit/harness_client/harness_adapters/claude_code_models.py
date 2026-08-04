"""Pydantic payload models for the Claude Code harness adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class ClaudeCodeHookEvent(BaseModel):
    """Claude Code pre-tool hook payload.

    Unknown fields are ignored because this is a foreign harness payload whose
    shape can grow independently of AgentKit. Rejecting such additions would
    block every matching tool call before governance runs.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

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
    def _validate_tool_input(cls, value: object) -> dict[str, object]:
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


__all__ = ["ClaudeCodeHookEvent", "ClaudeCodePostToolEvent"]
