# AG3-150 — Freeze states as admission-blocker: frozen implementation design

**Status:** FROZEN implementation contract. Feasibility verified at `main@d8bc9e89`
(scout report + orchestrator code-level adjudication of the four load-bearing
claims, 2026-07-11). The `story.md` affected-files table and every cited line
number predate AG3-148/149 and a large package decomposition — **they are
advisory; the coordinates in §0 are ground truth.** If any decision below
conflicts with the concept, STOP and report — do not silently diverge.

Concept basis (prescriptive): FK-56 §56.13f, `formal.operating-modes.invariants`
→ `freeze_states_are_admission_blockers_and_invalidate_challenges`, FK-54
§54.8.2 / §54.8.2a, FK-55 §55.8, FK-91 §91.1a Rules 13/14. Covers SOLL-086/087/092/093.

---

## 0. Corrected coordinates at HEAD (use these, not story.md)

| Concern | Current locus |
|---|---|
| Freeze overlay (A/R) | `governance/principal_capabilities/freeze.py` — `freeze()` :194, `release()` :237, `is_frozen()` :246, `apply()` :280, `_record_freeze_version` :386; counter is `freeze_version` (monotone), **no `freeze_epoch`** |
| Freeze record model | `state_backend/store/freeze_repository.py` — `FreezeRecord` :47 (`story_id, frozen_at, freeze_reason, freeze_version`); SQL literals `_SQLITE_UPSERT` :118 / `_PG_UPSERT` :130 / `_row_to_record` :226 |
| Freeze proof repo | `state_backend/store/conflict_freeze_proof_repository.py` |
| Schema (PG) | `state_backend/postgres_store/postgres_schema.sql` — `governance_freeze_records` :1151, `conflict_freeze_proofs` :1179 |
| Schema (gated SQLite) | `state_backend/sqlite_store/_schema_runtime.py` — :620 / :648 |
| Admission A-core | `control_plane/ownership_fence.py` — `evaluate_ownership_admission()` :74, `OwnershipAdmission` :61 (`.admitted/.active_record/.rejection_reason`) |
| Regime decision points | `runtime/_admission_phase_mutation.py:182` (complete/fail early read via `_run_was_admitted`) + **commit fence :224** (`OwnershipFenceViolationError`, AG3-142 no-TOCTOU choke point); `runtime/_admission_start_phase.py` (start, mint logic :424-530); `runtime/_service_resume.py`; `runtime/_service_closure.py` |
| No-active-record rejection (149 fence) | `runtime/_admission_rejections.py:198` (ended/reset/split/never-admitted), fence-violation :212-215 |
| Postgres-only guard | `runtime/_di.py:35` (`_require_postgres_control_plane_backend`) |
| Takeover confirm (A-core) | `control_plane/ownership_transfer.py` — `evaluate_takeover_confirm` :243; `InvalidationReason` literal :52; `challenge_invalidated_by_transition` :297; ping-pong barrier `evaluate_disowned_session_takeover_barrier` :304 |
| Takeover confirm (runtime) | `runtime/_ownership_transfer.py` — confirm call :541, commit :695, `_has_invalidating_transition` :1134 |
| Committed-invalidation probe | `repo.has_committed_ownership_invalidating_operation_for_run(...)` |
| Split saga | `story_split/service.py` — `split_story` :213, `_commit_terminal_transition` :590 (atomic marker+disown+terminalize), `_run_split_to_completion` :281, `_finalize_fence` :691 (called :411), `build_disown_plan` import :17 / split-disown :648, `derive_split_id` :234, resume :245-247 / `_resume` :1044, successor op_id `f"{split_id}:successor:{index}:{successor.story_id}"` :755, `materialize_split_lineage` :96, quiesce `purge_run` :325. **`_commit_fence` no longer exists.** No `object_claims` usage yet. |
| Per-story claim (AG3-141) | `control_plane/object_claims.py` — `acquire_story_claim` :185, `release_story_claim` :216, `ObjectClaimStorePort` :154, `ObjectClaimConflict` (deterministic 409+Retry-After, never blocking wait); table `object_mutation_claims` (`postgres_schema.sql:361`); repo `ObjectMutationClaimRepository` (`control_plane/repository.py:347`) |
| Enforcement freeze consult | `enforcement.py` — freeze `apply` :403, stacked `_disowned.apply` :404 (149), true-frozen hull :470/:476 |
| Integrity gate | `integrity_gate/dimensions.py:717` `_check_conflict_freeze_proof` (dispatch :436), reads `has_active_conflict_freeze` :727 + `has_conflict_freeze_proof` :728, fail-closed :729/:753 |

