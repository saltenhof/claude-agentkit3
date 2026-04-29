---
id: formal.story-contracts.invariants
title: Story Contract Invariants
status: active
doc_kind: spec
context: story-contracts
spec_kind: invariant-set
version: 1
prose_refs:
  - concept/technical-design/59_story_contract_axes_and_combination_matrix.md
  - concept/technical-design/24_story_type_mode_terminalitaet.md
  - concept/technical-design/56_ai_augmented_mode_and_story_execution_separation.md
  - concept/technical-design/05_integration_stabilization_contract.md
  - concept/technical-design/58_story_exit_human_takeover_handoff.md
---

# Story Contract Invariants

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-contracts.invariants
schema_version: 1
kind: invariant-set
context: story-contracts
invariants:
  - id: story-contracts.invariant.only_story_type_and_scoped_implementation_contract_are_persistent_axes
    scope: governance
    rule: the only persistent story contract axes are story_type and implementation_contract with implementation_contract scoped to story_type implementation
  - id: story-contracts.invariant.operating_mode_is_runtime_derived_not_story_metadata
    scope: governance
    rule: operating_mode is derived from lock binding and worktree consistency and must not be treated as a peer persisted story contract field
  - id: story-contracts.invariant.execution_route_is_distinct_from_operating_mode
    scope: governance
    rule: execution_route and operating_mode are different dimensions and the wire field mode is only an execution_route alias
  - id: story-contracts.invariant.integration_stabilization_is_not_valid_for_bugfix_or_non_implementation
    scope: governance
    rule: implementation_contract integration_stabilization is valid only for story_type implementation and never for bugfix concept or research
  - id: story-contracts.invariant.done_requires_delivery_semantics_not_exit_semantics
    scope: governance
    rule: Done requires delivery semantics and may not carry administrative exit semantics or exit_class
  - id: story-contracts.invariant.exit_class_is_valid_only_under_cancelled
    scope: governance
    rule: exit_class may only be recorded when the story terminal_state is Cancelled through an official administrative path
  - id: story-contracts.invariant.cancelled_is_not_normal_closure_success
    scope: governance
    rule: Cancelled is never produced by normal closure success and implies no merge no successful closure and no delivered outcome
  - id: story-contracts.invariant.binding_invalid_is_not_a_free_mode
    scope: governance
    rule: a broken story binding is a blocking inconsistency and must not silently degrade to ai_augmented
```
<!-- FORMAL-SPEC:END -->

