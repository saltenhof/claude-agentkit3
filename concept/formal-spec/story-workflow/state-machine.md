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
  - concept/technical-design/29_closure_sequence.md
---

# Story Workflow State Machine

Dieser Kontext trennt bewusst zwei Achsen:

- die fachliche Phase der Storybearbeitung
- den Kontrollstatus des aktuellen Runs

`PAUSED` und `ESCALATED` ersetzen keine Phase, sondern suspendieren oder
beenden den aktuellen Run relativ zu einer konkreten Phase.

Die Phase-Achse ist linear vorwaerts: `setup -> exploration |
implementation`, `exploration -> implementation`, `implementation ->
closure`. Output-QA ist kein eigener Phasenknoten, sondern interner
Subflow innerhalb der Implementation-Phase (analog zum Exit-Gate der
Exploration). Die Capability `verify-system` wird sowohl vom
Exploration-Exit-Gate als auch vom Implementation-QA-Subflow gegen
denselben fachlichen Vertrag aufgerufen; sie ist Capability-BC, kein
Phase-Owner.

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
    - id: story-workflow.transition.implementation_to_closure
      from: story-workflow.phase.implementation
      to: story-workflow.phase.closure
      guard: story-workflow.invariant.closure_requires_implementation_completed
status_axis:
  states:
    - id: story-workflow.status.in_progress
      initial: true
    - id: story-workflow.status.paused
    - id: story-workflow.status.escalated
      terminal: true
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
    - id: story-workflow.transition.reenter_after_failure
      from: story-workflow.status.failed
      to: story-workflow.status.in_progress
      guard: story-workflow.invariant.failed_reentry_returns_to_in_progress
    - id: story-workflow.transition.escalate
      from: story-workflow.status.in_progress
      to: story-workflow.status.escalated
    - id: story-workflow.transition.restart_after_escalation
      from: story-workflow.status.escalated
      to: story-workflow.status.in_progress
      guard: story-workflow.invariant.escalated_requires_new_run
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
  - id: story-workflow.rule.qa_subflow_is_implementation_internal
    description: The output-QA cycle runs as a subflow inside the implementation phase against the verify-system capability; subflow iterations are not phase transitions and never appear on the phase axis.
```
<!-- FORMAL-SPEC:END -->
