# AG3-151 — takeover reconcile / ex-owner quarantine / contested_local_writes: frozen design

**Status:** FROZEN implementation contract. Feasibility verified at main@6b5b7468 (scout report
`reports/AG3-151-reconcile-quarantine-feasibility.md` + orchestrator code-level adjudication of the
two load-bearing claims). `story.md` loci are STALE (control_plane runtime decomposed into
`control_plane/runtime/`; freeze/transfer reworked by 148/149/150) — the coordinates here are ground
truth. If a decision conflicts with the concept, STOP and report.

Concept basis: FK-56 §56.13e/f, FK-55 §55.8, FK-36 (worktree identity marker), decision-record
`concept/_meta/decisions/2026-07-09-takeover-challenge-persistence-und-reconcile-obligation.md`
(§2.4 reconcile obligation on the transfer-record; §6.6 distinct error codes). Covers the AG3-151
SOLL set (reconcile contract, ex-owner quarantine reuse, contested_local_writes entry, edge
publication + fail-closed consumption).

## 0. Adjudicated coordinates (HEAD, verified at code)
- **records.py:304 pattern lock — CONFIRMED (must widen).** `_ADMIN_TRANSITION_REF_PATTERN =
  ^admin_transition:[A-Za-z0-9][A-Za-z0-9_.:-]*$` (`control_plane/records.py:39-41`);
  `TakeoverTransferRecord.__post_init__` :304-310 rejects any `reconcile_ref` not matching it with
  "pre-AG3-151 takeover reconcile clear requires an audited admin_transition:{op_id} reconcile_ref".
  Paired-null invariants :298-303. AG3-151 widens the accepted vocabulary to ALSO allow
  `takeover_reconcile:{op_id}` (a second audited form) WITHOUT weakening the admin-audit invariant
  (admin_transition stays valid; the new form is the regular reconcile-endpoint clear).
- **Edge resolve() surface — CONFIRMED (models only binding_invalid today).**
  `harness_client/projectedge/runtime.py:187-272` is a fail-closed cascade: no bundle → ai_augmented
  (:205); no session → ai_augmented (:209); `session.status=="revoked"` → binding_invalid + block_reason
  (:215-238); session mismatch → binding_invalid (:240-246); lock not ACTIVE → binding_invalid (:248-258);
  cwd not in worktree → binding_invalid (:260-266); else → story_execution (:268-272). CRITICAL: a
  contested_local_writes freeze is NOT a revoked binding — the ownership record stays ACTIVE during a
  freeze (AG3-150) — so it will NOT be caught by the `status=="revoked"` branch. AG3-151 must PUBLISH the
  active blocking freeze-family state into the edge bundle and CONSUME it in resolve() as a new blocked
  outcome BEFORE the story_execution success path, fail-closed.
- Quarantine (reuse, no change): `harness_client/projectedge/quarantine.py` `quarantine_worktree(...)`
  :37, local-only. AG3-151 adds the caller `harness_client/projectedge/reconcile.py` (NEW).
- Freeze family (consume): `core_types/freeze.py` CONTESTED_LOCAL_WRITES :17 + resolver
  {"takeover_reconcile_clear"} :28; `state_backend/store/freeze_repository.py` set_freeze any-kind :182,
  read_freezes :273, challenge-invalidation-on-entry :229. `ConflictFreezeOverlay.freeze()/release()`
  hard-code CONFLICT_FREEZE (`principal_capabilities/freeze.py:238,257`) → contested entry/exit uses
  `FreezeRepository` directly (or a NEW thin overlay method), NOT the existing overlay.
- Reconcile obligation surface: `TakeoverTransferRecord.reconciled_at/reconcile_ref`
  (`records.py:287-288`); admission read `has_unreconciled_takeover_transfer_for_story_global`
  (`operation_ledger/__init__.py:636` → `_control_plane_rows.py:829`); rejection error_code
  `takeover_reconcile_required` (`runtime/_admission_rejections.py:67-83`); admin clear
  `runtime/_admin.py:150-269` + CAS `commit_takeover_reconcile_clear_global_row`
  (`_takeover_rows.py:306-344`).
- Edge command vocab: `control_plane/edge_commands.py` — `takeover_reconcile` REGISTERED but NOT
  executable (CommandKind :56; EXECUTABLE_COMMAND_KINDS lacks it :74-76). AG3-151 adds it to the executor
  set.
