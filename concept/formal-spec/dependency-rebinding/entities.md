---
id: formal.dependency-rebinding.entities
title: Dependency Rebinding Entities
status: active
doc_kind: spec
context: dependency-rebinding
spec_kind: entity-set
version: 1
prose_refs:
  - concept/technical-design/54_story_split_service_scope_explosion.md
  - concept/technical-design/17_fachliches_datenmodell_ownership.md
  - concept/technical-design/18_relationales_abbildungsmodell_postgres.md
---

# Dependency Rebinding Entities

Der Rebinding-Pfad benoetigt nur wenige Kernentitaeten.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.dependency-rebinding.entities
schema_version: 1
kind: entity-set
context: dependency-rebinding
entities:
  - id: dependency-rebinding.entity.rebinding-attempt
    identity_key: rebinding_id
    attributes:
      - rebinding_id
      - split_id
      - source_story_id
      - status
      - requested_at
  - id: dependency-rebinding.entity.dependency-edge
    identity_key: edge_id
    attributes:
      - edge_id
      - dependent_story_id
      - dependency_story_id
      - relation_type
      - active
  - id: dependency-rebinding.entity.rebinding-plan-entry
    identity_key: plan_entry_id
    attributes:
      - plan_entry_id
      - split_id
      - dependent_story_id
      - old_dependency_story_id
      - new_dependency_story_ids
      - selection_policy
```
<!-- FORMAL-SPEC:END -->
