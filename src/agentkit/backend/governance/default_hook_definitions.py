"""Default governance hook definitions for project installation.

This module is the production source for the hook definitions that the
installer hands to ``Governance.register_hooks``.  The settings writers remain
generic materializers; this source owns the project-default wiring.

AG3-086: the AG3-086 guard-hooks are PERMANENTLY-ACTIVE governance hooks
(FK-31 §31.7 / FK-30 §30.5.1a / FK-43 §43.6.2). The runner DISPATCHES them, but
a guard only becomes active in a real install when it is BOUND here — the
production default hook-registration path the installer runs
(``installer.runner`` -> ``Governance.register_hooks``). Without binding, the
dispatch helpers are dead code in a real install. This source therefore wires:

- a PreToolUse ``budget`` guard (``WebCallBudgetGuard``) on the web-call surface
  (``WebFetch|WebSearch``) — the single blocking budget owner (FK-30 §30.5.1a);
- a PostToolUse ``budget`` observational emitter on the same surface (the
  ``web_call`` counter, FK-30 §30.5.2 — never blocks);
- a PreToolUse ``skill_usage_check`` guard on ``Bash`` (ad-hoc methodology
  detection, FK-43 §43.6.2 / F-43-030);
- a PreToolUse ``prompt_integrity`` guard on every ``Agent`` sub-agent spawn
  (FK-31 §31.7 — permanently active, mode-specific).

ARCH-55: hook identifiers and matcher tokens are English.
"""

from __future__ import annotations

from agentkit.backend.governance.hook_registration import (
    HookDefinition,
    HookEventName,
    HookId,
)

#: Matcher for the web-call surface the budget guard / emitter intercept
#: (FK-30 §30.5.1a / FK-68 §68.6.1 — ``WebFetch`` / ``WebSearch``).
_WEB_CALL_MATCHER = "WebFetch|WebSearch"

#: Matcher for the ``Agent`` sub-agent spawn the prompt-integrity guard guards
#: (FK-31 §31.7 — every ``Agent`` tool call).
_AGENT_SPAWN_MATCHER = "Agent"

#: Matcher for the ad-hoc ``Bash`` tool calls the skill-usage check inspects
#: (FK-43 §43.6.2 / F-43-030 — the recognised ad-hoc signals are ``Bash``-shaped).
_BASH_MATCHER = "Bash"


def build_default_hook_definitions() -> list[HookDefinition]:
    """Return the default hook registrations installed for a project.

    Includes the FK-30 §30.10 worker-health monitor (AG3-080 owner) AND the
    AG3-086 permanently-active guard-hooks (FK-31 §31.7 / FK-30 §30.5.1a /
    FK-43 §43.6.2). Binding the AG3-086 guards HERE is what makes a default
    install actually enforce them — the runner dispatch alone is inert until the
    hook is registered in the harness settings (AC1b / AC3 "permanently active").
    """

    return [
        HookDefinition(
            hook_event_name=HookEventName.POST_TOOL_USE,
            matcher="Bash",
            command=f"agentkit-hook-claude post {HookId.HEALTH_MONITOR.value}",
        ),
        HookDefinition(
            hook_event_name=HookEventName.POST_TOOL_USE_FAILURE,
            matcher="Bash",
            command=f"agentkit-hook-claude post {HookId.HEALTH_MONITOR.value}",
        ),
        # AG3-086 / FK-30 §30.5.1a: the single blocking web-call budget owner
        # (PreToolUse ``WebCallBudgetGuard``).
        HookDefinition(
            hook_event_name=HookEventName.PRE_TOOL_USE,
            matcher=_WEB_CALL_MATCHER,
            command=f"agentkit-hook-claude pre {HookId.BUDGET.value}",
        ),
        # AG3-086 / FK-30 §30.5.2: the observational ``web_call`` counter emitter
        # (PostToolUse ``budget`` — never blocks).
        HookDefinition(
            hook_event_name=HookEventName.POST_TOOL_USE,
            matcher=_WEB_CALL_MATCHER,
            command=f"agentkit-hook-claude post {HookId.BUDGET.value}",
        ),
        # AG3-086 / FK-43 §43.6.2: the ad-hoc methodology guard (PreToolUse).
        HookDefinition(
            hook_event_name=HookEventName.PRE_TOOL_USE,
            matcher=_BASH_MATCHER,
            command=f"agentkit-hook-claude pre {HookId.SKILL_USAGE_CHECK.value}",
        ),
        # AG3-086 / FK-31 §31.7: the permanently-active prompt-integrity guard on
        # every ``Agent`` sub-agent spawn (PreToolUse).
        HookDefinition(
            hook_event_name=HookEventName.PRE_TOOL_USE,
            matcher=_AGENT_SPAWN_MATCHER,
            command=f"agentkit-hook-claude pre {HookId.PROMPT_INTEGRITY.value}",
        ),
    ]


__all__ = ["build_default_hook_definitions"]
