---
id: formal.story-closure.invariants
title: Story Closure Invariants
status: active
doc_kind: spec
context: story-closure
spec_kind: invariant-set
version: 1
prose_refs:
  - concept/technical-design/12_github_integration_repo_operationen.md
  - concept/technical-design/29_closure_sequence.md
  - concept/technical-design/31_branch_guard_orchestrator_guard_artefaktschutz.md
  - concept/technical-design/33_deterministische_checks_stage_registry_policy_engine.md
  - concept/technical-design/35_integrity_gate_governance_beobachtung_eskalation.md
  - concept/technical-design/04_betrieb_monitoring_audit_runbooks.md
---

# Story Closure Invariants

Diese Invarianten definieren den zulaessigen Closure-Pfad bis zum
terminalen Abschluss oder zur offiziellen Eskalation.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.story-closure.invariants
schema_version: 1
kind: invariant-set
context: story-closure
invariants:
  - id: story-closure.invariant.verify_completed_before_closure
    scope: process
    rule: closure may start only after the implementation phase has completed successfully (which implies the implementation-internal QA-subflow against the verify-system capability reached a passing verdict) for implementing stories, or after the direct closure shortcut for non-implementing stories has been selected
  - id: story-closure.invariant.push_precedes_merge
    scope: process
    rule: the final story branch state must be pushed to the remote before any merge into the target branch is attempted; within the Pre-Merge-Scan-und-Merge-Block (FK-29 §29.1a) this push always happens inside the merge-serialization lock, and when the sonarqube_gate is APPLICABLE it happens after the integrated candidate has been measured green, whereas in the NOT_APPLICABLE cases it happens after the corresponding gate (Dimensions 1-8 without Sonar for a deliberately absent Sonar, or the Sanity-Gate for mode fast) with no integrated-candidate Sonar measurement
  - id: story-closure.invariant.merge_requires_pushed_story_branch
    scope: process
    rule: merge into main is legal only after story_branch_pushed has been reached for the same closure attempt
  - id: story-closure.invariant.integrity_gate_precedes_merge_block
    scope: process
    rule: when the sonarqube_gate is APPLICABLE, inside the merge-serialization lock the Integrity-Gate (FK-35 §35.2), including Dimension 9 SonarQube-Green attestation verification (FK-35 §35.2.4a), runs AFTER the integrated-candidate Sonar scan has produced the commit-bound attestation and must pass BEFORE the story-branch push and the ff-only merge; Dimension 9 only verifies the fresh commit-bound attestation produced by that scan and never runs its own Sonar scan
  - id: story-closure.invariant.merge_block_runs_under_serialization_lock
    scope: process
    rule: the Pre-Merge-Scan-und-Merge-Block (FK-29 §29.1a) runs under a per-main merge-serialization lock so that at most one scan-then-merge block is active per main at any time; the locked main HEAD is recorded as locked_sha
  - id: story-closure.invariant.integrated_candidate_scanned_green_before_push
    scope: process
    rule: when the sonarqube_gate is APPLICABLE, after integrating the latest main into the story branch and cleaning the workspace, a full integrated-candidate Sonar scan must be read green by analysisId (overall-code invariant) with the exception ledger reconciled by single-match, and tree_hash(scan) must equal tree_hash(merge) before the story branch may be pushed; a QA-subflow-green branch alone is insufficient because of main-drift
  - id: story-closure.invariant.push_inside_lock_after_green_scan
    scope: process
    rule: the story-branch push always happens inside the merge-serialization lock; when the sonarqube_gate is APPLICABLE it happens only after the integrated candidate has been measured green, so the pushed branch carries exactly the measured green integration state; in the NOT_APPLICABLE cases there is no integrated-candidate Sonar measurement, and the push happens after the corresponding NOT_APPLICABLE gate instead (Dimensions 1-8 without Sonar for a deliberately absent Sonar per closure_proceeds_without_sonar_when_not_applicable, or the Sanity-Gate for mode fast per fast_mode_closure_uses_sanity_gate)
  - id: story-closure.invariant.red_integrated_candidate_blocks_merge
    scope: process
    rule: a red integrated candidate (typically caused by main-drift) blocks the merge; the story re-enters the remediation loop and the block is retried with a fresh locked_sha, and closure escalates if the block stays non-green or the merge is not ff-capable
  - id: story-closure.invariant.post_merge_reconcile_before_lock_release
    scope: process
    rule: after the ff-only update of main, when the sonarqube_gate is APPLICABLE the exception ledger is reconciled again against main (FK-33 §33.6.4) before the merge-serialization lock is released and the green-measured tree and the merged main must share one tree_hash; when the sonarqube_gate is NOT_APPLICABLE (deliberately absent Sonar or mode fast) there is no Sonar attestation or exception ledger to reconcile and no green-measured tree to compare, so the post-merge Sonar reconcile and the tree_hash equality are skipped while the lock-release ordering and all other post-merge obligations remain in force
  - id: story-closure.invariant.ff_only_is_default_policy
    scope: policy
    rule: ff_only is the default closure merge policy unless the official no_ff closure command is explicitly chosen
  - id: story-closure.invariant.no_ff_only_official_fallback
    scope: policy
    rule: no_ff is legal only as an official closure fallback path and never as an implicit manual workaround
  - id: story-closure.invariant.manual_history_rewrite_forbidden
    scope: governance
    rule: manual rebase, manual reset, and force-push are forbidden while a story is in the official closure path
  - id: story-closure.invariant.branch_guard_allows_official_closure
    scope: governance
    rule: the branch guard must allow the official closure push and official no_ff fallback path while still rejecting manual history-rewrite operations
  - id: story-closure.invariant.completed_requires_merge_and_story_close
    scope: outcome
    rule: closure is completed only after merge into main and story status set to Done have both succeeded for the same closure attempt
  - id: story-closure.invariant.merge_rejection_never_completes_closure
    scope: outcome
    rule: if merge is rejected after the story branch has been pushed the story must not complete and the closure path must remain resumable or escalate explicitly
  - id: story-closure.invariant.multi_repo_atomicity
    scope: outcome
    rule: in multi-repo stories with two or more participating repos, no main is made visible before all repos pass the atomic barrier-and-ff-mergeability check without push (FK-29 §29.1.6); the per-repo barrier verdict is resolved per applicability — APPLICABLE means the integrated-candidate Sonar-measured green plus Dimension 9, a deliberately absent Sonar means Dimensions 1-8 without the Sonar scan/Dimension 9, and mode fast means the Sanity-Gate — so the cross-repo atomicity holds over whichever applicability-resolved verdict applies; the subsequent cross-remote push is NOT transactionally atomic, so merge_done becomes true only when all participating repos have been merged into main and pushed, and any partial-merged or partial-pushed state is a defective end state that must escalate with compensating recovery (FK-29 §29.1.6.3)
  - id: story-closure.invariant.multi_repo_local_rollback_on_merge_failure
    scope: process
    rule: in multi-repo stories, if local fast-forward-merge fails for any participating repo, all repos that were already merged in the same closure attempt must be reset to their pre-merge SHA before escalation
  - id: story-closure.invariant.closure_proceeds_without_sonar_when_not_applicable
    scope: process
    rule: when the sonarqube_gate is NOT_APPLICABLE because Sonar is deliberately absent (sonarqube.available false), closure proceeds without the integrated-candidate Sonar scan, the exception-ledger reconcile, the tree_hash(scan)==tree_hash(merge) assert, and Integrity-Gate Dimension 9, skipped without fail-closed; all remaining closure obligations stay in force, namely the merge-serialization lock, locked_sha drift assert, clean workspace, build/test/coverage, Integrity-Gate Dimensions 1 to 8, story_branch_pushed inside the lock, ff-only merge with compare-and-swap, finding-resolution, and doc-fidelity; a configured-but-unreachable or red Sonar (sonarqube.available true) stays APPLICABLE and still fails closed (absent is not broken)
  - id: story-closure.invariant.fast_mode_closure_uses_sanity_gate
    scope: process
    rule: when the sonarqube_gate is NOT_APPLICABLE because mode is fast (story attribute mode per FK-24 24.3.4 / project-level mode_lock fast per 24.3.3), the integrated-candidate Sonar scan and the nine-dimension Integrity-Gate including Dimension 9 are not evaluated and are replaced by the sanity gate (tests green, worktree clean, pre-merge-rebase on main ok per FK-29 §29.1a.6), with escalation to the human on rebase conflict
```
<!-- FORMAL-SPEC:END -->
