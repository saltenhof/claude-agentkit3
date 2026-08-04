"""Codex governance hook adapter.

Official CLI entry point for Codex hook integration:
``agentkit-hook-codex``.

The adapter is the Codex-specific mediation layer: it maps Codex tool
events from stdin to the harness-neutral ``HookEvent`` and maps
``GuardVerdict`` decisions back to a JSON hook response on stdout. The
guard evaluation core remains unaware of Codex tool names, payload
shapes, and exit-code mechanics.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentkit.harness_client.harness_adapters.codex.cli import main as main
    from agentkit.harness_client.harness_adapters.codex.decision_mapping import (
        CodexHookOutput as CodexHookOutput,
    )
    from agentkit.harness_client.harness_adapters.codex.decision_mapping import (
        codex_exit_code as codex_exit_code,
    )
    from agentkit.harness_client.harness_adapters.codex.decision_mapping import (
        to_codex_output as to_codex_output,
    )
    from agentkit.harness_client.harness_adapters.codex.event_mapping import (
        CodexHookEvent as CodexHookEvent,
    )
    from agentkit.harness_client.harness_adapters.codex.event_mapping import (
        CodexPostToolEvent as CodexPostToolEvent,
    )
    from agentkit.harness_client.harness_adapters.codex.event_mapping import (
        to_neutral_event as to_neutral_event,
    )

_EXPORT_MODULES = {
    "main": "agentkit.harness_client.harness_adapters.codex.cli",
    "CodexHookOutput": "agentkit.harness_client.harness_adapters.codex.decision_mapping",
    "codex_exit_code": "agentkit.harness_client.harness_adapters.codex.decision_mapping",
    "to_codex_output": "agentkit.harness_client.harness_adapters.codex.decision_mapping",
    "CodexHookEvent": "agentkit.harness_client.harness_adapters.codex.event_mapping",
    "CodexPostToolEvent": "agentkit.harness_client.harness_adapters.codex.event_mapping",
    "to_neutral_event": "agentkit.harness_client.harness_adapters.codex.event_mapping",
}

__all__ = [
    "CodexHookEvent",
    "CodexHookOutput",
    "CodexPostToolEvent",
    "codex_exit_code",
    "main",
    "to_codex_output",
    "to_neutral_event",
]


def __getattr__(name: str) -> object:
    """Load Codex adapter surfaces without preloading the hook runtime."""
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module_name), name)
    globals()[name] = value
    return value
