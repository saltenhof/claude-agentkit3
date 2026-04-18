---
id: formal.example.events
title: Example Events
status: active
doc_kind: spec
context: example
spec_kind: event-set
version: 1
prose_refs:
  - docs/example.md
---

# Example Events

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.example.events
schema_version: 1
kind: event-set
context: example
events:
  - id: example.event.started
    producer: example
    role: lifecycle
    payload:
      required:
        - run_id
  - id: example.event.completed
    producer: example
    role: lifecycle
    payload:
      required:
        - run_id
```
<!-- FORMAL-SPEC:END -->
