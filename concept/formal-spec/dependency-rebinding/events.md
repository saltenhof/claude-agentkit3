---
id: formal.dependency-rebinding.events
title: Dependency Rebinding Events
status: active
doc_kind: spec
context: dependency-rebinding
spec_kind: event-set
version: 1
prose_refs:
  - concept/technical-design/54_story_split_service_scope_explosion.md
  - concept/technical-design/91_api_event_katalog.md
---

# Dependency Rebinding Events

Diese Events bilden den Rebinding-Subflow fachlich ab.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.dependency-rebinding.events
schema_version: 1
kind: event-set
context: dependency-rebinding
events:
  - id: dependency-rebinding.event.rebinding.started
    producer: dependency-rebinding
    role: lifecycle
    payload:
      required:
        - rebinding_id
        - split_id
        - source_story_id
  - id: dependency-rebinding.event.rebinding.validated
    producer: dependency-rebinding
    role: lifecycle
    payload:
      required:
        - rebinding_id
        - split_id
  - id: dependency-rebinding.event.edge.rebound
    producer: dependency-rebinding
    role: lifecycle
    payload:
      required:
        - rebinding_id
        - dependent_story_id
        - old_dependency_story_id
        - new_dependency_story_ids
  - id: dependency-rebinding.event.rebinding.completed
    producer: dependency-rebinding
    role: lifecycle
    payload:
      required:
        - rebinding_id
        - split_id
  - id: dependency-rebinding.event.rebinding.rejected
    producer: dependency-rebinding
    role: lifecycle
    payload:
      required:
        - rebinding_id
        - split_id
        - rejection_reason
```
<!-- FORMAL-SPEC:END -->
