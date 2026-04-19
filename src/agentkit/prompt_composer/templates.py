"""Prompt templates loaded from internal resource files."""

from __future__ import annotations

from agentkit.prompt_composer.resources import load_prompt_template


def _build_templates() -> dict[str, str]:
    names = (
        "worker-implementation",
        "worker-bugfix",
        "worker-concept",
        "worker-research",
        "worker-exploration",
        "worker-remediation",
        "qa-semantic-review",
        "qa-adversarial-review",
    )
    return {name: load_prompt_template(name) for name in names}


TEMPLATES = _build_templates()

__all__ = ["TEMPLATES"]
