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

from agentkit.governance.harness_adapters.codex.cli import main
from agentkit.governance.harness_adapters.codex.decision_mapping import (
    CodexHookOutput,
    codex_exit_code,
    to_codex_output,
)
from agentkit.governance.harness_adapters.codex.event_mapping import (
    CodexHookEvent,
    CodexPostToolEvent,
    to_neutral_event,
)

__all__ = [
    "CodexHookEvent",
    "CodexHookOutput",
    "CodexPostToolEvent",
    "codex_exit_code",
    "main",
    "to_codex_output",
    "to_neutral_event",
]
