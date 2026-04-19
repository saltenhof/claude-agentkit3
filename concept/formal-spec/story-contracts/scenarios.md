---
id: formal.story-contracts.scenarios
title: Story Contract Scenarios
status: active
doc_kind: spec
context: story-contracts
spec_kind: scenario-set
version: 1
prose_refs:
  - concept/technical-design/59_story_contract_axes_and_combination_matrix.md
---

# Story Contract Scenarios

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-contracts.scenarios
schema_version: 1
kind: scenario-set
context: story-contracts
scenarios:
  - id: story-contracts.scenario.standard-implementation-completes-normally
    start:
      status: story-contracts.status.unclassified
    trace:
      - command: story-contracts.command.classify-story-contract
      - command: story-contracts.command.mark-story-done
    expected_end:
      status: story-contracts.status.done
    requires:
      - story-contracts.invariant.only_story_type_and_scoped_implementation_contract_are_persistent_axes
      - story-contracts.invariant.done_requires_delivery_semantics_not_exit_semantics
  - id: story-contracts.scenario.administrative-cancel-records-exit-semantics
    start:
      status: story-contracts.status.classified
    trace:
      - command: story-contracts.command.cancel-story-administratively
    expected_end:
      status: story-contracts.status.cancelled
    requires:
      - story-contracts.invariant.exit_class_is_valid_only_under_cancelled
      - story-contracts.invariant.cancelled_is_not_normal_closure_success
```
<!-- FORMAL-SPEC:END -->
