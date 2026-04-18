---
id: formal.dependency-rebinding.scenarios
title: Dependency Rebinding Scenarios
status: active
doc_kind: spec
context: dependency-rebinding
spec_kind: scenario-set
version: 1
prose_refs:
  - concept/technical-design/54_story_split_service_scope_explosion.md
---

# Dependency Rebinding Scenarios

Diese Traces pruefen den Rebinding-Subflow gegen typische
Split-Edge-Cases.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.dependency-rebinding.scenarios
schema_version: 1
kind: scenario-set
context: dependency-rebinding
scenarios:
  - id: dependency-rebinding.scenario.one-to-one-rebinding
    start:
      status: dependency-rebinding.status.requested
    trace:
      - command: dependency-rebinding.command.validate
      - command: dependency-rebinding.command.apply
    expected_end:
      status: dependency-rebinding.status.completed
    requires:
      - dependency-rebinding.invariant.mapping_requires_successors_created
      - dependency-rebinding.invariant.no_stale_cancelled_target
  - id: dependency-rebinding.scenario.explicit-single-target-from-many-successors
    start:
      status: dependency-rebinding.status.requested
    trace:
      - command: dependency-rebinding.command.validate
      - command: dependency-rebinding.command.apply
    expected_end:
      status: dependency-rebinding.status.completed
    requires:
      - dependency-rebinding.invariant.deterministic_target_selection
      - dependency-rebinding.invariant.no_unjustified_fanout
  - id: dependency-rebinding.scenario.no-valid-successor-mapping
    start:
      status: dependency-rebinding.status.requested
    trace:
      - command: dependency-rebinding.command.validate
    expected_end:
      status: dependency-rebinding.status.rejected
    requires:
      - dependency-rebinding.invariant.no_silent_drop
  - id: dependency-rebinding.scenario.duplicate-or-cycle-would-be-created
    start:
      status: dependency-rebinding.status.validated
    trace:
      - command: dependency-rebinding.command.apply
    expected_end:
      status: dependency-rebinding.status.rejected
    requires:
      - dependency-rebinding.invariant.graph_integrity_preserved
```
<!-- FORMAL-SPEC:END -->
