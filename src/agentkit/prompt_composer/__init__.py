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
from agentkit.prompt_composer.pins import (
    PromptRunPin,
    ensure_prompt_run_pin,
    load_prompt_run_pin,
)
from agentkit.prompt_composer.resources import (
    load_prompt_template,
    prompt_bundle_id,
    prompt_bundle_version,
    prompt_manifest_sha256,
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
    "PromptRunPin",
    "compose_prompt",
    "ensure_prompt_run_pin",
    "extract_sentinel",
    "load_prompt_template",
    "load_prompt_run_pin",
    "make_sentinel",
    "prompt_bundle_id",
    "prompt_manifest_sha256",
    "prompt_bundle_version",
    "prompt_template_path",
    "prompt_template_relpath",
    "prompt_template_sha256",
    "select_template_name",
    "validate_sentinel",
    "write_prompt",
    "write_prompt_instance",
]
