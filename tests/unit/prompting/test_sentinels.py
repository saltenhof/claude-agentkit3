"""Tests for sentinel marker utilities."""

from __future__ import annotations

import pytest

from agentkit.prompting.sentinels import (
    extract_sentinel,
    make_sentinel,
    validate_sentinel,
)


class TestMakeSentinel:
    """Tests for make_sentinel()."""

    def test_produces_correct_format(self) -> None:
        """make_sentinel must produce [SENTINEL:{name}-v{ver}:{id}]."""
        result = make_sentinel("worker-implementation", "AG3-001")
        assert result == "[SENTINEL:worker-implementation-v1:AG3-001]"

    def test_custom_version(self) -> None:
        """make_sentinel must honour the version parameter."""
        result = make_sentinel("worker-bugfix", "BB2-058", version=2)
        assert result == "[SENTINEL:worker-bugfix-v2:BB2-058]"


class TestExtractSentinel:
    """Tests for extract_sentinel()."""

    def test_extracts_from_text(self) -> None:
        """extract_sentinel must find a sentinel embedded in text."""
        text = (
            "Some preamble\n"
            "[SENTINEL:worker-concept-v1:ODIN-42]\n"
            "Some epilogue"
        )
        data = extract_sentinel(text)
        assert data is not None
        assert data["template"] == "worker-concept"
        assert data["version"] == "1"
        assert data["story_id"] == "ODIN-42"

    def test_returns_none_for_text_without_sentinel(self) -> None:
        """extract_sentinel returns None when no sentinel is present."""
        assert extract_sentinel("No sentinel here") is None

    def test_returns_none_for_empty_string(self) -> None:
        """extract_sentinel must return None for empty input."""
        assert extract_sentinel("") is None

    @pytest.mark.parametrize(
        "story_id",
        ["AG3-001", "BB2-058", "ODIN-42", "test_123", "a-b-c"],
    )
    def test_various_story_ids(self, story_id: str) -> None:
        """extract_sentinel must handle various valid story ID formats."""
        sentinel = make_sentinel("worker-research", story_id)
        data = extract_sentinel(sentinel)
        assert data is not None
        assert data["story_id"] == story_id


class TestValidateSentinel:
    """Tests for validate_sentinel()."""

    def test_returns_true_for_matching_sentinel(self) -> None:
        """validate_sentinel returns True when template and ID match."""
        text = "[SENTINEL:worker-implementation-v1:AG3-001]"
        result = validate_sentinel(
            text, "worker-implementation", "AG3-001",
        )
        assert result is True

    def test_returns_false_for_wrong_template(self) -> None:
        """validate_sentinel returns False when template name differs."""
        text = "[SENTINEL:worker-bugfix-v1:AG3-001]"
        result = validate_sentinel(
            text, "worker-implementation", "AG3-001",
        )
        assert result is False

    def test_returns_false_for_wrong_story_id(self) -> None:
        """validate_sentinel returns False when story ID differs."""
        text = "[SENTINEL:worker-implementation-v1:AG3-001]"
        result = validate_sentinel(
            text, "worker-implementation", "AG3-999",
        )
        assert result is False

    def test_returns_false_for_text_without_sentinel(self) -> None:
        """validate_sentinel returns False when no sentinel exists."""
        result = validate_sentinel(
            "plain text", "worker-implementation", "AG3-001",
        )
        assert result is False
