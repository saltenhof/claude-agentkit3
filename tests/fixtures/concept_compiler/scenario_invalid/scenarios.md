---
id: formal.example.scenarios
title: Example Scenarios Broken
status: active
doc_kind: spec
context: example
spec_kind: scenario-set
version: 1
prose_refs:
  - docs/example.md
---

# Example Scenarios Broken

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.example.scenarios
schema_version: 1
kind: scenario-set
context: example
scenarios:
  - id: example.scenario.impossible_end
    start:
      status: example.status.pending
    trace:
      - command: example.command.run
    expected_end:
      status: example.status.running
```
<!-- FORMAL-SPEC:END -->
