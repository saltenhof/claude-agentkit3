---
id: formal.story-exit.commands
title: Story Exit Commands
status: active
doc_kind: spec
context: story-exit
spec_kind: command-set
version: 1
prose_refs:
  - concept/technical-design/58_story_exit_human_takeover_handoff.md
  - concept/technical-design/91_api_event_katalog.md
---

# Story Exit Commands

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-exit.commands
schema_version: 1
kind: command-set
context: story-exit
commands:
  - id: story-exit.command.exit-story
    actor: human_cli
    allowed_from:
      - story-exit.status.eligible
    emits:
      - story-exit.event.story_exit_requested
  - id: story-exit.command.run-exit-gate
    actor: admin_service
    allowed_from:
      - story-exit.status.exit_requested
    emits:
      - story-exit.event.story_exit_gate_passed
      - story-exit.event.story_exit_rejected
  - id: story-exit.command.revoke-binding
    actor: admin_service
    allowed_from:
      - story-exit.status.story_cancelled
    emits:
      - story-exit.event.story_exit_binding_revoked
```
<!-- FORMAL-SPEC:END -->
