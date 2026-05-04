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
