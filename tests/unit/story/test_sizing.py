"""Unit tests for story sizing.

``StorySize`` und ihre Heuristiken nutzen seit AG3-021 das
DK-10-§10.4-Vokabular XS/S/M/L/XL.
"""

from __future__ import annotations

from agentkit.story_context_manager.sizing import StorySize, estimate_size


class TestStorySize:
    """Tests for the StorySize enum."""

    def test_all_values(self) -> None:
        assert set(StorySize) == {
            StorySize.XS,
            StorySize.S,
            StorySize.M,
            StorySize.L,
            StorySize.XL,
        }

    def test_string_values(self) -> None:
        assert StorySize.XS.value == "XS"
        assert StorySize.S.value == "S"
        assert StorySize.M.value == "M"
        assert StorySize.L.value == "L"
        assert StorySize.XL.value == "XL"


class TestEstimateSize:
    """Tests for the estimate_size function."""

    # --- Label-based sizing (takes precedence) ---

    def test_label_xs(self) -> None:
        assert estimate_size(["size:xs"], "anything") == StorySize.XS

    def test_label_s(self) -> None:
        assert estimate_size(["size:s"], "anything") == StorySize.S

    def test_label_m(self) -> None:
        assert estimate_size(["size:m"], "anything") == StorySize.M

    def test_label_l(self) -> None:
        assert estimate_size(["size:l"], "anything") == StorySize.L

    def test_label_xl(self) -> None:
        assert estimate_size(["size:xl"], "anything") == StorySize.XL

    def test_label_case_insensitive(self) -> None:
        assert estimate_size(["Size:M"], "anything") == StorySize.M

    def test_label_with_whitespace(self) -> None:
        assert estimate_size(["  size:l  "], "anything") == StorySize.L

    def test_label_overrides_title_keywords(self) -> None:
        """Label takes precedence even when title suggests different size."""
        result = estimate_size(["size:xs"], "Refactor entire pipeline")
        assert result == StorySize.XS

    def test_first_matching_label_wins(self) -> None:
        assert estimate_size(["size:xs", "size:l"], "title") == StorySize.XS

    def test_invalid_size_label_ignored(self) -> None:
        assert estimate_size(["size:gigantic"], "simple task") == StorySize.S

    def test_legacy_label_values_ignored(self) -> None:
        """Alte v2-Werte small/medium/large/epic sind keine validen Labels."""
        assert estimate_size(["size:small"], "simple task") == StorySize.S
        assert estimate_size(["size:medium"], "simple task") == StorySize.S
        assert estimate_size(["size:large"], "simple task") == StorySize.S
        assert estimate_size(["size:epic"], "simple task") == StorySize.S

    def test_non_size_labels_ignored(self) -> None:
        result = estimate_size(["bugfix", "priority:high"], "simple task")
        assert result == StorySize.S

    # --- Title-based heuristic ---

    def test_title_with_large_keyword_returns_l_size(self) -> None:
        """Refactor-keywords yield L (conservative heuristic)."""
        assert estimate_size([], "Refactor the verify phase") == StorySize.L

    def test_title_with_migration_keyword(self) -> None:
        assert estimate_size([], "Migration to new schema") == StorySize.L

    def test_title_with_rewrite_keyword(self) -> None:
        assert estimate_size([], "Rewrite the prompt engine") == StorySize.L

    def test_title_with_medium_keyword_returns_m_size(self) -> None:
        """Integration-keywords yield M (conservative heuristic)."""
        assert estimate_size([], "Implement story sizing") == StorySize.M

    def test_title_with_pipeline_keyword(self) -> None:
        assert estimate_size([], "Add pipeline telemetry") == StorySize.M

    def test_title_with_framework_keyword(self) -> None:
        assert estimate_size([], "Build testing framework") == StorySize.M

    def test_title_with_no_keywords(self) -> None:
        assert estimate_size([], "Fix typo in readme") == StorySize.S

    def test_empty_labels_and_title(self) -> None:
        assert estimate_size([], "") == StorySize.S

    def test_title_keyword_case_insensitive(self) -> None:
        assert estimate_size([], "IMPLEMENT new feature") == StorySize.M
