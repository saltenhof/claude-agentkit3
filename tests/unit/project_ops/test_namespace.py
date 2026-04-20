"""Unit tests for project_ops namespace contract."""

import agentkit.project_ops as project_ops


def test_project_ops_has_no_public_api() -> None:
    assert project_ops.__all__ == []
