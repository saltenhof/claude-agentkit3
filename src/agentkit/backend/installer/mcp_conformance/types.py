"""Public types and constants for MCP conformance (AG3-164)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from agentkit.backend.installer.checkpoint_engine.reasons import (
    REASON_MCP_COMMAND_NOT_FOUND,
    REASON_MCP_PROCESS_CONTROL_ERROR,
    REASON_MCP_PROCESS_EXITED,
    REASON_MCP_PROTOCOL_ERROR,
    REASON_MCP_TIMEOUT,
    REASON_MCP_TOOLS_LIST_EMPTY,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

#: Default wall-clock budget for the full probe (handshake + reserved teardown).
DEFAULT_TIMEOUT_SECONDS: Final = 30.0
#: Reserved wall-clock for teardown (pumps join + tree kill) after handshake.
TEARDOWN_RESERVE_SECONDS: Final = 3.0
#: Max stdout/stderr line size (bytes) before protocol_error.
MAX_FRAME_BYTES: Final = 256 * 1024
#: Max pending well-formed stdout messages before protocol_error.
MAX_PENDING_STDOUT_MESSAGES: Final = 64
#: Max stderr detail characters retained (tail of stream).
STDERR_DETAIL_CHARS: Final = 500

#: Client-advertised protocol version.
CLIENT_PROTOCOL_VERSION: Final = "2024-11-05"
#: Server protocolVersion values accepted by this probe.
SUPPORTED_PROTOCOL_VERSIONS: Final[frozenset[str]] = frozenset(
    {
        "2024-11-05",
        "2025-03-26",
        "2025-06-18",
        "2025-11-25",
    }
)
CLIENT_NAME: Final = "agentkit-mcp-conformance"
CLIENT_VERSION: Final = "1.0.0"

POSIX_BASE_ENV_KEYS: Final[tuple[str, ...]] = (
    "HOME",
    "LOGNAME",
    "PATH",
    "SHELL",
    "TERM",
    "USER",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TMPDIR",
)
WIN_BASE_ENV_KEYS: Final[tuple[str, ...]] = (
    "APPDATA",
    "HOMEDRIVE",
    "HOMEPATH",
    "LOCALAPPDATA",
    "PATH",
    "PATHEXT",
    "PROCESSOR_ARCHITECTURE",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "USERNAME",
    "USERPROFILE",
    "COMSPEC",
    "NUMBER_OF_PROCESSORS",
    "OS",
    "WINDIR",
)


class McpConformanceReason(StrEnum):
    """Stable machine-readable failure reasons (SSOT values from reasons.py)."""

    COMMAND_NOT_FOUND = REASON_MCP_COMMAND_NOT_FOUND
    PROCESS_EXITED = REASON_MCP_PROCESS_EXITED
    TIMEOUT = REASON_MCP_TIMEOUT
    PROTOCOL_ERROR = REASON_MCP_PROTOCOL_ERROR
    TOOLS_LIST_EMPTY = REASON_MCP_TOOLS_LIST_EMPTY
    PROCESS_CONTROL_ERROR = REASON_MCP_PROCESS_CONTROL_ERROR


@dataclass(frozen=True, slots=True)
class McpServerCommand:
    """Command-line specification of a candidate stdio MCP server."""

    command: str
    args: Sequence[str] = ()
    env: Mapping[str, str] | None = None
    cwd: str | Path | None = None


@dataclass(frozen=True, slots=True)
class McpConformanceResult:
    """Outcome of the MCP conformance probe."""

    ok: bool
    reason: McpConformanceReason | None
    detail: str
    tool_names: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProcessIdentity:
    """Stable process identity: PID alone is not enough under reuse."""

    pid: int
    create_time: float


class TransportError(Exception):
    """Mapped pipe/transport failure for the conformance boundary."""

    def __init__(self, reason: McpConformanceReason, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


__all__ = [
    "CLIENT_NAME",
    "CLIENT_PROTOCOL_VERSION",
    "CLIENT_VERSION",
    "DEFAULT_TIMEOUT_SECONDS",
    "MAX_FRAME_BYTES",
    "MAX_PENDING_STDOUT_MESSAGES",
    "POSIX_BASE_ENV_KEYS",
    "STDERR_DETAIL_CHARS",
    "SUPPORTED_PROTOCOL_VERSIONS",
    "TEARDOWN_RESERVE_SECONDS",
    "WIN_BASE_ENV_KEYS",
    "McpConformanceReason",
    "McpConformanceResult",
    "McpServerCommand",
    "ProcessIdentity",
    "TransportError",
]
