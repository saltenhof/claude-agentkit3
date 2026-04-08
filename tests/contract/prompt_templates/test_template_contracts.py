"""Contract tests for prompt templates.

These tests protect the stability of prompt templates. If a template
changes, these tests break -- forcing conscious review of the change.

Contract tests are cheap to run (no I/O, no network) but catch
regressions in template structure, sentinel markers, and render
compatibility.
"""

from __future__ import annotations

import re

import pytest

from agentkit.prompting.sentinels import SENTINEL_PATTERN, extract_sentinel
from agentkit.prompting.templates import TEMPLATES

# Sentinel in template form (before rendering): [SENTINEL:<name>-v<N>:{story_id}]
_TEMPLATE_SENTINEL_RE = re.compile(
    r"\[SENTINEL:[a-z0-9-]+-v\d+:\{story_id\}\]"
)

# All placeholders used across all templates
_STANDARD_PLACEHOLDERS: dict[str, str] = {
    "story_id": "TEST-001",
    "title": "Test Story Title",
    "issue_nr": "42",
    "mode": "execution",
    "size": "M",
    "body": "Test body content.",
    "project_root": "/tmp/test-project",
    "round_nr": "1",
    "feedback": "No findings.",
}


@pytest.mark.contract
class TestTemplateContracts:
    """Contract tests verifying template structure stability."""

    @pytest.mark.parametrize("name", sorted(TEMPLATES.keys()))
    def test_every_template_has_sentinel(self, name: str) -> None:
        """Every template must contain exactly one SENTINEL marker."""
        content = TEMPLATES[name]
        matches = _TEMPLATE_SENTINEL_RE.findall(content)
        assert len(matches) == 1, (
            f"Template '{name}' has {len(matches)} sentinel markers, "
            f"expected exactly 1"
        )

    @pytest.mark.parametrize("name", sorted(TEMPLATES.keys()))
    def test_sentinel_name_matches_template_name(self, name: str) -> None:
        """The sentinel's template-name component must match the registry key."""
        content = TEMPLATES[name]
        # Render with story_id so SENTINEL_PATTERN can match
        rendered = content.format_map(_STANDARD_PLACEHOLDERS)
        data = extract_sentinel(rendered)
        assert data is not None, (
            f"Template '{name}' rendered sentinel not extractable"
        )
        assert data["template"] == name, (
            f"Template '{name}' sentinel says '{data['template']}'"
        )

    @pytest.mark.parametrize("name", sorted(TEMPLATES.keys()))
    def test_every_template_has_story_id_placeholder(self, name: str) -> None:
        """Every template must reference {{story_id}} as a format placeholder."""
        assert "{story_id}" in TEMPLATES[name], (
            f"Template '{name}' does not contain {{story_id}} placeholder"
        )

    def test_template_registry_has_all_required_templates(self) -> None:
        """Template registry must contain all required templates."""
        required = {
            "worker-implementation",
            "worker-bugfix",
            "worker-concept",
            "worker-research",
            "worker-exploration",
            "worker-remediation",
        }
        actual = set(TEMPLATES.keys())
        missing = required - actual
        assert not missing, (
            f"Missing required templates: {sorted(missing)}"
        )

    @pytest.mark.parametrize("name", sorted(TEMPLATES.keys()))
    def test_template_renders_without_error(self, name: str) -> None:
        """Every template must render with standard placeholders without KeyError."""
        content = TEMPLATES[name]
        # Must not raise KeyError or similar
        rendered = content.format_map(_STANDARD_PLACEHOLDERS)
        assert len(rendered) > 0, (
            f"Template '{name}' rendered to empty string"
        )

    @pytest.mark.parametrize("name", sorted(TEMPLATES.keys()))
    def test_rendered_sentinel_is_extractable(self, name: str) -> None:
        """After rendering, the sentinel must be extractable by SENTINEL_PATTERN."""
        content = TEMPLATES[name]
        rendered = content.format_map(_STANDARD_PLACEHOLDERS)
        match = SENTINEL_PATTERN.search(rendered)
        assert match is not None, (
            f"Template '{name}': rendered sentinel not matched by SENTINEL_PATTERN"
        )
        assert match.group("story_id") == "TEST-001"

    @pytest.mark.parametrize("name", sorted(TEMPLATES.keys()))
    def test_template_starts_with_markdown_header(self, name: str) -> None:
        """Every template must start with a markdown header (# ...)."""
        content = TEMPLATES[name]
        assert content.startswith("# "), (
            f"Template '{name}' does not start with '# '"
        )
