---
id: formal.operating-modes.scenarios
title: Operating Mode Scenarios
status: active
doc_kind: spec
context: operating-modes
spec_kind: scenario-set
version: 1
prose_refs:
  - concept/technical-design/56_ai_augmented_mode_and_story_execution_separation.md
---

# Operating Mode Scenarios

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.operating-modes.scenarios
schema_version: 1
kind: scenario-set
context: operating-modes
scenarios:
  - id: operating-modes.scenario.free-session-stays-ai-augmented
    start:
      status: operating-modes.status.unresolved
    trace:
      - command: operating-modes.command.resolve-operating-mode
    expected_end:
      status: operating-modes.status.resolved_ai_augmented
    requires:
      - operating-modes.invariant.ai_augmented_has_no_workflow_obligations
  - id: operating-modes.scenario.valid-binding-activates-story-execution
    start:
      status: operating-modes.status.unresolved
    trace:
      - command: operating-modes.command.bind-session-to-run
      - command: operating-modes.command.activate-story-execution-regime
      - command: operating-modes.command.materialize-local-edge-bundle
    expected_end:
      status: operating-modes.status.resolved_story_execution
    requires:
      - operating-modes.invariant.story_execution_requires_lock_binding_and_worktree_match
      - operating-modes.invariant.local_edge_bundle_is_derived_not_authoritative
  - id: operating-modes.scenario.lock-loss-enters-binding-invalid
    start:
      status: operating-modes.status.story_execution
    trace:
      - command: operating-modes.command.resolve-operating-mode
    expected_end:
      status: operating-modes.status.resolved_binding_invalid
    requires:
      - operating-modes.invariant.invalid_bound_session_must_not_fall_back_to_free_mode
  - id: operating-modes.scenario.uncertain-mutation-result-is-reconciled-before-local-publish
    start:
      status: operating-modes.status.story_execution
    trace:
      - command: operating-modes.command.reconcile-edge-operation
      - command: operating-modes.command.materialize-local-edge-bundle
    expected_end:
      status: operating-modes.status.resolved_story_execution
    requires:
      - operating-modes.invariant.uncertain_remote_mutation_must_be_reconciled_by_op_id
      - operating-modes.invariant.story_mutations_require_fresh_or_resynced_bundle
```
<!-- FORMAL-SPEC:END -->
