---
id: formal.story-exit.state-machine
title: Story Exit State Machine
status: active
doc_kind: spec
context: story-exit
spec_kind: state-machine
version: 1
prose_refs:
  - concept/technical-design/58_story_exit_human_takeover_handoff.md
  - concept/technical-design/56_ai_augmented_mode_and_story_execution_separation.md
---

# Story Exit State Machine

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-exit.state-machine
schema_version: 1
kind: state-machine
context: story-exit
states:
  - id: story-exit.status.eligible
    initial: true
  - id: story-exit.status.exit_requested
  - id: story-exit.status.exit_gate_passed
  - id: story-exit.status.story_cancelled
  - id: story-exit.status.binding_revoked
  - id: story-exit.status.ai_augmented_resumed
    terminal: true
  - id: story-exit.status.exit_rejected
    terminal: true
transitions:
  - id: story-exit.transition.eligible_to_exit_requested
    from: story-exit.status.eligible
    to: story-exit.status.exit_requested
    guard: story-exit.invariant.exit_requires_human_cli
  - id: story-exit.transition.exit_requested_to_exit_gate_passed
    from: story-exit.status.exit_requested
    to: story-exit.status.exit_gate_passed
    guard: story-exit.invariant.exit_requires_minimal_artifacts
  - id: story-exit.transition.exit_gate_passed_to_story_cancelled
    from: story-exit.status.exit_gate_passed
    to: story-exit.status.story_cancelled
  - id: story-exit.transition.story_cancelled_to_binding_revoked
    from: story-exit.status.story_cancelled
    to: story-exit.status.binding_revoked
    guard: story-exit.invariant.exit_must_revoke_story_binding_before_free_mode
  - id: story-exit.transition.binding_revoked_to_ai_augmented_resumed
    from: story-exit.status.binding_revoked
    to: story-exit.status.ai_augmented_resumed
  - id: story-exit.transition.exit_requested_to_exit_rejected
    from: story-exit.status.exit_requested
    to: story-exit.status.exit_rejected
    guard: story-exit.invariant.exit_must_not_replace_split_or_normal_replan_without_reason
compound_rules:
  - id: story-exit.rule.run-becomes-non-resumable
    description: once exit_gate_passed the current story run may not be resumed and further work belongs to ai_augmented or to a new official story run
```
<!-- FORMAL-SPEC:END -->
