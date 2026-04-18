---
id: formal.dependency-rebinding.invariants
title: Dependency Rebinding Invariants
status: active
doc_kind: spec
context: dependency-rebinding
spec_kind: invariant-set
version: 1
prose_refs:
  - concept/technical-design/54_story_split_service_scope_explosion.md
---

# Dependency Rebinding Invariants

Diese Invarianten definieren den zulaessigen Umbau expliziter
Story-Abhaengigkeiten im Split-Pfad.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.dependency-rebinding.invariants
schema_version: 1
kind: invariant-set
context: dependency-rebinding
invariants:
  - id: dependency-rebinding.invariant.mapping_requires_successors_created
    scope: process
    requires:
      - story-split.status.successors_created
    rule: dependency rebinding is legal only after successor stories exist and the split plan provides explicit rebinding entries
  - id: dependency-rebinding.invariant.no_stale_cancelled_target
    scope: outcome
    rule: no explicit dependency may remain on the cancelled source story when valid successors exist for that dependency mapping
  - id: dependency-rebinding.invariant.no_silent_drop
    scope: process
    rule: every removed dependency edge must either be rebound to declared successor edges or end in an explicit rejection, never disappear silently
  - id: dependency-rebinding.invariant.deterministic_target_selection
    scope: process
    rule: identical rebinding inputs and policy must always produce the same target dependency set
  - id: dependency-rebinding.invariant.no_unjustified_fanout
    scope: process
    rule: a single source dependency may expand to multiple successor dependencies only if the split plan declares that fanout explicitly
  - id: dependency-rebinding.invariant.graph_integrity_preserved
    scope: outcome
    rule: rebinding must not create duplicate active edges or dependency cycles in the explicit story graph
```
<!-- FORMAL-SPEC:END -->
