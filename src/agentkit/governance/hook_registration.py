"""Hook-registration data models for the governance BC.

Defines ``HookEventName``, ``HookId``, ``HookHarness``, ``HookDefinition``,
and ``RegistrationResult`` as the canonical typed surface for
``Governance.register_hooks``.

Sources:
- FK-30 §30.3.1 — ``Governance.register_hooks`` top-surface and
  ``HookDefinition`` fields (hook_event_name, matcher, command)
- FK-30 §30.5.1 — canonical guard-hook identifiers (11 values)

AG3-031 Pass-2 FK-30-Korrektur 2026-05-24
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from agentkit.governance.errors import HookRegistrationError


class HookEventName(StrEnum):
    """Hook event timing as defined by FK-30 §30.3.1.

    These are the harness-level hook trigger points.  The string values
    match the Claude Code ``hook_event_name`` field (§30.2.3) and are used
    as the top-level key in the harness settings file.
    """

    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"


class HookId(StrEnum):
    """Canonical guard-hook identifiers from FK-30 §30.5.1.

    11 values: 10 guard-hooks from the §30.5.1 table plus
    ``ccag_gatekeeper`` (FK-30 §30.3.1 JSON example).

    String values are FK-30 §30.5.1 wortgleich — no invented ``_guard``
    suffixes.
    """

    BRANCH_GUARD = "branch_guard"
    ORCHESTRATOR_GUARD = "orchestrator_guard"
    INTEGRITY = "integrity"
    QA_AGENT_GUARD = "qa_agent_guard"
    ADVERSARIAL_GUARD = "adversarial_guard"
    SELF_PROTECTION = "self_protection"
    STORY_CREATION_GUARD = "story_creation_guard"
    BUDGET = "budget"
    SKILL_USAGE_CHECK = "skill_usage_check"
    HEALTH_MONITOR = "health_monitor"
    CCAG_GATEKEEPER = "ccag_gatekeeper"


class HookHarness(StrEnum):
    """Agent harness target for a hook registration (FK-30 §30.11).

    Retained for test-setup and AC-checking purposes; not part of
    ``HookDefinition`` (FK-30 §30.3.1 fields are harness-neutral).
    """

    CLAUDE_CODE = "CLAUDE_CODE"
    CODEX = "CODEX"


class HookDefinition(BaseModel):
    """Typed representation of a single harness hook entry.

    Immutable (frozen) to enforce value-object semantics.  Fields are
    FK-30 §30.3.1 wortgleich:

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


class RegistrationResult(BaseModel):
    """Result of a ``register_hooks`` call.

    Attributes:
        registered: Matcher strings for hooks that were written to the backend.
        skipped: Matcher strings for hooks already registered and unchanged.
        errors: Non-fatal registration errors (fatal errors are raised).
    """

    registered: list[str] = []
    skipped: list[str] = []
    errors: list[HookRegistrationError] = []

    model_config = ConfigDict(arbitrary_types_allowed=True)


__all__ = [
    "HookDefinition",
    "HookEventName",
    "HookHarness",
    "HookId",
    "RegistrationResult",
]
