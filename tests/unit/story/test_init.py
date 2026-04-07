"""Unit tests for agentkit.story package re-exports."""

from __future__ import annotations

import agentkit.story as story_pkg


class TestPackageExports:
    """Verify that all expected symbols are re-exported from the package."""

    def test_story_type_exported(self) -> None:
        assert hasattr(story_pkg, "StoryType")

    def test_story_mode_exported(self) -> None:
        assert hasattr(story_pkg, "StoryMode")

    def test_story_context_exported(self) -> None:
        assert hasattr(story_pkg, "StoryContext")

    def test_phase_state_exported(self) -> None:
        assert hasattr(story_pkg, "PhaseState")

    def test_phase_status_exported(self) -> None:
        assert hasattr(story_pkg, "PhaseStatus")

    def test_phase_snapshot_exported(self) -> None:
        assert hasattr(story_pkg, "PhaseSnapshot")

    def test_story_size_exported(self) -> None:
        assert hasattr(story_pkg, "StorySize")

    def test_story_type_profile_exported(self) -> None:
        assert hasattr(story_pkg, "StoryTypeProfile")

    def test_get_profile_exported(self) -> None:
        assert hasattr(story_pkg, "get_profile")

    def test_get_phases_for_story_exported(self) -> None:
        assert hasattr(story_pkg, "get_phases_for_story")

    def test_all_list_matches_exports(self) -> None:
        expected = {
            "PhaseSnapshot",
            "PhaseState",
            "PhaseStatus",
            "StoryContext",
            "StoryMode",
            "StorySize",
            "StoryType",
            "StoryTypeProfile",
            "get_phases_for_story",
            "get_profile",
        }
        assert set(story_pkg.__all__) == expected
