"""Generic MCP stdio conformance check for installer registration (AG3-164).

Package layout:

* :mod:`.types` — public result/command types and constants
* :mod:`.protocol` — JSON-RPC / MCP payload validation (Blutgruppe A)
* :mod:`.transport` — bounded stdio pumps (Blutgruppe T)
* :mod:`.process` — process tree lifecycle / minimal env (Blutgruppe T)
* :mod:`.check` — public check facade wiring the layers

Success requires process start, MCP initialize, and a non-empty well-formed
tools list. Registration consumers must call the check only on the mutative
REGISTER path.

Timeout: a teardown reserve is held out of the total budget for pump joins and
tree kill. The synchronous OS ``Popen`` call itself is not interruptible on
all platforms; that launch window is outside the controlled budget.
"""

from __future__ import annotations

from agentkit.backend.installer.mcp_conformance.check import (
    check_mcp_conformance,
    server_command_from_mcp_entry,
)
from agentkit.backend.installer.mcp_conformance.types import (
    DEFAULT_TIMEOUT_SECONDS,
    SUPPORTED_PROTOCOL_VERSIONS,
    McpConformanceReason,
    McpConformanceResult,
    McpServerCommand,
)

__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "SUPPORTED_PROTOCOL_VERSIONS",
    "McpConformanceReason",
    "McpConformanceResult",
    "McpServerCommand",
    "check_mcp_conformance",
    "server_command_from_mcp_entry",
]
