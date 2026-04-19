---
id: formal.prompt-runtime.invariants
title: Prompt Runtime Invariants
status: active
doc_kind: spec
context: prompt-runtime
spec_kind: invariant-set
version: 1
prose_refs:
  - concept/technical-design/44_prompt_bundles_materialization_audit.md
---

# Prompt Runtime Invariants

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.prompt-runtime.invariants
schema_version: 1
kind: invariant-set
context: prompt-runtime
invariants:
  - id: prompt-runtime.invariant.canonical_prompt_source_is_immutable_system_bundle
    scope: source-of-truth
    rule: productive prompt templates may exist canonically only in immutable systemwide prompt bundles
  - id: prompt-runtime.invariant.project_prompt_binding_is_symlink_only
    scope: binding
    rule: project-local static prompt exposure is implemented only through symlink-style bindings to one concrete immutable bundle version and never by copying canonical prompt sources
  - id: prompt-runtime.invariant.project_local_prompt_copy_is_never_authoritative
    scope: project-runtime
    rule: project-local prompt files or caches may be used only as run-scoped instances and never as authoritative canonical source
  - id: prompt-runtime.invariant.active_run_uses_one_pinned_bundle
    scope: run
    rule: each active run must pin exactly one resolved prompt bundle version and manifest digest before the first prompt invocation
  - id: prompt-runtime.invariant.binding_changes_affect_only_future_runs
    scope: rebind
    rule: changing a project prompt binding may only affect future runs and never silently mutate prompts of an already pinned active run
  - id: prompt-runtime.invariant.every_agent_prompt_consumption_uses_run_scoped_instance
    scope: agent-consumption
    rule: every agent-facing prompt consumption must use a run-scoped prompt instance path derived from the pinned bundle
  - id: prompt-runtime.invariant.prompt_usage_is_auditable_to_exact_template_and_output_digest
    scope: audit
    rule: every productive prompt usage must be attributable to prompt bundle version manifest digest template digest and final output digest
  - id: prompt-runtime.invariant.referenced_prompt_bundles_are_not_garbage_collected_while_active_or_retained
    scope: retention
    rule: a prompt bundle referenced by an active run or retained audit record must not be garbage collected
```
<!-- FORMAL-SPEC:END -->
