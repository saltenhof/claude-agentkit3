---
id: formal.story-reset.invariants
title: Story Reset Invariants
status: active
doc_kind: spec
context: story-reset
spec_kind: invariant-set
version: 1
prose_refs:
  - concept/technical-design/53_story_reset_service_recovery_flow.md
  - concept/technical-design/20_workflow_engine_state_machine.md
  - concept/technical-design/52_betrieb_monitoring_audit_runbooks.md
---

# Story Reset Invariants

Diese Invarianten definieren den zulaessigen Reset-Pfad fuer korrupt
gewordene Umsetzungen.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-reset.invariants
schema_version: 1
kind: invariant-set
context: story-reset
invariants:
  - id: story-reset.invariant.reset_requires_official_authorization
    scope: command
    requires:
      - story-workflow.status.escalated
    rule: reset execution is legal only after an explicit human CLI decision, a durable reset record, and no competing administrative operation for the same story
  - id: story-reset.invariant.fence_before_purge
    scope: process
    rule: reset must fence the story before any destructive purge step starts
  - id: story-reset.invariant.runtime_purge_precedes_read_model_purge
    scope: process
    rule: runtime state must be purged before read models and analytics derived from that runtime are removed
  - id: story-reset.invariant.completed_reset_leaves_no_resumable_run
    scope: outcome
    rule: after completed reset there is no resumable run, no active lock, no active worker lease, and no active retry or resume residue for that story
  - id: story-reset.invariant.story_anchor_remains
    scope: outcome
    rule: reset keeps the story as a business work item while removing the corrupted execution epoch
  - id: story-reset.invariant.reset_failed_needs_same_reset_id
    scope: recovery
    rule: RESET_FAILED may only continue through the same reset_id resume path and never through a normal workflow resume
```
<!-- FORMAL-SPEC:END -->
