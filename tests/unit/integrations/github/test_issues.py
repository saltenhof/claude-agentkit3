"""Unit tests for GitHub issue operations."""

from __future__ import annotations

import pytest

from agentkit.exceptions import IntegrationError
from agentkit.integrations.github.issues import (
    IssueData,
    _parse_issue,
    add_comment,
    add_labels,
    close_issue,
    create_issue,
    get_issue,
    remove_labels,
    reopen_issue,
)


def test_parse_issue_handles_optional_fields() -> None:
    issue = _parse_issue(
        {
            "number": 42,
            "title": "Bug",
            "state": "OPEN",
            "labels": [{"name": "bug"}, {"name": "urgent"}],
            "url": "https://example.test/issues/42",
        },
    )

    assert issue == IssueData(
        number=42,
        title="Bug",
        state="OPEN",
        body="",
        labels=("bug", "urgent"),
        url="https://example.test/issues/42",
    )


def test_get_issue_returns_parsed_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "agentkit.integrations.github.issues.run_gh_json",
        lambda *args, **kwargs: {
            "number": 7,
            "title": "Fix pipeline",
            "state": "OPEN",
            "body": "Details",
            "labels": [{"name": "enhancement"}],
            "url": "https://example.test/issues/7",
        },
    )

    issue = get_issue("acme", "repo", 7)

    assert issue.title == "Fix pipeline"
    assert issue.labels == ("enhancement",)


def test_get_issue_rejects_unexpected_response_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "agentkit.integrations.github.issues.run_gh_json",
        lambda *args, **kwargs: ["not", "a", "dict"],
    )

    with pytest.raises(IntegrationError, match="Unexpected response type"):
        get_issue("acme", "repo", 7)


def test_create_issue_without_labels_fetches_created_issue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[tuple[str, ...], dict[str, object]]] = []
    expected = IssueData(
        number=18,
        title="New issue",
        state="OPEN",
        body="Created",
        labels=(),
        url="https://example.test/issues/18",
    )

    def fake_run_gh(*args: str, **kwargs: object) -> str:
        seen.append((args, kwargs))
        return "https://example.test/issues/18\n"

    monkeypatch.setattr("agentkit.integrations.github.issues.run_gh", fake_run_gh)
    monkeypatch.setattr(
        "agentkit.integrations.github.issues.get_issue",
        lambda owner, repo, issue_nr: expected,
    )

    issue = create_issue("acme", "repo", title="New issue", body="Created")

    assert issue == expected
    assert "--label" not in seen[0][0]


def test_create_issue_with_labels_passes_label_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[str, ...]] = []
    expected = IssueData(
        number=19,
        title="Labelled issue",
        state="OPEN",
        body="Created",
        labels=("bug", "p1"),
        url="https://example.test/issues/19",
    )

    def fake_run_gh(*args: str, **kwargs: object) -> str:
        seen.append(args)
        return "https://example.test/issues/19\n"

    monkeypatch.setattr("agentkit.integrations.github.issues.run_gh", fake_run_gh)
    monkeypatch.setattr(
        "agentkit.integrations.github.issues.get_issue",
        lambda owner, repo, issue_nr: expected,
    )

    issue = create_issue(
        "acme",
        "repo",
        title="Labelled issue",
        body="Created",
        labels=["bug", "p1"],
    )

    assert issue == expected
    assert "--label" in seen[0]
    assert "bug,p1" in seen[0]


@pytest.mark.parametrize(
    ("operation", "expected_args"),
    [
        (
            lambda: close_issue("acme", "repo", 1),
            ("issue", "close", "1", "--repo", "acme/repo"),
        ),
        (
            lambda: reopen_issue("acme", "repo", 1),
            ("issue", "reopen", "1", "--repo", "acme/repo"),
        ),
        (
            lambda: add_labels("acme", "repo", 1, ["bug", "p1"]),
            ("issue", "edit", "1", "--repo", "acme/repo", "--add-label", "bug,p1"),
        ),
        (
            lambda: remove_labels("acme", "repo", 1, ["bug", "p1"]),
            ("issue", "edit", "1", "--repo", "acme/repo", "--remove-label", "bug,p1"),
        ),
        (
            lambda: add_comment("acme", "repo", 1, "Looks good"),
            ("issue", "comment", "1", "--repo", "acme/repo", "--body", "Looks good"),
        ),
    ],
)
def test_issue_operations_delegate_to_gh(
    monkeypatch: pytest.MonkeyPatch,
    operation,
    expected_args: tuple[str, ...],
) -> None:
    seen: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def fake_run_gh(*args: str, **kwargs: object) -> str:
        seen.append((args, kwargs))
        return ""

    monkeypatch.setattr("agentkit.integrations.github.issues.run_gh", fake_run_gh)

    operation()

    assert seen == [(expected_args, {"owner": "acme"})]
