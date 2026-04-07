"""E2E tests for GitHub Project operations against real testbed.

Testbed Project: saltenhof #5 (AgentKit v3 Testbed)
Project ID: PVT_kwHODdCDrM4BT-Fu
"""

from __future__ import annotations

import pytest

from agentkit.integrations.github.projects import (
    add_issue_to_project,
    get_project_field_ids,
    get_project_field_options,
    list_project_items,
)

OWNER = "saltenhof"
PROJECT_NUMBER = 5
REPO = "agentkit3-testbed"


@pytest.mark.e2e
@pytest.mark.requires_gh
class TestProjectOperations:
    """Tests for GitHub Projects v2 operations."""

    def test_add_issue_to_project(self) -> None:
        """Add issue #1 to project and get item ID back."""
        issue_url = f"https://github.com/{OWNER}/{REPO}/issues/1"
        item_id = add_issue_to_project(OWNER, PROJECT_NUMBER, issue_url)
        assert item_id  # non-empty string

    def test_list_project_items(self) -> None:
        """List items in testbed project."""
        items = list_project_items(OWNER, PROJECT_NUMBER)
        assert isinstance(items, list)
        # After adding issue #1, there should be at least one item

    def test_get_project_field_ids(self) -> None:
        """Get field IDs for testbed project."""
        fields = get_project_field_ids(OWNER, PROJECT_NUMBER)
        assert isinstance(fields, dict)
        # Projects v2 always has at least "Status" and "Title"
        assert "Status" in fields or "Title" in fields

    def test_get_project_field_options(self) -> None:
        """Get single-select options for testbed project."""
        options = get_project_field_options(OWNER, PROJECT_NUMBER)
        assert isinstance(options, dict)
        # The Status field should have options
        assert "Status" in options
        status_opts = options["Status"]
        assert "Todo" in status_opts
        assert "Done" in status_opts
