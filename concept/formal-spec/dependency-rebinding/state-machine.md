---
id: formal.dependency-rebinding.state-machine
title: Dependency Rebinding State Machine
status: active
doc_kind: spec
context: dependency-rebinding
spec_kind: state-machine
version: 1
prose_refs:
  - concept/technical-design/54_story_split_service_scope_explosion.md
---

# Dependency Rebinding State Machine

Dependency-Rebinding ist ein kleiner, checkpointfaehiger Subflow
innerhalb des Story-SplitService.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.dependency-rebinding.state-machine
schema_version: 1
kind: state-machine
context: dependency-rebinding
states:
  - id: dependency-rebinding.status.requested
    initial: true
  - id: dependency-rebinding.status.validated
  - id: dependency-rebinding.status.applied
  - id: dependency-rebinding.status.completed
    terminal: true
  - id: dependency-rebinding.status.rejected
    terminal: true
transitions:
  - id: dependency-rebinding.transition.requested_to_validated
    from: dependency-rebinding.status.requested
    to: dependency-rebinding.status.validated
    guard: dependency-rebinding.invariant.mapping_requires_successors_created
  - id: dependency-rebinding.transition.validated_to_applied
    from: dependency-rebinding.status.validated
    to: dependency-rebinding.status.applied
    guard: dependency-rebinding.invariant.deterministic_target_selection
  - id: dependency-rebinding.transition.applied_to_completed
    from: dependency-rebinding.status.applied
    to: dependency-rebinding.status.completed
    guard: dependency-rebinding.invariant.no_stale_cancelled_target
  - id: dependency-rebinding.transition.requested_to_rejected
    from: dependency-rebinding.status.requested
    to: dependency-rebinding.status.rejected
    guard: dependency-rebinding.invariant.no_silent_drop
  - id: dependency-rebinding.transition.validated_to_rejected
    from: dependency-rebinding.status.validated
    to: dependency-rebinding.status.rejected
    guard: dependency-rebinding.invariant.graph_integrity_preserved
compound_rules:
  - id: dependency-rebinding.rule.rebinding_completes_before_split_completion
    description: Dependency rebinding must reach completed before the parent split may transition to completed.
```
<!-- FORMAL-SPEC:END -->
