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
  - id: story-workflow.invariant.forward_only
    scope: phase-transition
    rule: phase progression is strictly forward; remediation loops within a phase (e.g. exploration exit-gate iterations, implementation QA-subflow iterations) are subflow-internal and do not constitute phase transitions
  - id: story-workflow.invariant.closure_requires_implementation_completed
    scope: phase-transition
    rule: closure is legal only after implementation has completed successfully; for implementing stories (implementation, bugfix) this implies the implementation-internal QA-subflow reached a passing verdict from the verify-system capability, while for non-implementing stories (concept, research) the implementation phase produces the documentation/research artifact WITHOUT a code QA-subflow and closure proceeds via the direct non-implementing shortcut (FK-29 §29.2, RESOLUTION B); the QA-subflow-pass precondition therefore applies only to code stories
  - id: story-workflow.invariant.noncode_closure_skips_qa_subflow
    scope: phase-transition
    rule: concept and research stories close without the implementation QA-subflow, without the Finding-Resolution-Gate, without the Integrity-Gate and without the Pre-Merge-Scan-und-Merge-Block; their closure is legal once the implementation phase produced its non-code artifact, and integrity_passed/story_branch_pushed/merge_done are set true without any branch, scan or merge (FK-29 §29.1.1, §29.2)
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
  - id: story-workflow.invariant.internal_pause_or_escalation_does_not_close_story
    scope: status-coupling
    rule: paused, failed, or escalated workflow states do not by themselves set the AK3 story status to Done or Cancelled
```
<!-- FORMAL-SPEC:END -->