Other 148/149 drift the implementer must respect: `OwnershipBasis` (`ownership_transfer.py:56`), `disown.py` A-core (`build_disown_plan`/`DisownPlan`, four callers incl. split), the stacked `_disowned` enforcement overlay ordering, the ping-pong barriers at confirm.

---

## 1. Design decisions (the model — not negotiable without a STOP)

### Pillar 1 — Freeze family + `freeze_epoch`

- **One table, additive columns** on `governance_freeze_records` (dual-defined PG + gated SQLite): add `kind TEXT NOT NULL` and `freeze_epoch` (canonical decimal string, monotone-positive-integer domain). No new table (the family is a discriminated record set, not a new aggregate). New tables would fragment the single source of truth — forbidden here.
- **Family `kind` vocabulary** (closed, typed enum — ARCH-55 English): `conflict_freeze` (existing; the DEFAULT kind, behaviour unchanged), `split_admin_freeze` (pillar-4), `reconcile_repair` (AG3-138 member — folded in here as vocabulary + admission effect only; its *entry* is AG3-138), `contested_local_writes` (AG3-151 creates the *entry*; vocabulary + blocker mechanics born here).
- **`freeze_epoch` = DB-monotone per story**, derived from the previously-persisted epoch for that story + 1 (initial = MIN), mirroring the `binding_version` `_next_binding_version` pattern (FK-56 §56.13a CAS foundation). **NO wall clock, NO process counter, NO TTL.** Additive to the existing `freeze_version` (which stays for local-export match); `freeze_epoch` is the story-scoped monotone admission/challenge-invalidation anchor.
- **`FreezeRecord`** (`freeze_repository.py:47`) gains `kind` + `freeze_epoch`; the three SQL literals (`_SQLITE_UPSERT`/`_PG_UPSERT`/`_row_to_record`) and both schema files carry them. `conflict_freeze` set/read/clear/is_frozen and the proof path stay behaviourally identical (contract-green).
- **Resolving-command registry** = a typed mapping (blood-type A, in `freeze.py` or a sibling A-core module) `kind → frozenset[resolving command-id]`. This is the SINGLE allowlist the admission blocker (pillar-2) consults. No scattered string checks. Fail-closed: an unknown kind, a missing `freeze_reason`, or an unreadable freeze state is treated as a blocking freeze that NO command resolves.

### Pillar 2 — Generic story-scoped admission blocker

- **Predicate:** a mutating admission requires BOTH an active ownership record AND no blocking freeze. Extend `evaluate_ownership_admission` (`ownership_fence.py:74`) to accept the story's active blocking-freeze state (the set of active family records) and the invoking command-id; return `admitted=False` with a structured freeze `rejection_reason` when a blocking freeze is present that the command is not registered to resolve. The record stays `active` — the freeze blocks **additively**, it does not change ownership status.
- **No TOCTOU:** the freeze state is read at the persistence boundary of the SAME mutation whose atomic commit serialises the write, exactly like the ownership record. The blocker is enforced at BOTH the early `_run_was_admitted` read sites AND the AG3-142 commit fence (`_admission_phase_mutation.py:224` — the `OwnershipFenceViolationError` choke point) so a freeze entering between read and commit still blocks. All regime paths: start / complete / fail / resume / closure + executor commit.
- **Only registered resolving commands pass.** Fail-open exceptions are forbidden; there is no system-principal bypass (NO ERROR BYPASSING). The allowlist is the pillar-1 registry, keyed by `kind`.

### Pillar 3 — Challenge invalidation + takeover-admissibility

- **Extend `InvalidationReason`** (`ownership_transfer.py:52`) with `"freeze"`. On entry into ANY family-member freeze, open takeover challenges for the story are invalidated (the entry is an invalidating transition — additive to the existing basis-CAS + committed-invalidation-probe, both of which are blind to a still-`active` freeze).
- **Takeover-admissibility** precondition inside `evaluate_takeover_confirm` (`ownership_transfer.py:243`, A-core): a NEW input = the story's active blocking-freeze state. If any blocking freeze is active → confirm fails deterministically with a structured Rule-8 error (contract-pinned), regardless of basis. Slots ALONGSIDE the ping-pong barriers (`evaluate_disowned_session_takeover_barrier` :304) — does not replace them.
- After freeze resolution a NEW request is required; invalidated challenges do NOT revive (negative test).

### Pillar 4 — Split exclusive-fence → admin-freeze saga (highest churn)

