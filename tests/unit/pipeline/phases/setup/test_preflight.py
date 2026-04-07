"""Unit tests for setup phase preflight checks.

Uses monkeypatch on ``get_issue`` to avoid real GitHub CLI calls.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.exceptions import IntegrationError
from agentkit.integrations.github.issues import IssueData
from agentkit.pipeline.phases.setup.preflight import run_preflight

if TYPE_CHECKING:
    import pytest


def _make_issue(
    *,
    number: int = 1,
    title: str = "TEST-001: Sample issue",
    state: str = "OPEN",
    labels: tuple[str, ...] = ("implementation",),
    body: str = "Test body",
    url: str = "https://github.com/owner/repo/issues/1",
) -> IssueData:
    """Create an ``IssueData`` instance for testing."""
    return IssueData(
        number=number,
        title=title,
        state=state,
        body=body,
        labels=labels,
        url=url,
    )


class TestPreflightWithValidIssue:
    """Preflight with a valid, open issue passes all checks."""

    def test_all_checks_pass(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """All checks pass for a valid open issue with a type label."""
        monkeypatch.setattr(
            "agentkit.pipeline.phases.setup.preflight.get_issue",
            lambda owner, repo, nr: _make_issue(),
        )
        result = run_preflight("owner", "repo", 1)

        assert result.passed is True
        assert len(result.checks) == 3
        assert all(c.passed for c in result.checks)

    def test_issue_data_is_attached(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Successful preflight attaches the fetched IssueData."""
        issue = _make_issue()
        monkeypatch.setattr(
            "agentkit.pipeline.phases.setup.preflight.get_issue",
            lambda owner, repo, nr: issue,
        )
        result = run_preflight("owner", "repo", 1)
        assert result.issue_data is not None
        assert result.issue_data.number == 1


class TestPreflightIssueNotFound:
    """Preflight when the issue does not exist."""

    def test_issue_exists_check_fails(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The ``issue_exists`` check fails for a missing issue."""
        def _raise(*_args: object, **_kwargs: object) -> IssueData:
            raise IntegrationError("Not found")

        monkeypatch.setattr(
            "agentkit.pipeline.phases.setup.preflight.get_issue",
            _raise,
        )
        result = run_preflight("owner", "repo", 99999)

        assert result.passed is False
        check_names = {c.name for c in result.checks}
        assert "issue_exists" in check_names
        exists_check = next(c for c in result.checks if c.name == "issue_exists")
        assert exists_check.passed is False

    def test_all_checks_run_despite_missing_issue(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """All three checks run even when the issue cannot be fetched."""
        def _raise(*_args: object, **_kwargs: object) -> IssueData:
            raise IntegrationError("Not found")

        monkeypatch.setattr(
            "agentkit.pipeline.phases.setup.preflight.get_issue",
            _raise,
        )
        result = run_preflight("owner", "repo", 99999)

        assert len(result.checks) == 3


class TestPreflightClosedIssue:
    """Preflight when the issue is closed."""

    def test_issue_open_check_fails(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The ``issue_open`` check fails for a closed issue."""
        monkeypatch.setattr(
            "agentkit.pipeline.phases.setup.preflight.get_issue",
            lambda owner, repo, nr: _make_issue(state="CLOSED"),
        )
        result = run_preflight("owner", "repo", 1)

        assert result.passed is False
        open_check = next(c for c in result.checks if c.name == "issue_open")
        assert open_check.passed is False

    def test_other_checks_still_run(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """All checks run even when the issue is closed."""
        monkeypatch.setattr(
            "agentkit.pipeline.phases.setup.preflight.get_issue",
            lambda owner, repo, nr: _make_issue(state="CLOSED"),
        )
        result = run_preflight("owner", "repo", 1)

        assert len(result.checks) == 3
        # issue_exists should still pass
        exists_check = next(
            c for c in result.checks if c.name == "issue_exists"
        )
        assert exists_check.passed is True


class TestPreflightResultPassed:
    """PreflightResult.passed reflects aggregate of all checks."""

    def test_passed_false_when_any_check_fails(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``passed`` is False if at least one check fails."""
        monkeypatch.setattr(
            "agentkit.pipeline.phases.setup.preflight.get_issue",
            lambda owner, repo, nr: _make_issue(state="CLOSED"),
        )
        result = run_preflight("owner", "repo", 1)
        assert result.passed is False

    def test_passed_true_when_all_pass(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``passed`` is True when all checks pass."""
        monkeypatch.setattr(
            "agentkit.pipeline.phases.setup.preflight.get_issue",
            lambda owner, repo, nr: _make_issue(),
        )
        result = run_preflight("owner", "repo", 1)
        assert result.passed is True