- Foundation wire shapes (present): `control_plane/models.py` TakeoverErrorResult.result_type ∈
  {remote_branch_diverged_after_takeover, local_stale_or_dirty_takeover_target, contested_local_writes}
  :1089-1095; TakeoverQuarantineDetail :1064-1076; worktree-identity probe (head_sha, marker_present)
  :1060.

## 1. Settled design decisions
- **Two distinct obligations, two distinct error codes (decision-record §6.6 — SETTLED, do not conflate):**
  (a) transfer-record reconcile obligation → `takeover_reconcile_required` (the confirm→reconcile
  admission gate; cleared by writing `reconcile_ref` on the transfer-record). (b) failed/ambiguous
  reconcile → `contested_local_writes` freeze-family entry (a story-scoped admission-blocker; its edge
  block_reason is `contested_local_writes`). The single command `takeover_reconcile_clear` resolves BOTH
  on a successful reconcile (clears the transfer-record obligation AND, if a contested freeze exists,
  clears that freeze). Keep Repair-Lock (`reconcile_repair` kind, AG3-138) vs Reconcile-Obligation as
  DISTINCT codes.
- **Reconcile classifier is A-core pure** (`control_plane/takeover_reconcile.py`, blood-type A): per-repo
  SHA compare vs the transfer-record `takeover_base_sha` + worktree-identity marker (`.agentkit-story.json`,
  FK-36) → one of {identity_ok (reconciled), remote_branch_diverged_after_takeover,
  local_stale_or_dirty_takeover_target, contested_local_writes}. No IO/clock in the classifier.
- **Contested entry uses FreezeRepository directly** (not the conflict-freeze-only overlay); set_freeze
  kind=CONTESTED_LOCAL_WRITES + the local-export projection so the edge bundle sees it. Ownership record
  stays active (freeze blocks additively, AG3-150 INV). Challenge invalidation on entry is automatic
  (freeze_repository:229).
- **Edge publication + fail-closed consumption (the risk surface):** the backend bundle assembly
  (`control_plane/runtime/_edge_bundles.py`) publishes the active blocking freeze-family state (at minimum
  the contested_local_writes member) into the EdgeBundle; edge resolve() (`projectedge/runtime.py:187`)
  consumes it as a blocked outcome (a `contested_local_writes` block_reason under binding_invalid, or a new
  operating-mode literal if the concept/model requires one — verify against `core_types.operating_mode`
  before adding a literal) BEFORE the story_execution success path. Fail-closed: an unreadable/ambiguous
  published freeze state blocks. Tests drive the round-trip through the REAL 148 transfer + 145 command
  queue (testing-guardrail: no hand-assembled state).
- **Edge executor** (`harness_client/projectedge/reconcile.py`, NEW): marker+path identity classification,
  same-worktree quarantine via `quarantine.py` on contested, reprovision via `provision_worktree`; add
  `takeover_reconcile` to EXECUTABLE_COMMAND_KINDS; mirror into the deployed
  `bundles/target_project/tools/agentkit/projectedge.py`.
- **Blood types:** reconcile classifier + state transitions + obligation/freeze decision rules = A;
  row↔record + wire mappers + edge bundle projection = R; persistence row fns (reconcile clear CAS,
  freeze entry) = AT/T; the edge executor (fs move/quarantine/reprovision) = R/T at the edge boundary.

## 2. Implementation plan — TWO increments (mirror the AG3-150 discipline)
Each increment owns green-on-main and is review-converged (Codex + orchestrator code-adjudication +
Fable finale) BEFORE the next; the story closes only after both + full DoD.

- **Increment 1 — Backend reconcile contract + contested entry.** Widen records.py:304 pattern
  (`takeover_reconcile:{op_id}`); A-core `control_plane/takeover_reconcile.py` classifier; the
  takeover-reconcile-worktree HTTP route (`control_plane_http/`) + models (reuse foundation shapes);
  commission `takeover_reconcile` after confirm; clear the transfer-record obligation on success
  (reconcile_ref=`takeover_reconcile:{op_id}`, extend `_admin.py`/`commit_takeover_reconcile_clear` or a
  sibling regular-path clear); enter `contested_local_writes` freeze on failure (FreezeRepository +
  local export projection) with distinct error code; publish the contested state into the edge bundle
  (`_edge_bundles.py`). Contract/negative tests through the real transfer path.
