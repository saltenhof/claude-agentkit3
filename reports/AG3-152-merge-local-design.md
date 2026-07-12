# AG3-152 — merge_local edge relocation: DESIGN FREEZE

**Supersedes** `AG3-152-merge-local-feasibility.md` (whose path prefixes/line numbers were the
stale scout coordinates). Authoritative contract for the Codex worker. HEAD @848d3128-era; verify
line numbers at dispatch (they drift). Design-lane doc (orchestrator); no production Python here.

## 0. Verdict + the resolved spike
Implementable as scoped — an execution-LOCATION move (backend git → AG3-145 edge command), not
green-field. Deps AG3-145/147 completed; independent of the 148-155 ownership chain.

**SPIKE (highest scout risk) — RESOLVED at code, no contract escalation.** Both the productive CAS
path (`closure/merge_sequence.py`) and the saga building blocks (`closure/multi_repo_saga.py`)
already express the ENTIRE atomic merge (lock → ff-merge → `--force-with-lease` CAS main-update →
`pre_merge_sha` rollback → teardown) as **synchronous function calls over an injected `GitBackend`
Protocol** (`multi_repo_saga.py:66-73`; every fn takes `git: GitBackend`; `git_backend or
SubprocessGitBackend()`). `SubprocessGitBackend` (`multi_repo_saga.py:76-95`, raw `subprocess.run`
git) is the SOLE thing touching real git. Atomicity is a property of ONE in-process orchestration
over that port — all state (`locked_sha` per repo, `pre_merge_shas`, pushed/merged lists) lives in
the orchestrating call's locals. Therefore the atomic sequence FITS ONE `merge_local` execution
(one op_id): the edge simply HOSTS the same orchestration with an edge-side `GitBackend`. No
per-repo decomposition. The port abstraction is the clean seam.

