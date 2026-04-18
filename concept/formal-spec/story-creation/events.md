---
id: formal.story-creation.events
title: Story Creation Events
status: active
doc_kind: spec
context: story-creation
spec_kind: event-set
version: 1
prose_refs:
  - concept/technical-design/21_story_creation_pipeline.md
  - concept/technical-design/91_api_event_katalog.md
---

# Story Creation Events

Diese Events bilden den Story-Creation-Pfad fachlich ab.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-creation.events
schema_version: 1
kind: event-set
context: story-creation
events:
  - id: story-creation.event.creation.started
    producer: story-creation
    role: lifecycle
    payload:
      required:
        - draft_id
        - project_key
  - id: story-creation.event.story.validated
    producer: story-creation
    role: lifecycle
    payload:
      required:
        - draft_id
        - project_key
  - id: story-creation.event.story.classified
    producer: story-creation
    role: lifecycle
    payload:
      required:
        - story_type
        - repo_affinity
  - id: story-creation.event.story.backlog_created
    producer: story-creation
    role: lifecycle
    payload:
      required:
        - story_id
        - issue_number
        - project_status
  - id: story-creation.event.story_md.exported
    producer: story-creation
    role: lifecycle
    payload:
      required:
        - story_id
        - story_md_path
  - id: story-creation.event.story_md.indexed
    producer: story-creation
    role: lifecycle
    payload:
      required:
        - story_id
  - id: story-creation.event.story.approved
    producer: human
    role: lifecycle
    payload:
      required:
        - story_id
        - project_status
  - id: story-creation.event.creation.rejected
    producer: story-creation
    role: lifecycle
    payload:
      required:
        - draft_id
        - reason
```
<!-- FORMAL-SPEC:END -->
