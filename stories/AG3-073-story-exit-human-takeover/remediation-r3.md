# AG3-073 — Remediation R3 (after round-3 hostile re-review)

Scope: rewrote `story.md` only. `status.yaml` re-checked (no field genuinely wrong, untouched).
No production code, tests, or `concept/` files touched. Stayed strictly within the AG3-073 cut
from `_STORY_INDEX.md` (`exit-story` CLI, reason-enum, four artefacts, `exit_gate`,
`exit_class=viability_handoff` under Cancelled, controlled fallback to `ai_augmented`).
All code anchors re-verified against real source this pass.

`review-r3.md` confirmed both R2 ERRORs RESOLVED and listed exactly **one** new must-fix ERROR
(the per-dimension FAIL/WEAK verdicts are summaries of that one ERROR, no separate WARNINGs).
It is resolved below.

---

## Must-Fix ERROR 1 — administrative `Cancelled` / run-terminal owner not concretely anchored

**Reviewer evidence:** FK-58 §58.6 requires the active run to become terminal/non-resumable and
the story to become administratively `Cancelled`. The R2 story only anchored `StoryStatus.CANCELLED`
at enum level and said "marks the run terminal/non-resumable" without naming the actual
mutation/admission owner. The real `StoryService` (`service.py:80`/`:112`) **forbids**
`In Progress -> Cancelled` and explicitly tells callers to use Story-Reset/Story-Exit — so AG3-073
must build that official admin transition path, plus a run-terminal owner that the
dispatch/resume/retry gates consult so an exited run cannot resume even if old phase state remains.

**Root cause confirmed against real source (this pass):**
- Status owner: `_ALLOWED_TRANSITIONS` (`service.py:80`) has no `In Progress -> Cancelled`;
  `_check_transition` (`service.py:112-122`) hard-rejects it with the "Use Story-Reset (FK-53) or
  Story-Exit (FK-58)" hint. `cancel_story` (`service.py:594`→`:640`) only covers
  `Backlog/Approved -> Cancelled`; `complete_story` (`service.py:737`) is the only `-> Done` path.
- Run-terminal owner: the admission probe `_run_admission_evidence` (`runtime.py:981`) returns
  `True` if the binding matches OR `has_committed_operation_for_run(...)` (`repository.py:103`) is
  `True`. Since the exit teardown writes a **committed** `operation_kind="story_exit"` op, the
  committed-op branch alone would **re-admit the exited run** for `complete_phase`/`fail_phase`
  (`_run_was_admitted`, `runtime.py:929`), closure (`_closure_run_was_admitted`, `runtime.py:961`)
  and fresh dispatch (`_dispatch_phase`, `runtime.py:757`) — exactly the "resume even if old phase
  state remains" hole.

