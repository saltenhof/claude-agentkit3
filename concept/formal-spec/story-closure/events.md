---
id: formal.story-closure.events
title: Story Closure Events
status: active
doc_kind: spec
context: story-closure
spec_kind: event-set
version: 1
prose_refs:
  - concept/technical-design/29_closure_sequence.md
  - concept/technical-design/04_betrieb_monitoring_audit_runbooks.md
  - concept/technical-design/91_api_event_katalog.md
---

# Story Closure Events

Diese Events bilden den offiziellen Closure-Pfad und seine
Ausnahmesituationen fachlich ab.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-closure.events
schema_version: 1
kind: event-set
context: story-closure
events:
  - id: story-closure.event.closure.started
    producer: story-closure
    role: lifecycle
    payload:
      required:
        - closure_id
        - story_id
  - id: story-closure.event.policy.ff_only_selected
    producer: story-closure
    role: policy
    payload:
      required:
        - closure_id
        - story_id
        - merge_policy
  - id: story-closure.event.policy.no_ff_selected
    producer: story-closure
    role: policy
    payload:
      required:
        - closure_id
        - story_id
        - merge_policy
  - id: story-closure.event.policy_fallback.used
    producer: story-closure
    role: recovery
    payload:
      required:
        - closure_id
        - story_id
        - fallback_reason
  - id: story-closure.event.story_branch.pushed
    producer: story-closure
    role: lifecycle
    payload:
      required:
        - closure_id
        - story_id
  - id: story-closure.event.merge.attempted
    producer: story-closure
    role: lifecycle
    payload:
      required:
        - closure_id
        - story_id
        - merge_policy
  - id: story-closure.event.merge.completed
    producer: story-closure
    role: lifecycle
    payload:
      required:
        - closure_id
        - story_id
        - merge_policy
  - id: story-closure.event.merge.rejected
    producer: story-closure
    role: lifecycle
    payload:
      required:
        - closure_id
        - story_id
        - rejection_reason
  - id: story-closure.event.issue.closed
    producer: story-closure
    role: lifecycle
    payload:
      required:
        - closure_id
        - story_id
  - id: story-closure.event.manual_git.rejected
    producer: branch-guard
    role: governance
    payload:
      required:
        - story_id
        - rejected_operation
  - id: story-closure.event.closure.completed
    producer: story-closure
    role: lifecycle
    payload:
      required:
        - closure_id
        - story_id
  - id: story-closure.event.closure.escalated
    producer: story-closure
    role: lifecycle
    payload:
      required:
        - closure_id
        - story_id
        - escalation_reason
```
<!-- FORMAL-SPEC:END -->
