---
id: formal.execution-planning.scenarios
title: Execution Planning Scenarios
status: active
doc_kind: spec
context: execution-planning
spec_kind: scenario-set
version: 1
prose_refs:
  - concept/technical-design/66_story_planung_abhaengigkeiten_ausfuehrungsplanung.md
---

# Execution Planning Scenarios

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.execution-planning.scenarios
schema_version: 1
kind: scenario-set
context: execution-planning
scenarios:
  - id: execution-planning.scenario.structured-proposal-becomes-canonical-ready-state
    start:
      status: execution-planning.status.unstarted
    trace:
      - command: execution-planning.command.submit-planning-proposal
    expected_end:
      status: execution-planning.status.ready
    requires:
      - execution-planning.invariant.agent_handoff_uses_structured_planning_proposals
      - execution-planning.invariant.canonical_execution_plan_is_derived_not_blindly_imported
  - id: execution-planning.scenario.completed-predecessor-unblocks-successor
    start:
      status: execution-planning.status.unstarted
    trace:
      - command: execution-planning.command.compute-readiness
    expected_end:
      status: execution-planning.status.ready
    requires:
      - execution-planning.invariant.ready_requires_all_hard_dependencies_and_no_open_blocker
  - id: execution-planning.scenario.external-blocker-prevents-start
    start:
      status: execution-planning.status.unstarted
    trace:
      - command: execution-planning.command.record-blocker
    expected_end:
      status: execution-planning.status.blocked_external
    requires:
      - execution-planning.invariant.external_and_human_gates_are_first_class_blockers
      - execution-planning.invariant.no_story_may_enter_flight_with_unresolved_hard_predecessor
  - id: execution-planning.scenario.rulebook-compilation-stays-below-central-caps
    start:
      status: execution-planning.status.ready
    trace:
      - command: execution-planning.command.compile-rulebook
    expected_end:
      status: execution-planning.status.blocked_capacity
    requires:
      - execution-planning.invariant.rulebook_inputs_compile_into_canonical_planning_state
      - execution-planning.invariant.scheduling_precedence_is_hard_graph_then_budget_then_rulebook
  - id: execution-planning.scenario.feasible-story-is-held-back-by-capacity
    start:
      status: execution-planning.status.ready
    trace:
      - command: execution-planning.command.issue-scheduling-decision
    expected_end:
      status: execution-planning.status.blocked_capacity
    requires:
      - execution-planning.invariant.feasibility_and_scheduling_policy_are_distinct
      - execution-planning.invariant.capacity_policy_may_reduce_parallelism_without_negating_feasibility
  - id: execution-planning.scenario.human-gate-clearing-makes-story-ready
    start:
      status: execution-planning.status.blocked_human
    trace:
      - command: execution-planning.command.clear-gate
    expected_end:
      status: execution-planning.status.ready
    requires:
      - execution-planning.invariant.external_and_human_gates_are_first_class_blockers
  - id: execution-planning.scenario.wave-failure-collapses-active-plan
    start:
      status: execution-planning.status.ready
    trace:
      - command: execution-planning.command.replan
    expected_end:
      status: execution-planning.status.blocked_conflict
    requires:
      - execution-planning.invariant.wave_failure_requires_collapse_or_replan
  - id: execution-planning.scenario.dependency-cycle-escalates
    start:
      status: execution-planning.status.unstarted
    trace:
      - command: execution-planning.command.declare-dependency
    expected_end:
      status: execution-planning.status.blocked_conflict
    requires:
      - execution-planning.invariant.dependency_cycles_require_human_escalation
      - execution-planning.invariant.deadlocked_subgraphs_are_quarantined_before_remainder_progresses
```
<!-- FORMAL-SPEC:END -->
