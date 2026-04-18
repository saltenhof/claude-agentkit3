---
id: formal.story-workflow.events
title: Story Workflow Events
status: active
doc_kind: spec
context: story-workflow
spec_kind: event-set
version: 1
prose_refs:
  - concept/technical-design/20_workflow_engine_state_machine.md
  - concept/technical-design/14_telemetrie_eventing_workflow_metriken.md
  - concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md
---

# Story Workflow Events

Diese Events sind die semantisch relevanten Workflow-Ereignisse des
Story-Runs. Sie sind nicht die vollstaendige Telemetrie-Taxonomie,
sondern der fachliche Kern fuer Status- und Ablaufpruefungen.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-workflow.events
schema_version: 1
kind: event-set
context: story-workflow
events:
  - id: story-workflow.event.phase.started
    producer: story-workflow
    role: lifecycle
    payload:
      required:
        - run_id
        - phase
  - id: story-workflow.event.phase.completed
    producer: story-workflow
    role: lifecycle
    payload:
      required:
        - run_id
        - phase
        - status
  - id: story-workflow.event.phase.failed
    producer: story-workflow
    role: lifecycle
    payload:
      required:
        - run_id
        - phase
        - status
  - id: story-workflow.event.phase.paused
    producer: story-workflow
    role: lifecycle
    payload:
      required:
        - run_id
        - phase
        - pause_reason
  - id: story-workflow.event.phase.resumed
    producer: story-workflow
    role: lifecycle
    payload:
      required:
        - run_id
        - phase
  - id: story-workflow.event.phase.escalated
    producer: story-workflow
    role: lifecycle
    payload:
      required:
        - run_id
        - phase
        - escalation_reason
  - id: story-workflow.event.transition.rejected
    producer: story-workflow
    role: guard
    payload:
      required:
        - run_id
        - from_phase
        - to_phase
        - reason
  - id: story-workflow.event.run.restarted
    producer: story-workflow
    role: recovery
    payload:
      required:
        - previous_run_id
        - new_run_id
```
<!-- FORMAL-SPEC:END -->
