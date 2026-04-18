---
id: formal.example.drift-missing
title: Drift Missing
status: active
doc_kind: spec
context: example
spec_kind: invariant-set
version: "1"
prose_refs:
  - tests/fixtures/concept_compiler/drift_missing_backref/prose.md
---

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.example.drift-missing
schema_version: 1
kind: invariant-set
context: example
invariants:
  - id: example.invariant.missing
    scope: process
    rule: example
```
<!-- FORMAL-SPEC:END -->
