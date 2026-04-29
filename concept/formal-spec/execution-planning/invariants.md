---
id: formal.execution-planning.invariants
title: Execution Planning Invariants
status: active
doc_kind: spec
context: execution-planning
spec_kind: invariant-set
version: 1
prose_refs:
  - concept/technical-design/70_story_planung_abhaengigkeiten_ausfuehrungsplanung.md
---

# Execution Planning Invariants

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.execution-planning.invariants
schema_version: 1
kind: invariant-set
context: execution-planning
invariants:
  - id: execution-planning.invariant.story_creation_feeds_planning_metadata
    scope: creation
    rule: story creation and later refinement must feed planning metadata such as dependencies, repos, human touchpoints, and external prerequisites into the planning domain
  - id: execution-planning.invariant.agent_handoff_uses_structured_planning_proposals
    scope: adapters
    rule: agent-side planning handoff into AK3 uses a structured versioned planning proposal contract; free prose or DSL alone is not the official runtime boundary
  - id: execution-planning.invariant.imported_planning_assertions_carry_provenance
    scope: audit
    rule: imported planning assertions carry producer, evidence, and revision provenance so proposed dependencies, blockers, or waves do not become unauditable hard truth
  - id: execution-planning.invariant.canonical_execution_plan_is_derived_not_blindly_imported
    scope: adapters
    rule: the canonical execution plan is derived and validated by AK3 from accepted planning state and may never be treated as a blind passthrough of an agent proposal
  - id: execution-planning.invariant.optional_human_review_does_not_block_readiness
    scope: human-interaction
    rule: optional human review for quality improvement or validation may enrich planning quality but may never by itself prevent READY, wave computation, or plan activation
  - id: execution-planning.invariant.blocking_human_gate_requires_missing_rights_mandate_or_expertise
    scope: human-interaction
    rule: a blocking human gate exists only when the agent cannot resolve the blockage because rights, mandate, required expertise, or official external decision authority are missing
  - id: execution-planning.invariant.no_story_may_enter_flight_with_unresolved_hard_predecessor
    scope: readiness
    rule: a story may never enter FLIGHT while any hard predecessor or hard gate remains unresolved
  - id: execution-planning.invariant.ready_requires_all_hard_dependencies_and_no_open_blocker
    scope: readiness
    rule: READY requires all hard dependencies to be DONE and no active blocker of kind external, human, conflict, or contract to remain open
  - id: execution-planning.invariant.flight_requires_ready_and_scheduling_allowance
    scope: scheduling
    rule: a story may enter FLIGHT only if it is READY and the current scheduling policy explicitly allows its admission into the effective batch
  - id: execution-planning.invariant.soft_dependencies_do_not_block_pure_feasibility
    scope: scheduling
    rule: soft dependencies may influence prioritization or scheduling but may never by themselves prevent a story from becoming READY
  - id: execution-planning.invariant.external_and_human_gates_are_first_class_blockers
    scope: blockers
    rule: external and human gates are typed blocker objects that affect readiness directly and may not exist only as comments or free text
  - id: execution-planning.invariant.feasibility_and_scheduling_policy_are_distinct
    scope: scheduling
    rule: execution feasibility and execution scheduling policy are separate evaluations and may not collapse into one boolean decision
  - id: execution-planning.invariant.capacity_policy_may_reduce_parallelism_without_negating_feasibility
    scope: scheduling
    rule: capacity and risk policy may reduce effective parallelism below theoretical feasibility without changing the underlying feasibility result
  - id: execution-planning.invariant.scheduling_precedence_is_hard_graph_then_budget_then_rulebook
    scope: scheduling
    rule: "scheduling precedence is strict: hard graph and gate constraints first, central budget and risk caps second, project rulebooks and hints third"
  - id: execution-planning.invariant.execution_waves_and_batches_are_project_scoped
    scope: multi-tenancy
    rule: execution waves, ready sets, critical paths, and scheduling decisions are always project scoped and may not aggregate stories across different project_key values
  - id: execution-planning.invariant.e2e_and_endgate_stories_require_full_predecessor_sets
    scope: gating
    rule: endgate, e2e, and aggregate acceptance stories become READY only when their full required predecessor set is DONE
  - id: execution-planning.invariant.plan_revisions_are_auditable
    scope: audit
    rule: every recomputation that changes the graph, readiness set, critical path, wave structure, or scheduling decision produces an auditable planning revision
  - id: execution-planning.invariant.plan_revisions_are_idempotent_per_revision
    scope: audit
    rule: planning recomputation is revision bound and idempotent so the same graph and policy inputs cannot produce competing authoritative planning states
  - id: execution-planning.invariant.rulebook_inputs_compile_into_canonical_planning_state
    scope: adapters
    rule: project-specific rulebooks are input artifacts only and must compile into canonical planning entities and revisions before they influence runtime decisions
  - id: execution-planning.invariant.wave_failure_requires_collapse_or_replan
    scope: recovery
    rule: partial failure or conflict inside an active execution wave must mark the wave collapsed or trigger an auditable replan instead of silently continuing with stale membership
  - id: execution-planning.invariant.dependency_cycles_require_human_escalation
    scope: recovery
    rule: detected dependency cycles or deadlocked worklists are escalated explicitly and are never silently bypassed by the orchestrator
  - id: execution-planning.invariant.deadlocked_subgraphs_are_quarantined_before_remainder_progresses
    scope: recovery
    rule: a detected cycle or deadlocked planning subgraph is quarantined and escalated fail-closed instead of silently contaminating scheduling for unrelated stories
```
<!-- FORMAL-SPEC:END -->