- **Re-derive against the 149-rewritten surface** (`_commit_terminal_transition` :590 / `_finalize_fence` :691 / existing `build_disown_plan` :648) — the old `_commit_fence` is gone; do NOT resurrect it.
- **Admin-freeze over the saga:** at saga start enter a `split_admin_freeze` family record on the source story (audited, never auto-expiring, admission-blocker via pillar-2). It is resolved by the saga's own finalization path (a registered resolving command), never by TTL.
- **Per-step bounded claims:** each saga sub-commit (successor creation + numbering in one transaction) acquires its own per-story object-claim via `object_claims.acquire_story_claim` and releases it via `release_story_claim` per step. Between steps the saga holds NO serialization claim — an independent story of the same project stays mutable (concurrency integration test). The saga as a whole holds no claim across its runtime.
- **Reentrancy is docked, not rebuilt** (SOLL-087): preserve the existing `op_id`-lineage resume convergence (`derive_split_id` :234, successor op_id :755, resume :245-247 / :1044, `materialize_split_lineage` :96). Resume after a mid-saga abort with an active admin-freeze converges without double-execution (no duplicate successor, no second rebinding, no second source-cancel).

### Blood-type placement

Freeze-family model, `freeze_epoch` minting, admission predicate, admissibility + invalidation rules, saga model, resolving-command registry = **A** (pure, no persistence/clock). Row↔record and error-shape mappers = **R**. Persistence row functions in `state_backend` = **AT/T** (localized there). The A-core stays AT-free (no store/clock import).

---

## 2. Implementation plan — TWO sequential increments

Split to de-risk the highest-churn pillar and keep each increment reviewable
(no God-task). Each increment owns its own green-on-main loop and is
review-converged (Codex + orchestrator adjudication + **Fable finale**) BEFORE
the next starts — pillar-4 must not be built on an unreviewed base. The story
closes (`status.yaml=completed`) only after BOTH increments + full DoD green.

- **Increment 1 — Freeze family + admission + challenge (pillars 1+2+3).**
  Additive schema/columns + family vocabulary + `freeze_epoch` + resolving
  registry + admission-blocker at all regime paths (incl. commit-fence no-TOCTOU)
  + `InvalidationReason "freeze"` + takeover-admissibility. Cohesive: all read
  the same family. `conflict_freeze` + proof semantics stay contract-green.
- **Increment 2 — Split admin-freeze saga (pillar-4).** On the stable
  increment-1 base: admin-freeze wrap + per-step `acquire/release_story_claim`
  + reentrancy docking, against `_commit_terminal_transition`/`_finalize_fence`.

### Acceptance (from story.md, unchanged) — all 10 ACs; highlights per increment

- Inc-1: AC1 (record form: `freeze_epoch`/`freeze_reason`/kind/audit, contract-pinned;
  conflict_freeze unchanged), AC2 (blocker at every regime path, record stays
  active, negative test per phase boundary, no state-write), AC3 (resolving
  commands pass; every other blocked; registry not scatter-checks), AC4
  (challenge invalidation per kind + no revival), AC5 (takeover-admissibility
  Rule-8 error, contract-pinned), AC6 (no auto-expiry: code-proof + advanced-clock
  negative test), AC9 (fail-closed on unknown kind / missing reason / unreadable),
  AC10 (cov≥85, mypy strict + `--platform linux`, ruff, ARCH-55).
- Inc-2: AC7 (admin-freeze during saga; exclusive committed-op hold replaced,
  code-proof; per-step claim acquired+released; independent story mutable —
  concurrency integration test), AC8 (resume converges, no double-execution,
  + abort-between-sub-commits-with-active-admin-freeze case).

### Guardrails carried into every worker prompt

venv only (`.venv\Scripts\python`); local Postgres 127.0.0.1:55442 then 55642;
`--basetemp var\t` removed after; single-pass coverage + scoped inner loop
(control_plane / governance / story_split / state_backend) per
`guardrails/test-execution-efficiency.md`, full suite once pre-push, mypy always
full both platforms; 4 concept gates green. Green-on-main: ruff → mypy src →
mypy src --platform linux → pytest → 4 gates → push main → Jenkins
`buildWithParameters?agentkit_mode=ci&sonar_project_key=claude-agentkit3&sonar_branch=main&delay=0sec`
(CSRF crumb + admin:password) → Jenkins SUCCESS + Sonar OK. Sonar
http://localhost:9901 admin/`meinSonarCube2026!` key `claude-agentkit3` (0/0/0,
new-code cov≥80). Do NOT set `status.yaml=completed` (review + Fable finale
follow). If a fix conflicts with this frozen design → STOP and report.

---

## R1 Remediation addendum — 2026-07-11 (Inc-1 defect review, 4 ERRORs)

