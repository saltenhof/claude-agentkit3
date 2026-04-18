---
id: formal.example.drift
title: Drift OK
status: active
doc_kind: spec
context: example
spec_kind: invariant-set
version: "1"
prose_refs:
  - tests/fixtures/concept_compiler/drift_ok/prose.md
---

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.example.drift
schema_version: 1
kind: invariant-set
context: example
invariants:
  - id: example.invariant.ok
    scope: process
    rule: example
```
<!-- FORMAL-SPEC:END -->
