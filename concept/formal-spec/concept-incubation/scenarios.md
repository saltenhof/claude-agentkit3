---
id: formal.concept-incubation.scenarios
title: Concept Incubation Scenarios
status: active
doc_kind: spec
context: concept-incubation
spec_kind: scenario-set
version: 1
prose_refs:
  - concept/technical-design/78_concept_incubation_process.md
---

# Concept Incubation Scenarios

Deklarierte Traces fuer den Lauf-Lifecycle inkl. Ausfall-, Drift-,
Takeover- und Abbruchpfaden. Jeder Trace endet in einem terminalen
Status.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.concept-incubation.scenarios
schema_version: 1
kind: scenario-set
context: concept-incubation
scenarios:
  - id: concept-incubation.scenario.happy-path
    start:
      status: concept-incubation.status.framing
    trace:
      - command: concept-incubation.command.freeze-baseline
      - command: concept-incubation.command.approve-staffing
      - command: concept-incubation.command.dispatch-round
      - command: concept-incubation.command.seal-round
      - command: concept-incubation.command.freeze-input-sources
      - command: concept-incubation.command.record-synthesis
      - command: concept-incubation.command.record-decisions
      - command: concept-incubation.command.acquire-scope-locks
      - command: concept-incubation.command.enter-promotion
      - command: concept-incubation.command.complete-promotion
    expected_end:
      status: concept-incubation.status.closed
    requires:
      - concept-incubation.invariant.promoted_requires_full_closure
      - concept-incubation.invariant.diff_hunks_fully_covered
  - id: concept-incubation.scenario.tension-field-to-po-then-promotion
    start:
      status: concept-incubation.status.converging
    trace:
      - command: concept-incubation.command.freeze-input-sources
      - command: concept-incubation.command.record-synthesis
      - command: concept-incubation.command.record-decisions
      - command: concept-incubation.command.acquire-scope-locks
      - command: concept-incubation.command.enter-promotion
      - command: concept-incubation.command.complete-promotion
    expected_end:
      status: concept-incubation.status.closed
    requires:
      - concept-incubation.invariant.open_questions_decided_or_deferred_visibly
  - id: concept-incubation.scenario.participant-timeout-run-continues
    start:
      status: concept-incubation.status.proposing
    trace:
      - command: concept-incubation.command.seal-round
      - command: concept-incubation.command.freeze-input-sources
      - command: concept-incubation.command.record-synthesis
      - command: concept-incubation.command.record-decisions
      - command: concept-incubation.command.acquire-scope-locks
      - command: concept-incubation.command.enter-promotion
      - command: concept-incubation.command.complete-promotion
    expected_end:
      status: concept-incubation.status.closed
    requires:
      - concept-incubation.invariant.round_seal_before_cross_read
  - id: concept-incubation.scenario.crash-and-resume-to-closure
    start:
      status: concept-incubation.status.blocked
    trace:
      - command: concept-incubation.command.resume-run
      - command: concept-incubation.command.freeze-baseline
      - command: concept-incubation.command.approve-staffing
      - command: concept-incubation.command.dispatch-round
      - command: concept-incubation.command.seal-round
      - command: concept-incubation.command.freeze-input-sources
      - command: concept-incubation.command.record-synthesis
      - command: concept-incubation.command.record-decisions
      - command: concept-incubation.command.acquire-scope-locks
      - command: concept-incubation.command.enter-promotion
      - command: concept-incubation.command.complete-promotion
    expected_end:
      status: concept-incubation.status.closed
    requires:
      - concept-incubation.invariant.resume_restores_recorded_state
  - id: concept-incubation.scenario.drift-recheck-before-landing
    start:
      status: concept-incubation.status.recheck
    trace:
      - command: concept-incubation.command.adjudicate-recheck
      - command: concept-incubation.command.complete-promotion
    expected_end:
      status: concept-incubation.status.closed
    requires:
      - concept-incubation.invariant.recheck_requires_adjudication
      - concept-incubation.invariant.scope_lock_exclusive_during_promoting
  - id: concept-incubation.scenario.gate-red-then-remediation
    start:
      status: concept-incubation.status.promoting
    trace:
      - command: concept-incubation.command.fail-promotion
      - command: concept-incubation.command.retry-promotion
      - command: concept-incubation.command.complete-promotion
    expected_end:
      status: concept-incubation.status.closed
    requires:
      - concept-incubation.invariant.open_findings_block_promotion
      - concept-incubation.invariant.lock_release_requires_cas_ownership
  - id: concept-incubation.scenario.lease-takeover-fences-stale-writer
    start:
      status: concept-incubation.status.synthesizing
    trace:
      - command: concept-incubation.command.takeover-lease
      - command: concept-incubation.command.record-synthesis
      - command: concept-incubation.command.record-decisions
      - command: concept-incubation.command.acquire-scope-locks
      - command: concept-incubation.command.enter-promotion
      - command: concept-incubation.command.complete-promotion
    expected_end:
      status: concept-incubation.status.closed
    requires:
      - concept-incubation.invariant.takeover_only_after_ttl_or_release
      - concept-incubation.invariant.run_state_single_writer_cas
  - id: concept-incubation.scenario.takeover-during-promoting-keeps-cas
    start:
      status: concept-incubation.status.promoting
    trace:
      - command: concept-incubation.command.takeover-lease
      - command: concept-incubation.command.complete-promotion
    expected_end:
      status: concept-incubation.status.closed
    requires:
      - concept-incubation.invariant.takeover_only_after_ttl_or_release
      - concept-incubation.invariant.run_state_single_writer_cas
      - concept-incubation.invariant.mutation_mutex_compare_before_delete
  - id: concept-incubation.scenario.abort-after-failed-promotion-releases-under-cas
    start:
      status: concept-incubation.status.promotion_failed
    trace:
      - command: concept-incubation.command.takeover-lease
      - command: concept-incubation.command.abort-run
    expected_end:
      status: concept-incubation.status.aborted
    requires:
      - concept-incubation.invariant.lock_release_requires_cas_ownership
      - concept-incubation.invariant.aborted_run_leaves_visible_blockers
  - id: concept-incubation.scenario.resume-after-takeover-restores-recorded-state
    start:
      status: concept-incubation.status.blocked
    trace:
      - command: concept-incubation.command.takeover-lease
      - command: concept-incubation.command.resume-run
      - command: concept-incubation.command.abort-run
    expected_end:
      status: concept-incubation.status.aborted
    requires:
      - concept-incubation.invariant.takeover_only_after_ttl_or_release
      - concept-incubation.invariant.resume_restores_recorded_state
  - id: concept-incubation.scenario.abort-leaves-visible-blockers
    start:
      status: concept-incubation.status.deciding
    trace:
      - command: concept-incubation.command.abort-run
    expected_end:
      status: concept-incubation.status.aborted
    requires:
      - concept-incubation.invariant.aborted_run_leaves_visible_blockers
```
<!-- FORMAL-SPEC:END -->
