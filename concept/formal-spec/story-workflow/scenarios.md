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
  - concept/technical-design/27_verify_pipeline_closure_orchestration.md
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
        target_phase: story-workflow.phase.verify
      - command: story-workflow.command.run-phase
        target_phase: story-workflow.phase.closure
    expected_end:
      phase: story-workflow.phase.closure
      status: story-workflow.status.completed
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
        target_phase: story-workflow.phase.verify
      - command: story-workflow.command.run-phase
        target_phase: story-workflow.phase.closure
    expected_end:
      phase: story-workflow.phase.closure
      status: story-workflow.status.completed
  - id: story-workflow.scenario.verify-feedback-loop
    start:
      phase: story-workflow.phase.verify
      status: story-workflow.status.failed
    trace:
      - command: story-workflow.command.run-phase
        target_phase: story-workflow.phase.implementation
      - command: story-workflow.command.run-phase
        target_phase: story-workflow.phase.verify
      - command: story-workflow.command.run-phase
        target_phase: story-workflow.phase.closure
    expected_end:
      phase: story-workflow.phase.closure
      status: story-workflow.status.completed
  - id: story-workflow.scenario.scope-explosion-pauses-run
    start:
      phase: story-workflow.phase.exploration
      status: story-workflow.status.in_progress
    trace:
      - command: story-workflow.command.run-phase
        target_phase: story-workflow.phase.exploration
    expected_end:
      phase: story-workflow.phase.exploration
      status: story-workflow.status.paused
    notes:
      - current run stops in PAUSED and awaits explicit human split decision
      - story-split is out of scope for this context and handled by StorySplitService
  - id: story-workflow.scenario.merge-conflict-escalates-run
    start:
      phase: story-workflow.phase.closure
      status: story-workflow.status.in_progress
    trace:
      - command: story-workflow.command.run-phase
        target_phase: story-workflow.phase.closure
      - command: story-workflow.command.reset-escalation
    expected_end:
      status: story-workflow.status.in_progress
    notes:
      - closure merge conflict ends the old run in ESCALATED
      - reset-escalation starts a new run_id for further processing
```
<!-- FORMAL-SPEC:END -->