Codex Inc-1 defect review (`job-633928a6`) + orchestrator code-level adjudication
found 4 real ERRORs. Two are a **model defect** (FIX THE MODEL, not the symptom);
two are an executor-path fencing gap + its fake test. This addendum CORRECTS the
pillar-1 persistence model and TIGHTENS pillar-2 executor coverage. It supersedes
the "one table, additive columns" wording of §1 pillar-1 where they conflict.

### F1+F2 — freeze family must be a per-`(story_id, kind)` SET with story-monotone epoch
- **Root cause:** `governance_freeze_records` PK is `story_id` only (schema :1163;
  upsert `ON CONFLICT (story_id)` :131/:146) → at most ONE freeze row per story.
  A second family member overwrites the first; `clear_freeze` hard-deletes the
  sole row (:250). Two consequences: (a) two coexisting members collapse to one,
  so resolving one silently erases an unresolved sibling and admission wrongly
  passes — violates "block on ANY unresolved member"; (b) `freeze_epoch` resets to
  `"1"` on enter→resolve→re-enter — not story-monotone.
- **Why coexistence is real (concept):** `reconcile_repair` (AG3-138 admin_abort
  partial-write) and `contested_local_writes` (AG3-151 takeover-reconcile) are
  RECOVERY states that must be enterable precisely WHILE another freeze is active;
  gating them behind "no other freeze" would deadlock recovery. The family is a
  set, not a scalar.
- **Required model:**
  1. PK becomes `(story_id, kind)` (both schema files; upsert conflict target
     `(story_id, kind)`). One row per active `(story, kind)`.
  2. Reads return the SET of active members for a story; admission (`_run_gates`
     early read + `_enforce_blocking_freeze_row` commit fence) blocks on ANY
     unresolved member the command does not resolve — the commit-fence query must
     select ALL rows for the story (drop the implicit single-row assumption), keep
     `FOR UPDATE` + advisory lock.
  3. Resolution clears the SPECIFIC `(story_id, kind)`, never the whole story;
     `clear_freeze` gains the `kind` argument AND takes the story advisory lock
     (it currently takes none).
  4. `freeze_epoch` is minted **monotone per story across all members** and MUST
     survive member resolution (no reset). Source the monotone value from a
     per-story highwater that persists independent of active rows — the freeze
     **audit trail** is the natural append-only source (next = max(story audit
     epoch) + 1), or an equivalent never-decremented per-story counter. NO wall
     clock, NO process counter. `next_freeze_epoch` stays the pure `prev+1` rule;
     only the "prev" READ changes to the surviving story highwater.
  5. `conflict_freeze` behavioural parity: its reads/writes/proof path must stay
     green — a `conflict_freeze` row is just the `kind='conflict_freeze'` member of
     the set; existing set/read/clear/is_frozen callers keep working (clear defaults
     to / passes `kind='conflict_freeze'`).

### F3+F4 — executor path bypasses the transactional freeze fence
- **Root cause:** start/resume read no freeze then enter the real phase executor;
  the executor persists `AttemptRecord` + `PhaseState` via INDEPENDENT persistence
  calls (`_admission_start_phase.py:395-460/:731-744`, `_service_resume.py:201-292`,
  `pipeline_engine/phase_executor/save_phase_completion.py:66-67`) with NO freeze
  fence. A freeze entering mid-execution → control-plane finalize rejects
  `story_frozen`, but the executor's productive phase state is already durable
  (`_service_resume.py:277-292` says it stands). Violates AC2 "no state-write on a
  frozen rejection".
- **Required:** the executor/committed-op path must pass the SAME transactional
  freeze fence as the control-plane commit — either (a) the executor's phase/attempt
  persistence checks the blocking-freeze set in its own commit transaction and
  refuses to persist when a blocking freeze is active, or (b) the finalize rejection
  path guarantees the executor writes are not durable (roll back / never committed)
  when `story_frozen`. Whichever is chosen, the invariant to prove: NO durable
  phase/attempt state exists after a `story_frozen` rejection. Preserve resume
  idempotency.
- **F4 (fake test):** `test_postgres_freeze_entering_during_executor_dispatch_blocks_commit`
  (`test_ownership_fencing_pg.py:232-260`) uses `_FreezingDispatcher` that fabricates
  a `PhaseDispatchResult` and never runs `PipelineEngine` or persists phase/attempt
  state; `_assert_real_freeze_block` (:521-532) checks only control-plane operation
  absence + active ownership, NOT executor-state absence. Rewrite it to drive the
  REAL PipelineEngine and assert NO durable phase/attempt state after the frozen
  rejection (this is the test that must fail-before / pass-after for F3).

### Non-goal
No pillar-4 (split saga) work — still Increment 2.

---

## R2 OPEN DESIGN QUESTION — freeze entering mid-admitted-execution (2026-07-11)

