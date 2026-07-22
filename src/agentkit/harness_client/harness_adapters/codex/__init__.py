"""Codex governance hook adapter.

Official CLI entry point for Codex hook integration:
``agentkit-hook-codex``.

The adapter is the Codex-specific mediation layer: it maps Codex tool
events from stdin to the harness-neutral ``HookEvent`` and maps
``GuardVerdict`` decisions back to a JSON hook response on stdout. The
guard evaluation core remains unaware of Codex tool names, payload
shapes, and exit-code mechanics.

MCP project-local config writing (FK-76 §76.5.4) lives at
``agentkit.harness_client.harness_adapters.codex_mcp_config_writer`` — a
sibling of ``settings_writer``, not this internal hook-adapter package
(architecture-conformance marks ``HarnessAdaptersCodex`` as internal).
"""

from __future__ import annotations

from agentkit.harness_client.harness_adapters.codex.cli import main
from agentkit.harness_client.harness_adapters.codex.decision_mapping import (
    CodexHookOutput,
    codex_exit_code,
    to_codex_output,
)
from agentkit.harness_client.harness_adapters.codex.event_mapping import (
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
