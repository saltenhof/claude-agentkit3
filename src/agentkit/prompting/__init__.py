"""Prompting subsystem -- prompt composition, selection, and sentinel tracking."""

from __future__ import annotations

from agentkit.prompting.composer import (
    ComposeConfig,
    ComposedPrompt,
    compose_prompt,
    write_prompt,
)
from agentkit.prompting.selectors import select_template_name
from agentkit.prompting.sentinels import (
    extract_sentinel,
    make_sentinel,
    validate_sentinel,
)
from agentkit.prompting.templates import TEMPLATES

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
