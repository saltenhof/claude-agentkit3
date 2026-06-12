"""GitHub integration adapter — thin wrapper around the ``gh`` CLI.

Public API
----------
Client layer:
    :func:`run_gh` — execute any ``gh`` command, return stdout.

Issue operations:
    :class:`IssueData`, :func:`get_issue`, :func:`create_issue`,
    :func:`close_issue`, :func:`reopen_issue`, :func:`add_labels`,
    :func:`remove_labels`, :func:`add_comment`.

GitHub Projects / board operations are intentionally NOT exposed: GitHub is the
code backend only (FK-12 §12.1.1). Story identity, status and attributes live in
the AK3 Story-Backend (FK-91), never on a GitHub Project board.
"""

from __future__ import annotations

from agentkit.integrations.github.client import resolve_token_for_owner, run_gh
from agentkit.integrations.github.issues import (
    IssueData,
    add_comment,
    add_labels,
    close_issue,
    create_issue,
    get_issue,
    remove_labels,
    reopen_issue,
)

__all__ = [
    "IssueData",
    "add_comment",
    "add_labels",
    "close_issue",
    "create_issue",
    "get_issue",
    "remove_labels",
    "reopen_issue",
    "resolve_token_for_owner",
    "run_gh",
]
