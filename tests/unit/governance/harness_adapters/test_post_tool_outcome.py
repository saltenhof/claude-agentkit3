"""Regression tests for post_tool_outcome exit-code parsing.

Covers the newline-tolerant whitespace-normalisation path that was
restored in AG3-Sonar-fix: collapse all whitespace (incl. newlines) to
single spaces before matching so inputs like ``"status:\\n1"`` or
``"Command failed\\nexit code:\\n1"`` are still parsed correctly.
"""

from __future__ import annotations

import pytest

from agentkit.governance.harness_adapters.post_tool_outcome import map_post_tool_outcome

# ---------------------------------------------------------------------------
# Regression: newline-separated patterns must still yield a parsed exit_code
# ---------------------------------------------------------------------------


class TestExitCodeNewlineRegression:
    """Exit-code extraction must handle newline-separated tokens (DoS-safe)."""

    def test_status_newline_1(self) -> None:
        """``status:\\n1`` -> exit_code == 1."""
        result = map_post_tool_outcome({}, fallback_error="status:\n1")
        assert result["exit_code"] == 1

    def test_command_failed_newline_exit_code_newline_1(self) -> None:
        """Multi-line payload: ``Command failed\\nexit code:\\n1`` -> exit_code == 1."""
        result = map_post_tool_outcome(
            {},
            fallback_error="Command failed\nexit code:\n1",
        )
        assert result["exit_code"] == 1

    def test_exit_code_with_leading_trailing_newlines(self) -> None:
        """Leading/trailing newlines around the pattern are ignored."""
        result = map_post_tool_outcome(
            {},
            fallback_error="\n\nexit code: 127\n",
        )
        assert result["exit_code"] == 127

    def test_multispace_between_tokens(self) -> None:
        """Multiple horizontal spaces between tokens are collapsed correctly."""
        result = map_post_tool_outcome({}, fallback_error="exit    code   =   2")
        assert result["exit_code"] == 2

    def test_return_code_newline_negative(self) -> None:
        """Negative exit code across a newline boundary is parsed correctly."""
        result = map_post_tool_outcome(
            {},
            fallback_error="return code:\n-1",
        )
        assert result["exit_code"] == -1

    def test_no_exit_code_in_plain_text(self) -> None:
        """Irrelevant text yields exit_code == None (sanity guard)."""
        result = map_post_tool_outcome(
            {},
            fallback_error="Operation completed successfully.",
        )
        assert result["exit_code"] is None


# ---------------------------------------------------------------------------
# Existing single-line cases must remain green
# ---------------------------------------------------------------------------


class TestExitCodeSingleLine:
    """Single-line patterns must continue to work as before."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("exit code: 0", 0),
            ("exit code = 1", 1),
            ("exit code 1", 1),
            ("status: 2", 2),
            ("return code: 3", 3),
            ("exit: 0", 0),
            ("EXIT CODE: 128", 128),
            ("Command exited with non-zero status code 1", 1),
        ],
    )
    def test_single_line_patterns(self, text: str, expected: int) -> None:
        result = map_post_tool_outcome({}, fallback_error=text)
        assert result["exit_code"] == expected


# ---------------------------------------------------------------------------
# Structured response fields take priority over fallback text
# ---------------------------------------------------------------------------


class TestStructuredFieldPriority:
    """Structured dict keys shadow the fallback-text regex path."""

    def test_exit_code_key_wins_over_fallback(self) -> None:
        result = map_post_tool_outcome(
            {"exit_code": 42},
            fallback_error="exit code: 99",
        )
        assert result["exit_code"] == 42

    def test_fallback_used_when_no_structured_key(self) -> None:
        result = map_post_tool_outcome(
            {"stdout": "ok"},
            fallback_error="exit code: 5",
        )
        assert result["exit_code"] == 5
