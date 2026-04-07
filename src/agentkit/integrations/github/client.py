"""Low-level gh CLI wrapper for GitHub operations.

All GitHub communication goes through the ``gh`` CLI tool
(subprocess), never through direct HTTP calls. This module
provides the thin wrapper that every higher-level module
(issues, projects) builds on.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

from agentkit.exceptions import IntegrationError


def run_gh(*args: str, check: bool = True) -> str:
    """Run a gh CLI command and return stdout.

    Args:
        *args: Arguments passed to the ``gh`` command.
        check: If ``True`` (default), raise on non-zero exit code.

    Returns:
        The captured stdout of the command.

    Raises:
        IntegrationError: If ``gh`` is not found, the command times out,
            or it exits with a non-zero code (when *check* is ``True``).
    """
    try:
        result = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if check and result.returncode != 0:
            raise IntegrationError(
                f"gh command failed: gh {' '.join(args)}",
                detail={"stderr": result.stderr, "returncode": result.returncode},
            )
        return result.stdout
    except FileNotFoundError as exc:
        raise IntegrationError(
            "gh CLI not found. Install: https://cli.github.com/"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise IntegrationError(
            f"gh command timed out: gh {' '.join(args)}"
        ) from exc


def run_gh_json(*args: str) -> dict[str, Any] | list[Any]:
    """Run a gh CLI command and parse JSON output.

    Args:
        *args: Arguments passed to the ``gh`` command.

    Returns:
        The parsed JSON output (dict or list).

    Raises:
        IntegrationError: On command failure or invalid JSON.
    """
    output = run_gh(*args)
    try:
        result: dict[str, Any] | list[Any] = json.loads(output)
        return result
    except json.JSONDecodeError as e:
        raise IntegrationError(f"Failed to parse gh JSON output: {e}") from e


def run_gh_graphql(query: str, **variables: str) -> dict[str, Any]:
    """Run a GraphQL query via ``gh api graphql``.

    Args:
        query: The GraphQL query string.
        **variables: Named GraphQL variables passed via ``-f``.

    Returns:
        The parsed JSON response (the full response including ``data``).

    Raises:
        IntegrationError: On command failure, invalid JSON, or GraphQL errors.
    """
    cmd: list[str] = ["api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        cmd.extend(["-f", f"{key}={value}"])
    result = run_gh_json(*cmd)
    if not isinstance(result, dict):
        raise IntegrationError(
            "GraphQL response is not a JSON object",
            detail={"response": result},
        )
    if "errors" in result:
        raise IntegrationError(
            "GraphQL query returned errors",
            detail={"errors": result["errors"]},
        )
    return result
