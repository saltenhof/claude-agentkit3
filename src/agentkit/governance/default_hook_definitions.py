"""Default governance hook definitions for project installation.

This module is the production source for the hook definitions that the
installer hands to ``Governance.register_hooks``.  The settings writers remain
generic materializers; this source owns the project-default wiring.
"""

from __future__ import annotations

from agentkit.governance.hook_registration import (
    HookDefinition,
    HookEventName,
    HookId,
)


def build_default_hook_definitions() -> list[HookDefinition]:
    """Return the default hook registrations installed for a project."""

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
    ]


__all__ = ["build_default_hook_definitions"]
