---
id: formal.setup-preflight.entities
title: Setup Preflight Entities
status: active
doc_kind: spec
context: setup-preflight
spec_kind: entity-set
version: 1
prose_refs:
  - concept/technical-design/22_setup_preflight_worktree_guard_activation.md
  - concept/technical-design/45_phase_runner_cli.md
---

# Setup Preflight Entities

Der Setup-Pfad braucht nur wenige, aber fachlich stabile
Kernentitaeten.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.setup-preflight.entities
schema_version: 1
kind: entity-set
context: setup-preflight
entities:
  - id: setup-preflight.entity.setup-attempt
    identity_key: run_id
    attributes:
      - run_id
      - project_key
      - story_id
      - story_type
      - mode
      - status
  - id: setup-preflight.entity.preflight-report
    identity_key: run_id
    attributes:
      - run_id
      - passed
      - checks
      - errors
      - warnings
  - id: setup-preflight.entity.story-context
    identity_key: story_id
    attributes:
      - story_id
      - project_key
      - story_type
      - dependencies
      - repo_bindings
      - scope_keys
  - id: setup-preflight.entity.worktree-binding
    identity_key: repo_id
    attributes:
      - repo_id
      - story_id
      - worktree_path
      - branch_name
```
<!-- FORMAL-SPEC:END -->
