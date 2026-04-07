"""Unit tests for the gh CLI wrapper.

Subprocess is mocked here because it is an external system
dependency (OS process invocation). This is one of the two
permitted mock exceptions per project rules.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from agentkit.exceptions import IntegrationError
from agentkit.integrations.github.client import (
    _resolve_token_from_credentials_file,
    _resolve_token_from_keyring,
    resolve_token_for_owner,
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
            run_gh_graphql(
                "query($repo_owner: String!) { }",
                repo_owner="test",
            )
            call_args = mock_run.call_args[0][0]
            assert "-f" in call_args
            assert "repo_owner=test" in call_args


@pytest.mark.unit
class TestResolveTokenForOwner:
    """Tests for the two-step token resolution (keyring then credential file)."""

    def test_prefers_keyring_token(self) -> None:
        """When keyring has a token, it takes precedence over cred file."""
        with patch(
            "agentkit.integrations.github.client._resolve_token_from_keyring",
            return_value="gho_keyring_token",
        ):
            token = resolve_token_for_owner("testowner")
            assert token == "gho_keyring_token"

    def test_falls_back_to_credentials_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Falls back to cred file when keyring returns None."""
        creds_file = tmp_path / ".git-credentials-testowner"
        creds_file.write_text("https://testowner:ghp_test123@github.com\n")
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.setenv("HOME", str(tmp_path))
        with patch(
            "agentkit.integrations.github.client._resolve_token_from_keyring",
            return_value=None,
        ):
            token = resolve_token_for_owner("testowner")
            assert token == "ghp_test123"

    def test_returns_none_for_unknown_owner(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Returns None when neither keyring nor credentials file exists."""
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.setenv("HOME", str(tmp_path))
        with patch(
            "agentkit.integrations.github.client._resolve_token_from_keyring",
            return_value=None,
        ):
            token = resolve_token_for_owner("unknown")
            assert token is None

    def test_returns_none_for_empty_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Returns None when credentials file has no matching line."""
        creds_file = tmp_path / ".git-credentials-testowner"
        creds_file.write_text("# comment only\n")
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.setenv("HOME", str(tmp_path))
        with patch(
            "agentkit.integrations.github.client._resolve_token_from_keyring",
            return_value=None,
        ):
            token = resolve_token_for_owner("testowner")
            assert token is None

    def test_ignores_non_matching_user_in_cred_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Returns None when cred file has credentials for a different user."""
        creds_file = tmp_path / ".git-credentials-testowner"
        creds_file.write_text("https://otheruser:ghp_other@github.com\n")
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.setenv("HOME", str(tmp_path))
        with patch(
            "agentkit.integrations.github.client._resolve_token_from_keyring",
            return_value=None,
        ):
            token = resolve_token_for_owner("testowner")
            assert token is None

    def test_picks_first_matching_line_in_cred_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When multiple lines match in cred file, returns the first token."""
        creds_file = tmp_path / ".git-credentials-testowner"
        creds_file.write_text(
            "https://testowner:ghp_first@github.com\n"
            "https://testowner:ghp_second@github.com\n"
        )
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.setenv("HOME", str(tmp_path))
        with patch(
            "agentkit.integrations.github.client._resolve_token_from_keyring",
            return_value=None,
        ):
            token = resolve_token_for_owner("testowner")
            assert token == "ghp_first"


@pytest.mark.unit
class TestResolveTokenFromKeyring:
    """Tests for the keyring-based token resolution."""

    def test_returns_token_from_keyring(self) -> None:
        """Returns token when gh auth token succeeds."""
        with patch(
            "agentkit.integrations.github.client.subprocess.run",
        ) as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="gho_keyring123\n", stderr="",
            )
            token = _resolve_token_from_keyring("testowner")
            assert token == "gho_keyring123"
            mock_run.assert_called_once_with(
                ["gh", "auth", "token", "--user", "testowner"],
                capture_output=True,
                text=True,
                timeout=5,
            )

    def test_returns_none_on_failure(self) -> None:
        """Returns None when gh auth token fails."""
        with patch(
            "agentkit.integrations.github.client.subprocess.run",
        ) as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1, stdout="", stderr="not logged in",
            )
            token = _resolve_token_from_keyring("unknown")
            assert token is None

    def test_returns_none_on_gh_not_found(self) -> None:
        """Returns None when gh binary is not installed."""
        with patch(
            "agentkit.integrations.github.client.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            token = _resolve_token_from_keyring("testowner")
            assert token is None


@pytest.mark.unit
class TestResolveTokenFromCredentialsFile:
    """Tests for the credential-file token resolution."""

    def test_finds_token(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Reads token from ~/.git-credentials-{owner}."""
        creds_file = tmp_path / ".git-credentials-testowner"
        creds_file.write_text("https://testowner:ghp_abc@github.com\n")
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.setenv("HOME", str(tmp_path))
        token = _resolve_token_from_credentials_file("testowner")
        assert token == "ghp_abc"

    def test_returns_none_when_file_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Returns None when no credentials file exists."""
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.setenv("HOME", str(tmp_path))
        token = _resolve_token_from_credentials_file("missing")
        assert token is None


@pytest.mark.unit
class TestRunGhOwnerRouting:
    """Tests for token routing via the owner parameter."""

    def test_run_gh_passes_token_via_env(self) -> None:
        """When owner has a token, GH_TOKEN is set in subprocess env."""
        with (
            patch(
                "agentkit.integrations.github.client.resolve_token_for_owner",
                return_value="ghp_xxx",
            ),
            patch(
                "agentkit.integrations.github.client.subprocess.run",
            ) as mock_run,
        ):
            mock_run.return_value = MagicMock(
                returncode=0, stdout="ok\n", stderr="",
            )
            run_gh("version", owner="testowner")
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["env"] is not None
            assert call_kwargs["env"]["GH_TOKEN"] == "ghp_xxx"

    def test_run_gh_no_env_without_owner(self) -> None:
        """Without owner, env is None (inherits current environment)."""
        with patch(
            "agentkit.integrations.github.client.subprocess.run",
        ) as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="ok\n", stderr="",
            )
            run_gh("version")
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["env"] is None

    def test_run_gh_no_env_when_token_not_found(self) -> None:
        """When owner is given but no token found, env is None."""
        with (
            patch(
                "agentkit.integrations.github.client.resolve_token_for_owner",
                return_value=None,
            ),
            patch(
                "agentkit.integrations.github.client.subprocess.run",
            ) as mock_run,
        ):
            mock_run.return_value = MagicMock(
                returncode=0, stdout="ok\n", stderr="",
            )
            run_gh("version", owner="unknown")
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["env"] is None

    def test_run_gh_json_passes_owner(self) -> None:
        """run_gh_json forwards owner to run_gh."""
        with (
            patch(
                "agentkit.integrations.github.client.resolve_token_for_owner",
                return_value="ghp_json",
            ),
            patch(
                "agentkit.integrations.github.client.subprocess.run",
            ) as mock_run,
        ):
            mock_run.return_value = MagicMock(
                returncode=0, stdout='{"k": "v"}', stderr="",
            )
            result = run_gh_json("api", "test", owner="testowner")
            assert result == {"k": "v"}
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["env"]["GH_TOKEN"] == "ghp_json"

    def test_run_gh_graphql_passes_owner(self) -> None:
        """run_gh_graphql forwards owner to run_gh."""
        with (
            patch(
                "agentkit.integrations.github.client.resolve_token_for_owner",
                return_value="ghp_gql",
            ),
            patch(
                "agentkit.integrations.github.client.subprocess.run",
            ) as mock_run,
        ):
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='{"data": {"viewer": {"login": "test"}}}',
                stderr="",
            )
            run_gh_graphql("{ viewer { login } }", owner="testowner")
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["env"]["GH_TOKEN"] == "ghp_gql"