- **Increment 2 — Edge executor + resolve() consumption + round-trip.** `harness_client/projectedge/
  reconcile.py` (identity marker+path, same-worktree quarantine, reprovision); add `takeover_reconcile`
  to EXECUTABLE_COMMAND_KINDS; mirror deployed projectedge; edge resolve() consumes the contested/reconcile
  bundle states fail-closed; full round-trip + multi-repo + SOLL-079 exit contract tests through the REAL
  148 transfer + 145 command queue.

## 3. Guardrails carried into every worker prompt
venv only (`.venv\Scripts\python`); local Postgres 127.0.0.1:55442 then 55642; `--basetemp var\t` removed
after; single-pass coverage + scoped inner loop per `guardrails/test-execution-efficiency.md`; full suite
once pre-push; mypy full both platforms; 4 concept gates. Green-on-main: ruff → mypy src → mypy src
--platform linux → pytest → 4 gates → push main → Jenkins
`buildWithParameters?agentkit_mode=ci&sonar_project_key=claude-agentkit3&sonar_branch=main&delay=0sec`
(CSRF crumb + admin:password, http://localhost:9900) → Jenkins SUCCESS + Sonar OK. Sonar
http://localhost:9901 admin/`meinSonarCube2026!` key `claude-agentkit3` (0/0/0, new-code cov≥80). Do NOT
set status.yaml=completed (review + Fable finale + Inc-2 follow). Fire Codex jobs serially. Ignore
harness-bridge jobs not self-started.

---

## AG3-151 — WHOLE STORY CLOSED (2026-07-11)

CLOSED at code SHA `5af89461` (Jenkins #1811/#1812 SUCCESS, Sonar 0/0/0, new-code cov 83.9%,
9307 tests). Two increments, full review convergence:
- **Inc-1** (backend reconcile contract + contested_local_writes entry, a27bdbb0): Codex defect
  review APPROVE (8 areas) + orchestrator code-adjudication (pattern widen + A-core purity).
- **Inc-2** (edge executor + resolve() consumption + round-trip): Codex review found 1 crash-recovery
  ERROR + 3 test gaps → R1 (1eefbd59, shared crash-recovery helper + airtight remnant data-loss
  guard) + orchestrator adjudication.
- **Whole-story Fable finale** (1eefbd59): APPROVED all areas incl. the data-loss guard (verified
  AIRTIGHT byte-for-byte) EXCEPT 1 HIGH liveness defect — reconcile replay non-convergence at the
  WIRE PROTOCOL (a resolved-but-unreported takeover_reconcile command + the fresh-op_id +
  takeover_reconcile_not_required + raise-before-report cycle permanently wedged the session's whole
  edge command loop; untested path, the shared blind spot that fooled the per-increment reviews AND
  the orchestrator's filesystem-only adjudication).
- **R2** (5af89461): treat status=rejected+error_code=takeover_reconcile_not_required as a convergent
  no-op (proceed to sync + report → the command terminalizes; every other status stays fail-closed) +
  NB2 symlink-rmtree hardening. Codex convergence re-review APPROVE (no false-convergent: the
  not_required query uses the identical active (run_id, ownership_epoch) identity as the canonical
  obligation query; real 2-repo scenario tests prove both commands terminalize + next fetch empty) +
  orchestrator code-adjudication.

Covers the AG3-151 SOLL set. Unblocks AG3-153, AG3-155. Deferred/tracked: Fable non-blocking
NB1 (remnant guard gitignored-files residual — hardening: quarantine instead of remove), NB5
(reconcile↔command_executor lazy-import cycle), NB3/NB6 (diagnostic) → tech-debt #22. Distinct
error codes (takeover_reconcile_required / contested_local_writes / repair_lock_required) settled
per decision-record §6.6.

Process note: the whole-story Fable finale earned its keep — a HIGH wire-protocol defect survived
Inc-1/Inc-2 Codex reviews AND the orchestrator's per-round adjudication (which verified filesystem
convergence but not protocol convergence). The independent finale gate is why it was caught before
close.
