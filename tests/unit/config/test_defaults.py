"""Unit tests for agentkit.config.defaults."""

from __future__ import annotations

from agentkit.config.defaults import (
    DEFAULT_CONFIG_DIR,
    DEFAULT_CONFIG_FILE,
    DEFAULT_MAX_FEEDBACK_ROUNDS,
    DEFAULT_MAX_REMEDIATION_ROUNDS,
    DEFAULT_STORY_TYPES,
    DEFAULT_VERIFY_LAYERS,
)


class TestDefaultValues:
    """Verify that default constants have expected values."""

    def test_config_dir(self) -> None:
        assert DEFAULT_CONFIG_DIR == ".agentkit/config"

    def test_config_file(self) -> None:
        assert DEFAULT_CONFIG_FILE == "project.yaml"

    def test_story_types(self) -> None:
        assert DEFAULT_STORY_TYPES == (
            "implementation",
            "bugfix",
            "concept",
            "research",
        )

    def test_max_feedback_rounds(self) -> None:
        assert DEFAULT_MAX_FEEDBACK_ROUNDS == 3

    def test_max_remediation_rounds(self) -> None:
        assert DEFAULT_MAX_REMEDIATION_ROUNDS == 2

    def test_verify_layers(self) -> None:
        assert DEFAULT_VERIFY_LAYERS == (
            "structural",
            "semantic",
            "adversarial",
            "policy",
        )

    def test_story_types_is_tuple(self) -> None:
        assert isinstance(DEFAULT_STORY_TYPES, tuple)

    def test_verify_layers_is_tuple(self) -> None:
        assert isinstance(DEFAULT_VERIFY_LAYERS, tuple)
