"""Prompt composer component namespace."""

from __future__ import annotations

from agentkit.prompt_composer.composer import (
    ComposeConfig,
    ComposedPrompt,
    MaterializedPromptInstance,
    compose_prompt,
    write_prompt,
    write_prompt_instance,
)
from agentkit.prompt_composer.resources import (
    load_prompt_template,
    prompt_bundle_id,
    prompt_bundle_version,
    prompt_template_path,
    prompt_template_relpath,
    prompt_template_sha256,
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
    "MaterializedPromptInstance",
    "compose_prompt",
    "extract_sentinel",
    "load_prompt_template",
    "make_sentinel",
    "prompt_bundle_id",
    "prompt_bundle_version",
    "prompt_template_path",
    "prompt_template_relpath",
    "prompt_template_sha256",
    "select_template_name",
    "validate_sentinel",
    "write_prompt",
    "write_prompt_instance",
]
