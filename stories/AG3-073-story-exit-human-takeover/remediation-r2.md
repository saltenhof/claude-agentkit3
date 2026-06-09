# AG3-073 — Remediation R2 (after round-2 hostile re-review)

Scope: rewrote `story.md` only. `status.yaml` re-checked (no field genuinely wrong, untouched).
No production code, tests, or `concept/` files touched. Stayed strictly within the AG3-073 cut
from `_STORY_INDEX.md` (`exit-story` CLI, reason-enum, four artefacts, `exit_gate`,
`exit_class=viability_handoff` under Cancelled, controlled fallback to `ai_augmented`).
No scope expansion; all code anchors re-verified against real source this pass.

`review-r2.md` listed exactly two remaining must-fix ERRORs and no separate WARNINGs
(the per-dimension FAIL/WEAK verdicts are summaries of those two ERRORs, not extra findings).
Both are resolved below.

---

## Must-Fix ERROR 1 — §58.3 context prohibitions not genuinely enforceable/testable
**Reviewer evidence:** FK-58 §58.3 forbids exit for normal difficulty, mere agent uncertainty,
usual remediation, and split/replan-solvable cases. The R1 story only required `AlternativeReview`
booleans + non-empty rejection strings, and AC3 tested only missing alternatives / empty reasons.
A non-empty rejection reason can still encode "agent was unsure" / "normal remediation is hard"
and the ACs would pass. Also: who produces `AlternativeReview` was undefined.

**Resolved (story.md):**
- **New typed admissibility model `AdmissibilityAssessment` (§2.1 #3a)** with four standalone
  Pydantic-v2 predicates `normal_difficulty_excluded` / `mere_agent_uncertainty_excluded` /
  `usual_remediation_excluded` / `split_or_replan_excluded`, each **deterministically derived by
  `story_exit_service` from the bound run-state** (manifest snapshot / integration budget /
  remediation history / blockers) — never from agent/prompt text. Any non-excluded prohibition →
  Exit AND Exit-Gate fail-closed. This is the §58.3 admissibility owner, explicitly NOT covered by
  enum membership (#2) nor by a filled `AlternativeReview` string (#3b).
- **Producer of `AlternativeReview` now defined (§2.1 #3b):** the `story_exit_service` produces it
  from the bound run-state, preserving FK-58 §58.4 lightweight CLI rule (the human still only types
  `--reason`/`--note`; AgentKit computes admissibility).
- **`StoryExitRecord` field list extended** with `admissibility_assessment: AdmissibilityAssessment`
  (§2.1 #5).
- **AC3 rewritten into two parts (3a + 3b)** with the required §58.3 negative tests: one per
  prohibition (normal difficulty, agent uncertainty, usual remediation not exhausted,
  split/replan-solvable) → each blocks Exit and Exit-Gate; plus the explicit gap test
  (a filled `AlternativeReview` string that encodes a §58.3 prohibition is still blocked by 3a).
  The §58.7 alternative tests from R1 are kept as (3b).
- **§58.3 source-concept line** rewritten to call out the four prohibitions as standalone typed
  predicates, not coverable by enum membership or a free-text string.
- **Propagated** into §2.1 #4 (service orchestrates §58.3 + §58.7), #7 / AC7 (gate condition (a)
  now = passed §58.3 prohibitions AND passed alternatives), §5 FAIL-CLOSED / ZERO DEBT / TYPISIERT,
  §6 pitfall, and the "done" test-name list.

## Must-Fix ERROR 2 — teardown anchor/owner imprecise (closure-path reuse risk)
**Reviewer evidence:** R1 cited `runtime.py:1233` as teardown owner, but that line is inside
`complete_closure` (method at `runtime.py:1020`) writing `operation_kind="closure_complete"` /
`phase="closure"` (`runtime.py:1213`/`:1224`). The reusable atomic primitive is actually
`ControlPlaneRuntimeRepository.commit_operation_with_side_effects` at `repository.py:95`. R1 said
normal closure must not run but did not require an exit-specific control-plane operation kind.

**Resolved (story.md), all anchors re-verified:**
- **Corrected the teardown anchor to the reusable primitive** `repository.py:95`
  (`ControlPlaneRuntimeRepository.commit_operation_with_side_effects`), called **directly** with a
  **dedicated `operation_kind="story_exit"`** (non-closure phase / no `phase`).
- **Explicitly forbade** reuse of `complete_closure` (`runtime.py:1020`) and
  `operation_kind="closure_complete"` for the exit teardown — flagged as the regular closure path
  (§58.10).
- Updated §1 teardown-owner block, §2.1 #4, #8, AC7, AC8, AC12, §5 FIX-THE-MODEL, §6 critical
  anchors + two pitfalls + test-name list.
- **New test obligations:** AC8 / AC12 / AC7 require an assertion that `complete_closure` /
  `operation_kind="closure_complete"` is NOT called and that the exit uses `operation_kind="story_exit"`.

---

## WARNINGs
None separate in `review-r2.md`. (R1 WARNING on schema/producer owner remained resolved and was
left intact.)

## Owner-routing check (stayed in AG3-073 cut)
- §58.3 admissibility predicates belong to **AG3-073** (it owns FK-58 §58.2–§58.10). AG3-074 owns
  only the `terminal_state`/`exit_class` axis constraints — not §58.3 context admissibility — so no
  re-routing was needed; the existing AG3-074/AG3-069/AG3-087/AG3-097 Out-of-Scope routing is intact.

## Anchor verification log (read from real source this pass)
- `control_plane/runtime.py:1020` — `def complete_closure`; `:1213`/`:1224` write
  `operation_kind="closure_complete"`; `:1233` is the in-method call to the primitive.
- `control_plane/repository.py:95` — `commit_operation_with_side_effects` field on
  `ControlPlaneRuntimeRepository` (reusable atomic primitive). Confirmed.
- `control_plane/runtime.py:1977` — `_resolve_operating_mode` (unchanged, still valid).
- `control_plane/records.py:18` — `BindingDeleteScope` (run-scoped key only, unchanged).
- `governance/runner.py:265` — `Governance.deactivate_locks` (unchanged).
- `concept/.../58_story_exit_human_takeover_handoff.md` §58.3 (lines 121–138 forbidden contexts),
  §58.4 (147 lightweight), §58.7 (191–202 alternatives), §58.10 (242–256 gate) — re-read.

## status.yaml
Re-checked: `status: draft`, `phase: review_pending`, `depends_on: [AG3-032, AG3-053]`, `size: L`,
`type: implementation` all match `_STORY_INDEX.md` (AG3-073, L, depends_on AG3-032/AG3-053).
No field wrong; left unchanged.

## Files written
- `stories/AG3-073-story-exit-human-takeover/story.md` (rewritten)
- `stories/AG3-073-story-exit-human-takeover/remediation-r2.md` (this file)
- `status.yaml` — unchanged (verified correct)
