"""Unit tests for agentkit.backend.story package re-exports."""

from __future__ import annotations

import agentkit.backend.story_context_manager as story_pkg


class TestPackageExports:
    """Verify that all expected symbols are re-exported from the package."""

    def test_story_type_exported(self) -> None:
        assert hasattr(story_pkg, "StoryType")

    def test_story_mode_exported(self) -> None:
        assert hasattr(story_pkg, "StoryMode")

    def test_story_context_exported(self) -> None:
        assert hasattr(story_pkg, "StoryContext")




    def test_story_size_exported(self) -> None:
        assert hasattr(story_pkg, "StorySize")

    def test_story_type_profile_exported(self) -> None:
        assert hasattr(story_pkg, "StoryTypeProfile")

    def test_get_profile_exported(self) -> None:
        assert hasattr(story_pkg, "get_profile")

    def test_get_phases_for_story_exported(self) -> None:
        assert hasattr(story_pkg, "get_phases_for_story")

    def test_format_story_display_id_exported(self) -> None:
        # AG3-050: the canonical display-ID formatter replaces the removed
        # dead ``create_story`` lifecycle re-export.
        assert hasattr(story_pkg, "format_story_display_id")

    def test_all_list_matches_exports(self) -> None:
        # The phase-state models (PhaseSnapshot/PhaseState/PhaseStatus) are NOT
        # here: their owner is pipeline_engine.phase_executor (FK-39 §39.7) and
        # the re-export bridge that duplicated them was removed on 2026-08-02.
        expected = {
            "ImplementationContract",
            "StoryContext",
            "StoryMode",
            "StorySize",
            "StoryType",
            "StoryTypeProfile",
            "format_story_display_id",
            "get_phases_for_story",
            "get_profile",
            # AG3-074 (FK-59): the consolidated result axis is re-exported from
            # the story_context_manager namespace.
            "ExitClass",
            "TerminalState",
            "derive_terminal_state",
            "validate_exit_class_constraints",
        }
        assert set(story_pkg.__all__) == expected
