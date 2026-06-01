---
id: formal.story-workflow.scenarios
title: Story Workflow Scenarios
status: active
doc_kind: spec
context: story-workflow
spec_kind: scenario-set
version: 1
prose_refs:
  - concept/domain-design/02-pipeline-orchestrierung.md
  - concept/technical-design/20_workflow_engine_state_machine.md
  - concept/technical-design/29_closure_sequence.md
  - concept/technical-design/54_story_split_service_scope_explosion.md
---

# Story Workflow Scenarios

Diese Traces pruefen die zentrale Story-Orchestrierung entlang
deklarierten, konzepttreuen End-to-End-Pfaden.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-workflow.scenarios
schema_version: 1
kind: scenario-set
context: story-workflow
scenarios:
  - id: story-workflow.scenario.execution-happy-path
    start:
      phase: story-workflow.phase.setup
      status: story-workflow.status.in_progress
    trace:
      - command: story-workflow.command.run-phase
        target_phase: story-workflow.phase.setup
      - command: story-workflow.command.run-phase
        target_phase: story-workflow.phase.implementation
      - command: story-workflow.command.run-phase
        target_phase: story-workflow.phase.closure
    expected_end:
      phase: story-workflow.phase.closure
      status: story-workflow.status.completed
    notes:
      - implementation completes only after the internal QA-subflow against the verify-system capability reaches a passing verdict
  - id: story-workflow.scenario.exploration-happy-path
    start:
      phase: story-workflow.phase.setup
      status: story-workflow.status.in_progress
    trace:
      - command: story-workflow.command.run-phase
        target_phase: story-workflow.phase.setup
      - command: story-workflow.command.run-phase
        target_phase: story-workflow.phase.exploration
      - command: story-workflow.command.run-phase
        target_phase: story-workflow.phase.implementation
      - command: story-workflow.command.run-phase
        target_phase: story-workflow.phase.closure
    expected_end:
      phase: story-workflow.phase.closure
      status: story-workflow.status.completed
    notes:
      - exploration exit-gate and implementation QA-subflow both invoke the verify-system capability; neither is a phase transition
  - id: story-workflow.scenario.noncode-closure-shortcut
    start:
      phase: story-workflow.phase.setup
      status: story-workflow.status.in_progress
    trace:
      - command: story-workflow.command.run-phase
        target_phase: story-workflow.phase.setup
      - command: story-workflow.command.run-phase
        target_phase: story-workflow.phase.implementation
      - command: story-workflow.command.run-phase
        target_phase: story-workflow.phase.closure
    expected_end:
      phase: story-workflow.phase.closure
      status: story-workflow.status.completed
    requires:
      - story-workflow.invariant.noncode_closure_skips_qa_subflow
    notes:
      - concept and research stories run the implementation phase to produce their documentation/research artifact WITHOUT a code QA-subflow against the verify-system capability
      - closure for non-implementing stories uses the direct shortcut (no Finding-Resolution-Gate, no Integrity-Gate, no Pre-Merge-Scan-und-Merge-Block); integrity_passed/story_branch_pushed/merge_done are set true without branch, scan or merge (FK-29 §29.1.1, §29.2; RESOLUTION B)
  - id: story-workflow.scenario.merge-conflict-escalates-run
    start:
      phase: story-workflow.phase.closure
      status: story-workflow.status.in_progress
    trace:
      - command: story-workflow.command.run-phase
        target_phase: story-workflow.phase.closure
    expected_end:
      phase: story-workflow.phase.closure
      status: story-workflow.status.escalated
    notes:
      - closure merge conflict ends the old run in ESCALATED
      - reset-escalation belongs to the dedicated escalation context
```
<!-- FORMAL-SPEC:END -->
