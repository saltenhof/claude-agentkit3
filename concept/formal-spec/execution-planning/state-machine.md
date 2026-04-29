---
id: formal.execution-planning.state-machine
title: Execution Planning State Machine
status: active
doc_kind: spec
context: execution-planning
spec_kind: state-machine
version: 1
prose_refs:
  - concept/technical-design/70_story_planung_abhaengigkeiten_ausfuehrungsplanung.md
  - concept/technical-design/91_api_event_katalog.md
---

# Execution Planning State Machine

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.execution-planning.state-machine
schema_version: 1
kind: state-machine
context: execution-planning
states:
  - id: execution-planning.status.unstarted
    initial: true
  - id: execution-planning.status.ready
    terminal: true
  - id: execution-planning.status.flight
  - id: execution-planning.status.done
    terminal: true
  - id: execution-planning.status.blocked_external
    terminal: true
  - id: execution-planning.status.blocked_human
    terminal: true
  - id: execution-planning.status.blocked_capacity
    terminal: true
  - id: execution-planning.status.blocked_conflict
    terminal: true
transitions:
  - id: execution-planning.transition.unstarted_to_ready
    from: execution-planning.status.unstarted
    to: execution-planning.status.ready
    guard: execution-planning.invariant.ready_requires_all_hard_dependencies_and_no_open_blocker
  - id: execution-planning.transition.ready_to_flight
    from: execution-planning.status.ready
    to: execution-planning.status.flight
    guard: execution-planning.invariant.flight_requires_ready_and_scheduling_allowance
  - id: execution-planning.transition.flight_to_done
    from: execution-planning.status.flight
    to: execution-planning.status.done
  - id: execution-planning.transition.unstarted_to_blocked_external
    from: execution-planning.status.unstarted
    to: execution-planning.status.blocked_external
  - id: execution-planning.transition.unstarted_to_blocked_human
    from: execution-planning.status.unstarted
    to: execution-planning.status.blocked_human
  - id: execution-planning.transition.ready_to_blocked_capacity
    from: execution-planning.status.ready
    to: execution-planning.status.blocked_capacity
    guard: execution-planning.invariant.capacity_policy_may_reduce_parallelism_without_negating_feasibility
  - id: execution-planning.transition.ready_to_blocked_conflict
    from: execution-planning.status.ready
    to: execution-planning.status.blocked_conflict
  - id: execution-planning.transition.blocked_external_to_ready
    from: execution-planning.status.blocked_external
    to: execution-planning.status.ready
    guard: execution-planning.invariant.external_and_human_gates_are_first_class_blockers
  - id: execution-planning.transition.blocked_human_to_ready
    from: execution-planning.status.blocked_human
    to: execution-planning.status.ready
    guard: execution-planning.invariant.external_and_human_gates_are_first_class_blockers
  - id: execution-planning.transition.blocked_capacity_to_ready
    from: execution-planning.status.blocked_capacity
    to: execution-planning.status.ready
  - id: execution-planning.transition.blocked_conflict_to_ready
    from: execution-planning.status.blocked_conflict
    to: execution-planning.status.ready
compound_rules:
  - id: execution-planning.rule.feasibility_precedes_scheduling
    description: A story may be feasible yet still remain unscheduled because scheduling policy applies after feasibility.
```
<!-- FORMAL-SPEC:END -->
