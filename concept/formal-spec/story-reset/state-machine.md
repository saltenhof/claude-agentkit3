---
id: formal.story-reset.state-machine
title: Story Reset State Machine
status: active
doc_kind: spec
context: story-reset
spec_kind: state-machine
version: 1
prose_refs:
  - concept/technical-design/53_story_reset_service_recovery_flow.md
  - concept/technical-design/91_api_event_katalog.md
---

# Story Reset State Machine

Der Story-Reset ist ein checkpointfaehiger administrativer Flow, keine
normale Workflow-Phase.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-reset.state-machine
schema_version: 1
kind: state-machine
context: story-reset
states:
  - id: story-reset.status.requested
    initial: true
  - id: story-reset.status.fenced
  - id: story-reset.status.quiesced
  - id: story-reset.status.runtime_purged
  - id: story-reset.status.read_models_purged
  - id: story-reset.status.workspace_cleared
  - id: story-reset.status.completed
    terminal: true
  - id: story-reset.status.reset_failed
    terminal: true
transitions:
  - id: story-reset.transition.request_to_fenced
    from: story-reset.status.requested
    to: story-reset.status.fenced
    guard: story-reset.invariant.reset_requires_official_authorization
  - id: story-reset.transition.fenced_to_quiesced
    from: story-reset.status.fenced
    to: story-reset.status.quiesced
  - id: story-reset.transition.quiesced_to_runtime_purged
    from: story-reset.status.quiesced
    to: story-reset.status.runtime_purged
    guard: story-reset.invariant.fence_before_purge
  - id: story-reset.transition.runtime_purged_to_read_models_purged
    from: story-reset.status.runtime_purged
    to: story-reset.status.read_models_purged
    guard: story-reset.invariant.runtime_purge_precedes_read_model_purge
  - id: story-reset.transition.read_models_purged_to_workspace_cleared
    from: story-reset.status.read_models_purged
    to: story-reset.status.workspace_cleared
  - id: story-reset.transition.workspace_cleared_to_completed
    from: story-reset.status.workspace_cleared
    to: story-reset.status.completed
    guard: story-reset.invariant.completed_reset_leaves_no_resumable_run
  - id: story-reset.transition.any_to_reset_failed
    from: story-reset.status.requested
    to: story-reset.status.reset_failed
compound_rules:
  - id: story-reset.rule.reset_failed_is_not_runnable
    description: A reset in RESET_FAILED may only continue through the same reset_id resume path, never through normal workflow execution.
```
<!-- FORMAL-SPEC:END -->
