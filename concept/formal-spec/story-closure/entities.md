---
id: formal.story-closure.entities
title: Story Closure Entities
status: active
doc_kind: spec
context: story-closure
spec_kind: entity-set
version: 1
prose_refs:
  - concept/technical-design/17_fachliches_datenmodell_ownership.md
  - concept/technical-design/18_relationales_abbildungsmodell_postgres.md
  - concept/technical-design/29_closure_sequence.md
---

# Story Closure Entities

Der Closure-Pfad braucht nur wenige, aber stabile Kernentitaeten.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-closure.entities
schema_version: 1
kind: entity-set
context: story-closure
entities:
  - id: story-closure.entity.closure-attempt
    identity_key: closure_id
    attributes:
      - closure_id
      - project_key
      - story_id
      - merge_policy
      - current_status
      - requested_at
      - resumed_from_status
  - id: story-closure.entity.branch-binding
    identity_key: story_id
    attributes:
      - project_key
      - story_id
      - story_branch_ref
      - target_branch_ref
      - remote_tracking_ref
      - story_branch_pushed
      - merge_done
```
<!-- FORMAL-SPEC:END -->
