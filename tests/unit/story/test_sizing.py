"""Unit tests for agentkit.story.sizing."""

from __future__ import annotations

from agentkit.story.sizing import StorySize, estimate_size


class TestStorySize:
    """Tests for the StorySize enum."""

    def test_all_values(self) -> None:
        assert set(StorySize) == {
            StorySize.SMALL,
            StorySize.MEDIUM,
            StorySize.LARGE,
            StorySize.EPIC,
        }

    def test_string_values(self) -> None:
        assert StorySize.SMALL == "small"
        assert StorySize.MEDIUM == "medium"
        assert StorySize.LARGE == "large"
        assert StorySize.EPIC == "epic"


class TestEstimateSize:
    """Tests for the estimate_size function."""

    # --- Label-based sizing (takes precedence) ---

    def test_label_small(self) -> None:
        assert estimate_size(["size:small"], "anything") == StorySize.SMALL

    def test_label_medium(self) -> None:
        assert estimate_size(["size:medium"], "anything") == StorySize.MEDIUM

    def test_label_large(self) -> None:
        assert estimate_size(["size:large"], "anything") == StorySize.LARGE

    def test_label_epic(self) -> None:
        assert estimate_size(["size:epic"], "anything") == StorySize.EPIC

    def test_label_case_insensitive(self) -> None:
        assert estimate_size(["Size:Medium"], "anything") == StorySize.MEDIUM

    def test_label_with_whitespace(self) -> None:
        assert estimate_size(["  size:large  "], "anything") == StorySize.LARGE

    def test_label_overrides_title_keywords(self) -> None:
        """Label takes precedence even when title suggests different size."""
        result = estimate_size(["size:small"], "Refactor entire pipeline")
        assert result == StorySize.SMALL

    def test_first_matching_label_wins(self) -> None:
        assert estimate_size(["size:small", "size:large"], "title") == StorySize.SMALL

    def test_invalid_size_label_ignored(self) -> None:
        assert estimate_size(["size:gigantic"], "simple task") == StorySize.SMALL

    def test_non_size_labels_ignored(self) -> None:
        result = estimate_size(["bugfix", "priority:high"], "simple task")
        assert result == StorySize.SMALL

    # --- Title-based heuristic ---

    def test_title_with_epic_keyword_returns_large(self) -> None:
        """Epic keywords yield LARGE (conservative heuristic)."""
        assert estimate_size([], "Refactor the verify phase") == StorySize.LARGE

    def test_title_with_migration_keyword(self) -> None:
        assert estimate_size([], "Migration to new schema") == StorySize.LARGE

    def test_title_with_rewrite_keyword(self) -> None:
        assert estimate_size([], "Rewrite the prompt engine") == StorySize.LARGE

    def test_title_with_large_keyword_returns_medium(self) -> None:
        """Large keywords yield MEDIUM (conservative heuristic)."""
        assert estimate_size([], "Implement story sizing") == StorySize.MEDIUM

    def test_title_with_pipeline_keyword(self) -> None:
        assert estimate_size([], "Add pipeline telemetry") == StorySize.MEDIUM

    def test_title_with_framework_keyword(self) -> None:
        assert estimate_size([], "Build testing framework") == StorySize.MEDIUM

    def test_title_with_no_keywords(self) -> None:
        assert estimate_size([], "Fix typo in readme") == StorySize.SMALL

    def test_empty_labels_and_title(self) -> None:
        assert estimate_size([], "") == StorySize.SMALL

    def test_title_keyword_case_insensitive(self) -> None:
        assert estimate_size([], "IMPLEMENT new feature") == StorySize.MEDIUM