**Further de-risked:** the productive `merge_sequence.py` block is SINGLE-REPO
(`merge_sequence.py:258-262`: "a multi-repo (>= 2) run escalates fail-closed — per-repo barrier
binding needs a State change, out of scope here"). The saga blocks are n-repo-capable but the
integrated-candidate barrier binds one repo. So the productive relocation target is the single-repo
CAS merge; the scout's "atomic multi-repo CAS" worst case is NOT on the productive path. AG3-152
must preserve the ≥2-repo fail-closed escalation exactly (do not accidentally enable multi-repo).

## 1. The ONE genuine new design item (end-to-end, not the atomicity): idempotent replay
`locked_sha` is captured FRESH edge-side inside the sequence (`_lock_and_capture`
merge_sequence.py:854-930 re-reads `origin/main` at lock time), so it does NOT cross the wire —
correct CAS. But: if the edge completes the CAS push to main and the result POST is lost (edge
crash / dropped ack), a REPLAYED `merge_local` re-reads `origin/main`, finds it moved (because WE
advanced it), and `_verify_main_unchanged` (merge_sequence.py:1061-1078) would mis-escalate a
benign replay as a CAS conflict. **The edge executor needs ALREADY-MERGED DETECTION before treating
`locked_sha` drift as contention:** on entry, if `origin/main` HEAD already equals this story's
expected post-merge commit (i.e. main's tip is the story merge commit / contains the story
branch tip via `merge-base --is-ancestor story_tip origin/main` AND worktree already merged), report
SUCCESS (merge_done) idempotently instead of re-pushing. This maps onto the existing backend
`merge_done` checkpoint (merge_sequence.py:288-296 "`merge_done` returns MERGED immediately") — the
edge is now the crash surface the checkpoint must survive, so the detection lives edge-side and the
result carries the merged-sha the backend checkpoints. THIS is the item to nail (it is the analogue
of the AG3-151 wire-protocol wedge: a replay that raises instead of converging permanently wedges
closure). Cover it with an explicit replay test (edge crashes after CAS, before POST → re-fetch →
SUCCESS, no second push, no false ESCALATE).

## 2. Relocation boundary (what merge_local is, precisely)
The backend block `run_pre_merge_and_merge_block` (merge_sequence.py:224 →
`_run_standard_block`) runs the STRUCTURAL order (merge_sequence.py:240-247): lock/`locked_sha` →
integrate-latest-main → clean workspace → capture candidate commit/tree → Build/Test → scan →
tree+commit binding (E3) → IntegrityGate Dim 1-9 → CAS re-assert `origin/main==locked_sha` → ff-merge
+ atomic CAS main-update. The candidate-ref push is ALREADY an edge command (`sync_push`, AG3-147).
Scan + IntegrityGate stay BACKEND-orchestrated (they consume the edge-pushed ref via Jenkins/Sonar;
the gate VERIFIES edge-reported tree hashes, does not re-measure).

**`merge_local` subsumes the git envelope that must be co-located for atomicity — the POST-gate
segment:** ff-merge → atomic CAS push main (`--force-with-lease=main:<locked_sha>`) → rollback-to-
`pre_merge_sha` on failure → teardown. Entered only after `integrity_passed` is durable
(merge_sequence.py `_resume_merge_only`:390 already models this substate: "`integrity_passed` SKIPS
scan/gate and goes straight to the ff/CAS merge"). The backend commissions merge_local at exactly
that seam, waits for the typed result, then checkpoints `merge_done`.

**PRE-gate git prep boundary — confirm in Increment 1, in-scope either way.** The block ALSO runs
git BEFORE the scan (integrate-latest-main, clean, capture candidate commit/tree, `_lock_and_capture`).
AC-1 ("backend runs no git") requires these move to the edge too. Cleanest seam: fold the pre-gate
git prep + candidate tree-hash capture into the AG3-147 `sync_push` envelope (or a companion
`merge_local`-phase-0 within the same command family), reporting the candidate tree hash the
IntegrityGate Dim-9 then VERIFIES. If the inventory shows the pre-gate prep cannot ride sync_push
and needs its own command, THAT IS IN SCOPE — not a surprise; note it and proceed. The `locked_sha`
lock, however, MUST be captured inside merge_local (fresh, right before CAS) — never earlier /
across the wire.

## 3. Wire contract (Increment 1, blood-type A)
- `MergeLocalCommandPayload` (new, `control_plane/edge_commands.py` or its models sibling): story_id,
  base branch (`main`), participating repo(s) (name + repo_root + worktree_path) — the single-repo
  productive case is one element; carry the list shape but preserve the ≥2 fail-closed escalation,
  fast-vs-standard mode flag (fast skips gate; merge_local segment identical), and the expected
  candidate tree hash / story-branch tip for already-merged detection (§1). NO `locked_sha` (captured
  edge-side).
- New `ResultType` — extend `RESULT_TYPES` (edge_commands.py:105-109, currently
  {branch_ref_report, push_status_report, worktree_report}; NO merge shape today = the gap). Add e.g.
  `merge_local_report`: per-repo {pushed, merged, rolled_back, failed} + `escalated: bool` +
  `merged_main_sha` + `locked_sha`/`pre_merge_shas` echoes (audit) + a NAMED failure reason (mirror
  the takeover family's named-not-collective-FAIL discipline, edge_commands.py:111-127). Do NOT
  overload `push_status_report`.
- Result→`ClosureProgress`/`MultiRepoClosureState` mapper (R): translate `merge_local_report` onto
  the exact booleans the block sets today (`merge_done`, `pushed_repos`, `merged_repos`,
  `rolled_back_repos`, `failed_repo`) so the closure phase advances IDENTICALLY. Port the existing
  vertrags/golden merge tests onto this shape (no behavior change in Increment 1).
- Add `merge_local` to `EXECUTABLE_COMMAND_KINDS` (edge_commands.py:75-84) ONLY when Increment 2
  lands the executor — never before (an executable flag without an executor = silent no-op, the exact
  Scope-item-4 failure edge_commands.py:135-142 guards against).

## 4. Edge executor (Increment 2, blood-type T) — HIGHEST RISK increment
New module `src/agentkit/harness_client/projectedge/merge_local.py` (mirror `reconcile.py`:412 lines
— DO NOT bloat `command_executor.py`:828). Port the `merge_sequence.py` post-gate segment +
`multi_repo_saga` building blocks (ff-merge + `_cas_push_main`:1234 + `_rollback_after_cas_failure`
:1255 + `_rollback_remote_main`:1289 + teardown) to run edge-side over a real git backend.
- **Reuse the AG3-154 destructive-op safety pattern** (`command_executor.py` worktree-root identity
  binding: `show-toplevel==worktree_path` + registered-linked-worktree + primary-checkout refusal +
  re-validate-before-each-destructive-op). The rollback `reset --hard pre_merge_sha`
  (multi_repo_saga.py:561) is destructive — it MUST carry the same identity binding AG3-154 added for
  `reset_worktree`, or it can climb to the primary checkout. This is the AG3-154 data-loss class;
  do not re-open it.
- **Already-merged detection (§1) at executor entry — before any push/CAS.**
- Wire into the edge loop (`command_executor.py` `_dispatch_executable` + `process_open_commands`)
  WITHOUT perturbing the takeover_reconcile special-case block (it fail-closes on unreadable payload
  — keep that intact).
- Land Increment 2 with the atomic single-repo CAS + rollback + replay PROVEN edge-side (tests) BEFORE
  Increment 3 flips the backend off git.

## 5. Backend commission + precondition (Increment 3)
- `_run_merge_block` (`closure/phase.py:521`, and `_run_fast_merge_block`:657): at the post-gate seam,
  instead of calling the in-process saga segment, commission `merge_local` (mirror
  `commission_sync_push_commands` / the AG3-154 `execute_reset_worktree` commission path via
  `EdgeCommandRecord` + `commission()`), wait for the typed result, apply via the §3 mapper, then
  `checkpoint(merge_done)`.
- **Gate commissioning on the AG3-147 push-verification checkpoint (fail-closed, AC-4):** never
  commission merge_local unless the candidate ref is proven pushed+attested. A missing/failed
  push-verification ESCALATES (no merge of an unverified/unpushed candidate — same discipline as
  phase.py:544-555 CI-absent).
- Remove the in-process merge-git default: today prod uses the implicit `SubprocessGitBackend()`
  fallback (`ClosureConfig(story_dir=...)` at `composition_pipeline.py:125` never sets `git_backend`).
  After relocation the backend merge segment runs NO git.
- Relocate the three composition_closure.py git-READ seams that are part of AC-1
  (`:393` ProductiveSanityGatePort, `:425` CiBuildTestFastRunner, `:546` _CiBuildTestEvidenceAdapter —
  all `SubprocessGitBackend()`) + `closure/runtime_ports.py` SanityPort git + the verify_system
  tree-hash reads (scan_runner / sonarqube_gate `_resolve_head_commit_tree`) to edge-reported values;
  keep Integrity-Gate Dim-9 VERIFYING edge-reported tree hashes, not re-measuring. Inventory these
  with a conformance grep (AC-1) — see Increment 5.

## 6. Cross-resume (Increment 4)
If the session resumed and the worktree is gone/stale, reprovision-before-merge via the AG3-145
`provision_worktree` commissioner before commissioning merge_local (AC-5). Compose with §1
already-merged detection: a resume where main already carries the merge must converge to merge_done,
NOT reprovision-and-re-merge.

## 7. Cleanup + conformance (Increment 5)
Conformance grep proving AC-1 (no `subprocess.*git` / `SubprocessGitBackend` reachable from the
closure merge path in the backend); delete now-dead `utils/git.py` closure fns; port every
CAS-failure / rollback / ESCALATED / lease-drift / replay / ≥2-repo-fail-closed test onto the edge
executor + the wire contract. The deployed `bundles/target_project/tools/agentkit/projectedge.py`
mirror must carry the merge_local transport (SINGLE SOURCE OF TRUTH — deployed mirror == shared
transport).

## 8. Acceptance criteria (freeze)
- AC-1: backend runs NO git on the closure merge path (conformance grep green).
- AC-2: `merge_local` executes edge-side, one op_id, atomic ff+CAS+rollback+teardown in one execution.
- AC-3: the atomic green+FF barrier holds BEFORE the CAS; ESCALATED = no push, no main update, clean
  rollback to `pre_merge_sha` on partial failure; ≥2-repo still escalates fail-closed.
- AC-4: commissioning gated on AG3-147 push-verification (fail-closed).
- AC-5: cross-resume reprovisions-before-merge; already-merged replay converges to merge_done
  idempotently (no second push, no false ESCALATE).
- AC-6: result→ClosureProgress mapping advances closure byte-identically to the pre-relocation block
  (vertrags/golden tests ported, green); Integrity-Gate Dim-9 verifies edge tree hashes.
- AC-7: deployed projectedge.py mirror carries merge_local; concept gates + Sonar 0/0/0 + full suite
  green on main; coverage ≥85%.

## 9. Review plan (per session pattern)
Codex worker (write, owns green-on-main) per increment → Codex read-only review each increment →
orchestrator code-adjudication EVERY verdict → final whole-story Fable pass (the AG3-151 lesson:
the wire-protocol wedge was caught ONLY by the whole-story Fable finale). Independently verify CI
(git fetch + Sonar `project_status` API + run the concept gates myself) — never trust the job
self-report.
