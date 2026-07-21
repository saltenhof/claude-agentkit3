---
id: formal.concept-incubation.state-machine
title: Concept Incubation State Machine
status: active
doc_kind: spec
context: concept-incubation
spec_kind: state-machine
version: 1
prose_refs:
  - concept/technical-design/78_concept_incubation_process.md
---

# Concept Incubation State Machine

Der administrative Lauf-Lifecycle (`run_status`). Die fachlichen Achsen
`promotion_disposition` und `assertion_status` sind KEINE Zustaende dieser
Maschine (FK-78 §78.11/§78.12).

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.concept-incubation.state-machine
schema_version: 1
kind: state-machine
context: concept-incubation
states:
  - id: concept-incubation.status.framing
    initial: true
  - id: concept-incubation.status.staffing
  - id: concept-incubation.status.proposing
  - id: concept-incubation.status.converging
  - id: concept-incubation.status.synthesizing
  - id: concept-incubation.status.deciding
  - id: concept-incubation.status.promoting
  - id: concept-incubation.status.promotion_failed
  - id: concept-incubation.status.blocked
  - id: concept-incubation.status.recheck
  - id: concept-incubation.status.closed
    terminal: true
  - id: concept-incubation.status.aborted
    terminal: true
transitions:
  - id: concept-incubation.transition.framing_to_staffing
    from: concept-incubation.status.framing
    to: concept-incubation.status.staffing
    guard: concept-incubation.invariant.baseline_frozen_before_staffing
  - id: concept-incubation.transition.staffing_to_proposing
    from: concept-incubation.status.staffing
    to: concept-incubation.status.proposing
    guard: concept-incubation.invariant.staffing_requires_user_approval
  - id: concept-incubation.transition.proposing_to_converging
    from: concept-incubation.status.proposing
    to: concept-incubation.status.converging
    guard: concept-incubation.invariant.round_seal_before_cross_read
  - id: concept-incubation.transition.converging_to_proposing
    from: concept-incubation.status.converging
    to: concept-incubation.status.proposing
  - id: concept-incubation.transition.converging_to_synthesizing
    from: concept-incubation.status.converging
    to: concept-incubation.status.synthesizing
    guard: concept-incubation.invariant.input_freeze_and_inventory_closure_before_synthesis
  - id: concept-incubation.transition.synthesizing_to_deciding
    from: concept-incubation.status.synthesizing
    to: concept-incubation.status.deciding
  - id: concept-incubation.transition.deciding_to_promoting
    from: concept-incubation.status.deciding
    to: concept-incubation.status.promoting
    guard: concept-incubation.invariant.disposition_closure_and_locks_before_promoting
  - id: concept-incubation.transition.promoting_to_closed
    from: concept-incubation.status.promoting
    to: concept-incubation.status.closed
    guard: concept-incubation.invariant.promoted_requires_full_closure
  - id: concept-incubation.transition.promoting_to_promotion_failed
    from: concept-incubation.status.promoting
    to: concept-incubation.status.promotion_failed
  - id: concept-incubation.transition.promotion_failed_to_promoting
    from: concept-incubation.status.promotion_failed
    to: concept-incubation.status.promoting
    guard: concept-incubation.invariant.scope_lock_exclusive_during_promoting
  - id: concept-incubation.transition.promotion_failed_to_aborted
    from: concept-incubation.status.promotion_failed
    to: concept-incubation.status.aborted
    guard: concept-incubation.invariant.aborted_run_leaves_visible_blockers
  - id: concept-incubation.transition.framing_to_blocked
    from: concept-incubation.status.framing
    to: concept-incubation.status.blocked
  - id: concept-incubation.transition.staffing_to_blocked
    from: concept-incubation.status.staffing
    to: concept-incubation.status.blocked
  - id: concept-incubation.transition.proposing_to_blocked
    from: concept-incubation.status.proposing
    to: concept-incubation.status.blocked
  - id: concept-incubation.transition.converging_to_blocked
    from: concept-incubation.status.converging
    to: concept-incubation.status.blocked
  - id: concept-incubation.transition.synthesizing_to_blocked
    from: concept-incubation.status.synthesizing
    to: concept-incubation.status.blocked
  - id: concept-incubation.transition.deciding_to_blocked
    from: concept-incubation.status.deciding
    to: concept-incubation.status.blocked
  - id: concept-incubation.transition.promoting_to_blocked
    from: concept-incubation.status.promoting
    to: concept-incubation.status.blocked
  - id: concept-incubation.transition.recheck_to_blocked
    from: concept-incubation.status.recheck
    to: concept-incubation.status.blocked
  - id: concept-incubation.transition.promotion_failed_to_blocked
    from: concept-incubation.status.promotion_failed
    to: concept-incubation.status.blocked
  - id: concept-incubation.transition.blocked_resume_to_recheck
    from: concept-incubation.status.blocked
    to: concept-incubation.status.recheck
    guard: concept-incubation.invariant.resume_restores_recorded_state
  - id: concept-incubation.transition.blocked_resume_to_promotion_failed
    from: concept-incubation.status.blocked
    to: concept-incubation.status.promotion_failed
    guard: concept-incubation.invariant.resume_restores_recorded_state
  - id: concept-incubation.transition.blocked_resume_to_framing
    from: concept-incubation.status.blocked
    to: concept-incubation.status.framing
    guard: concept-incubation.invariant.resume_restores_recorded_state
  - id: concept-incubation.transition.blocked_resume_to_staffing
    from: concept-incubation.status.blocked
    to: concept-incubation.status.staffing
    guard: concept-incubation.invariant.resume_restores_recorded_state
  - id: concept-incubation.transition.blocked_resume_to_proposing
    from: concept-incubation.status.blocked
    to: concept-incubation.status.proposing
    guard: concept-incubation.invariant.resume_restores_recorded_state
  - id: concept-incubation.transition.blocked_resume_to_converging
    from: concept-incubation.status.blocked
    to: concept-incubation.status.converging
    guard: concept-incubation.invariant.resume_restores_recorded_state
  - id: concept-incubation.transition.blocked_resume_to_synthesizing
    from: concept-incubation.status.blocked
    to: concept-incubation.status.synthesizing
    guard: concept-incubation.invariant.resume_restores_recorded_state
  - id: concept-incubation.transition.blocked_resume_to_deciding
    from: concept-incubation.status.blocked
    to: concept-incubation.status.deciding
    guard: concept-incubation.invariant.resume_restores_recorded_state
  - id: concept-incubation.transition.blocked_resume_to_promoting
    from: concept-incubation.status.blocked
    to: concept-incubation.status.promoting
    guard: concept-incubation.invariant.resume_restores_recorded_state
  - id: concept-incubation.transition.converging_to_recheck
    from: concept-incubation.status.converging
    to: concept-incubation.status.recheck
  - id: concept-incubation.transition.recheck_to_converging
    from: concept-incubation.status.recheck
    to: concept-incubation.status.converging
    guard: concept-incubation.invariant.recheck_requires_adjudication
  - id: concept-incubation.transition.synthesizing_to_recheck
    from: concept-incubation.status.synthesizing
    to: concept-incubation.status.recheck
  - id: concept-incubation.transition.deciding_to_recheck
    from: concept-incubation.status.deciding
    to: concept-incubation.status.recheck
  - id: concept-incubation.transition.promoting_to_recheck
    from: concept-incubation.status.promoting
    to: concept-incubation.status.recheck
  - id: concept-incubation.transition.recheck_to_synthesizing
    from: concept-incubation.status.recheck
    to: concept-incubation.status.synthesizing
    guard: concept-incubation.invariant.recheck_requires_adjudication
  - id: concept-incubation.transition.recheck_to_deciding
    from: concept-incubation.status.recheck
    to: concept-incubation.status.deciding
    guard: concept-incubation.invariant.recheck_requires_adjudication
  - id: concept-incubation.transition.recheck_to_promoting
    from: concept-incubation.status.recheck
    to: concept-incubation.status.promoting
    guard: concept-incubation.invariant.recheck_requires_adjudication
  - id: concept-incubation.transition.recheck_to_aborted
    from: concept-incubation.status.recheck
    to: concept-incubation.status.aborted
    guard: concept-incubation.invariant.aborted_run_leaves_visible_blockers
  - id: concept-incubation.transition.framing_to_aborted
    from: concept-incubation.status.framing
    to: concept-incubation.status.aborted
  - id: concept-incubation.transition.staffing_to_aborted
    from: concept-incubation.status.staffing
    to: concept-incubation.status.aborted
  - id: concept-incubation.transition.proposing_to_aborted
    from: concept-incubation.status.proposing
    to: concept-incubation.status.aborted
    guard: concept-incubation.invariant.aborted_run_leaves_visible_blockers
  - id: concept-incubation.transition.converging_to_aborted
    from: concept-incubation.status.converging
    to: concept-incubation.status.aborted
    guard: concept-incubation.invariant.aborted_run_leaves_visible_blockers
  - id: concept-incubation.transition.synthesizing_to_aborted
    from: concept-incubation.status.synthesizing
    to: concept-incubation.status.aborted
    guard: concept-incubation.invariant.aborted_run_leaves_visible_blockers
  - id: concept-incubation.transition.deciding_to_aborted
    from: concept-incubation.status.deciding
    to: concept-incubation.status.aborted
    guard: concept-incubation.invariant.aborted_run_leaves_visible_blockers
  - id: concept-incubation.transition.promoting_to_aborted
    from: concept-incubation.status.promoting
    to: concept-incubation.status.aborted
    guard: concept-incubation.invariant.aborted_run_leaves_visible_blockers
  - id: concept-incubation.transition.blocked_to_aborted
    from: concept-incubation.status.blocked
    to: concept-incubation.status.aborted
    guard: concept-incubation.invariant.aborted_run_leaves_visible_blockers
compound_rules:
  - id: concept-incubation.rule.blocked-resume-target-equals-since-state
    description: Exactly one blocked_resume transition fires per resume, and its target state must equal the state recorded in blocked.since_state of RUN.json; resuming into any other state violates resume_restores_recorded_state.
  - id: concept-incubation.rule.no-normative-write-outside-promoting
    description: Writes below the concept roots are legal only while the owning run is in status promoting and holds the scope locks; every other normative write is a rule violation regardless of state.
  - id: concept-incubation.rule.locks-held-across-failure-states
    description: Scope locks acquired for promoting stay held through promotion_failed, recheck, and blocked; they are released exclusively as an inseparable part of the complete-promotion or abort-run command, that is on the transitions into closed or aborted, with CAS ownership verification. There is no separately callable release command.
  - id: concept-incubation.rule.reject-traces-are-not-expressible-yet
    description: The scenario-set kind expresses declared traces with terminal outcomes only. Rules whose violation must be rejected (stale release, stale write, unauthorised takeover) are therefore carried by invariants rather than by negative traces; expressing explicit reject traces requires the declared compiler follow-up on step-accurate command-transition binding.
```
<!-- FORMAL-SPEC:END -->
