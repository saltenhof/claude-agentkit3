---
id: formal.prompt-runtime.state-machine
title: Prompt Runtime State Machine
status: active
doc_kind: spec
context: prompt-runtime
spec_kind: state-machine
version: 1
prose_refs:
  - concept/technical-design/44_prompt_bundles_materialization_audit.md
---

# Prompt Runtime State Machine

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.prompt-runtime.state-machine
schema_version: 1
kind: state-machine
context: prompt-runtime
states:
  - id: prompt-runtime.status.binding_resolved
  - id: prompt-runtime.status.run_pinned
  - id: prompt-runtime.status.instance_materialized
    terminal: true
  - id: prompt-runtime.status.rejected
    terminal: true
transitions:
  - id: prompt-runtime.transition.binding_resolved_to_run_pinned
    from: prompt-runtime.status.binding_resolved
    to: prompt-runtime.status.run_pinned
  - id: prompt-runtime.transition.run_pinned_to_run_pinned_rebind
    from: prompt-runtime.status.run_pinned
    to: prompt-runtime.status.run_pinned
  - id: prompt-runtime.transition.run_pinned_to_instance_materialized
    from: prompt-runtime.status.run_pinned
    to: prompt-runtime.status.instance_materialized
  - id: prompt-runtime.transition.binding_resolved_to_rejected
    from: prompt-runtime.status.binding_resolved
    to: prompt-runtime.status.rejected
  - id: prompt-runtime.transition.run_pinned_to_rejected
    from: prompt-runtime.status.run_pinned
    to: prompt-runtime.status.rejected
```
<!-- FORMAL-SPEC:END -->
