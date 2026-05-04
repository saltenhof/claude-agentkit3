"""Map harness-neutral guard decisions to Codex hook responses."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from agentkit.governance.protocols import GuardVerdict


class CodexHookOutput(BaseModel):
    """Codex hook response emitted by the AK3 adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: Literal["allow", "block"]
    guard: str
    message: str | None = None
    detail: dict[str, object] | None = None


def to_codex_output(verdict: GuardVerdict) -> CodexHookOutput:
    """Map a guard verdict to the Codex hook JSON payload."""
    if verdict.allowed:
        return CodexHookOutput(decision="allow", guard=verdict.guard_name)
    return CodexHookOutput(
        decision="block",
        guard=verdict.guard_name,
        message=verdict.message,
        detail=verdict.detail,
    )


def codex_exit_code(output: CodexHookOutput) -> int:
    """Return the Codex hook process exit code for one output payload."""
    return 0 if output.decision == "allow" else 2


__all__ = [
    "CodexHookOutput",
    "codex_exit_code",
    "to_codex_output",
]
