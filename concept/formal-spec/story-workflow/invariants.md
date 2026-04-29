---
id: formal.story-workflow.invariants
title: Story Workflow Invariants
status: active
doc_kind: spec
context: story-workflow
spec_kind: invariant-set
version: 1
prose_refs:
  - concept/technical-design/20_workflow_engine_state_machine.md
  - concept/technical-design/39_phase_state_persistenz.md
  - concept/domain-design/02-pipeline-orchestrierung.md
  - concept/technical-design/29_closure_sequence.md
  - concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md
---

# Story Workflow Invariants

Diese Invarianten begrenzen den zulaessigen Story-Run-Kontrollfluss.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-workflow.invariants
schema_version: 1
kind: invariant-set
context: story-workflow
invariants:
  - id: story-workflow.invariant.setup_routes_fail_closed
    scope: phase-transition
    rule: setup may route only to exploration or implementation according to deterministic mode routing; no other target phase is legal
  - id: story-workflow.invariant.exploration_gate_required
    scope: phase-transition
    rule: the first transition from exploration to implementation is legal only if ExplorationGateStatus is APPROVED
  - id: story-workflow.invariant.forward_only_except_verify_feedback
    scope: phase-transition
    rule: phase progression is strictly forward except for the explicit verify to implementation remediation path
  - id: story-workflow.invariant.verify_feedback_requires_failed
    scope: phase-transition
    rule: verify may transition back to implementation only when verify ended with status FAILED and the feedback-round guard permits another remediation loop
  - id: story-workflow.invariant.closure_requires_verify_completed
    scope: phase-transition
    rule: closure is legal only after verify has completed successfully
  - id: story-workflow.invariant.completion_only_after_closure
    scope: status-transition
    rule: status COMPLETED is legal only when current_phase is closure and closure progress reached its completion state
  - id: story-workflow.invariant.resume_preserves_run_and_phase
    scope: status-transition
    rule: resume continues the same run_id and the same current_phase that was active at pause time
  - id: story-workflow.invariant.failed_reentry_returns_to_in_progress
    scope: status-transition
    rule: an official remediation re-entry from FAILED returns the workflow status to IN_PROGRESS before implementation continues
  - id: story-workflow.invariant.escalated_requires_new_run
    scope: status-transition
    rule: ESCALATED may not continue through resume; a new run_id is required before workflow execution continues
  - id: story-workflow.invariant.internal_pause_or_escalation_does_not_close_issue
    scope: external-status-coupling
    rule: paused, failed, or escalated workflow states do not by themselves set the GitHub issue to Done or Closed
```
<!-- FORMAL-SPEC:END -->
