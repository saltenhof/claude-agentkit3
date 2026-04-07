"""Unit tests for agentkit.story.types."""

from __future__ import annotations

import pytest

from agentkit.story.types import (
    PROFILES,
    StoryMode,
    StoryType,
    StoryTypeProfile,
    get_profile,
)


class TestStoryType:
    """Tests for the StoryType enum."""

    def test_all_values(self) -> None:
        assert set(StoryType) == {
            StoryType.IMPLEMENTATION,
            StoryType.BUGFIX,
            StoryType.CONCEPT,
            StoryType.RESEARCH,
        }

    def test_string_values(self) -> None:
        assert StoryType.IMPLEMENTATION == "implementation"
        assert StoryType.BUGFIX == "bugfix"
        assert StoryType.CONCEPT == "concept"
        assert StoryType.RESEARCH == "research"

    def test_is_str_subclass(self) -> None:
        assert isinstance(StoryType.IMPLEMENTATION, str)


class TestStoryMode:
    """Tests for the StoryMode enum."""

    def test_all_values(self) -> None:
        assert set(StoryMode) == {
            StoryMode.EXECUTION,
            StoryMode.EXPLORATION,
            StoryMode.NOT_APPLICABLE,
        }

    def test_string_values(self) -> None:
        assert StoryMode.EXECUTION == "execution"
        assert StoryMode.EXPLORATION == "exploration"
        assert StoryMode.NOT_APPLICABLE == "not_applicable"


class TestStoryTypeProfile:
    """Tests for the StoryTypeProfile dataclass."""

    def test_frozen(self) -> None:
        profile = get_profile(StoryType.IMPLEMENTATION)
        with pytest.raises(AttributeError):
            profile.uses_worktree = False  # type: ignore[misc]


class TestProfiles:
    """Tests for the PROFILES dict and profile definitions."""

    def test_all_story_types_have_profiles(self) -> None:
        for story_type in StoryType:
            assert story_type in PROFILES

    def test_implementation_profile(self) -> None:
        p = PROFILES[StoryType.IMPLEMENTATION]
        assert p.story_type == StoryType.IMPLEMENTATION
        assert p.uses_worktree is True
        assert p.uses_full_qa is True
        assert p.uses_merge is True
        assert p.allowed_modes == (StoryMode.EXECUTION, StoryMode.EXPLORATION)
        assert p.default_mode == StoryMode.EXPLORATION
        assert p.phases == (
            "setup",
            "exploration",
            "implementation",
            "verify",
            "closure",
        )

    def test_bugfix_profile(self) -> None:
        p = PROFILES[StoryType.BUGFIX]
        assert p.story_type == StoryType.BUGFIX
        assert p.uses_worktree is True
        assert p.uses_full_qa is True
        assert p.uses_merge is True
        assert p.allowed_modes == (StoryMode.EXECUTION,)
        assert p.default_mode == StoryMode.EXECUTION
        assert p.phases == ("setup", "implementation", "verify", "closure")

    def test_concept_profile(self) -> None:
        p = PROFILES[StoryType.CONCEPT]
        assert p.story_type == StoryType.CONCEPT
        assert p.uses_worktree is False
        assert p.uses_full_qa is False
        assert p.uses_merge is False
        assert p.allowed_modes == (StoryMode.NOT_APPLICABLE,)
        assert p.default_mode == StoryMode.NOT_APPLICABLE
        assert p.phases == ("setup", "implementation", "verify", "closure")

    def test_research_profile(self) -> None:
        p = PROFILES[StoryType.RESEARCH]
        assert p.story_type == StoryType.RESEARCH
        assert p.uses_worktree is False
        assert p.uses_full_qa is False
        assert p.uses_merge is False
        assert p.allowed_modes == (StoryMode.NOT_APPLICABLE,)
        assert p.default_mode == StoryMode.NOT_APPLICABLE
        assert p.phases == ("setup", "implementation", "closure")

    def test_default_mode_is_in_allowed_modes(self) -> None:
        for story_type, profile in PROFILES.items():
            assert profile.default_mode in profile.allowed_modes, (
                f"{story_type}: default_mode {profile.default_mode!r} "
                f"not in allowed_modes {profile.allowed_modes!r}"
            )

    def test_all_phases_start_with_setup(self) -> None:
        for story_type, profile in PROFILES.items():
            assert profile.phases[0] == "setup", (
                f"{story_type}: first phase is {profile.phases[0]!r}, expected 'setup'"
            )

    def test_code_types_use_worktree(self) -> None:
        """Implementation and bugfix stories need worktrees."""
        assert PROFILES[StoryType.IMPLEMENTATION].uses_worktree is True
        assert PROFILES[StoryType.BUGFIX].uses_worktree is True

    def test_non_code_types_skip_worktree(self) -> None:
        """Concept and research stories don't need worktrees."""
        assert PROFILES[StoryType.CONCEPT].uses_worktree is False
        assert PROFILES[StoryType.RESEARCH].uses_worktree is False


class TestGetProfile:
    """Tests for the get_profile function."""

    def test_returns_correct_profile(self) -> None:
        for story_type in StoryType:
            profile = get_profile(story_type)
            assert isinstance(profile, StoryTypeProfile)
            assert profile.story_type == story_type

    def test_returns_same_object_as_dict(self) -> None:
        for story_type in StoryType:
            assert get_profile(story_type) is PROFILES[story_type]
