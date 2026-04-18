---
id: formal.story-reset.events
title: Story Reset Events
status: active
doc_kind: spec
context: story-reset
spec_kind: event-set
version: 1
prose_refs:
  - concept/technical-design/53_story_reset_service_recovery_flow.md
  - concept/technical-design/91_api_event_katalog.md
---

# Story Reset Events

Diese Events bilden die Reset-Sequenz fachlich ab.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-reset.events
schema_version: 1
kind: event-set
context: story-reset
events:
  - id: story-reset.event.reset.requested
    producer: story-reset
    role: lifecycle
    payload:
      required:
        - reset_id
        - story_id
        - reason
  - id: story-reset.event.reset.started
    producer: story-reset
    role: lifecycle
    payload:
      required:
        - reset_id
        - story_id
  - id: story-reset.event.reset.fenced
    producer: story-reset
    role: lifecycle
    payload:
      required:
        - reset_id
        - story_id
  - id: story-reset.event.reset.quiesced
    producer: story-reset
    role: lifecycle
    payload:
      required:
        - reset_id
        - story_id
  - id: story-reset.event.reset.runtime_purged
    producer: story-reset
    role: lifecycle
    payload:
      required:
        - reset_id
        - story_id
  - id: story-reset.event.reset.read_models_purged
    producer: story-reset
    role: lifecycle
    payload:
      required:
        - reset_id
        - story_id
  - id: story-reset.event.reset.workspace_cleared
    producer: story-reset
    role: lifecycle
    payload:
      required:
        - reset_id
        - story_id
  - id: story-reset.event.reset.resumed
    producer: story-reset
    role: recovery
    payload:
      required:
        - reset_id
        - story_id
  - id: story-reset.event.reset.completed
    producer: story-reset
    role: lifecycle
    payload:
      required:
        - reset_id
        - story_id
  - id: story-reset.event.reset.failed
    producer: story-reset
    role: lifecycle
    payload:
      required:
        - reset_id
        - story_id
        - failure_reason
```
<!-- FORMAL-SPEC:END -->
