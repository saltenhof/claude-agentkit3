---
id: formal.example.scenarios
title: Example Scenarios
status: active
doc_kind: spec
context: example
spec_kind: scenario-set
version: 1
prose_refs:
  - docs/example.md
---

# Example Scenarios

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.example.scenarios
schema_version: 1
kind: scenario-set
context: example
scenarios:
  - id: example.scenario.happy_path
    start:
      status: example.status.pending
    trace:
      - command: example.command.run
    expected_end:
      status: example.status.completed
```
<!-- FORMAL-SPEC:END -->