The R1 convergence review (`job-608798bd`) returned CHANGES-REQUIRED with 3 findings.
Findings 1+2 are NOT a plain guard-hole; they expose a genuine design-semantics
tension that must be RULED before any R2 code. STOP-and-decide, per anti-loop
discipline (the AG3-148 lesson: when findings move from instance-bug to
invariant-in-tension, fix the model/spec, do not loop remediation).

### The findings
- F1: `flow_executions.status="IN_PROGRESS"` is written at `phase_start` (BEFORE the
  handler) unfenced (`engine.py:267`, `runtime_state.py:130`, `_runtime_rows.py:337`).
  The start path IS freeze-checked, so a freeze active AT start blocks it — this is
  the MID-EXECUTION race: a freeze entering during the handler leaves the admitted
  IN_PROGRESS row durable while `save_phase_completion_rows` correctly blocks the
  completion.
- F2: the executor fence (`save_phase_completion_rows`) is in a transaction SEPARATE
  from the control-plane finalize (`_finalize_start_phase`, `_admission_start_phase.py:271`).
  Window: handler completes → completion commits (no freeze) → concurrent `set_freeze`
  commits → engine does more unfenced snapshot/flow/ledger writes → finalize observes
  the freeze → returns `story_frozen`, but the completed PhaseState/attempt/snapshot/
  FlowExecution/ledger are already durable. A fence separate from finalize cannot
  guarantee "NO durable state after a story_frozen rejection".
- F3: the rewritten race test covers only the newly-fenced window; does not assert the
  IN_PROGRESS row absence, cannot expose the post-commit/pre-finalize race. (Valid
  regardless of the ruling; will be fixed with whatever remediation follows.)

### The tension
AC2 says a regime mutation "bei aktivem blockierendem Freeze" is rejected "ohne
State-Write". That is the STEADY STATE (freeze already active at the mutation point).
F1/F2 are a RACE (freeze entering during / just after an already-ADMITTED in-flight
execution). The R1 prompt's invariant "NO durable phase/attempt state after a
story_frozen rejection" (my wording) is possibly STRONGER than the concept requires
for the race — enforcing it literally forces executor writes to be atomic with
finalize (one DB transaction spanning a long-running LLM handler) or a provisional/
two-phase-commit model. Candidate readings:
- (A) BLOCK-FORWARD-ONLY: a freeze blocks forward progress (completion, next phase,
  finalize) but does not retroactively guarantee zero durable trace of an
  already-admitted in-flight execution; in-flight/partial productive state is
  reconciled via resume idempotency + the `reconcile_repair` family member (AG3-138).
  Under (A), F1's IN_PROGRESS trace is expected-and-reconciled; F2's completed-then-
  frozen finalize may still need finalize to treat an already-completed phase as
  completed (not story_frozen), i.e. the ordering/decision is the fix, not atomicity.
- (B) NO-TRACE: AC2's "no state-write" applies whenever story_frozen is returned,
  requiring executor+finalize atomicity or provisional commits — a larger change.

### Ruling needed (Fable design agent, concept-grounded)
Which reading does FK-56 §56.13f + FK-54 §54.8.2/§54.8.2a (quiesce) +
`formal.operating-modes.invariants` require? And what is the BOUNDED, concept-faithful
Inc-1 fix (vs what defers to AG3-138 reconcile_repair / resume)? The ruling is the
input to R2. Do NOT dispatch R2 code until this is decided.

### R2 RULING (SETTLED, Fable + orchestrator concept-adjudication 2026-07-11)

**READING: A — commit-fence + no-retroaction + truthful-finalize.** Reading B (no-trace)
has NO concept basis. Citations verified verbatim by the orchestrator:
- `formal-spec/state-storage/invariants.md:69` (`operation_finalize_requires_cas_on_operation_epoch`):
  "an aborted operation with partial writes **enters an audited reconcile repair state**
  instead of silently becoming failed" → partial in-flight traces are first-class, owned
  by `reconcile_repair` (AG3-138) + resume idempotency.
- `invariants.md:72` (`stale_results_never_overwrite_current_projections`): "rejected
  deterministically **with no state write**" is scoped "**at commit time**" — per-commit,
  never retroactive. Mirrored by FK-91 §91.1a Rule 15 (Abschluss-Commit fence). FK-54
  separates fence (§54.8.2) from quiesce (§54.8.3) as two explicit saga steps — freeze
  entry does NOT imply quiesce. FK-91 Rule 14/16: long-running sync execution +
  reconciliation is the sanctioned model. Crash-equivalence clinches it: a power loss
  mid-handler leaves the identical durable IN_PROGRESS row; the concept owns that class
  via reconcile/resume, so no-trace-for-freeze-but-trace-for-crash would be incoherent.

