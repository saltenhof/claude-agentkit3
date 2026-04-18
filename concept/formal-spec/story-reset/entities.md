---
id: formal.story-reset.entities
title: Story Reset Entities
status: active
doc_kind: spec
context: story-reset
spec_kind: entity-set
version: 1
prose_refs:
  - concept/technical-design/53_story_reset_service_recovery_flow.md
  - concept/technical-design/17_fachliches_datenmodell_ownership.md
  - concept/technical-design/18_relationales_abbildungsmodell_postgres.md
---

# Story Reset Entities

Der Reset-Pfad braucht wenige, aber dauerhafte Kernentitaeten.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-reset.entities
schema_version: 1
kind: entity-set
context: story-reset
entities:
  - id: story-reset.entity.reset-record
    identity_key: reset_id
    attributes:
      - reset_id
      - project_key
      - story_id
      - requested_by
      - reason
      - escalation_ref
      - requested_at
      - status
  - id: story-reset.entity.story-anchor
    identity_key: story_id
    attributes:
      - story_id
      - project_key
      - story_exists
      - story_context_retained
```
<!-- FORMAL-SPEC:END -->
