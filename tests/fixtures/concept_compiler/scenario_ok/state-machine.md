---
id: formal.example.state-machine
title: Example State Machine
status: active
doc_kind: spec
context: example
spec_kind: state-machine
version: 1
prose_refs:
  - docs/example.md
---

# Example State Machine

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.example.state-machine
schema_version: 1
kind: state-machine
context: example
states:
  - id: example.status.pending
    initial: true
  - id: example.status.running
  - id: example.status.completed
    terminal: true
transitions:
  - id: example.transition.pending_to_running
    from: example.status.pending
    to: example.status.running
  - id: example.transition.running_to_completed
    from: example.status.running
    to: example.status.completed
```
<!-- FORMAL-SPEC:END -->
