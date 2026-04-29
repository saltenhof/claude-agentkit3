---
id: formal.story-reset.scenarios
title: Story Reset Scenarios
status: active
doc_kind: spec
context: story-reset
spec_kind: scenario-set
version: 1
prose_refs:
  - concept/technical-design/53_story_reset_service_recovery_flow.md
  - concept/technical-design/04_betrieb_monitoring_audit_runbooks.md
---

# Story Reset Scenarios

Diese Traces pruefen den offiziellen Story-Reset als administrativen
Recovery-Pfad.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-reset.scenarios
schema_version: 1
kind: scenario-set
context: story-reset
scenarios:
  - id: story-reset.scenario.happy-path
    start:
      status: story-reset.status.requested
    trace:
      - command: story-reset.command.execute
    expected_end:
      status: story-reset.status.completed
    requires:
      - story-reset.invariant.completed_reset_leaves_no_resumable_run
      - story-reset.invariant.story_anchor_remains
  - id: story-reset.scenario.mid-reset-failure
    start:
      status: story-reset.status.runtime_purged
    trace:
      - command: story-reset.command.execute
    expected_end:
      status: story-reset.status.reset_failed
  - id: story-reset.scenario.resume-after-reset-failed
    start:
      status: story-reset.status.reset_failed
    trace:
      - command: story-reset.command.resume
    expected_end:
      status: story-reset.status.completed
    requires:
      - story-reset.invariant.reset_failed_needs_same_reset_id
```
<!-- FORMAL-SPEC:END -->
