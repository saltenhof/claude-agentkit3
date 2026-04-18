---
id: formal.story-split.entities
title: Story Split Entities
status: active
doc_kind: spec
context: story-split
spec_kind: entity-set
version: 1
prose_refs:
  - concept/technical-design/54_story_split_service_scope_explosion.md
  - concept/technical-design/17_fachliches_datenmodell_ownership.md
  - concept/technical-design/18_relationales_abbildungsmodell_postgres.md
---

# Story Split Entities

Der Split-Pfad braucht nur wenige, aber stabile Kernentitaeten.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-split.entities
schema_version: 1
kind: entity-set
context: story-split
entities:
  - id: story-split.entity.split-record
    identity_key: split_id
    attributes:
      - split_id
      - project_key
      - source_story_id
      - requested_by
      - reason
      - plan_ref
      - status
  - id: story-split.entity.split-plan
    identity_key: plan_ref
    attributes:
      - source_story_id
      - successors
      - dependency_rebinding
      - story_lineage
  - id: story-split.entity.successor-story
    identity_key: story_id
    attributes:
      - story_id
      - title
      - scope_slice
      - initial_project_status
```
<!-- FORMAL-SPEC:END -->
