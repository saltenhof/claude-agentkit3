---
id: formal.story-split.commands
title: Story Split Commands
status: active
doc_kind: spec
context: story-split
spec_kind: command-set
version: 1
prose_refs:
  - concept/technical-design/54_story_split_service_scope_explosion.md
  - concept/technical-design/91_api_event_katalog.md
---

# Story Split Commands

Der Story-Split wird nur ueber den offiziellen administrativen Pfad
ausgeloest.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-split.commands
schema_version: 1
kind: command-set
context: story-split
commands:
  - id: story-split.command.execute
    signature: agentkit split-story --story <story_id> --plan <plan_ref> --reason <reason>
    allowed_statuses:
      - story-split.status.requested
    requires:
      - story-split.invariant.split_requires_official_preconditions
    emits:
      - story-split.event.split.requested
      - story-split.event.split.started
      - story-split.event.split.completed
      - story-split.event.split.failed
```
<!-- FORMAL-SPEC:END -->
