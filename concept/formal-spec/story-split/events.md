---
id: formal.story-split.events
title: Story Split Events
status: active
doc_kind: spec
context: story-split
spec_kind: event-set
version: 1
prose_refs:
  - concept/technical-design/54_story_split_service_scope_explosion.md
  - concept/technical-design/91_api_event_katalog.md
---

# Story Split Events

Diese Events bilden die administrative Split-Sequenz fachlich ab.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-split.events
schema_version: 1
kind: event-set
context: story-split
events:
  - id: story-split.event.split.requested
    producer: story-split
    role: lifecycle
    payload:
      required:
        - split_id
        - source_story_id
        - plan_ref
  - id: story-split.event.split.started
    producer: story-split
    role: lifecycle
    payload:
      required:
        - split_id
        - source_story_id
  - id: story-split.event.split.fenced
    producer: story-split
    role: lifecycle
    payload:
      required:
        - split_id
        - source_story_id
  - id: story-split.event.split.quiesced
    producer: story-split
    role: lifecycle
    payload:
      required:
        - split_id
        - source_story_id
  - id: story-split.event.split.successors_created
    producer: story-split
    role: lifecycle
    payload:
      required:
        - split_id
        - successor_story_ids
  - id: story-split.event.split.dependencies_rebound
    producer: story-split
    role: lifecycle
    payload:
      required:
        - split_id
        - dependency_rebinding_count
  - id: story-split.event.split.source_cancelled
    producer: story-split
    role: lifecycle
    payload:
      required:
        - split_id
        - source_story_id
  - id: story-split.event.split.completed
    producer: story-split
    role: lifecycle
    payload:
      required:
        - split_id
        - source_story_id
        - successor_story_ids
  - id: story-split.event.split.failed
    producer: story-split
    role: lifecycle
    payload:
      required:
        - split_id
        - source_story_id
        - failure_reason
```
<!-- FORMAL-SPEC:END -->
