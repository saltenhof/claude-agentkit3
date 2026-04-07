"""GitHub Issue operations via gh CLI.

Provides CRUD operations for GitHub issues: fetch, create, close,
reopen, label management, and commenting. All operations go through
the ``gh`` CLI subprocess wrapper in :mod:`.client`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agentkit.integrations.github.client import run_gh, run_gh_json


@dataclass(frozen=True)
class IssueData:
    """Data from a GitHub issue.

    Attributes:
        number: The issue number.
        title: The issue title.
        state: Issue state (``"OPEN"`` or ``"CLOSED"``).
        body: The issue body text.
        labels: Tuple of label names attached to the issue.
        url: The full URL of the issue on GitHub.
    """

    number: int
    title: str
    state: str
    body: str
    labels: tuple[str, ...]
    url: str


def _parse_issue(raw: dict[str, Any]) -> IssueData:
    """Parse a raw gh JSON response into an IssueData.

    Args:
        raw: The JSON dict from ``gh issue view --json ...``.

    Returns:
        A populated ``IssueData`` instance.
    """
    label_objects: list[dict[str, Any]] = raw.get("labels", [])
    label_names = tuple(lb["name"] for lb in label_objects)
    return IssueData(
        number=raw["number"],
        title=raw["title"],
        state=raw["state"],
        body=raw.get("body", "") or "",
        labels=label_names,
        url=raw["url"],
    )


def get_issue(owner: str, repo: str, issue_nr: int) -> IssueData:
    """Fetch an issue by number.

    Args:
        owner: Repository owner (user or org).
        repo: Repository name.
        issue_nr: The issue number.

    Returns:
        The issue data.

    Raises:
        IntegrationError: If the issue does not exist or the command fails.
    """
    result = run_gh_json(
        "issue", "view", str(issue_nr),
        "--repo", f"{owner}/{repo}",
        "--json", "number,title,state,body,labels,url",
    )
    if not isinstance(result, dict):
        from agentkit.exceptions import IntegrationError

        raise IntegrationError(
            f"Unexpected response type for issue #{issue_nr}",
            detail={"response": result},
        )
    return _parse_issue(result)


def create_issue(
    owner: str,
    repo: str,
    *,
    title: str,
    body: str,
    labels: list[str] | None = None,
) -> IssueData:
    """Create a new issue.

    Args:
        owner: Repository owner (user or org).
        repo: Repository name.
        title: Issue title.
        body: Issue body text.
        labels: Optional list of label names to attach.

    Returns:
        The newly created issue data.

    Raises:
        IntegrationError: If issue creation fails.
    """
    cmd: list[str] = [
        "issue", "create",
        "--repo", f"{owner}/{repo}",
        "--title", title,
        "--body", body,
    ]
    if labels:
        cmd.extend(["--label", ",".join(labels)])

    # gh issue create returns the URL of the new issue on stdout
    url_output = run_gh(*cmd).strip()

    # Extract issue number from the URL (last path segment)
    issue_nr = int(url_output.rstrip("/").split("/")[-1])

    # Fetch the full issue data
    return get_issue(owner, repo, issue_nr)


def close_issue(owner: str, repo: str, issue_nr: int) -> None:
    """Close an issue.

    Args:
        owner: Repository owner (user or org).
        repo: Repository name.
        issue_nr: The issue number to close.

    Raises:
        IntegrationError: If the close operation fails.
    """
    run_gh(
        "issue", "close", str(issue_nr),
        "--repo", f"{owner}/{repo}",
    )


def reopen_issue(owner: str, repo: str, issue_nr: int) -> None:
    """Reopen a closed issue.

    Args:
        owner: Repository owner (user or org).
        repo: Repository name.
        issue_nr: The issue number to reopen.

    Raises:
        IntegrationError: If the reopen operation fails.
    """
    run_gh(
        "issue", "reopen", str(issue_nr),
        "--repo", f"{owner}/{repo}",
    )


def add_labels(owner: str, repo: str, issue_nr: int, labels: list[str]) -> None:
    """Add labels to an issue.

    Args:
        owner: Repository owner (user or org).
        repo: Repository name.
        issue_nr: The issue number.
        labels: List of label names to add.

    Raises:
        IntegrationError: If the label operation fails.
    """
    run_gh(
        "issue", "edit", str(issue_nr),
        "--repo", f"{owner}/{repo}",
        "--add-label", ",".join(labels),
    )


def remove_labels(
    owner: str, repo: str, issue_nr: int, labels: list[str]
) -> None:
    """Remove labels from an issue.

    Args:
        owner: Repository owner (user or org).
        repo: Repository name.
        issue_nr: The issue number.
        labels: List of label names to remove.

    Raises:
        IntegrationError: If the label operation fails.
    """
    run_gh(
        "issue", "edit", str(issue_nr),
        "--repo", f"{owner}/{repo}",
        "--remove-label", ",".join(labels),
    )


def add_comment(owner: str, repo: str, issue_nr: int, body: str) -> None:
    """Add a comment to an issue.

    Args:
        owner: Repository owner (user or org).
        repo: Repository name.
        issue_nr: The issue number.
        body: The comment body text.

    Raises:
        IntegrationError: If the comment operation fails.
    """
    run_gh(
        "issue", "comment", str(issue_nr),
        "--repo", f"{owner}/{repo}",
        "--body", body,
    )
