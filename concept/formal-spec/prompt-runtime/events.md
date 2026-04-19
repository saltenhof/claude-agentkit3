---
id: formal.prompt-runtime.events
title: Prompt Runtime Events
status: active
doc_kind: spec
context: prompt-runtime
spec_kind: event-set
version: 1
prose_refs:
  - concept/technical-design/44_prompt_bundles_materialization_audit.md
---

# Prompt Runtime Events

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.prompt-runtime.events
schema_version: 1
kind: event-set
context: prompt-runtime
events:
  - id: prompt-runtime.event.binding.resolved
    producer: prompt_runtime
    payload:
      - project_key
      - prompt_bundle_version
      - binding_digest
    role: project binding for future runs resolved
  - id: prompt-runtime.event.run.prompt_bundle_pinned
    producer: prompt_runtime
    payload:
      - run_id
      - resolved_prompt_bundle_version
      - resolved_prompt_bundle_manifest_digest
    role: active run pinned one immutable prompt bundle
  - id: prompt-runtime.event.prompt.instance_materialized
    producer: prompt_runtime
    payload:
      - run_id
      - prompt_instance_id
      - logical_prompt_id
      - render_mode
      - output_sha256
      - artifact_path
    role: run-scoped prompt file materialized for agent consumption
  - id: prompt-runtime.event.prompt.rendered
    producer: prompt_runtime
    payload:
      - run_id
      - prompt_instance_id
      - logical_prompt_id
      - render_mode
      - output_sha256
    role: evaluator prompt resolved from pinned bundle and rendered for use
  - id: prompt-runtime.event.prompt.stale_cache_detected
    producer: prompt_runtime
    payload:
      - project_key
      - offending_path
      - reason
    role: mutable local prompt copy or stale prompt cache was rejected
```
<!-- FORMAL-SPEC:END -->
