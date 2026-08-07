"""Hook-registration vocabulary of the ``/v1`` boundary (FK-30 §30.3.1).

Both sides need these two symbols: the edge builds hook definitions and
materialises them into the harness settings files on the developer machine, the
core persists them as canonical state.

Membership follows
``architecture-conformance.symbol_boundary.governance_hook_registration``:
``HookDefinition`` and ``HookEventName`` migrate; ``HookId``, ``HookHarness``
and ``RegistrationResult`` are the CORE remainder and stay in
``agentkit.backend.governance.hook_registration``. ``RegistrationResult`` cannot
follow because its hull reaches behaviour --
``governance.errors.HookRegistrationError`` -- and ``HookId`` is local dispatch
vocabulary, not a contract field.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class HookEventName(StrEnum):
    """Hook event timing as defined by FK-30 §30.3.1.

    These are the harness-level hook trigger points. The string values match the
    Claude Code ``hook_event_name`` field (§30.2.3) and are used as the top-level
    key in the harness settings file.
    """

    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    POST_TOOL_USE_FAILURE = "PostToolUseFailure"


class HookDefinition(BaseModel):
    """Typed representation of a single harness hook entry.

    Immutable (frozen) to enforce value-object semantics. Fields are FK-30
    §30.3.1 literal concept values:

    Attributes:
        hook_event_name: Hook timing — ``"PreToolUse"`` or ``"PostToolUse"``.
        matcher: Harness tool-matcher pattern, e.g. ``"Bash"`` or
            ``"Write|Edit"``.
        command: Harness command string, e.g.
            ``"agentkit-hook-claude pre branch_guard"``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    hook_event_name: HookEventName
    matcher: str
    command: str


__all__ = [
    "HookDefinition",
    "HookEventName",
]
