"""Minimal stdio MCP server for installer conformance tests (AG3-164).

Speaks newline-delimited JSON-RPC 2.0 over stdin/stdout:
``initialize`` and ``tools/list`` (one tool named ``ping``). No third-party
MCP SDK dependency — production conformance uses the same framing.
"""

from __future__ import annotations

import json
import sys
from typing import Any


def _write(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _read() -> dict[str, Any] | None:
    line = sys.stdin.readline()
    if not line:
        return None
    loaded = json.loads(line)
    if not isinstance(loaded, dict):
        msg = "expected JSON object"
        raise TypeError(msg)
    return loaded


def main() -> int:
    """Run the minimal MCP stdio loop until stdin closes."""
    while True:
        message = _read()
        if message is None:
            return 0
        method = message.get("method")
        req_id = message.get("id")
        if method == "initialize":
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "minimal-mcp-test", "version": "0.0.1"},
                    },
                }
            )
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "tools": [
                            {
                                "name": "ping",
                                "description": "Minimal test tool",
                                "inputSchema": {"type": "object", "properties": {}},
                            }
                        ]
                    },
                }
            )
        elif req_id is not None:
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Method not found: {method!r}"},
                }
            )


if __name__ == "__main__":
    raise SystemExit(main())
