---
id: formal.example.state-machine
title: State Machine
status: active
doc_kind: spec
context: example
spec_kind: state-machine
version: "1"
---

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.example.state-machine
schema_version: 1
kind: state-machine
context: example
states:
  - id: example.state.initial
  - id: example.state.done
transitions:
  - id: example.transition.finish
    from: example.state.initial
    to: example.state.done
    guard: example.invariant.can_finish
```
<!-- FORMAL-SPEC:END -->
