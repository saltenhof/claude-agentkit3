---
id: formal.execution-planning.commands
title: Execution Planning Commands
status: active
doc_kind: spec
context: execution-planning
spec_kind: command-set
version: 1
prose_refs:
  - concept/technical-design/70_story_planung_abhaengigkeiten_ausfuehrungsplanung.md
  - concept/technical-design/91_api_event_katalog.md
---

# Execution Planning Commands

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.execution-planning.commands
schema_version: 1
kind: command-set
context: execution-planning
commands:
  - id: execution-planning.command.capture-planning-metadata
    signature: internal capture planning metadata for a story during creation or refinement
    allowed_statuses:
      - execution-planning.status.unstarted
    requires:
      - execution-planning.invariant.story_creation_feeds_planning_metadata
    emits:
      - execution-planning.event.planning_metadata_captured
  - id: execution-planning.command.submit-planning-proposal
    signature: official submit of a structured planning proposal from agent analysis or another intake path
    allowed_statuses:
      - execution-planning.status.unstarted
      - execution-planning.status.ready
      - execution-planning.status.blocked_external
      - execution-planning.status.blocked_human
      - execution-planning.status.blocked_capacity
      - execution-planning.status.blocked_conflict
      - execution-planning.status.done
    requires:
      - execution-planning.invariant.agent_handoff_uses_structured_planning_proposals
      - execution-planning.invariant.imported_planning_assertions_carry_provenance
      - execution-planning.invariant.canonical_execution_plan_is_derived_not_blindly_imported
    emits:
      - execution-planning.event.planning_proposal_submitted
      - execution-planning.event.planning_proposal_rejected
      - execution-planning.event.planning_proposal_applied
  - id: execution-planning.command.request-human-review
    signature: non-blocking request for human quality review or validation of planning artifacts
    allowed_statuses:
      - execution-planning.status.unstarted
      - execution-planning.status.ready
      - execution-planning.status.blocked_capacity
      - execution-planning.status.done
    requires:
      - execution-planning.invariant.optional_human_review_does_not_block_readiness
    emits:
      - execution-planning.event.human_review_requested
      - execution-planning.event.human_review_recorded
  - id: execution-planning.command.declare-dependency
    signature: internal or official administrative declaration of a dependency edge
    allowed_statuses:
      - execution-planning.status.unstarted
      - execution-planning.status.ready
      - execution-planning.status.blocked_external
      - execution-planning.status.blocked_human
      - execution-planning.status.blocked_conflict
    requires:
      - execution-planning.invariant.no_story_may_enter_flight_with_unresolved_hard_predecessor
    emits:
      - execution-planning.event.dependency_declared
  - id: execution-planning.command.compile-rulebook
    signature: official administrative compile of a project-specific planning rulebook into canonical planning records
    allowed_statuses:
      - execution-planning.status.unstarted
      - execution-planning.status.ready
      - execution-planning.status.blocked_external
      - execution-planning.status.blocked_human
      - execution-planning.status.blocked_capacity
      - execution-planning.status.blocked_conflict
      - execution-planning.status.done
    requires:
      - execution-planning.invariant.rulebook_inputs_compile_into_canonical_planning_state
      - execution-planning.invariant.scheduling_precedence_is_hard_graph_then_budget_then_rulebook
    emits:
      - execution-planning.event.planning_rulebook_compiled
  - id: execution-planning.command.record-blocker
    signature: internal or official administrative recording of external, human, capacity, or conflict blocker
    allowed_statuses:
      - execution-planning.status.unstarted
      - execution-planning.status.ready
      - execution-planning.status.blocked_capacity
      - execution-planning.status.blocked_conflict
    requires:
      - execution-planning.invariant.external_and_human_gates_are_first_class_blockers
    emits:
      - execution-planning.event.blocker_recorded
  - id: execution-planning.command.clear-gate
    signature: official administrative clearance of a human or external gate with audit evidence
    allowed_statuses:
      - execution-planning.status.blocked_external
      - execution-planning.status.blocked_human
    requires:
      - execution-planning.invariant.external_and_human_gates_are_first_class_blockers
    emits:
      - execution-planning.event.external_gate_cleared
      - execution-planning.event.human_gate_satisfied
  - id: execution-planning.command.compute-readiness
    signature: internal compute readiness set from graph, blockers, and hard rules
    allowed_statuses:
      - execution-planning.status.unstarted
      - execution-planning.status.blocked_external
      - execution-planning.status.blocked_human
      - execution-planning.status.blocked_conflict
      - execution-planning.status.blocked_capacity
      - execution-planning.status.done
    requires:
      - execution-planning.invariant.ready_requires_all_hard_dependencies_and_no_open_blocker
    emits:
      - execution-planning.event.story_became_ready
      - execution-planning.event.story_became_blocked
  - id: execution-planning.command.compute-execution-plan
    signature: internal derive execution waves, critical path, and ready queue from planning state
    allowed_statuses:
      - execution-planning.status.ready
      - execution-planning.status.blocked_capacity
      - execution-planning.status.done
    requires:
      - execution-planning.invariant.execution_waves_and_batches_are_project_scoped
    emits:
      - execution-planning.event.execution_plan_created
  - id: execution-planning.command.replan
    signature: internal or official recompute plan after dependency, blocker, or state change
    allowed_statuses:
      - execution-planning.status.ready
      - execution-planning.status.flight
      - execution-planning.status.done
      - execution-planning.status.blocked_external
      - execution-planning.status.blocked_human
      - execution-planning.status.blocked_capacity
      - execution-planning.status.blocked_conflict
    requires:
      - execution-planning.invariant.plan_revisions_are_auditable
    emits:
      - execution-planning.event.execution_plan_replanned
  - id: execution-planning.command.issue-scheduling-decision
    signature: internal emit recommended and maximum allowed batch for the orchestrator
    allowed_statuses:
      - execution-planning.status.ready
      - execution-planning.status.blocked_capacity
    requires:
      - execution-planning.invariant.feasibility_and_scheduling_policy_are_distinct
      - execution-planning.invariant.capacity_policy_may_reduce_parallelism_without_negating_feasibility
      - execution-planning.invariant.scheduling_precedence_is_hard_graph_then_budget_then_rulebook
    emits:
      - execution-planning.event.scheduling_decision_issued
```
<!-- FORMAL-SPEC:END -->
