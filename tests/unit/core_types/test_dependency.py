"""Unit-Tests fuer StoryDependencyKind (AG3-021 §2.1.9.1)."""

from __future__ import annotations

import pytest

from agentkit.core_types import StoryDependencyKind


def test_each_value_constructable() -> None:
    for raw in (
        "hard_story_dependency",
        "soft_story_dependency",
        "serial_execution_constraint",
        "mutex_constraint",
        "shared_contract_dependency",
        "shared_file_conflict",
        "external_dependency",
        "human_gate_dependency",
    ):
        assert StoryDependencyKind(raw).value == raw


def test_iteration_is_deterministic() -> None:
    assert list(StoryDependencyKind) == [
        StoryDependencyKind.HARD_STORY_DEPENDENCY,
        StoryDependencyKind.SOFT_STORY_DEPENDENCY,
        StoryDependencyKind.SERIAL_EXECUTION_CONSTRAINT,
        StoryDependencyKind.MUTEX_CONSTRAINT,
        StoryDependencyKind.SHARED_CONTRACT_DEPENDENCY,
        StoryDependencyKind.SHARED_FILE_CONFLICT,
        StoryDependencyKind.EXTERNAL_DEPENDENCY,
        StoryDependencyKind.HUMAN_GATE_DEPENDENCY,
    ]


def test_str_enum_invariants() -> None:
    assert (
        StoryDependencyKind.HARD_STORY_DEPENDENCY.value
        == "hard_story_dependency"
    )
    assert isinstance(StoryDependencyKind.HARD_STORY_DEPENDENCY, str)


def test_eight_values() -> None:
    assert len(StoryDependencyKind) == 8


def test_legacy_three_word_vocab_rejected() -> None:
    """v2-Vokabular blocks/derives_from/branches_off entfaellt mit AG3-021."""
    for legacy in ("blocks", "derives_from", "branches_off"):
        with pytest.raises(ValueError):
            StoryDependencyKind(legacy)
