---
id: formal.prompt-runtime.commands
title: Prompt Runtime Commands
status: active
doc_kind: spec
context: prompt-runtime
spec_kind: command-set
version: 1
prose_refs:
  - concept/technical-design/44_prompt_bundles_materialization_audit.md
---

# Prompt Runtime Commands

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.prompt-runtime.commands
schema_version: 1
kind: command-set
context: prompt-runtime
commands:
  - id: prompt-runtime.command.resolve-project-prompt-binding
    signature: internal resolve and validate project prompt binding lock for future run selection
    allowed_statuses:
      - prompt-runtime.status.binding_resolved
      - prompt-runtime.status.run_pinned
    emits:
      - prompt-runtime.event.binding.resolved
  - id: prompt-runtime.command.pin-run-prompt-bundle
    signature: internal pin resolved prompt bundle version and manifest digest onto run and persist a run-scoped pin record
    allowed_statuses:
      - prompt-runtime.status.binding_resolved
    requires:
      - prompt-runtime.invariant.active_run_uses_one_pinned_bundle
    emits:
      - prompt-runtime.event.run.prompt_bundle_pinned
  - id: prompt-runtime.command.materialize-agent-prompt-instance
    signature: internal materialize run-scoped prompt file for agent consumption
    allowed_statuses:
      - prompt-runtime.status.run_pinned
    requires:
      - prompt-runtime.invariant.every_agent_prompt_consumption_uses_run_scoped_instance
    emits:
      - prompt-runtime.event.prompt.instance_materialized
  - id: prompt-runtime.command.render-evaluator-prompt
    signature: internal resolve prompt from pinned bundle for evaluator execution
    allowed_statuses:
      - prompt-runtime.status.run_pinned
    emits:
      - prompt-runtime.event.prompt.rendered
  - id: prompt-runtime.command.reject-stale-local-prompt-cache
    signature: internal reject local mutable prompt source or stale cache
    allowed_statuses:
      - prompt-runtime.status.binding_resolved
      - prompt-runtime.status.run_pinned
    requires:
      - prompt-runtime.invariant.project_local_prompt_copy_is_never_authoritative
    emits:
      - prompt-runtime.event.prompt.stale_cache_detected
```
<!-- FORMAL-SPEC:END -->
