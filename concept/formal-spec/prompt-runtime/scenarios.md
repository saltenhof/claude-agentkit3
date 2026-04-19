---
id: formal.prompt-runtime.scenarios
title: Prompt Runtime Scenarios
status: active
doc_kind: spec
context: prompt-runtime
spec_kind: scenario-set
version: 1
prose_refs:
  - concept/technical-design/44_prompt_bundles_materialization_audit.md
---

# Prompt Runtime Scenarios

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.prompt-runtime.scenarios
schema_version: 1
kind: scenario-set
context: prompt-runtime
scenarios:
  - id: prompt-runtime.scenario.static_prompt_is_materialized_from_pinned_bundle
    start:
      status: prompt-runtime.status.binding_resolved
    trace:
      - command: prompt-runtime.command.pin-run-prompt-bundle
      - command: prompt-runtime.command.materialize-agent-prompt-instance
    expected_end:
      status: prompt-runtime.status.instance_materialized
    requires:
      - prompt-runtime.invariant.active_run_uses_one_pinned_bundle
      - prompt-runtime.invariant.project_prompt_binding_is_symlink_only
      - prompt-runtime.invariant.every_agent_prompt_consumption_uses_run_scoped_instance
  - id: prompt-runtime.scenario.dynamic_prompt_is_rendered_and_audited
    start:
      status: prompt-runtime.status.binding_resolved
    trace:
      - command: prompt-runtime.command.pin-run-prompt-bundle
      - command: prompt-runtime.command.materialize-agent-prompt-instance
    expected_end:
      status: prompt-runtime.status.instance_materialized
    requires:
      - prompt-runtime.invariant.prompt_usage_is_auditable_to_exact_template_and_output_digest
  - id: prompt-runtime.scenario.mid_run_rebind_does_not_mutate_active_run
    start:
      status: prompt-runtime.status.run_pinned
    trace:
      - command: prompt-runtime.command.resolve-project-prompt-binding
      - command: prompt-runtime.command.materialize-agent-prompt-instance
    expected_end:
      status: prompt-runtime.status.instance_materialized
    requires:
      - prompt-runtime.invariant.binding_changes_affect_only_future_runs
  - id: prompt-runtime.scenario.stale_project_prompt_cache_is_rejected
    start:
      status: prompt-runtime.status.binding_resolved
    trace:
      - command: prompt-runtime.command.reject-stale-local-prompt-cache
    expected_end:
      status: prompt-runtime.status.rejected
    requires:
      - prompt-runtime.invariant.project_local_prompt_copy_is_never_authoritative
```
<!-- FORMAL-SPEC:END -->
