"""Tests for prompt template definitions."""

from __future__ import annotations

import pytest

from agentkit.prompting.templates import TEMPLATES


class TestTemplateRegistry:
    """Tests for the TEMPLATES registry."""

    def test_registry_has_at_least_six_entries(self) -> None:
        """TEMPLATES dict must contain at least 6 templates."""
        assert len(TEMPLATES) >= 6

    @pytest.mark.parametrize(
        "name",
        [
            "worker-implementation",
            "worker-bugfix",
            "worker-concept",
            "worker-research",
            "worker-exploration",
            "worker-remediation",
        ],
    )
    def test_expected_template_exists(self, name: str) -> None:
        """Each expected template name must be present in TEMPLATES."""
        assert name in TEMPLATES

    @pytest.mark.parametrize("name", list(TEMPLATES.keys()))
    def test_template_is_nonempty_string(self, name: str) -> None:
        """Every template must be a non-empty string."""
        template = TEMPLATES[name]
        assert isinstance(template, str)
        assert len(template.strip()) > 0

    @pytest.mark.parametrize("name", list(TEMPLATES.keys()))
    def test_template_contains_story_id_placeholder(self, name: str) -> None:
        """Every template must contain the {story_id} placeholder."""
        assert "{story_id}" in TEMPLATES[name]

    @pytest.mark.parametrize("name", list(TEMPLATES.keys()))
    def test_template_contains_sentinel_marker(self, name: str) -> None:
        """Every template must contain a [SENTINEL:...] marker."""
        assert "[SENTINEL:" in TEMPLATES[name]

    @pytest.mark.parametrize("name", list(TEMPLATES.keys()))
    def test_template_renders_with_dummy_data(self, name: str) -> None:
        """Every template must render without KeyError using dummy data.

        This verifies that no unknown placeholders exist in templates.
        """
        dummy_data = {
            "story_id": "TEST-001",
            "title": "Dummy Title",
            "issue_nr": "42",
            "mode": "execution",
            "size": "M",
            "body": "Dummy body text",
            "project_root": "/tmp/project",
            "round_nr": "1",
            "feedback": "No findings",
        }
        # Should not raise KeyError
        rendered = TEMPLATES[name].format_map(dummy_data)
        assert "TEST-001" in rendered
