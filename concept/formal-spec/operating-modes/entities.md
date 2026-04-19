---
id: formal.operating-modes.entities
title: Operating Mode Entities
status: active
doc_kind: spec
context: operating-modes
spec_kind: entity-set
version: 1
prose_refs:
  - concept/technical-design/56_ai_augmented_mode_and_story_execution_separation.md
  - concept/technical-design/55_principal_capability_model_story_scope_enforcement.md
---

# Operating Mode Entities

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.operating-modes.entities
schema_version: 1
kind: entity-set
context: operating-modes
entities:
  - id: operating-modes.entity.session-run-binding
    identity: session_id
    attributes:
      - project_key
      - story_id
      - run_id
      - principal_type
      - worktree_roots
      - binding_version
  - id: operating-modes.entity.mode-resolution
    identity: session_id + resolved_at
    attributes:
      - session_id
      - operating_mode
      - basis
      - story_lock_ref
      - binding_ref
```
<!-- FORMAL-SPEC:END -->
