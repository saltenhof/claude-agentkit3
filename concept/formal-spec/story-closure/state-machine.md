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
  # BEFORE the main update, still inside the lock. Dimension 9 (FK-35
  # §35.2.4a) verifies the FRESH commit-bound attestation produced in the
  # integrated_candidate_green step and never runs its own Sonar scan.
  - id: story-closure.status.integrity_passed
  # NOT_APPLICABLE — Sonar deliberately absent (sonarqube.available false,
  # FK-33 §33.6.5): the integrated-candidate Sonar scan, exception-ledger
  # reconcile, tree_hash(scan)==tree_hash(merge) assert and Integrity-Gate
  # Dimension 9 are SKIPPED (NOT a fail-closed). The block still runs under
  # the merge-serialization lock and still enforces locked_sha drift assert,
  # clean workspace, build/test/coverage and Integrity-Gate Dimensions 1-8
  # before this status is reached. This is strictly distinct from a
  # configured-but-unreachable/red Sonar (available true), which stays
  # APPLICABLE and routes into `escalated` via the red-candidate edge
  # (absent != broken).
  - id: story-closure.status.sonar_not_applicable_integrity_passed
  # NOT_APPLICABLE — mode fast (FK-24 §24.3.4 / mode_lock fast §24.3.3,
  # FK-33 §33.6.5): the integrated-candidate Sonar scan and the
  # nine-dimension Integrity-Gate (incl. Dimension 9) are replaced by the
  # sanity gate (tests green, worktree clean, pre-merge-rebase on main ok per
  # FK-29 §29.1a.6). A rebase conflict escalates to the human.
  - id: story-closure.status.sanity_gate_passed
  # story branch pushed INSIDE the lock. In the APPLICABLE case it carries the
  # measured green integration state; in the NOT_APPLICABLE cases it carries the
  # state cleared by the corresponding gate instead (Dimensions 1-8 without
  # Sonar for a deliberately absent Sonar, or the Sanity-Gate for mode fast).
  - id: story-closure.status.story_branch_pushed
  # ff-only update of main under compare-and-swap/lease against locked_sha.
  - id: story-closure.status.merged_to_main
  # post-merge: lock released. In the APPLICABLE case the exception ledger is
  # re-checked against main (FK-33 §33.6.4) and the green-measured tree and the
  # merged main must share one tree_hash; in the NOT_APPLICABLE cases there is
  # no Sonar attestation/ledger to reconcile, so that reconcile and the
  # tree_hash equality are skipped while the lock-release ordering remains.
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
    guard: story-closure.invariant.integrated_candidate_scanned_green_before_main_update
  # Integrity-Gate runs on the FRESH attestation produced by the scan above.
  - id: story-closure.transition.integrated_candidate_green_to_integrity_passed
    from: story-closure.status.integrated_candidate_green
    to: story-closure.status.integrity_passed
    guard: story-closure.invariant.integrity_gate_precedes_merge_block
  - id: story-closure.transition.integrity_passed_to_story_branch_pushed
    from: story-closure.status.integrity_passed
    to: story-closure.status.story_branch_pushed
    guard: story-closure.invariant.push_inside_lock_before_ci_scan
  # APPLICABILITY-RESOLVED NOT_APPLICABLE PATHS (FK-33 §33.6.5). These are
  # reached ONLY when the sonarqube_gate is NOT_APPLICABLE; they neither read
  # an attestation nor run a Sonar scan and never substitute for the
  # fail-closed `escalated` route. A configured-but-unreachable/red Sonar
  # (available true) is NOT routed here — it stays APPLICABLE and escalates
  # via merge_lock_acquired_to_escalated (absent is not broken). There is
  # intentionally NO edge from these NOT_APPLICABLE states back into
  # integrated_candidate_green, so a skipped Sonar can never be silently
  # upgraded into an unverified green attestation.
  #
  # NOT_APPLICABLE (Sonar deliberately absent, sonarqube.available false):
  # the lock is held and Dimensions 1-8 pass without the Sonar scan/Dim 9.
  - id: story-closure.transition.merge_lock_acquired_to_sonar_not_applicable_integrity_passed
    from: story-closure.status.merge_lock_acquired
    to: story-closure.status.sonar_not_applicable_integrity_passed
    guard: story-closure.invariant.closure_proceeds_without_sonar_when_not_applicable
  - id: story-closure.transition.sonar_not_applicable_integrity_passed_to_story_branch_pushed
    from: story-closure.status.sonar_not_applicable_integrity_passed
    to: story-closure.status.story_branch_pushed
    guard: story-closure.invariant.closure_proceeds_without_sonar_when_not_applicable
  # NOT_APPLICABLE (mode fast): the nine-dimension gate is replaced by the
  # sanity gate; a passing sanity gate advances to the push, a rebase
  # conflict escalates via the shared merge_lock_acquired_to_escalated edge.
  - id: story-closure.transition.merge_lock_acquired_to_sanity_gate_passed
    from: story-closure.status.merge_lock_acquired
    to: story-closure.status.sanity_gate_passed
    guard: story-closure.invariant.fast_mode_closure_uses_sanity_gate
  - id: story-closure.transition.sanity_gate_passed_to_story_branch_pushed
    from: story-closure.status.sanity_gate_passed
    to: story-closure.status.story_branch_pushed
    guard: story-closure.invariant.fast_mode_closure_uses_sanity_gate
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
    description: From merge_lock_acquired through post_merge_reconciled the closure runs inside a single per-main merge-serialization lock (FK-29 §29.1a). In the APPLICABLE case (sonarqube.available true AND mode not fast, FK-33 §33.6.5) the order under that lock is integrated-candidate ref push for Jenkins -> Jenkins build/test/Sonar scan (produces the commit-bound attestation) -> Integrity-Gate Dimensions 1-9 (Dimension 9, FK-35 §35.2.4a, verifies that fresh attestation and does not re-measure) -> ff-only compare-and-swap update of main -> post-merge ledger reconcile, so that the green-measured tree and the merged main share one tree_hash. In the NOT_APPLICABLE cases the lock and all non-Sonar obligations stay in force. For a deliberately absent Sonar (available false) the Sonar scan, ledger reconcile, tree_hash(scan)==tree_hash(merge) assert and Dimension 9 are skipped (no fail-closed) while Dimensions 1-8 and the pushed-ref/ff-merge/reconcile sequence remain. For mode fast the scan and the nine-dimension gate are replaced by the sanity gate (tests green, worktree clean, pre-merge-rebase ok). A configured-but-unreachable or red Sonar (available true) is NOT a NOT_APPLICABLE case — it stays APPLICABLE and escalates the block. The whole locked block is a single recoverable unit keyed on merge_done (FK-29 §29.1); its intra-lock sub-steps are not separately resumable.
  - id: story-closure.rule.multi-repo-merge-block-per-repo
    description: For multi-repo stories (FK-29 §29.1.6) the merge-serialization lock and the Pre-Merge-Scan-und-Merge-Block apply per participating repo. Candidate refs may be pushed for Jenkins, but the closure guarantees an atomic green-and-ff-mergeability barrier across ALL repos before any main update begins; cross-remote main update itself is NOT transactionally atomic, so a partial push to main escalates (ESCALATED) with compensating recovery (FK-29 §29.1.6.3). merge_done becomes true only after all repos pass the push-to-main stage.
```
<!-- FORMAL-SPEC:END -->
