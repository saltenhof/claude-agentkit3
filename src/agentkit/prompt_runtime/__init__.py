"""Prompt runtime component namespace."""

from __future__ import annotations

from agentkit.prompt_runtime.audit import (
    PromptAuditHash,
    build_prompt_audit_envelope,
    compute_prompt_audit_hash,
)
from agentkit.prompt_runtime.composer import (
    ComposeConfig,
    ComposedPrompt,
    MaterializedPromptInstance,
    StaticMaterializedPromptInstance,
    WorkerWorktreeContext,
    build_worker_worktree_context,
    compose_named_prompt,
    compose_prompt,
    materialize_static_prompt_instance,
    write_prompt,
    write_prompt_instance,
)
from agentkit.prompt_runtime.pins import (
    PromptRunPin,
    ensure_prompt_run_pin,
    ensure_run_prompt_pin_present,
    initialize_prompt_run_pin,
    load_prompt_run_pin,
    resolve_run_prompt_binding,
)
from agentkit.prompt_runtime.register import register_prompt_runtime_producers
from agentkit.prompt_runtime.resources import (
    PromptBundleBinding,
    load_prompt_template,
    prompt_bundle_id,
    prompt_bundle_version,
    prompt_manifest_sha256,
    prompt_template_path,
    prompt_template_relpath,
    prompt_template_sha256,
    reject_stale_local_prompt_cache,
    resolve_bootstrap_prompt_binding,
    resolve_pinned_prompt_binding,
    resolve_project_prompt_binding,
)
from agentkit.prompt_runtime.runtime import PromptInstance, PromptRuntime
from agentkit.prompt_runtime.selectors import select_template_name
from agentkit.prompt_runtime.sentinels import (
    extract_sentinel,
    make_sentinel,
    validate_sentinel,
)
from agentkit.prompt_runtime.templates import TEMPLATES

__all__ = [
    "TEMPLATES",
    "ComposeConfig",
    "ComposedPrompt",
    "MaterializedPromptInstance",
    "PromptAuditHash",
    "PromptInstance",
    "PromptRuntime",
    "StaticMaterializedPromptInstance",
    "WorkerWorktreeContext",
    "build_prompt_audit_envelope",
    "build_worker_worktree_context",
    "compose_named_prompt",
    "compute_prompt_audit_hash",
    "PromptBundleBinding",
    "PromptRunPin",
    "compose_prompt",
    "ensure_prompt_run_pin",
    "ensure_run_prompt_pin_present",
    "extract_sentinel",
    "initialize_prompt_run_pin",
    "load_prompt_template",
    "load_prompt_run_pin",
    "make_sentinel",
    "materialize_static_prompt_instance",
    "prompt_bundle_id",
    "prompt_manifest_sha256",
    "prompt_bundle_version",
    "prompt_template_path",
    "prompt_template_relpath",
    "prompt_template_sha256",
    "register_prompt_runtime_producers",
    "reject_stale_local_prompt_cache",
    "resolve_bootstrap_prompt_binding",
    "resolve_pinned_prompt_binding",
    "resolve_project_prompt_binding",
    "resolve_run_prompt_binding",
    "select_template_name",
    "validate_sentinel",
    "write_prompt",
    "write_prompt_instance",
]