**Resolved (story.md):**
- **New Quell-Konzept anchors:** `formal.story-exit.invariant.story_becomes_cancelled_not_done`
  (Cancelled, never Done; administrative, not normal closure — ties to FK-59 §59.8 #4),
  `formal.story-exit.rule.run-becomes-non-resumable`, and
  `formal.story-exit.invariant.exit_must_revoke_story_binding_before_free_mode`.
- **Ist-Zustand:** added a concrete **status transition owner** block (`service.py:80/:97/:112`,
  `cancel_story`/`complete_story`) and a concrete **run-terminal/resumability owner** block
  (`_run_admission_evidence` `runtime.py:981`, its three consumers, and the
  `has_committed_operation_for_run` `repository.py:103` re-admission gap).
- **New scope item #6a — dedicated administrative `Cancelled` transition:** a dedicated
  `StoryService` method (e.g. `administratively_cancel_for_story_exit`) makes `In Progress ->
  Cancelled` legal **only** for Story-Exit, hard-gated by valid `StoryExitRecord` (#3a+#3b) +
  `operation_kind="story_exit"` + `Principal.HUMAN_CLI`; the Frontend `cancel_story` path and the
  generic `_ALLOWED_TRANSITIONS` table are **not** weakened.
- **Rewrote scope item #9 — run-terminal owner:** the committed `operation_kind="story_exit"` op is
  the run-terminal **write** owner; `_run_admission_evidence` (`runtime.py:981`) is the **read**
  owner, extended so a run with a committed `story_exit` op is treated as terminal/non-resumable and
  admission is fail-closed **prioritized over** `has_committed_operation_for_run`. This blocks
  dispatch/resume/retry/complete/fail/closure of the exited run via the three existing consumers.
- **Service orchestration #4** updated: write run-terminal marker + teardown → administrative
  `Cancelled` (#6a) → mode fallback, fail-closed ordering.
- **AC4 rewritten into 4a (run-terminal) + 4b (administrative transition)** with the exact tests
  named by review-r3.md:
  - normal `cancel_story` still rejects `In Progress -> Cancelled` (`service.py:112`);
  - the Story-Exit administrative transition succeeds (gated by StoryExitRecord + story_exit op +
    HUMAN_CLI);
  - normal closure (`complete_story` / `closure/phase.py`) cannot produce `Cancelled` (FK-59 §59.8 #4);
  - same-run resume/retry after `story_exit_record` / committed `story_exit` op is fail-closed, even
    with old phase-state residue and despite `has_committed_operation_for_run`.
- **Propagated** into §2.2 (clean axis split), §5 (FAIL-CLOSED + FIX-THE-MODEL), §6 critical anchors,
  three new pitfalls, and the "done" test-name list.

---

## Clean split with AG3-074 (run-terminal axis overlap)

`review-r3.md` flagged that the run-terminal axis overlaps AG3-074. Verified against
`_STORY_INDEX.md`: AG3-074 owns the **consolidated story result axis** `terminal_state`
(Open/Done/Cancelled, FK-59 §59.6.1/§59.8/§59.12 + the six §59.12 contract/negative tests). The
**run-terminality** (control-plane run admission: an exited run is non-resumable, FK-58 §58.6 #1 /
`formal.story-exit.rule.run-becomes-non-resumable`) is FK-58/story-exit property and belongs to
**AG3-073**. The story now states this split explicitly in §2.2 and in a §6 pitfall: AG3-073 builds
the run-terminal admission gate; AG3-074 builds the story `terminal_state` result axis + the §59.8
hard-invalids (incl. #4 `Cancelled` from normal closure). No second axis, no duplication.

## WARNINGs
None separate in `review-r3.md`.

## Owner-routing check (stayed in AG3-073 cut)
- Administrative `Cancelled` transition + run-terminal admission gate are FK-58/story-exit owned →
  AG3-073. Story result axis `terminal_state` → AG3-074 (consumed here, mirrored there). Existing
  AG3-074/AG3-069/AG3-087/AG3-097/AG3-076 Out-of-Scope routing intact; no new re-routing needed.

## Anchor verification log (read from real source this pass)
- `story_context_manager/service.py:80` — `_ALLOWED_TRANSITIONS` (no `In Progress -> Cancelled`).
- `service.py:97` — `_check_transition`; `:112-122` — the explicit `In Progress -> Cancelled`
  rejection ("Use Story-Reset (FK-53) or Story-Exit (FK-58)").
- `service.py:594`/`:640` — `cancel_story` → `_check_transition(.., CANCELLED)` (Backlog/Approved only).
- `service.py:737` — `complete_story` (only `In Progress -> Done`).
- `control_plane/runtime.py:981` — `_run_admission_evidence` (binding-match OR
  `has_committed_operation_for_run`).
- `runtime.py:929` `_run_was_admitted`, `:961` `_closure_run_was_admitted`, `:757` `_dispatch_phase`
  (`run_admitted`) — the three consumers.
- `control_plane/repository.py:95` `commit_operation_with_side_effects` (run-terminal write path),
  `:103` `has_committed_operation_for_run` (re-admission gap).
- `story_context_manager/story_model.py:46` — `StoryStatus.CANCELLED`.
- `formal.story-exit.invariants` — `story_becomes_cancelled_not_done`,
  `exit_must_revoke_story_binding_before_free_mode`; `formal.story-exit.state-machine` —
  `rule.run-becomes-non-resumable`; FK-59 §59.8 #4 (`Cancelled` from normal closure invalid),
  §59.6.1 (`terminal_state`), FK-58 §58.6 — re-read via concept index.

## status.yaml
Re-checked: `status: draft`, `phase: review_pending`, `depends_on: [AG3-032, AG3-053]`, `size: L`,
`type: implementation` all match `_STORY_INDEX.md` (AG3-073, L, depends_on AG3-032/AG3-053).
No field wrong; left unchanged.

## Files written
- `stories/AG3-073-story-exit-human-takeover/story.md` (rewritten)
- `stories/AG3-073-story-exit-human-takeover/remediation-r3.md` (this file)
- `status.yaml` — unchanged (verified correct)
