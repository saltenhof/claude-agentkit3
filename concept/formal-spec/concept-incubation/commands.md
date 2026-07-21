---
id: formal.concept-incubation.commands
title: Concept Incubation Commands
status: active
doc_kind: spec
context: concept-incubation
spec_kind: command-set
version: 1
prose_refs:
  - concept/technical-design/78_concept_incubation_process.md
---

# Concept Incubation Commands

Offizielle Commands des Council-Orchestrators. Alle mutierenden Commands
setzen eine gueltige Writer-Lease und das CAS-Schreibprotokoll voraus
(FK-78 §78.4).

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.concept-incubation.commands
schema_version: 1
kind: command-set
context: concept-incubation
commands:
  - id: concept-incubation.command.create-run
    signature: skill concept-incubation create-run --profile <profile> --title <title>
    allowed_statuses: []
    requires:
      - concept-incubation.invariant.run_state_single_writer_cas
    emits:
      - concept-incubation.event.run.created
      - concept-incubation.event.lease.acquired
  - id: concept-incubation.command.freeze-baseline
    signature: internal freeze_baseline <run_id>
    allowed_statuses:
      - concept-incubation.status.framing
    requires:
      - concept-incubation.invariant.baseline_frozen_before_staffing
    emits:
      - concept-incubation.event.baseline.frozen
  - id: concept-incubation.command.approve-staffing
    signature: internal approve_staffing <run_id> <participants>
    allowed_statuses:
      - concept-incubation.status.staffing
    requires:
      - concept-incubation.invariant.staffing_requires_user_approval
      - concept-incubation.invariant.data_release_bounded_per_participant
    emits:
      - concept-incubation.event.staffing.approved
  - id: concept-incubation.command.dispatch-round
    signature: internal dispatch_round <run_id> <round>
    allowed_statuses:
      - concept-incubation.status.proposing
    requires:
      - concept-incubation.invariant.worker_writes_only_own_outbox
    emits:
      - concept-incubation.event.round.dispatched
  - id: concept-incubation.command.seal-round
    signature: internal seal_round <run_id> <round>
    allowed_statuses:
      - concept-incubation.status.proposing
    requires:
      - concept-incubation.invariant.round_seal_before_cross_read
    emits:
      - concept-incubation.event.round.sealed
  - id: concept-incubation.command.freeze-input-sources
    signature: internal freeze_input_sources <run_id>
    allowed_statuses:
      - concept-incubation.status.converging
    requires:
      - concept-incubation.invariant.input_freeze_and_inventory_closure_before_synthesis
      - concept-incubation.invariant.every_input_unit_claimed_or_empty_reasoned
    emits:
      - concept-incubation.event.input-sources.frozen
      - concept-incubation.event.claims.inventory-closed
  - id: concept-incubation.command.record-synthesis
    signature: internal record_synthesis <run_id>
    allowed_statuses:
      - concept-incubation.status.synthesizing
    requires:
      - concept-incubation.invariant.derived_sources_registered
    emits:
      - concept-incubation.event.synthesis.recorded
  - id: concept-incubation.command.record-decisions
    signature: internal record_po_decisions <run_id>
    allowed_statuses:
      - concept-incubation.status.deciding
    requires:
      - concept-incubation.invariant.open_questions_decided_or_deferred_visibly
    emits:
      - concept-incubation.event.decisions.recorded
  - id: concept-incubation.command.acquire-scope-locks
    signature: internal acquire_scope_locks <run_id> <scopes>
    allowed_statuses:
      - concept-incubation.status.deciding
    requires:
      - concept-incubation.invariant.scope_lock_exclusive_during_promoting
    emits:
      - concept-incubation.event.scope-lock.acquired
  - id: concept-incubation.command.enter-promotion
    signature: internal enter_promotion <run_id>
    allowed_statuses:
      - concept-incubation.status.deciding
    requires:
      - concept-incubation.invariant.disposition_closure_and_locks_before_promoting
      - concept-incubation.invariant.derived_sources_registered
    emits:
      - concept-incubation.event.promotion.started
  - id: concept-incubation.command.complete-promotion
    signature: internal complete_promotion <run_id>
    allowed_statuses:
      - concept-incubation.status.promoting
    requires:
      - concept-incubation.invariant.promoted_requires_full_closure
      - concept-incubation.invariant.coverage_final_before_promotion_exit
      - concept-incubation.invariant.diff_hunks_fully_covered
      - concept-incubation.invariant.receipt_reviewer_independent
      - concept-incubation.invariant.open_findings_block_promotion
      - concept-incubation.invariant.lock_release_requires_cas_ownership
    emits:
      - concept-incubation.event.promotion.completed
      - concept-incubation.event.scope-lock.released
      - concept-incubation.event.run.closed
  - id: concept-incubation.command.fail-promotion
    signature: internal fail_promotion <run_id> <findings>
    allowed_statuses:
      - concept-incubation.status.promoting
    emits:
      - concept-incubation.event.promotion.check-failed
  - id: concept-incubation.command.retry-promotion
    signature: internal retry_promotion <run_id>
    allowed_statuses:
      - concept-incubation.status.promotion_failed
    requires:
      - concept-incubation.invariant.open_findings_block_promotion
      - concept-incubation.invariant.scope_lock_exclusive_during_promoting
    emits:
      - concept-incubation.event.promotion.retried
  - id: concept-incubation.command.block-run
    signature: internal block_run <run_id> <reason>
    allowed_statuses:
      - concept-incubation.status.framing
      - concept-incubation.status.staffing
      - concept-incubation.status.proposing
      - concept-incubation.status.converging
      - concept-incubation.status.synthesizing
      - concept-incubation.status.deciding
      - concept-incubation.status.promoting
      - concept-incubation.status.recheck
      - concept-incubation.status.promotion_failed
    emits:
      - concept-incubation.event.run.blocked
  - id: concept-incubation.command.resume-run
    signature: internal resume_run <run_id>
    allowed_statuses:
      - concept-incubation.status.blocked
    requires:
      - concept-incubation.invariant.resume_restores_recorded_state
    emits:
      - concept-incubation.event.run.resumed
  - id: concept-incubation.command.adjudicate-recheck
    signature: internal adjudicate_recheck <run_id>
    allowed_statuses:
      - concept-incubation.status.recheck
    requires:
      - concept-incubation.invariant.recheck_requires_adjudication
    emits:
      - concept-incubation.event.recheck.adjudicated
  - id: concept-incubation.command.takeover-lease
    signature: internal takeover_lease <run_id>
    allowed_statuses:
      - concept-incubation.status.framing
      - concept-incubation.status.staffing
      - concept-incubation.status.proposing
      - concept-incubation.status.converging
      - concept-incubation.status.synthesizing
      - concept-incubation.status.deciding
      - concept-incubation.status.promoting
      - concept-incubation.status.blocked
      - concept-incubation.status.recheck
      - concept-incubation.status.promotion_failed
    requires:
      - concept-incubation.invariant.takeover_only_after_ttl_or_release
    emits:
      - concept-incubation.event.lease.taken-over
  - id: concept-incubation.command.abort-run
    signature: internal abort_run <run_id> <reason>
    allowed_statuses:
      - concept-incubation.status.framing
      - concept-incubation.status.staffing
      - concept-incubation.status.proposing
      - concept-incubation.status.converging
      - concept-incubation.status.synthesizing
      - concept-incubation.status.deciding
      - concept-incubation.status.promoting
      - concept-incubation.status.blocked
      - concept-incubation.status.recheck
      - concept-incubation.status.promotion_failed
    requires:
      - concept-incubation.invariant.aborted_run_leaves_visible_blockers
      - concept-incubation.invariant.lock_release_requires_cas_ownership
    emits:
      - concept-incubation.event.scope-lock.released
      - concept-incubation.event.run.aborted
```
<!-- FORMAL-SPEC:END -->
