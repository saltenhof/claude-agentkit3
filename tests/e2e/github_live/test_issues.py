"""E2E tests for GitHub issue operations against real testbed.

Testbed: saltenhof/agentkit3-testbed
Pre-existing issues: #1 (implementation), #2 (bugfix), #3 (concept).
"""

from __future__ import annotations

import contextlib

import pytest

from agentkit.exceptions import IntegrationError
from agentkit.integrations.github.issues import (
    add_comment,
    add_labels,
    close_issue,
    create_issue,
    get_issue,
    remove_labels,
    reopen_issue,
)

OWNER = "saltenhof"
REPO = "agentkit3-testbed"


@pytest.mark.e2e
@pytest.mark.requires_gh
class TestIssueRead:
    """Tests that only read existing issues (non-destructive)."""

    def test_get_existing_issue(self) -> None:
        """Read issue #1 from testbed."""
        issue = get_issue(OWNER, REPO, 1)
        assert issue.number == 1
        assert "TEST-001" in issue.title
        assert issue.state == "OPEN"

    def test_get_issue_has_body(self) -> None:
        """Issue #1 has a non-empty body."""
        issue = get_issue(OWNER, REPO, 1)
        assert issue.body  # non-empty

    def test_get_issue_has_url(self) -> None:
        """Issue #1 has a valid GitHub URL."""
        issue = get_issue(OWNER, REPO, 1)
        assert issue.url.startswith("https://github.com/")
        assert "/issues/1" in issue.url

    def test_get_nonexistent_issue_raises(self) -> None:
        """Reading a non-existent issue raises IntegrationError."""
        with pytest.raises(IntegrationError):
            get_issue(OWNER, REPO, 99999)


@pytest.mark.e2e
@pytest.mark.requires_gh
class TestIssueLifecycle:
    """Tests that create/modify issues (clean up after themselves)."""

    def test_create_and_close_issue(self) -> None:
        """Create a test issue, verify it, then close it."""
        issue = create_issue(
            OWNER, REPO,
            title="E2E-AUTO: ephemeral test issue",
            body="Created by automated test. Will be closed immediately.",
        )
        try:
            assert issue.number > 0
            assert issue.state == "OPEN"
            assert "E2E-AUTO" in issue.title

            # Close it
            close_issue(OWNER, REPO, issue.number)

            # Verify closed
            closed = get_issue(OWNER, REPO, issue.number)
            assert closed.state == "CLOSED"
        except Exception:
            # Best-effort cleanup: close the issue even if assertions fail
            with contextlib.suppress(IntegrationError):
                close_issue(OWNER, REPO, issue.number)
            raise

    def test_close_and_reopen(self) -> None:
        """Create, close, reopen, then close again for cleanup."""
        issue = create_issue(
            OWNER, REPO,
            title="E2E-AUTO: reopen test",
            body="Tests the reopen_issue function.",
        )
        try:
            close_issue(OWNER, REPO, issue.number)
            closed = get_issue(OWNER, REPO, issue.number)
            assert closed.state == "CLOSED"

            reopen_issue(OWNER, REPO, issue.number)
            reopened = get_issue(OWNER, REPO, issue.number)
            assert reopened.state == "OPEN"
        finally:
            # Cleanup: always close at the end
            with contextlib.suppress(IntegrationError):
                close_issue(OWNER, REPO, issue.number)

    def test_add_and_remove_labels(self) -> None:
        """Add labels to issue #1, then remove them."""
        add_labels(OWNER, REPO, 1, ["e2e-test-label"])
        try:
            issue = get_issue(OWNER, REPO, 1)
            assert "e2e-test-label" in issue.labels
        finally:
            # Cleanup: always remove the label
            with contextlib.suppress(IntegrationError):
                remove_labels(OWNER, REPO, 1, ["e2e-test-label"])

        issue = get_issue(OWNER, REPO, 1)
        assert "e2e-test-label" not in issue.labels

    def test_add_comment(self) -> None:
        """Add a comment to issue #1."""
        # No assertion needed beyond no exception
        add_comment(
            OWNER, REPO, 1,
            "Automated E2E test comment -- please ignore.",
        )
