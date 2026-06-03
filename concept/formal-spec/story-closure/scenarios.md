---
id: formal.story-closure.scenarios
title: Story Closure Scenarios
status: active
doc_kind: spec
context: story-closure
spec_kind: scenario-set
version: 1
prose_refs:
  - concept/technical-design/12_github_integration_repo_operationen.md
  - concept/technical-design/29_closure_sequence.md
  - concept/technical-design/31_branch_guard_orchestrator_guard_artefaktschutz.md
  - concept/technical-design/33_deterministische_checks_stage_registry_policy_engine.md
  - concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md
  - concept/technical-design/04_betrieb_monitoring_audit_runbooks.md
---

# Story Closure Scenarios

Diese Traces pruefen den offiziellen Closure-Pfad und seine kritischen
Edge Cases.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-closure.scenarios
schema_version: 1
kind: scenario-set
context: story-closure
scenarios:
  - id: story-closure.scenario.happy-path-ff-only
    start:
      status: story-closure.status.requested
    trace:
      - command: story-closure.command.execute-default
    expected_end:
      status: story-closure.status.completed
    requires:
      - story-closure.invariant.ff_only_is_default_policy
      - story-closure.invariant.integrity_gate_precedes_merge_block
      - story-closure.invariant.merge_block_runs_under_serialization_lock
      - story-closure.invariant.integrated_candidate_scanned_green_before_push
      - story-closure.invariant.push_inside_lock_after_green_scan
      - story-closure.invariant.push_precedes_merge
      - story-closure.invariant.post_merge_reconcile_before_lock_release
      - story-closure.invariant.completed_requires_merge_and_story_close
  - id: story-closure.scenario.main-drift-red-candidate-escalates
    start:
      status: story-closure.status.merge_lock_acquired
    trace:
      - command: story-closure.command.execute-default
    expected_end:
      status: story-closure.status.escalated
    requires:
      - story-closure.invariant.integrated_candidate_scanned_green_before_push
      - story-closure.invariant.red_integrated_candidate_blocks_merge
  - id: story-closure.scenario.ff-only-rejected-then-no-ff-fallback
    start:
      status: story-closure.status.requested
    trace:
      - command: story-closure.command.execute-default
      - command: story-closure.command.execute-no-ff
    expected_end:
      status: story-closure.status.completed
    requires:
      - story-closure.invariant.ff_only_is_default_policy
      - story-closure.invariant.no_ff_only_official_fallback
      - story-closure.invariant.branch_guard_allows_official_closure
  - id: story-closure.scenario.manual-history-rewrite-rejected
    start:
      status: story-closure.status.policy_checked
    trace:
      - command: story-closure.command.illegal-history-rewrite
    expected_end:
      status: story-closure.status.escalated
    requires:
      - story-closure.invariant.manual_history_rewrite_forbidden
  - id: story-closure.scenario.resume-from-pushed-unmerged
    start:
      status: story-closure.status.story_branch_pushed
    trace:
      - command: story-closure.command.execute-default
    expected_end:
      status: story-closure.status.completed
    requires:
      - story-closure.invariant.merge_requires_pushed_story_branch
      - story-closure.invariant.completed_requires_merge_and_story_close
  - id: story-closure.scenario.merge-rejected-after-push
    start:
      status: story-closure.status.story_branch_pushed
    trace:
      - command: story-closure.command.execute-default
    expected_end:
      status: story-closure.status.escalated
    requires:
      - story-closure.invariant.merge_rejection_never_completes_closure
  # NOT_APPLICABLE — Sonar deliberately absent (sonarqube.available false,
  # FK-33 §33.6.5): resumed from the absent-Sonar intra-lock checkpoint, the
  # integrated-candidate Sonar scan / ledger reconcile / tree_hash assert /
  # Dimension 9 are skipped WITHOUT fail-closed while Dimensions 1-8 and the
  # push/ff-merge/reconcile sequence remain in force, terminating at completed.
  - id: story-closure.scenario.sonar-absent-closure-skips-sonar-completes
    start:
      status: story-closure.status.sonar_not_applicable_integrity_passed
    trace:
      - command: story-closure.command.execute-default
    expected_end:
      status: story-closure.status.completed
    requires:
      - story-closure.invariant.closure_proceeds_without_sonar_when_not_applicable
      - story-closure.invariant.merge_requires_pushed_story_branch
      - story-closure.invariant.completed_requires_merge_and_story_close
  # NOT_APPLICABLE — mode fast (FK-24 §24.3.4 / mode_lock fast §24.3.3,
  # FK-33 §33.6.5): resumed from the Sanity-Gate checkpoint that replaces the
  # nine-dimension Integrity-Gate and the integrated-candidate Sonar scan,
  # terminating at completed.
  - id: story-closure.scenario.fast-mode-closure-sanity-gate-completes
    start:
      status: story-closure.status.sanity_gate_passed
    trace:
      - command: story-closure.command.execute-default
    expected_end:
      status: story-closure.status.completed
    requires:
      - story-closure.invariant.fast_mode_closure_uses_sanity_gate
      - story-closure.invariant.merge_requires_pushed_story_branch
      - story-closure.invariant.completed_requires_merge_and_story_close
```
<!-- FORMAL-SPEC:END -->
