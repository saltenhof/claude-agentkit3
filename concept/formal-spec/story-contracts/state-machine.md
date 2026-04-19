---
id: formal.story-contracts.state-machine
title: Story Contract State Machine
status: active
doc_kind: spec
context: story-contracts
spec_kind: state-machine
version: 1
prose_refs:
  - concept/technical-design/59_story_contract_axes_and_combination_matrix.md
  - concept/technical-design/58_story_exit_human_takeover_handoff.md
---

# Story Contract State Machine

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-contracts.state-machine
schema_version: 1
kind: state-machine
context: story-contracts
states:
  - id: story-contracts.status.unclassified
    initial: true
  - id: story-contracts.status.classified
  - id: story-contracts.status.done
    terminal: true
  - id: story-contracts.status.cancelled
    terminal: true
transitions:
  - id: story-contracts.transition.classify
    from: story-contracts.status.unclassified
    to: story-contracts.status.classified
    guard: story-contracts.invariant.only_story_type_and_scoped_implementation_contract_are_persistent_axes
  - id: story-contracts.transition.complete
    from: story-contracts.status.classified
    to: story-contracts.status.done
    guard: story-contracts.invariant.done_requires_delivery_semantics_not_exit_semantics
  - id: story-contracts.transition.cancel
    from: story-contracts.status.classified
    to: story-contracts.status.cancelled
    guard: story-contracts.invariant.exit_class_is_valid_only_under_cancelled
compound_rules:
  - id: story-contracts.rule.operating_mode_is_runtime_derived
    description: operating_mode is resolved from run binding and lock state and is never a peer persistent story contract field
  - id: story-contracts.rule.execution_route_is_not_operating_mode
    description: execution_route and operating_mode are distinct dimensions and must not share meaning
  - id: story-contracts.rule.exit_class_subordinates_to_cancelled
    description: exit_class is a cancellation subtype and not a universal classification axis
```
<!-- FORMAL-SPEC:END -->