**The two invariants replacing R1's over-strong wording:**
- **INV-FRZ-1 (per-commit, AC2):** any mutating commit executed while a blocking freeze is
  active (command not registered-resolving) is rejected deterministically; THAT mutation
  writes no productive state (no phase_state/attempt/snapshot from it); ownership record
  stays `active`; the rejection terminalizes the operation with a structured, replayable
  freeze error (audit/ledger terminal status is NOT a productive write).
- **INV-FRZ-2 (truthful finalize):** finalize NEVER returns `story_frozen` for an operation
  whose productive completion commit is already durable; a `story_frozen` result implies no
  durable productive state from that operation's completion. Op-ledger terminal status and
  durable canonical state never contradict (SINGLE SOURCE OF TRUTH; op_id replay Rule 5/17).

**Per-finding (settled):**
- **F1 = EXPECTED, deferred.** The IN_PROGRESS row was a legally admitted freeze-checked
  commit; a freeze during the handler blocks the COMPLETION commit (R1's fence, kept). The
  leftover trace is the concept's partial-write condition, owned by resume + admin_abort →
  reconcile_repair (AG3-138). Bounded Inc-1 obligation only: deterministic terminal
  op-ledger outcome on the frozen rejection + ownership stays active + no phase_state/
  attempt/snapshot from the blocked completion.
- **F2 = MUST-FIX-IN-INC-1, via finalize decision/ordering (NOT atomicity).** Completion
  that passed the fence with no freeze active STANDS; finalize reports the completed
  outcome (freeze at most advisory detail); the freeze blocks the NEXT mutating admission
  (next start/resume/closure/takeover-confirm). Fence-separate-from-finalize is correct
  under Reading A.
- **F3 = fix test, both race windows, real PipelineEngine.**

**R2 MUST do:** (1) finalize decision fix in `_finalize_start_phase`
(`_admission_start_phase.py:271`): decide from what durably committed — completion durable
→ report completed; completion fenced out → `story_frozen`. (2) Keep R1's completion fence
(the linearization point). (3) Frozen-rejection path terminalizes the op-ledger entry with
the structured freeze error; IN_PROGRESS row remains as tolerated in-flight trace.
(4) Rewrite the race test for BOTH windows (w1 mid-handler → completion fenced, no
attempt/phase_state/snapshot, IN_PROGRESS tolerated, record active, op terminal-frozen,
subsequent start/resume blocked; w2 post-completion-commit pre-finalize → finalize returns
completed + consistent, NEXT admission blocked). (5) Document the reconcile obligation
(this note; no code).

**R2 MUST NOT build:** executor+finalize single-transaction atomicity; provisional/
two-phase phase-state commit; freeze-entry quiesce barriers aborting running handlers
(quiesce belongs to the admin sagas, FK-54 §54.8.3 / FK-53 §53.7.3); rollback of
legally-committed completions; the reconcile_repair ENTRY (AG3-138) or contested_local_writes
entry (AG3-151).

**Optional concept belt-and-braces (P3, not Inc-1 code):** a one-paragraph clarifying
sentence in FK-56 §56.13f ("Der Freeze wirkt am Commit; bereits gefenct-committete
Ergebnisse einer zuvor admitteten Operation bleiben bestehen; Teil-Spuren unterbrochener
Operationen sind Gegenstand des auditierten Reconcile-/Repair-Zustands") + a decision record.

---

## R3 — truthful finalize must decide from durable truth, not a narrow flag (2026-07-11)

R2 convergence re-review (`job-446fc0a3`) returned CHANGES-REQUIRED with 3 findings;
orchestrator adjudicated each at code.

- **F1 + F2 = REAL (same root).** R2's truthful-finalize predicate is TOO NARROW:
  `_has_durable_phase_completion` requires `state.status='completed' AND attempt.outcome='COMPLETED'`,
  and `productive_completion_returned` is True only for dispatch `status=="phase_completed"`.
  But the executor durably commits MANY productive dispatch outcomes through the
  freeze-fenced `save_phase_completion_rows` (FAILED-with-backtrack + SKIPPED override →
  dispatch returns phase_completed but attempt≠COMPLETED, `engine.py:806-861`;
  PAUSED/YIELDED/FAILED/ESCALATED → durable via `result_handling.py:571-823`,
  `_runtime_rows.py:217-290`, but `productive_completion_returned=False`). In all these,
  a freeze entering after that fenced commit but before finalize makes finalize report/
  terminalize `story_frozen` over durable canonical state → INV-FRZ-2 violation (op-ledger
  lie). Verified at `_admission_start_phase.py:283-287` + `_mutation_commit_rows.py:135-185`.
- **F3 = NOT A DEFECT (rejected; contradicts the settled ruling).** `result_handling.py:475-503`:
  `save_phase_completion` (fenced canonical commit) is FIRST (comment :475-479); then
  `save_phase_snapshot` (PhaseSnapshot status=COMPLETED, derived from `completed_state`) and
  `record_flow_execution`/`record_node_outcome` follow as PROJECTIONS of the already-committed
  completion. Per the R2 ruling, post-completion snapshot/flow are projections that MUST be
  allowed to complete — blocking/fencing them would desync projections from canonical state.
  INV-FRZ-1 applies only to a REJECTED mutation; this completion stood. Crash-equivalence: a
  crash between :480 and :485 yields the identical attempt-without-snapshot state that resume
  already tolerates. Fencing the snapshot (as the finding implies) would be the actual defect.
  R3 must NOT fence save_phase_snapshot / record_flow_execution / record_node_outcome.

### R3 FIX (F1+F2, FIX-THE-MODEL): finalize decides from DURABLE TRUTH, not the in-memory flag
- Replace the narrow flag / completed-only check with: finalize re-reads the durable canonical
  phase_state + attempt FOR THIS operation's dispatch (keyed to this op_id / run / phase /
  attempt_id — must not honor a stale PRIOR attempt) and reports the ACTUAL durable outcome
  (completed / failed(+backtrack) / paused / escalated / skipped / needs_review). It reports
  `story_frozen` ONLY when this operation's productive commit did NOT durably land (the fence
  rejected it — no durable attempt/phase_state from THIS dispatch). This closes the whole
  outcome class by construction; do NOT enumerate statuses (a future outcome would reintroduce
  the bug).
