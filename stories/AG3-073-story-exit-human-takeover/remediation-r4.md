# AG3-073 — Remediation R4 (after round-4 hostile re-review)

Scope: rewrote `story.md` only. `status.yaml` re-checked (no field genuinely wrong, untouched).
No production code, tests, or `concept/` files touched. Other stories' files untouched.
Stayed strictly within the AG3-073 cut from `_STORY_INDEX.md` (row AG3-073: `exit-story` CLI,
reason-enum, four artefacts, `exit_gate`, `exit_class=viability_handoff` under Cancelled,
controlled fallback to `ai_augmented`). All code anchors re-verified against real source this pass.

`review-r4.md` confirmed both R3 ERRORs RESOLVED and listed exactly **one** new must-fix ERROR
(the per-dimension FAIL/WEAK verdicts summarize that one ERROR; no separate WARNINGs in R4).
It is resolved below.

---

## Must-Fix ERROR 1 — exit orchestration can leave a partially exited run (no atomicity / recovery boundary; wrong ordering vs. the formal state machine)

**Reviewer evidence (verified against real source this pass):**
- The R3 story ordered `story_exit` control-plane commit + teardown **before** the administrative
  `Cancelled` transition, then fallback, then `exit_gate` (gate last). This **inverts** the canonical
  story-exit sequence.
- The control-plane primitive is atomic **only** for op/binding/locks/events, NOT the StoryService
  status: `commit_control_plane_operation_with_side_effects_global` (`facade.py:871`) covers the
  op-row + binding + locks + events in one store transaction. `StoryService.cancel_story`/
  `complete_story` persist status via a **separate** repository path
  `self._story_repo.save(story)` (`service.py:652`/`:758`; concrete impl `story_repository.py:152`).
  → Two separate persistence paths, **no** cross-repo ACID transaction. If teardown commits and the
  later administrative cancel fails, the run is terminal/binding-revoked while the story can remain
  `In Progress` — a durable half-exit.
- This also conflicts with the formal story-exit state machine, which transitions
  `exit_gate_passed → story_cancelled → binding_revoked → ai_augmented_resumed`
  (`formal.story-exit.state-machine`, lines 42–51) and with FK-58 §58.6 ordering
  (1 run-terminal → 2 Cancelled → 4 binding/locks released → 5 `ai_augmented`).

**Reviewer's required fix:** specify ONE authoritative atomic or idempotently-recoverable exit
transaction boundary for the `story_exit` op, administrative `Cancelled`, binding/lock teardown, and
gate/fallback; add negative tests for failure between the `story_exit` op commit and StoryService
cancellation (no durable half-exit, or deterministic recovery to `Cancelled + non-resumable +
binding revoked`).

**Resolved (story.md):**
- **New Quell-Konzept anchor:** `formal.story-exit.state-machine` added with the canonical exit
  ordering `exit_gate_passed → story_cancelled → binding_revoked → ai_augmented_resumed` (= FK-58
  §58.6), and the story-service is bound to that exact ordering.
- **Ist-Zustand (§1):** added the **two-separate-persistence-paths** fact with concrete anchors —
  `facade.py:871` (control-plane atomic commit, op/binding/locks/events only) vs.
  `service.py:652`/`:758` → `story_repository.py:152` (StoryService status). Stated explicitly that
  there is no cross-repo ACID transaction, so consistency must be secured by fence + idempotent
  `exit_id` resume (model-faithful, not a faked global transaction).
