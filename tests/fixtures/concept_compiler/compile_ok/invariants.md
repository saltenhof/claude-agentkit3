---
id: formal.example.invariants
title: Invariants
status: active
doc_kind: spec
context: example
spec_kind: invariant-set
version: "1"
---

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.example.invariants
schema_version: 1
kind: invariant-set
context: example
invariants:
  - id: example.invariant.can_finish
    scope: transition
    rule: finish requires the initial state
```
<!-- FORMAL-SPEC:END -->
