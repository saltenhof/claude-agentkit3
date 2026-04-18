---
id: formal.setup-preflight.events
title: Setup Preflight Events
status: active
doc_kind: spec
context: setup-preflight
spec_kind: event-set
version: 1
prose_refs:
  - concept/technical-design/22_setup_preflight_worktree_guard_activation.md
  - concept/technical-design/91_api_event_katalog.md
---

# Setup Preflight Events

Diese Events bilden den Setup- und Preflight-Pfad fachlich ab.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.setup-preflight.events
schema_version: 1
kind: event-set
context: setup-preflight
events:
  - id: setup-preflight.event.preflight.passed
    producer: setup-preflight
    role: lifecycle
    payload:
      required:
        - run_id
        - story_id
  - id: setup-preflight.event.preflight.failed
    producer: setup-preflight
    role: lifecycle
    payload:
      required:
        - run_id
        - story_id
        - failed_checks
  - id: setup-preflight.event.context.materialized
    producer: setup-preflight
    role: lifecycle
    payload:
      required:
        - run_id
        - story_id
  - id: setup-preflight.event.worktrees.created
    producer: setup-preflight
    role: lifecycle
    payload:
      required:
        - run_id
        - story_id
        - repo_ids
  - id: setup-preflight.event.guards.activated
    producer: setup-preflight
    role: lifecycle
    payload:
      required:
        - run_id
        - story_id
  - id: setup-preflight.event.mode.routed
    producer: setup-preflight
    role: lifecycle
    payload:
      required:
        - run_id
        - story_id
        - mode
  - id: setup-preflight.event.setup.completed
    producer: setup-preflight
    role: lifecycle
    payload:
      required:
        - run_id
        - story_id
        - mode
```
<!-- FORMAL-SPEC:END -->
