---
id: formal.example.anchor
title: Anchor OK
status: active
doc_kind: spec
context: example
spec_kind: invariant-set
version: "1"
prose_refs:
  - tests/fixtures/concept_compiler/drift_anchor_ok/prose.md
---

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.example.anchor
schema_version: 1
kind: invariant-set
context: example
invariants:
  - id: example.invariant.anchor-ok
    scope: process
    rule: example
```
<!-- FORMAL-SPEC:END -->
