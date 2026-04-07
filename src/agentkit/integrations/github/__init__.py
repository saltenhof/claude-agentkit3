"""GitHub integration adapter — thin wrapper around the ``gh`` CLI.

Public API
----------
Client layer:
    :func:`run_gh` — execute any ``gh`` command, return stdout.

Issue operations:
    :class:`IssueData`, :func:`get_issue`, :func:`create_issue`,
    :func:`close_issue`, :func:`reopen_issue`, :func:`add_labels`,
    :func:`remove_labels`, :func:`add_comment`.

Project operations:
    :class:`ProjectItem`, :func:`list_project_items`,
    :func:`add_issue_to_project`.
"""

from __future__ import annotations

from agentkit.integrations.github.client import run_gh
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
from agentkit.integrations.github.projects import (
    ProjectItem,
    add_issue_to_project,
    list_project_items,
)

__all__ = [
    "IssueData",
    "ProjectItem",
    "add_comment",
    "add_issue_to_project",
    "add_labels",
    "close_issue",
    "create_issue",
    "get_issue",
    "list_project_items",
    "remove_labels",
    "reopen_issue",
    "run_gh",
]
