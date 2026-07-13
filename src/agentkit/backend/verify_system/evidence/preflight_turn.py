"""Preflight turn orchestration for review evidence enrichment."""

from __future__ import annotations

from agentkit.backend.prompt_runtime.resources import load_prompt_template

PREFLIGHT_TEMPLATE_NAME = "review-preflight"
PREFLIGHT_TEMPLATE_VERSION = 1


def render_preflight_prompt(bundle_manifest_header: str, story_id: str) -> str:
    """Render the registered review-preflight prompt template."""
    template = load_prompt_template(PREFLIGHT_TEMPLATE_NAME)
    return template.format(
        story_id=story_id,
        BUNDLE_MANIFEST_HEADER=bundle_manifest_header,
    )


__all__ = [
    "PREFLIGHT_TEMPLATE_NAME",
    "PREFLIGHT_TEMPLATE_VERSION",
    "render_preflight_prompt",
]
