---
id: formal.setup-preflight.commands
title: Setup Preflight Commands
status: active
doc_kind: spec
context: setup-preflight
spec_kind: command-set
version: 1
prose_refs:
  - concept/technical-design/22_setup_preflight_worktree_guard_activation.md
  - concept/technical-design/91_api_event_katalog.md
---

# Setup Preflight Commands

Setup laeuft ueber den offiziellen Phase-Runner-Service.
Normative Aufruf-Parameter (story_id, phase) sind in FK-91 §91.1a definiert.
Die Operator-Recovery-CLI `agentkit run-phase setup --story <story_id>`
ist ein Spezialfall (FK-91 §91.1, FK-45 §45.4).

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.setup-preflight.commands
schema_version: 1
kind: command-set
context: setup-preflight
commands:
  - id: setup-preflight.command.run-phase
    signature: POST /v1/story-runs/{run_id}/phases/setup/start {story_id}
    allowed_statuses:
      - setup-preflight.status.requested
    requires:
      - setup-preflight.invariant.fail_closed_on_any_preflight_failure
      - setup-preflight.invariant.no_active_runtime_residue_before_start
    emits:
      - setup-preflight.event.preflight.passed
      - setup-preflight.event.preflight.failed
      - setup-preflight.event.context.materialized
      - setup-preflight.event.worktrees.created
      - setup-preflight.event.guards.activated
      - setup-preflight.event.mode.routed
      - setup-preflight.event.setup.completed
```
<!-- FORMAL-SPEC:END -->
