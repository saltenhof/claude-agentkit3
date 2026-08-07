"""Core-side hook-registration data models for the governance BC.

Defines ``HookId``, ``HookHarness`` and ``RegistrationResult``.

``HookDefinition`` and ``HookEventName`` are NOT here: both machines need them,
so they live in ``agentkit_wire.governance_registration`` (AG3-239, per
``architecture-conformance.symbol_boundary.governance_hook_registration``). The
three symbols below are the core remainder that entry names -- ``HookId`` is
local dispatch vocabulary rather than a contract field, and
``RegistrationResult`` cannot migrate because its hull reaches behaviour
(``governance.errors.HookRegistrationError``).

Sources:
- FK-30 §30.5.1 — canonical guard-hook identifiers (11 values)

AG3-031 Pass-2 FK-30-Korrektur 2026-05-24; symbol cut AG3-239.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from agentkit.backend.governance.errors import HookRegistrationError


class HookId(StrEnum):
    """Canonical guard-hook identifiers from FK-30 §30.5.1.

    11 values: 10 guard-hooks from the §30.5.1 table plus
    ``ccag_gatekeeper`` (FK-30 §30.3.1 JSON example).

    String values are FK-30 §30.5.1 literal concept values — no invented ``_guard``
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
    #: AG3-086 (FK-31 §31.7): the prompt-integrity guard — a NEW PreToolUse hook
    #: on every ``Agent`` sub-agent spawn (escape detection, spawn-schema
    #: validation, template integrity). Not in the FK-30 §30.5.1 table; it is the
    #: FK-31 §31.7 spawn guard, registered as its own identifier.
    PROMPT_INTEGRITY = "prompt_integrity"


class HookHarness(StrEnum):
    """Agent harness target for a hook registration (FK-30 §30.11).

    Retained for test-setup and AC-checking purposes; not part of
    ``HookDefinition`` (FK-30 §30.3.1 fields are harness-neutral).
    """

    CLAUDE_CODE = "CLAUDE_CODE"
    CODEX = "CODEX"


class RegistrationResult(BaseModel):
    """Result of a ``register_hooks`` call.

    Attributes:
        registered: Matcher strings for hooks that were written (or overwritten)
            in the backend.  Includes new entries and entries whose ``command``
            changed (UPSERT — Fix E3, AG3-031 Pass-3).
        skipped: Matcher strings for hooks already registered with an identical
            ``command`` value.  Only truly identical rows are skipped.
        errors: Non-fatal registration errors (fatal errors are raised).
    """

    registered: list[str] = []
    skipped: list[str] = []
    errors: list[HookRegistrationError] = []

    model_config = ConfigDict(arbitrary_types_allowed=True)


__all__ = [
    "HookHarness",
    "HookId",
    "RegistrationResult",
]
