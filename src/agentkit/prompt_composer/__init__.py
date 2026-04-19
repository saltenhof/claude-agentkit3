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
    initialize_prompt_run_pin,
    load_prompt_run_pin,
    resolve_run_prompt_binding,
)
from agentkit.prompt_composer.resources import (
    PromptBundleBinding,
    load_prompt_template,
    prompt_bundle_id,
    prompt_bundle_version,
    prompt_manifest_sha256,
    prompt_template_path,
    prompt_template_relpath,
    prompt_template_sha256,
    resolve_bootstrap_prompt_binding,
    resolve_project_prompt_binding,
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
    "PromptBundleBinding",
    "PromptRunPin",
    "compose_prompt",
    "ensure_prompt_run_pin",
    "extract_sentinel",
    "initialize_prompt_run_pin",
    "load_prompt_template",
    "load_prompt_run_pin",
    "make_sentinel",
    "prompt_bundle_id",
    "prompt_manifest_sha256",
    "prompt_bundle_version",
    "prompt_template_path",
    "prompt_template_relpath",
    "prompt_template_sha256",
    "resolve_bootstrap_prompt_binding",
    "resolve_project_prompt_binding",
    "resolve_run_prompt_binding",
    "select_template_name",
    "validate_sentinel",
    "write_prompt",
    "write_prompt_instance",
]
