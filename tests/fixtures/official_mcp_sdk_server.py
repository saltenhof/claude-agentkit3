"""stdio MCP server built on the official MCP Python SDK (AG3-164 interop).

Requires the optional ``mcp`` package (available in the project venv / dev
environment). Used only by integration tests to prove the production probe
interoperates with an independent implementation.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

app = FastMCP("agentkit-official-sdk-fixture")


@app.tool()
def ping() -> str:
    """Minimal tool for conformance tools/list."""
    return "pong"


def main() -> None:
    """Run the FastMCP stdio transport."""
    app.run(transport="stdio")


if __name__ == "__main__":
    main()
