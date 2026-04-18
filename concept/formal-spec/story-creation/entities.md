---
id: formal.story-creation.entities
title: Story Creation Entities
status: active
doc_kind: spec
context: story-creation
spec_kind: entity-set
version: 1
prose_refs:
  - concept/technical-design/21_story_creation_pipeline.md
  - concept/technical-design/17_fachliches_datenmodell_ownership.md
  - concept/technical-design/18_relationales_abbildungsmodell_postgres.md
---

# Story Creation Entities

Der Story-Creation-Pfad braucht wenige, aber fachlich stabile
Kernentitaeten.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-creation.entities
schema_version: 1
kind: entity-set
context: story-creation
entities:
  - id: story-creation.entity.story-draft
    identity_key: draft_id
    attributes:
      - draft_id
      - project_key
      - title
      - problem_statement
      - solution_approach
      - acceptance_criteria
      - concept_refs
      - dependency_refs
      - story_type
      - size
  - id: story-creation.entity.story-record
    identity_key: story_id
    attributes:
      - story_id
      - project_key
      - issue_number
      - project_status
      - labels
      - custom_fields
      - repo_affinity
  - id: story-creation.entity.story-md-export
    identity_key: story_id
    attributes:
      - story_id
      - story_md_path
      - exported_at
      - indexed
```
<!-- FORMAL-SPEC:END -->
