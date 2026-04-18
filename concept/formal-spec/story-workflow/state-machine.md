---
id: formal.story-workflow.state-machine
title: Story Workflow State Machine
status: active
doc_kind: spec
context: story-workflow
spec_kind: state-machine
version: 1
prose_refs:
  - concept/technical-design/20_workflow_engine_state_machine.md
  - concept/domain-design/02-pipeline-orchestrierung.md
  - concept/technical-design/27_verify_pipeline_closure_orchestration.md
---

# Story Workflow State Machine

Dieser Kontext trennt bewusst zwei Achsen:

- die fachliche Phase der Storybearbeitung
- den Kontrollstatus des aktuellen Runs

`PAUSED` und `ESCALATED` ersetzen keine Phase, sondern suspendieren oder
beenden den aktuellen Run relativ zu einer konkreten Phase.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-workflow.state-machine
schema_version: 1
kind: state-machine
context: story-workflow
phase_axis:
  states:
    - id: story-workflow.phase.setup
      initial: true
    - id: story-workflow.phase.exploration
    - id: story-workflow.phase.implementation
    - id: story-workflow.phase.verify
    - id: story-workflow.phase.closure
  transitions:
    - id: story-workflow.transition.setup_to_exploration
      from: story-workflow.phase.setup
      to: story-workflow.phase.exploration
      guard: story-workflow.invariant.setup_routes_fail_closed
    - id: story-workflow.transition.setup_to_implementation
      from: story-workflow.phase.setup
      to: story-workflow.phase.implementation
      guard: story-workflow.invariant.setup_routes_fail_closed
    - id: story-workflow.transition.exploration_to_implementation
      from: story-workflow.phase.exploration
      to: story-workflow.phase.implementation
      guard: story-workflow.invariant.exploration_gate_required
    - id: story-workflow.transition.implementation_to_verify
      from: story-workflow.phase.implementation
      to: story-workflow.phase.verify
      guard: story-workflow.invariant.forward_only_except_verify_feedback
    - id: story-workflow.transition.verify_to_implementation
      from: story-workflow.phase.verify
      to: story-workflow.phase.implementation
      guard: story-workflow.invariant.verify_feedback_requires_failed
    - id: story-workflow.transition.verify_to_closure
      from: story-workflow.phase.verify
      to: story-workflow.phase.closure
      guard: story-workflow.invariant.closure_requires_verify_completed
status_axis:
  states:
    - id: story-workflow.status.in_progress
      initial: true
    - id: story-workflow.status.paused
    - id: story-workflow.status.escalated
    - id: story-workflow.status.failed
    - id: story-workflow.status.completed
      terminal: true
  transitions:
    - id: story-workflow.transition.pause
      from: story-workflow.status.in_progress
      to: story-workflow.status.paused
    - id: story-workflow.transition.resume
      from: story-workflow.status.paused
      to: story-workflow.status.in_progress
      guard: story-workflow.invariant.resume_preserves_run_and_phase
    - id: story-workflow.transition.escalate
      from: story-workflow.status.in_progress
      to: story-workflow.status.escalated
    - id: story-workflow.transition.fail
      from: story-workflow.status.in_progress
      to: story-workflow.status.failed
    - id: story-workflow.transition.complete
      from: story-workflow.status.in_progress
      to: story-workflow.status.completed
      guard: story-workflow.invariant.completion_only_after_closure
compound_rules:
  - id: story-workflow.rule.paused_does_not_change_phase
    description: Pausing and resuming do not advance or rewind current_phase.
  - id: story-workflow.rule.escalated_ends_current_run
    description: ESCALATED ends the current run and requires an external reset-escalation path before a new run may start.
  - id: story-workflow.rule.verify_feedback_is_explicit_exception
    description: The only backward phase transition in the normal workflow is verify to implementation.
```
<!-- FORMAL-SPEC:END -->
