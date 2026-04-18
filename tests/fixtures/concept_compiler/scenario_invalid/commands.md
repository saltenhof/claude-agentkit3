---
id: formal.example.commands
title: Example Commands
status: active
doc_kind: spec
context: example
spec_kind: command-set
version: 1
prose_refs:
  - docs/example.md
---

# Example Commands

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.example.commands
schema_version: 1
kind: command-set
context: example
commands:
  - id: example.command.run
    signature: run example
    allowed_statuses:
      - example.status.pending
    emits:
      - example.event.started
      - example.event.completed
```
<!-- FORMAL-SPEC:END -->
