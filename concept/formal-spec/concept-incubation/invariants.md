---
id: formal.concept-incubation.invariants
title: Concept Incubation Invariants
status: active
doc_kind: spec
context: concept-incubation
spec_kind: invariant-set
version: 1
prose_refs:
  - concept/technical-design/78_concept_incubation_process.md
---

# Concept Incubation Invariants

Harte Regeln fuer Rollen- und Schreibgrenzen, Freezes, Closures, Receipts,
Locks und Datenklassen. Severity aller Verstoesse: ERROR.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.concept-incubation.invariants
schema_version: 1
kind: invariant-set
context: concept-incubation
invariants:
  - id: concept-incubation.invariant.run_state_single_writer_cas
    scope: process
    rule: RUN.json is the only authoritative run state; every mutation of that file happens under a valid writer lease inside the mutation mutex, re-verifies the caller principal the lease fencing token and the state_revision, and lands as an atomic replace write with a strictly monotonic revision; a writer that cannot re-verify aborts without writing; lease and run state carry the same fencing token in every consistent state
  - id: concept-incubation.invariant.mutation_mutex_compare_before_delete
    scope: process
    rule: the mutation mutex carries owner principal session nonce and heartbeat; expiry is measured against the heartbeat; a holder releases only after re-reading and matching its own nonce and a takeover of an expired mutex requires the caller fencing token to match the run state and replaces the mutex atomically
  - id: concept-incubation.invariant.takeover_only_after_ttl_or_release
    scope: process
    rule: lease or lock takeover is legal only after explicit release or ttl expiry, uses the exclusive intent procedure, and increments the fencing token; a stale owner must never release or overwrite a taken-over lease or lock
  - id: concept-incubation.invariant.baseline_frozen_before_staffing
    scope: process
    rule: the corpus baseline inventory including digests is frozen before staffing starts and is never regenerated during the run; later corpus changes surface as drift and trigger recheck
  - id: concept-incubation.invariant.staffing_requires_user_approval
    scope: process
    rule: the participant panel including models spawn modes and data releases is approved by the user; there is no silent default staffing
  - id: concept-incubation.invariant.data_release_bounded_per_participant
    scope: process
    rule: each participant carries a user approved data release naming max data class and concrete source or package sets; sensitive material never leaves the machine without explicit per backend approval
  - id: concept-incubation.invariant.worker_writes_only_own_outbox
    scope: process
    rule: a council worker writes exclusively inside its own outbox; writes to concept roots foreign sandboxes rounds synthesis promotion or run state are violations regardless of harness
  - id: concept-incubation.invariant.round_seal_before_cross_read
    scope: process
    rule: proposals become readable for other participants only after the round seal has bound their digests; unsealed proposals are never distributed
  - id: concept-incubation.invariant.input_freeze_and_inventory_closure_before_synthesis
    scope: process
    rule: before synthesizing starts the input source set with units and the claims inventory are digest pinned; the input freeze is never overwritten; every input unit carries claim refs or a reasoned empty disposition
  - id: concept-incubation.invariant.every_input_unit_claimed_or_empty_reasoned
    scope: register
    rule: source units are derived deterministically by the toolchain and re-derived by the checker; each unit has claim refs or exactly one reasoned empty record; there are no source level empty markers and no pseudo claims
  - id: concept-incubation.invariant.derived_sources_registered
    scope: register
    rule: synthesis dissent map and po decisions are registered as derived sources with units; every material derived unit references upstream claims or creates a new claim that is disposed before promoting; the final source set digest is pinned before promotion closure
  - id: concept-incubation.invariant.single_disposition_per_claim
    scope: register
    rule: every inventory claim has exactly one synthesis disposition; non adopted claims carry a residual edge; minority claims of the final round never carry none_required
  - id: concept-incubation.invariant.open_questions_decided_or_deferred_visibly
    scope: process
    rule: every open question from the dissent map is either decided by the po or deferred with owner trigger and an anchor visible from the normative world or a backlog
  - id: concept-incubation.invariant.coverage_final_before_promotion_exit
    scope: register
    rule: source coverage has exactly one final row per source and normative coverage covers the union of baseline and current files with change kind; pass_with_gaps and fail rows reference findings; no open or recheck rows remain
  - id: concept-incubation.invariant.disposition_closure_and_locks_before_promoting
    scope: process
    rule: promoting starts only after disposition closure and after all affected scope locks are acquired and recorded in the promotion manifest
  - id: concept-incubation.invariant.scope_lock_exclusive_during_promoting
    scope: coordination
    rule: a normative scope is bound by at most one run in status promoting; lock acquisition uses the backend specific cas; ownership is re-verified immediately before the final landing together with the expected base revision
  - id: concept-incubation.invariant.receipt_reviewer_independent
    scope: register
    rule: every projection receipt names writer and reviewer principals and sessions; reviewer principal and reviewer session both differ from the writer side; a disagrees verdict escalates to the po and is never overridden by the writer
  - id: concept-incubation.invariant.diff_hunks_fully_covered
    scope: outcome
    rule: every non format only diff hunk below the concept roots maps to its smallest enclosing heading anchor and is covered by at least one receipt or atom target on that anchor or an ancestor anchor of the same file
  - id: concept-incubation.invariant.open_findings_block_promotion
    scope: outcome
    rule: open findings block promoted dispositions for their scopes; a run may only close with such scopes as deferred or via promotion_failed handling
  - id: concept-incubation.invariant.promoted_requires_full_closure
    scope: outcome
    rule: a scope becomes promoted only with zero blockers zero open_missing or deferred_backlog atoms passed semantic gates held locks final coverage matching register digests and green deterministic gates
  - id: concept-incubation.invariant.register_digests_immutable_after_gate
    scope: register
    rule: register digests pinned in the run state are immutable after their gate; changes require recheck adjudication with a new gate pass
  - id: concept-incubation.invariant.resume_restores_recorded_state
    scope: process
    rule: resume after blocked crash or compaction restores exactly the state and next action recorded in the run state; no new run is started while a resumable run exists
  - id: concept-incubation.invariant.recheck_requires_adjudication
    scope: process
    rule: leaving recheck requires an explicit adjudication of every drifted path; silent continuation over drift is a violation
  - id: concept-incubation.invariant.aborted_run_leaves_visible_blockers
    scope: outcome
    rule: aborting or closing with unpromoted material leaves every affected scope with a blocker entry whose anchor is visible from the normative world or a backlog; nothing rests silently in the workshop
  - id: concept-incubation.invariant.lock_release_requires_cas_ownership
    scope: coordination
    rule: scope locks are released exclusively on the transitions into closed or aborted; the filesystem release re-verifies owner and fencing token under the intent procedure and the git-remote release uses a cas against the expected ref oid; a stale owner can never release a taken-over lock
  - id: concept-incubation.invariant.projection_lifecycle_first
    scope: register
    rule: every projection manifest entry carries a lifecycle determined solely by decision and supersession state; draft deprecated and superseded entries are never overwritten by status derivation which applies only to the current accepted assertion
  - id: concept-incubation.invariant.projection_status_derivation
    scope: register
    rule: for current entries the equivalence status of each required projection derives deterministically as unreviewed on missing or unbound receipt stale on digest mismatch and blocked_missing_target on missing target; a receipt counts only when it is bound through the promotion manifest and atom register of the recorded run whose scope carries promotion_disposition promoted and whose writer and reviewer principals and sessions differ; the assertion status is active exactly when all required projections are equivalent and no blockers are open and blocked_projection otherwise
  - id: concept-incubation.invariant.projection_target_digest_by_mode
    scope: register
    rule: every required projection declares a target mode and its digest follows that mode deterministically; markdown-section digests the canonicalised anchored section, whole-file digests the file bytes, structured-selector digests the canonically serialised selected subtree, and directory-tree digests the sorted relative-path and file-digest listing; an active projection always carries a non null target digest
  - id: concept-incubation.invariant.unclassified_is_sensitive
    scope: register
    rule: artifacts without classification are treated as sensitive; effective class is the maximum of declared and input classes; downgrades require a digest bound declassification receipt for exactly that output artifact
  - id: concept-incubation.invariant.sensitive_stays_local_without_declassification
    scope: register
    rule: artifacts with effective class sensitive keep vcs disposition local; the commit gate blocks violations; sensitive paths never leak through versioned registers thanks to the sanitized register plus local overlay split
```
<!-- FORMAL-SPEC:END -->