- Keep INV-FRZ-2 intact in BOTH directions: never report `story_frozen` over a durable
  productive outcome; never report a productive outcome when nothing durably committed.
- Keep the R1 completion fence (the linearization point) and F1 terminalization for the
  genuinely-fenced-out case (nothing durable → story_frozen terminal, replayable).
- Tests: extend the race suite with the FAILED-backtrack and PAUSED/ESCALATED post-commit
  windows — freeze after a non-COMPLETED-but-durable outcome commits → finalize honors that
  actual outcome (not story_frozen), op-ledger == canonical truth, NEXT admission blocked.
- R3 must NOT: fence projections (F3); build executor/finalize atomicity, provisional/two-phase
  commit, rollback, or a quiesce barrier; change story_split/service.py.

---

## Inc-1 CONVERGENCE STATUS (2026-07-11)

Increment 1 (pillars 1+2+3 + truthful-finalize) CONVERGED at **main@ba422598**
(Jenkins #1792 SUCCESS, Sonar 0/0/0, new-code cov 84.0%, 9264 tests).
Round trajectory: worker → review-1 (4 real) → R1 → review-2 (3 real, design) →
Fable ruling (Reading A) → R2 → review-3 (2 real + 1 rejected-as-ruling-contradiction) →
R3 (durable-truth by construction) → review-4 **APPROVE** + orchestrator code-adjudication
of every round. PENDING GATE: Fable finale on Inc-1 (dispatched). On Fable APPROVE →
proceed to **Increment 2 (pillar 4 — split admin-freeze saga)** on this base;
Inc-2 is dispatched against §1 pillar-4 + §0 coordinates, using object_claims
acquire/release per saga step against the 149-restructured
_commit_terminal_transition/_finalize_fence surface. story_split/service.py
still unchanged as of ba422598. status.yaml NOT yet completed (whole story closes
after Inc-2 + full DoD + a final review pass).

---

## Inc-1 FABLE FINALE — APPROVE (2026-07-11)

Fable finale on main@ba422598: **VERDICT: APPROVE** (deep adversarial, 65 tool-uses;
per-area 1-7 file:line evidence; independent unfenced-writer hunt + Component-Architecture
lens). Converges with Codex R3 APPROVE + orchestrator code adjudication. Increment 1 is
ship-fit. Three-reviewer convergence achieved.

### Non-blocking observations — disposition (ZERO DEBT: recorded, not silent)
- **O1 (sanctioned, NOT a defect + tracked):** the CCAG lazy TTL escalator
  (`governance/ccag/expiry.py:122`, wired `governance/runner.py:2218-2234`) writes canonical
  `PhaseState → ESCALATED` unfenced at the hook edge; a PAUSED+frozen story whose permission
  TTL elapses gets a status mutation while frozen. RULING: this is NOT an INV-FRZ-1 violation
  and MUST NOT be fenced in Inc-1. Reasoning (Reading A + FK-42): a freeze blocks forward
  PRODUCTIVE progress; an ESCALATED transition is HALT-DIRECTIONAL safety signalling, not
  productive progress, and FK-42 §42.4.2 mandates it deterministically — fencing it would
  VIOLATE FK-42. It is the one canonical writer outside the freeze admission surface, sanctioned
  here explicitly. Tracked as awareness tech-debt (revisit only if a concept later requires
  halt-signals to also pause under freeze).
- **O2 (DRY nit, tech-debt):** `_enforce_blocking_freeze_row:241-255` hand-rolls the row→
  ActiveFreezeState mapping though `core_types.freeze.active_freeze_state_from_record` exists;
  semantics verified identical. Cosmetic; tracked.
- **O3 (Inc-2 uniformity):** asymmetric frozen-fence ledger footprint — start terminalizes the
  op as `story_frozen`; resume releases the claim and returns a non-stored rejection. Both safe
  (nothing durable, deterministic replay/retry). Noted for Increment-2 uniformity, not a defect.
- **O4 (design-letter, awareness):** a takeover request minted WHILE a freeze is already active
  is not invalidated (invalidation fires at freeze ENTRY only); its challenge becomes confirmable
  after resolution without a new request. Basis-CAS still protects correctness. Matches the
  design letter; awareness only.
- **O5 (moot):** SQLite set_freeze does no challenge invalidation — control plane is PG-only
  (`_di.py:35`), SQLite has no takeover tables. Structurally moot.

Inc-1 SEALED at main@ba422598. Proceeding to Increment 2 (pillar 4).

---

## Inc-2 R1 — successor creation must run under the per-step claim (2026-07-11)

Inc-2 defect review (`job-29609627`): CHANGES-REQUIRED, 1 ERROR (other 6 areas closed).
Orchestrator confirmed at code (`service.py:985-1009`): the successor-creation loop calls
`create_story` DIRECTLY at :986 — OUTSIDE `run_claimed_step`; only the checkpoint (:998) and
the following step (:1010) are claim-gated. So the productive successor create+number
sub-commit is NOT under the per-story object claim: a foreign claim on the source lets the
successor be durably created, conflict detected too late (AC7 + fail-closed violation). Test
gap: `acquired==released` cannot detect an OMITTED acquisition.
R1 (`job-6c10a16c`, dispatched): wrap the create_story sub-commit in run_claimed_step
(story_id=source, distinct op_id), fail-closed BEFORE the create; preserve op-id idempotency,
crash-before-export checkpoint ordering, and op_id-lineage resume convergence; add a test that a
held conflicting claim rejects the creation with NO successor durably created. Inc-2 base:
main@e9c1e44f (Jenkins #1796). After R1 green: adjudicate → re-review → Fable finale Inc-2 →
whole-story DoD + status.yaml=completed (unblocks AG3-151).

---

## Inc-2 FABLE FINALE — APPROVE + STORY CLOSED (2026-07-11)

Fable finale on main@31b44c6a: **VERDICT: APPROVE** (38 tool-uses; per-area 1-7 file:line
evidence; explicit confirmation the R1 claim-wrap introduced NO reentrancy/resume regression;
full durable-writer sweep confirms every productive sub-commit is claim-gated). Whole story
closeable. Non-blocking: N1 (resume finalized-replay clear runs without a per-step claim —
idempotent/kind+reason-scoped/rowcount-checked; cosmetic, same family as sealed O3), N2 (no-TTL
strand → same-instance startup reconciliation / admin_abort; deliberate design), N3
(freeze_version=1 constant is the local-export-match counter, consistent — freeze_epoch is the
monotone anchor). All recorded per ZERO DEBT; none gates shipping.

### AG3-150 — WHOLE STORY CLOSED at main@31b44c6a
Inc-1 SEALED (ba422598, 3-reviewer convergence) + Inc-2 R1 (31b44c6a, Codex review + orchestrator
code-adjudication + Fable finale APPROVE). Covers SOLL-086/087/092/093. DoD: all ACs met
(freeze-family record form + epoch, admission-blocker at every regime path, resolving-command
registry, challenge invalidation + takeover-admissibility, no auto-expiry, split admin-freeze
saga with per-step claims + docked reentrancy); gate suite green (ruff, mypy both platforms,
pytest 9268 passed, cov 92.44% local / 84.0% new-code Sonar, 4 concept gates); Jenkins #1800
SUCCESS; Sonar 0/0/0. Unblocks AG3-151. Deferred by ruling: positive self-rebind → AG3-154 (via
149). Carried tech-debt: O1 CCAG escalator (sanctioned), O2/N1 DRY/uniformity nits, SQLite
ResourceWarnings (#20).
