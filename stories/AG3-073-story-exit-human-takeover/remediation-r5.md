# AG3-073 — Remediation R5 (after round-5 hostile re-review)

Scope: rewrote `story.md` only. `status.yaml` re-checked (matches `_STORY_INDEX.md`,
no field genuinely wrong → untouched). No production code, tests, or `concept/` files
touched. Other stories' files untouched. Stayed strictly within the AG3-073 cut (exit
orchestration is FK-58/story-exit property; the consolidated `terminal_state` result axis
stays AG3-074). All code/spec anchors re-verified against real source this pass.

`review-r5.md` listed exactly **two** must-fix design ERRORs. Both resolved below.

---

## Must-Fix ERROR 1 — ordering: binding/lock teardown was committed BEFORE the `Cancelled` transition (violates `exit_gate_passed → story_cancelled → binding_revoked`)

**Reviewer evidence (verified against real source/spec this pass):**
- The R4 story committed the `story_exit` op **together with** binding-delete + Lock-INACTIVE +
  deactivation events in ONE Phase-B commit, **before** the administrative `Cancelled` transition
  (Phase C). That sets `binding_revoked` before `story_cancelled`.
- The formal state machine requires `exit_gate_passed → story_cancelled → binding_revoked →
  ai_augmented_resumed` (`concept/formal-spec/story-exit/state-machine.md:42-51`).
- The formal command `revoke-binding` is `allowed_from: [story_cancelled]` **only**
  (`concept/formal-spec/story-exit/commands.md:36-40`).
- FK-58 §58.6 has the same order: 1 run-terminal → 2 `Cancelled` → 4 locks/binding/guards released
  → 5 `ai_augmented` (`58_story_exit_human_takeover_handoff.md:181-188`).

**Reviewer's required fix:** separate the run-terminal FENCE (non-resumable `story_exit` marker, MAY
commit first) from binding/lock revocation, which MUST happen only AFTER the administrative
`Cancelled` transition has succeeded or been idempotently confirmed.

**Buildability check (real code):** `commit_operation_with_side_effects`
(`control_plane/repository.py:95` → `state_backend/store/facade.py:871`) accepts
`binding_to_delete=None`, `locks=()`, `events=()`. So the FENCE can be a first call that writes ONLY
the `story_exit` op-row (no binding/lock side effects), and the teardown can be a SECOND call after
`Cancelled` carrying `BindingDeleteScope` + lock-INACTIVE + events. Model-faithful, no faked global
ACID tx, no second teardown owner.

**Resolved (story.md):**
- **Quell-Konzepte (`story.md:14`):** added `formal.story-exit.commands` `revoke-binding`
  `allowed_from: [story_cancelled]` and stated the binding/lock revocation must happen only AFTER
  `Cancelled`; fence is separated from teardown.
- **§1 Ist-Zustand:** added the two-separate-commits consequence — fence-only first call
  (`binding_to_delete=None`/`locks=()`/`events=()`), teardown second call only after `Cancelled`.
- **Scope #4 — phase model restructured A–E (was A–D):**
  - **Phase A** — validation + pre-mutation `exit_gate`, NO mutation.
  - **Phase B** — run-terminal FENCE: fence-only `story_exit` op-row (no binding/lock teardown);
    run becomes non-resumable; binding/locks untouched.
  - **Phase C** — administrative `Cancelled` transition (idempotent).
  - **Phase D** — binding/lock teardown (`binding_revoked`) — SECOND commit, **only after** `Cancelled`.
  - **Phase E** — controlled `ai_augmented` fallback (after D).
  - Recovery boundary keeps the canonical order C→D→E on resume; a crash between B and C leaves NO
    prematurely-revoked binding (teardown is D after C).
- **#6a / #8 / #9 / #12:** rewritten so the fence (B) is op-row-only, the teardown (D) is a separate
  commit after `Cancelled`, and the `exit_id` recovery re-drives C→D→E in canonical order.
- **AC4c:** added the `Cancelled`-before-`binding_revoked` ordering assertion + ordering negative
  tests (D not before C; E not before D); half-exit recovery test now asserts binding is NOT yet
  revoked at the crash point between B and C.
- **§5 / §6:** half-exit and FIX-THE-MODEL clauses + the R4/R5 pitfall updated to the corrected
  A→B(fence)→C→D(teardown)→E order; test-name list updated.

---

## Must-Fix ERROR 2 — `exit_gate` was specified as BOTH a pre-mutation no-mutation approval gate AND an FK-58 §58.10 post-cleanup gate (contradictory / unbuildable)

