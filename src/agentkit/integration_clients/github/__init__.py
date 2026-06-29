"""GitHub integration adapter — thin wrapper around the ``gh`` CLI.

Public API
----------
Client layer:
    :func:`run_gh` — execute any ``gh`` command, return stdout.
    :func:`resolve_token_for_owner` — resolve the owner-scoped ``gh`` token.

GitHub is the code backend ONLY (FK-12 §12.1.1): branch / worktree / merge
mechanics via the ``gh`` / ``git`` client. GitHub Issues and Projects are
intentionally NOT exposed — story identity, status and attributes live in the
AK3 Story-Backend (FK-91 §91.2 rule 9), never on a GitHub issue or Project
board.
"""

from __future__ import annotations

from agentkit.integration_clients.github.client import resolve_token_for_owner, run_gh

__all__ = [
    "resolve_token_for_owner",
    "run_gh",
]
