---
id: formal.story-reset.commands
title: Story Reset Commands
status: active
doc_kind: spec
context: story-reset
spec_kind: command-set
version: 1
prose_refs:
  - concept/technical-design/53_story_reset_service_recovery_flow.md
  - concept/technical-design/91_api_event_katalog.md
---

# Story Reset Commands

Der Reset wird nur ueber offizielle administrative Pfade angestossen.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-reset.commands
schema_version: 1
kind: command-set
context: story-reset
commands:
  - id: story-reset.command.execute
    signature: agentkit reset-story --story <story_id> --reason <reason>
    allowed_statuses:
      - story-reset.status.requested
    requires:
      - story-reset.invariant.reset_requires_official_authorization
    emits:
      - story-reset.event.reset.requested
      - story-reset.event.reset.started
      - story-reset.event.reset.completed
      - story-reset.event.reset.failed
  - id: story-reset.command.resume
    signature: internal resume_reset <reset_id>
    allowed_statuses:
      - story-reset.status.reset_failed
    requires:
      - story-reset.invariant.reset_failed_needs_same_reset_id
    emits:
      - story-reset.event.reset.resumed
```
<!-- FORMAL-SPEC:END -->
