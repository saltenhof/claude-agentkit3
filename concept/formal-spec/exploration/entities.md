---
id: formal.exploration.entities
title: Exploration Entities
status: active
doc_kind: spec
context: exploration
spec_kind: entity-set
version: 1
prose_refs:
  - concept/technical-design/23_modusermittlung_exploration_change_frame.md
  - concept/technical-design/25_mandatsgrenzen_feindesign_autonomie.md
---

# Exploration Entities

Die Exploration benoetigt wenige fachlich stabile Kernentitaeten.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.exploration.entities
schema_version: 1
kind: entity-set
context: exploration
entities:
  - id: exploration.entity.payload
    identity_key: story_id
    attributes:
      - story_id
      - project_key
      - gate_status
      - review_rounds
      - current_draft_ref
      - frozen
  - id: exploration.entity.design-draft
    identity_key: draft_ref
    attributes:
      - draft_ref
      - story_id
      - created_at
      - frozen
      - finding_refs
  - id: exploration.entity.mandate-finding
    identity_key: finding_id
    attributes:
      - finding_id
      - story_id
      - class
      - action_ref
      - source_review_ref
```
<!-- FORMAL-SPEC:END -->
