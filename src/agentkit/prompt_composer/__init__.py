"""Prompt composer component namespace."""

from __future__ import annotations

from agentkit.prompt_composer.composer import (
    ComposeConfig,
    ComposedPrompt,
    compose_prompt,
    write_prompt,
)
from agentkit.prompt_composer.selectors import select_template_name
from agentkit.prompt_composer.sentinels import (
    extract_sentinel,
    make_sentinel,
    validate_sentinel,
)
from agentkit.prompt_composer.templates import TEMPLATES

__all__ = [
    "TEMPLATES",
    "ComposeConfig",
    "ComposedPrompt",
    "compose_prompt",
    "extract_sentinel",
    "make_sentinel",
    "select_template_name",
    "validate_sentinel",
    "write_prompt",
]
