"""Low-level gh CLI wrapper for GitHub operations.

All GitHub communication goes through the ``gh`` CLI tool
(subprocess), never through direct HTTP calls. This module
provides the thin wrapper that every higher-level module
(issues, projects) builds on.

Token routing
-------------
When an ``owner`` is provided to :func:`run_gh`, the wrapper
resolves a per-owner ``GH_TOKEN`` from the git credential files
on disk (``~/.git-credentials-{owner}``).  The token is injected
into the subprocess environment only -- **no** global
``os.environ`` mutation, **no** ``gh auth switch``.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from agentkit.exceptions import IntegrationError

# Pre-compiled pattern: https://{user}:{token}@github.com
_CREDENTIAL_RE = re.compile(
    r"^https://(?P<user>[^:]+):(?P<token>[^@]+)@github\.com",
)


def _resolve_token_from_keyring(owner: str) -> str | None:
    """Try to get a token from the gh CLI keyring for *owner*.

    Runs ``gh auth token --user {owner}`` which returns the OAuth
    token stored in the system keyring (if the user is logged in).
    This token typically has full scopes including ``project``.

    Args:
        owner: The GitHub user or organisation login.

    Returns:
        The keyring token string, or ``None`` on any failure.
    """
    try:
        result = subprocess.run(
            ["gh", "auth", "token", "--user", owner],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def _resolve_token_from_credentials_file(owner: str) -> str | None:
    """Resolve a token from ``~/.git-credentials-{owner}``.

    Parses the git credential store file for the given owner and
    extracts the token from the first matching
    ``https://{owner}:{token}@github.com`` line.

    Args:
        owner: The GitHub user or organisation whose token to look up.

    Returns:
        The personal access token string, or ``None``.
    """
    creds_path = Path.home() / f".git-credentials-{owner}"
    if not creds_path.is_file():
        return None

    text = creds_path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        stripped = line.strip()
        match = _CREDENTIAL_RE.match(stripped)
        if match and match.group("user") == owner:
            return match.group("token")

    return None


def resolve_token_for_owner(owner: str) -> str | None:
    """Resolve a ``GH_TOKEN`` for a specific repository owner.

    Resolution order (first match wins):

    1. **gh keyring** -- ``gh auth token --user {owner}``.  Returns
       the OAuth token from the system keyring which has full scopes
       (including ``project``).
    2. **Credential file** -- ``~/.git-credentials-{owner}``.  Falls
       back to the classic PAT stored in the git credential store.

    Returns ``None`` when neither source has credentials for *owner*.
    In that case ``gh`` uses its default (active account) auth.

    Args:
        owner: The GitHub user or organisation whose token to look up.

    Returns:
        The token string, or ``None``.
    """
    # Prefer keyring token (has full scopes, including project)
    token = _resolve_token_from_keyring(owner)
    if token is not None:
        return token

    # Fall back to credential file (classic PAT, may lack scopes)
    return _resolve_token_from_credentials_file(owner)


def _build_env(owner: str | None) -> dict[str, str] | None:
    """Build a subprocess environment dict with ``GH_TOKEN`` if needed.

    Args:
        owner: Optional repository owner for token resolution.

    Returns:
        A new environment dict with ``GH_TOKEN`` set, or ``None``
        to inherit the current environment unchanged.
    """
    if owner is None:
        return None
    token = resolve_token_for_owner(owner)
    if token is None:
        return None
    return {**os.environ, "GH_TOKEN": token}


def run_gh(*args: str, check: bool = True, owner: str | None = None) -> str:
    """Run a gh CLI command and return stdout.

    Args:
        *args: Arguments passed to the ``gh`` command.
        check: If ``True`` (default), raise on non-zero exit code.
        owner: Optional repository owner.  When provided and a
            matching token is found on disk, ``GH_TOKEN`` is set
            in the subprocess environment (not globally).

    Returns:
        The captured stdout of the command.

    Raises:
        IntegrationError: If ``gh`` is not found, the command times out,
            or it exits with a non-zero code (when *check* is ``True``).
    """
    env = _build_env(owner)
    try:
        result = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
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


def run_gh_json(
    *args: str, owner: str | None = None,
) -> dict[str, Any] | list[Any]:
    """Run a gh CLI command and parse JSON output.

    Args:
        *args: Arguments passed to the ``gh`` command.
        owner: Optional repository owner for token routing.

    Returns:
        The parsed JSON output (dict or list).

    Raises:
        IntegrationError: On command failure or invalid JSON.
    """
    output = run_gh(*args, owner=owner)
    try:
        result: dict[str, Any] | list[Any] = json.loads(output)
        return result
    except json.JSONDecodeError as e:
        raise IntegrationError(f"Failed to parse gh JSON output: {e}") from e


def run_gh_graphql(
    query: str, *, owner: str | None = None, **variables: str,
) -> dict[str, Any]:
    """Run a GraphQL query via ``gh api graphql``.

    Args:
        query: The GraphQL query string.
        owner: Optional repository owner for token routing.
        **variables: Named GraphQL variables passed via ``-f``.

    Returns:
        The parsed JSON response (the full response including ``data``).

    Raises:
        IntegrationError: On command failure, invalid JSON, or GraphQL errors.
    """
    cmd: list[str] = ["api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        cmd.extend(["-f", f"{key}={value}"])
    result = run_gh_json(*cmd, owner=owner)
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
