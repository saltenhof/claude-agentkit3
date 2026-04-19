---
id: formal.story-exit.events
title: Story Exit Events
status: active
doc_kind: spec
context: story-exit
spec_kind: event-set
version: 1
prose_refs:
  - concept/technical-design/58_story_exit_human_takeover_handoff.md
  - concept/technical-design/91_api_event_katalog.md
---

# Story Exit Events

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-exit.events
schema_version: 1
kind: event-set
context: story-exit
events:
  - id: story-exit.event.story_exit_requested
    producer: human_cli
  - id: story-exit.event.story_exit_gate_passed
    producer: admin_service
  - id: story-exit.event.story_exit_rejected
    producer: admin_service
  - id: story-exit.event.story_exit_completed
    producer: admin_service
  - id: story-exit.event.story_exit_binding_revoked
    producer: admin_service
```
<!-- FORMAL-SPEC:END -->
