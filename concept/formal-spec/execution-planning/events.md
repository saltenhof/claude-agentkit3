---
id: formal.execution-planning.events
title: Execution Planning Events
status: active
doc_kind: spec
context: execution-planning
spec_kind: event-set
version: 1
prose_refs:
  - concept/technical-design/66_story_planung_abhaengigkeiten_ausfuehrungsplanung.md
  - concept/technical-design/91_api_event_katalog.md
---

# Execution Planning Events

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.execution-planning.events
schema_version: 1
kind: event-set
context: execution-planning
events:
  - id: execution-planning.event.planning_metadata_captured
    role: lifecycle
  - id: execution-planning.event.dependency_declared
    role: lifecycle
  - id: execution-planning.event.planning_rulebook_compiled
    role: audit
  - id: execution-planning.event.blocker_recorded
    role: governance
  - id: execution-planning.event.story_became_ready
    role: lifecycle
  - id: execution-planning.event.story_became_blocked
    role: governance
  - id: execution-planning.event.execution_plan_created
    role: audit
  - id: execution-planning.event.execution_plan_replanned
    role: audit
  - id: execution-planning.event.scheduling_decision_issued
    role: lifecycle
  - id: execution-planning.event.external_gate_cleared
    role: governance
  - id: execution-planning.event.human_gate_satisfied
    role: governance
  - id: execution-planning.event.capacity_window_opened
    role: lifecycle
  - id: execution-planning.event.capacity_consumed
    role: audit
  - id: execution-planning.event.wave_collapsed
    role: audit
  - id: execution-planning.event.planning_state_sync_conflict
    role: audit
  - id: execution-planning.event.deadlock_detected
    role: audit
  - id: execution-planning.event.dependency_cycle_detected
    role: audit
```
<!-- FORMAL-SPEC:END -->
