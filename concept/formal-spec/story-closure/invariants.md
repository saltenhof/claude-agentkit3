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
    rule: the final story branch state must be pushed to the remote before any merge into the target branch is attempted; within the Pre-Merge-Scan-und-Merge-Block (FK-29 §29.1a) this push happens inside the merge-serialization lock, after the integrated candidate has been measured green
  - id: story-closure.invariant.merge_requires_pushed_story_branch
    scope: process
    rule: merge into main is legal only after story_branch_pushed has been reached for the same closure attempt
  - id: story-closure.invariant.integrity_gate_precedes_merge_block
    scope: process
    rule: inside the merge-serialization lock the Integrity-Gate (FK-35 §35.2), including Dimension 9 SonarQube-Green attestation verification (FK-35 §35.2.4a), runs AFTER the integrated-candidate Sonar scan has produced the commit-bound attestation and must pass BEFORE the story-branch push and the ff-only merge; Dimension 9 only verifies the fresh commit-bound attestation produced by that scan and never runs its own Sonar scan
  - id: story-closure.invariant.merge_block_runs_under_serialization_lock
    scope: process
    rule: the Pre-Merge-Scan-und-Merge-Block (FK-29 §29.1a) runs under a per-main merge-serialization lock so that at most one scan-then-merge block is active per main at any time; the locked main HEAD is recorded as locked_sha
  - id: story-closure.invariant.integrated_candidate_scanned_green_before_push
    scope: process
    rule: after integrating the latest main into the story branch and cleaning the workspace, a full integrated-candidate Sonar scan must be read green by analysisId (overall-code invariant) with the exception ledger reconciled by single-match, and tree_hash(scan) must equal tree_hash(merge) before the story branch may be pushed; a QA-subflow-green branch alone is insufficient because of main-drift
  - id: story-closure.invariant.push_inside_lock_after_green_scan
    scope: process
    rule: the story-branch push happens inside the merge-serialization lock and only after the integrated candidate has been measured green, so the pushed branch carries exactly the measured green integration state
  - id: story-closure.invariant.red_integrated_candidate_blocks_merge
    scope: process
    rule: a red integrated candidate (typically caused by main-drift) blocks the merge; the story re-enters the remediation loop and the block is retried with a fresh locked_sha, and closure escalates if the block stays non-green or the merge is not ff-capable
  - id: story-closure.invariant.post_merge_reconcile_before_lock_release
    scope: process
    rule: after the ff-only update of main the exception ledger is reconciled again against main (FK-33 §33.6.4) before the merge-serialization lock is released; the green-measured tree and the merged main must share one tree_hash
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
    rule: in multi-repo stories with two or more participating repos, no main is made visible before all repos pass the atomic green-and-ff-mergeability barrier without push (FK-29 §29.1.6); the subsequent cross-remote push is NOT transactionally atomic, so merge_done becomes true only when all participating repos have been merged into main and pushed, and any partial-merged or partial-pushed state is a defective end state that must escalate with compensating recovery (FK-29 §29.1.6.3)
  - id: story-closure.invariant.multi_repo_local_rollback_on_merge_failure
    scope: process
    rule: in multi-repo stories, if local fast-forward-merge fails for any participating repo, all repos that were already merged in the same closure attempt must be reset to their pre-merge SHA before escalation
```
<!-- FORMAL-SPEC:END -->
