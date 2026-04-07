"""Unit tests for the gh CLI wrapper.

Subprocess is mocked here because it is an external system
dependency (OS process invocation). This is one of the two
permitted mock exceptions per project rules.
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from agentkit.exceptions import IntegrationError
from agentkit.integrations.github.client import (
    run_gh,
    run_gh_graphql,
    run_gh_json,
)


@pytest.mark.unit
class TestRunGh:
    """Tests for the low-level run_gh function."""

    def test_successful_command(self) -> None:
        """run_gh returns stdout on success."""
        with patch("agentkit.integrations.github.client.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="ok\n", stderr=""
            )
            result = run_gh("version")
            assert result == "ok\n"
            mock_run.assert_called_once()

    def test_failed_command_raises(self) -> None:
        """run_gh raises IntegrationError on non-zero exit."""
        with patch("agentkit.integrations.github.client.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1, stdout="", stderr="error msg"
            )
            with pytest.raises(IntegrationError, match="gh command failed"):
                run_gh("bad-command")

    def test_failed_command_check_false(self) -> None:
        """run_gh with check=False does not raise on non-zero exit."""
        with patch("agentkit.integrations.github.client.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1, stdout="some output", stderr="warning"
            )
            result = run_gh("some-command", check=False)
            assert result == "some output"

    def test_missing_gh_raises(self) -> None:
        """run_gh raises IntegrationError if gh not found."""
        with (
            patch(
                "agentkit.integrations.github.client.subprocess.run",
                side_effect=FileNotFoundError,
            ),
            pytest.raises(IntegrationError, match="gh CLI not found"),
        ):
            run_gh("version")

    def test_timeout_raises(self) -> None:
        """run_gh raises IntegrationError on timeout."""
        with (
            patch(
                "agentkit.integrations.github.client.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="gh", timeout=30),
            ),
            pytest.raises(IntegrationError, match="timed out"),
        ):
            run_gh("version")

    def test_error_detail_contains_stderr(self) -> None:
        """IntegrationError detail includes stderr and returncode."""
        with patch("agentkit.integrations.github.client.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=128, stdout="", stderr="fatal: not a repo"
            )
            with pytest.raises(IntegrationError) as exc_info:
                run_gh("status")
            assert exc_info.value.detail["stderr"] == "fatal: not a repo"
            assert exc_info.value.detail["returncode"] == 128


@pytest.mark.unit
class TestRunGhJson:
    """Tests for the JSON-parsing run_gh_json function."""

    def test_valid_json(self) -> None:
        """run_gh_json parses valid JSON output."""
        with patch("agentkit.integrations.github.client.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout='{"key": "value"}', stderr=""
            )
            result = run_gh_json("api", "something")
            assert result == {"key": "value"}

    def test_valid_json_list(self) -> None:
        """run_gh_json parses a JSON list."""
        with patch("agentkit.integrations.github.client.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout='[1, 2, 3]', stderr=""
            )
            result = run_gh_json("api", "something")
            assert result == [1, 2, 3]

    def test_invalid_json_raises(self) -> None:
        """run_gh_json raises IntegrationError on invalid JSON."""
        with patch("agentkit.integrations.github.client.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="not json at all", stderr=""
            )
            with pytest.raises(IntegrationError, match="Failed to parse"):
                run_gh_json("api", "something")


@pytest.mark.unit
class TestRunGhGraphql:
    """Tests for the GraphQL wrapper."""

    def test_successful_query(self) -> None:
        """run_gh_graphql returns the parsed response."""
        with patch("agentkit.integrations.github.client.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='{"data": {"viewer": {"login": "test"}}}',
                stderr="",
            )
            result = run_gh_graphql("{ viewer { login } }")
            assert result["data"]["viewer"]["login"] == "test"

    def test_graphql_errors_raise(self) -> None:
        """run_gh_graphql raises on GraphQL-level errors."""
        with patch("agentkit.integrations.github.client.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='{"errors": [{"message": "bad query"}]}',
                stderr="",
            )
            with pytest.raises(IntegrationError, match="GraphQL query returned errors"):
                run_gh_graphql("{ invalid }")

    def test_variables_passed_correctly(self) -> None:
        """run_gh_graphql passes variables via -f flags."""
        with patch("agentkit.integrations.github.client.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='{"data": {}}',
                stderr="",
            )
            run_gh_graphql("query($owner: String!) { }", owner="test")
            call_args = mock_run.call_args[0][0]
            assert "-f" in call_args
            assert "owner=test" in call_args
