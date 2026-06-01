---
id: formal.story-closure.state-machine
title: Story Closure State Machine
status: active
doc_kind: spec
context: story-closure
spec_kind: state-machine
version: 1
prose_refs:
  - concept/technical-design/12_github_integration_repo_operationen.md
  - concept/technical-design/29_closure_sequence.md
  - concept/technical-design/31_branch_guard_orchestrator_guard_artefaktschutz.md
  - concept/technical-design/33_deterministische_checks_stage_registry_policy_engine.md
  - concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md
---

# Story Closure State Machine

Der offizielle Closure-Pfad ist ein checkpointfaehiger Abschluss-Flow
mit klarer Reihenfolge und offizieller Fallback-Policy.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-closure.state-machine
schema_version: 1
kind: state-machine
context: story-closure
states:
  - id: story-closure.status.requested
    initial: true
  - id: story-closure.status.policy_checked
  # Pre-Merge-Scan-und-Merge-Block (FK-29 §29.1a, FK-33 §33.6.3 point 3)
  # runs entirely under the merge-serialization lock (one merge per main).
  # The whole locked block is a single recoverable unit keyed on merge_done
  # (FK-29 §29.1 recovery): its intra-lock sub-steps below are NOT separately
  # resumable; on resume the block re-acquires the lock and re-runs from the
  # integrated-candidate scan with a fresh locked_sha.
  - id: story-closure.status.merge_lock_acquired
  # latest main integrated into the story branch, clean workspace,
  # build/test/coverage + full integrated-candidate Sonar scan green,
  # exception ledger reconciled (single-match), QG verified by analysisId,
  # tree_hash(scan) == tree_hash(merge) asserted -> attestation produced.
  # This is the step that PRODUCES the commit-bound attestation.
  - id: story-closure.status.integrated_candidate_green
  # Integrity-Gate (FK-35 §35.2) Dimensions 1-9 run here, AFTER the scan and
  # BEFORE the push/merge, still inside the lock. Dimension 9 (FK-35
  # §35.2.4a) verifies the FRESH commit-bound attestation produced in the
  # integrated_candidate_green step and never runs its own Sonar scan.
  - id: story-closure.status.integrity_passed
  # story branch pushed INSIDE the lock, carrying the measured green state.
  - id: story-closure.status.story_branch_pushed
  # ff-only update of main under compare-and-swap/lease against locked_sha.
  - id: story-closure.status.merged_to_main
  # post-merge reconcile (ledger re-checked against main), lock released.
  - id: story-closure.status.post_merge_reconciled
  - id: story-closure.status.story_closed
  - id: story-closure.status.completed
    terminal: true
  - id: story-closure.status.escalated
    terminal: true
transitions:
  - id: story-closure.transition.request_to_policy_checked
    from: story-closure.status.requested
    to: story-closure.status.policy_checked
    guard: story-closure.invariant.verify_completed_before_closure
  # Closure acquires the per-main merge-serialization lock right after the
  # Finding-Resolution-Gate / policy check; the Integrity-Gate has moved
  # INSIDE the lock (after the scan) so it no longer precedes lock acquisition.
  - id: story-closure.transition.policy_checked_to_merge_lock_acquired
    from: story-closure.status.policy_checked
    to: story-closure.status.merge_lock_acquired
    guard: story-closure.invariant.merge_block_runs_under_serialization_lock
  - id: story-closure.transition.merge_lock_acquired_to_integrated_candidate_green
    from: story-closure.status.merge_lock_acquired
    to: story-closure.status.integrated_candidate_green
    guard: story-closure.invariant.integrated_candidate_scanned_green_before_push
  # Integrity-Gate runs on the FRESH attestation produced by the scan above.
  - id: story-closure.transition.integrated_candidate_green_to_integrity_passed
    from: story-closure.status.integrated_candidate_green
    to: story-closure.status.integrity_passed
    guard: story-closure.invariant.integrity_gate_precedes_merge_block
  - id: story-closure.transition.integrity_passed_to_story_branch_pushed
    from: story-closure.status.integrity_passed
    to: story-closure.status.story_branch_pushed
    guard: story-closure.invariant.push_inside_lock_after_green_scan
  - id: story-closure.transition.story_branch_pushed_to_merged_to_main
    from: story-closure.status.story_branch_pushed
    to: story-closure.status.merged_to_main
    guard: story-closure.invariant.merge_requires_pushed_story_branch
  - id: story-closure.transition.merged_to_main_to_post_merge_reconciled
    from: story-closure.status.merged_to_main
    to: story-closure.status.post_merge_reconciled
    guard: story-closure.invariant.post_merge_reconcile_before_lock_release
  - id: story-closure.transition.post_merge_reconciled_to_story_closed
    from: story-closure.status.post_merge_reconciled
    to: story-closure.status.story_closed
  - id: story-closure.transition.story_closed_to_completed
    from: story-closure.status.story_closed
    to: story-closure.status.completed
    guard: story-closure.invariant.completed_requires_merge_and_story_close
  - id: story-closure.transition.policy_checked_to_escalated
    from: story-closure.status.policy_checked
    to: story-closure.status.escalated
    guard: story-closure.invariant.manual_history_rewrite_forbidden
  # main-drift (red integrated candidate) escalates the merge block; the
  # remediation loop and retry are owned by the QA-subflow / workflow engine.
  - id: story-closure.transition.merge_lock_acquired_to_escalated
    from: story-closure.status.merge_lock_acquired
    to: story-closure.status.escalated
    guard: story-closure.invariant.red_integrated_candidate_blocks_merge
  - id: story-closure.transition.story_branch_pushed_to_escalated
    from: story-closure.status.story_branch_pushed
    to: story-closure.status.escalated
    guard: story-closure.invariant.merge_rejection_never_completes_closure
compound_rules:
  - id: story-closure.rule.ff-only-is-default-policy
    description: The default closure path selects ff_only unless the official no_ff flag is explicitly chosen.
  - id: story-closure.rule.story-branch-pushed-is-resumable
    description: A closure resumed from story_branch_pushed continues with the ff-merge under the merge-serialization lock and must not require a new semantic re-entry into the implementation QA-subflow against the verify-system capability.
  - id: story-closure.rule.pre-merge-scan-and-merge-block-is-locked
    description: From merge_lock_acquired through post_merge_reconciled the closure runs inside a single per-main merge-serialization lock (FK-29 §29.1a). Under that lock the order is integrated-candidate Sonar scan (produces the commit-bound attestation) -> Integrity-Gate Dimensions 1-9 (Dimension 9, FK-35 §35.2.4a, verifies that fresh attestation and does not re-measure) -> story-branch push -> ff-only compare-and-swap update of main -> post-merge ledger reconcile, so that the green-measured tree and the merged main share one tree_hash. The whole locked block is a single recoverable unit keyed on merge_done (FK-29 §29.1); its intra-lock sub-steps are not separately resumable.
  - id: story-closure.rule.multi-repo-merge-block-per-repo
    description: For multi-repo stories (FK-29 §29.1.6) the merge-serialization lock and the Pre-Merge-Scan-und-Merge-Block apply per participating repo. The closure guarantees an atomic green-and-ff-mergeability barrier across ALL repos before any push begins; cross-remote push itself is NOT transactionally atomic, so a partial push escalates (ESCALATED) with compensating recovery (FK-29 §29.1.6.3). merge_done becomes true only after all repos pass the push-to-main stage.
```
<!-- FORMAL-SPEC:END -->