**Reviewer evidence (verified):**
- Phase A said `exit_gate` is evaluated before any mutation, failure leaves nothing mutated
  (`story.md:64`, old).
- But the same `exit_gate` required "Lock-/Binding-/Export-Cleanup abgeschlossen" + "Session nicht
  mehr im Story-Regime gebunden" (`story.md:79`, AC7 `story.md:106`, old) — exactly the FK-58 §58.10
  post-cleanup conditions (`58_story_exit_human_takeover_handoff.md:246-253`), which cannot be true
  before the Phase-B/-D teardown.

**Reviewer's required fix:** pick ONE model. Chosen explicitly: make `exit_gate` the **pre-mutation
admissibility/approval gate** and move the FK-58 §58.10 post-cleanup verification into a SEPARATE
postcondition/finalizer (`exit_finalized`).

**Resolved (story.md):**
- **Quell-Konzepte (`story.md:18`):** records the explicit model decision — `exit_gate` =
  pre-mutation approval gate (reason incl. §58.3/alternatives + record + dossier present);
  §58.10 post-cleanup conditions = separate `exit_finalized` postcondition after teardown.
- **Scope #7 rewritten:** `exit_gate` (Phase A, pre-mutation) checks exactly the three
  before-teardown-true conditions (valid reason incl. §58.3 contraindications/alternatives, record
  present, dossier present). Failure ⇒ nothing mutated. The cleanup/session-unbound conditions are
  explicitly NOT in `exit_gate`.
- **New Scope #7a — `exit_finalized`:** separate post-cleanup postcondition/finalizer verifying the
  remaining two §58.10 conditions (cleanup complete; session no longer bound to story regime), after
  Phase D/E; fail-closed if a postcondition is not reached; explicitly not a second approval gate.
  Maps to `formal.story-exit.status.ai_augmented_resumed`.
- **AC7 split:** AC7 = `exit_gate` 3 pre-mutation conditions (3 negative tests; nothing mutated on
  failure); AC7a = `exit_finalized` 2 post-cleanup conditions (2 negative tests) + a model-separation
  assertion (`exit_gate` evaluated pre-mutation and does not check (d)/(e); `exit_finalized`
  evaluated post-teardown, not an approval gate).
- **§5 / §6:** added the R5-ERROR-2 pitfall (do not double-model `exit_gate`) and the model-separation
  guardrail; test-name list updated (`exit_gate-3-Bedingungen` pre-mutation, `exit_finalized-2-
  Nachbedingungen` post-cleanup).

---

## Owner-routing check (stayed in AG3-073 cut)

Both fixes are exit-orchestration sequencing/gate-model properties of FK-58/story-exit and belong to
**AG3-073**. No cross-story re-routing: AG3-074 still owns only the consolidated `terminal_state`
result axis + `exit_class` invariants; AG3-071 (FK-53 §53.9) remains only the cited recovery
precedent (not reused machinery). No `depends_on` change (existing `[AG3-032, AG3-053]` suffices).

## status.yaml
Re-checked: `status: draft`, `phase: review_pending`, `depends_on: [AG3-032, AG3-053]`, `size: L`,
`type: implementation` — all match `_STORY_INDEX.md` (AG3-073, L). No field wrong; left unchanged.

## Anchor verification log (read from real source this pass)
- `concept/formal-spec/story-exit/state-machine.md:42-51` — order
  `exit_gate_passed → story_cancelled → binding_revoked → ai_augmented_resumed`. Verified.
- `concept/formal-spec/story-exit/commands.md:36-40` — `revoke-binding` `allowed_from:
  [story-exit.status.story_cancelled]`. Verified.
- `58_story_exit_human_takeover_handoff.md:177-189` (§58.6 order) and `:242-256` (§58.10 gate
  conditions, incl. cleanup-complete + session-not-bound as post-cleanup). Verified.
- `control_plane/repository.py:95` `commit_operation_with_side_effects`;
  `state_backend/store/facade.py:871` signature accepts `binding_to_delete=None`/`locks=()`/`events=()`
  (fence-only first call buildable). Verified.
- `story_context_manager/service.py:649-652` `cancel_story` status set + `self._story_repo.save(story)`
  (separate persistence path). Verified.

## Files written (AG3-073 only)
- `stories/AG3-073-story-exit-human-takeover/story.md` (Quell-Konzepte; §1; §2.1 #4/#6a/#7/#7a/#8/#9/#12;
  §3 AC4c/AC7/AC7a/AC8; §5; §6).
- `stories/AG3-073-story-exit-human-takeover/remediation-r5.md` (this file).
- `status.yaml` — unchanged (verified correct).