- **Rewrote scope item #4 into a single authoritative, fence-first, `exit_id`-idempotently-recoverable
  exit transaction** with four ordered phases:
  - **Phase A — validation, NO mutation:** principal + §58.3 admissibility (#3a) + alternatives (#3b)
    + artefacts + `exit_gate` (#7). Failure ⇒ nothing mutated.
  - **Phase B — authoritative fence commit (the only durable commit point):** the committed
    `operation_kind="story_exit"` op lands atomically via `commit_operation_with_side_effects`
    (`repository.py:95`) together with binding-delete + lock-INACTIVE + deactivation events. This one
    commit is simultaneously the run-terminal fence (#9) AND the lock/binding teardown (#8). From the
    Phase-B commit the run is non-resumable regardless of whether C/D ran.
  - **Phase C — administrative `Cancelled` transition (#6a):** idempotent on `StoryService`,
    re-drivable by the same `exit_id`.
  - **Phase D — controlled `ai_augmented` fallback:** derived via `_resolve_operating_mode`
    (`runtime.py:1977`), only after B (binding already revoked) and C; idempotent.
  - **Atomicity/Recovery boundary:** explicitly NOT a global cross-repo ACID tx; instead Fence +
    idempotent `exit_id` resume, modelled on FK-53 §53.9 / AG3-071 (no global ACID tx, convergent
    steps, same-id resume). A crash between Phase B and C/D leaves (i) a durably non-resumable run
    (no silently-resumable half-exit) and (ii) a deterministically resumable exit to the end-state.
- **New scope item #12 — idempotent `exit_id` recovery path** (in the AG3-073 cut), with the explicit
  "no second recovery truth — the `exit_id`/`story_exit` op is the only recovery source" guard.
- **#6a (Cancelled transition)** marked as Phase C, made **idempotent** (re-call on already-Cancelled
  = no-op success), and annotated with the separate-persistence-path / recovery rationale; gate (ii)
  changed from "operation_kind=story_exit" to "committed story_exit op (Phase B already fenced)".
- **#8/#9** rewritten to identify the committed `story_exit` op as the **Phase-B fence** (run-terminal
  write owner + binding/lock teardown), with the mode fallback explicitly after B and C.
- **AC4 extended with (4c):** canonical ordering assertion (`exit_gate (A) → Phase-B fence → Cancelled
  (C) → ai_augmented (D)`) + mandatory **half-exit recovery test** (abort after Phase B before C:
  run durably non-resumable; same-`exit_id` resume reaches the full end-state), **Cancelled-transition
  idempotency test** (second call = no-op success), and an **ordering negative test** (mode fallback
  must not precede binding revoke / Cancelled).
- **Propagated** into §5 (FAIL-CLOSED half-exit clause + FIX-THE-MODEL single-transaction/no-faked-
  ACID/single-recovery-truth), §6 (new R4 pitfall + two new critical anchors for the two persistence
  paths) and the §6 "done" test-name list (half-exit-recovery, Cancelled-idempotent,
  ordering-negative).

---

## Owner-routing check (stayed in AG3-073 cut — no cross-story re-routing)

The atomicity/recovery boundary for the exit transaction is FK-58/story-exit orchestration property
and belongs to **AG3-073** (the exit orchestration owner). Verified against `_STORY_INDEX.md`:
- **AG3-074** (depends on AG3-073) owns only the consolidated story result axis `terminal_state`
  (Open/Done/Cancelled) + `exit_class` invariants + the six §59.12 contract/negative tests — NOT the
  run-exit transaction atomicity. So nothing here belongs to AG3-074.
- **AG3-071** (Story-Reset, FK-53 §53.9) is **referenced as the model precedent** for the recovery
  approach (no global ACID tx, convergent steps, same-id resume) but its machinery is NOT reused or
  re-scoped here; AG3-073 builds its own `exit_id`-keyed recovery on the existing control-plane op +
  StoryService owners. No dependency change.

No new cross-story prerequisite is required: the existing `depends_on: [AG3-032, AG3-053]` already
covers the control-plane runtime/store + governance/principal foundations the exit transaction reuses.

## Genuine cross-story prerequisite (informational)

None beyond the recorded `depends_on`. The recovery boundary is fully constructible from the existing
control-plane primitives (`commit_operation_with_side_effects`, `_run_admission_evidence`,
`_resolve_operating_mode`), the StoryService transition owner, and a new `exit_id`-keyed resume in the
story-exit BC — all within the AG3-073 cut.

## WARNINGs
None separate in `review-r4.md`.

## Anchor verification log (read from real source this pass)
- `state_backend/store/facade.py:871` — `commit_control_plane_operation_with_side_effects_global`
  (atomic op/binding/locks/events ONLY; status NOT included). Verified.
- `story_context_manager/service.py:652` — `self._story_repo.save(story)` inside `cancel_story`
  (status set `service.py:649`); `service.py:758` — same inside `complete_story` (status set
  `:756-757`). Verified (reviewer's `story_repository.py:616` anchor does not exist — the file is 179
  lines; the concrete `save` is `story_repository.py:152`; corrected in the story).
- `story_context_manager/story_repository.py:152` — concrete `save(self, story)`. Verified.
- `control_plane/repository.py:95` — `commit_operation_with_side_effects` (reusable atomic primitive).
- `control_plane/runtime.py:981` — `_run_admission_evidence` (run-terminal read owner), `:929`
  `_run_was_admitted`, `:961` `_closure_run_was_admitted`, `:757` `_dispatch_phase`, `:1977`
  `_resolve_operating_mode`. `repository.py:103` `has_committed_operation_for_run`.
- `formal.story-exit.state-machine` — states/transitions
  `eligible → exit_requested → exit_gate_passed → story_cancelled → binding_revoked →
  ai_augmented_resumed` + `rule.run-becomes-non-resumable`. `formal.story-exit.invariants` —
  `story_becomes_cancelled_not_done`, `exit_must_revoke_story_binding_before_free_mode`.
  FK-58 §58.6 ordering, §58.9/§58.10. FK-53 §53.9 (recovery precedent). Re-read via concept index.

## status.yaml
Re-checked: `status: draft`, `phase: review_pending`, `depends_on: [AG3-032, AG3-053]`, `size: L`,
`type: implementation` all match `_STORY_INDEX.md` (AG3-073, L, depends_on AG3-032/AG3-053).
No field wrong; left unchanged.

## Files written
- `stories/AG3-073-story-exit-human-takeover/story.md` (rewritten sections: Quell-Konzepte, §1, §2.1
  #4/#6a/#8/#9/#12-13, §3 AC4c, §5, §6).
- `stories/AG3-073-story-exit-human-takeover/remediation-r4.md` (this file).
- `status.yaml` — unchanged (verified correct).
