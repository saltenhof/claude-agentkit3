# AG3-083 — Remediation r3 (hostile Codex re-review CHANGES-REQUESTED, round 3)

Scope of this remediation: edits to `story.md` only. `status.yaml` was already
correct (`depends_on: [AG3-038, AG3-081]`, `unblocks: [AG3-082]`) and is
**unchanged** — the review confirmed AG3-083's own metadata encodes the correct
direction. No production code, tests, or `concept/` files were touched. No other
story's files were edited (the AG3-082 contradictions are **routed** to their
owner, not silently fixed inside another story).

## Remaining Must-Fix ERROR (review-r3 #1)

### E1 (r3) — AG3-082/AG3-083 ordering not honestly routed completely
**Finding (review-r3):** AG3-083 correctly states its own truth (it unblocks
AG3-082; AG3-082 should depend on AG3-083) and routes the AG3-082 *prose* and
the `_STORY_INDEX.md` conflict, but it **falsely claimed** that AG3-082
`status.yaml` is already correct and only the prose/index need updates. In
reality AG3-082 `status.yaml:11` still says `unblocks: AG3-083`, which encodes
the **opposite** direction (AG3-082 before AG3-083, AG3-083 depends on AG3-082).

**Resolution (in `story.md` §1 routing block):**
- The false statement "AG3-082 `status.yaml` ist bereits korrekt … nur die
  AG3-082-Prosa und der Index sind nachzuziehen" was **removed and explicitly
  retracted**.
- The routing block now enumerates **three** external sources that contradict
  the correct direction (was two), each routed to its owner — AG3-083 is not
  allowed to edit any of them:
  1. `var/concept-gap-analysis/_STORY_INDEX.md:89` — lists AG3-083 with
     `depends_on AG3-038, AG3-082` (inverted). Owner: index/backlog
     maintenance. Correct to `depends_on AG3-038, AG3-081`.
  2. `stories/AG3-082-kpi-refresh-worker/status.yaml:11-12` — `unblocks:
     [AG3-083]` encodes the reverse direction. Owner: **AG3-082**. Correct to
     `depends_on: [AG3-038, AG3-081, AG3-083]` and remove `AG3-083` from
     `unblocks`. The earlier "already correct" claim is retracted here.
  3. `stories/AG3-082-kpi-refresh-worker/story.md` — pervasively built on
     "AG3-082 VOR AG3-083" (e.g. `:25`, `:48`, `:52`, `:56`, `:70`, `:92`,
     §6 W1; `:52` literally writes "AG3-083 (depends_on AG3-082; kommt also
     NACH AG3-082)"). Owner: **AG3-082**.
- Added a consistency note: whoever flips the direction must pull AG3-082 and
  AG3-083 **together** to avoid an ordering cycle. AG3-083 persists no
  percentiles and only claims the FK-62 target column `response_time_p50_ms`
  (Scope §2.1 #6), so the flip does not pull p95 into AG3-083.
- The closing sentence now reports **all three** external deviations (index +
  AG3-082 `status.yaml` + AG3-082 prose) to their owners instead of silently
  inheriting them (ZERO DEBT / no silent inheritance).

## Code-anchor correction (incidental to E1)
The prior r2 text cited `stories/AG3-082-.../story.md:48` as listing
`response_time_p95_ms` as an **AG3-083 target column**. That anchor was wrong:
AG3-082 `:48` is the `_percentile` blockquote that keeps p95 INVENTAR ("in
keiner der beiden Stories Schreibziel"), and `:52` lists the **p50** column as
the AG3-083 write target, not p95. The routing text now states the anchors
correctly: `:52` = direction + p50-as-AG3-083-target, `:48` = p95 stays
INVENTAR in both stories. No false "p95 = AG3-083 target column" claim remains.

## Resolved Round-2 items (per review-r3, untouched)
- `[N]` KPI owner model (§2.1.3, five FK-61 source-owner classes): resolved,
  unchanged.
- p95 INVENTAR / p50 in scope (Scope §2.1 #6, AC6): resolved, unchanged.
- `§2.3` self-anchor: resolved in `story.md`, unchanged.
- Real code anchors (catalog skeleton, reduced AG3-038 fact names): broadly
  correct per review, unchanged.

## Scope discipline
Stayed strictly within the AG3-083 cut. Only AG3-083 `story.md` was edited
(§1 routing block: intro count two→three, new routing item for the AG3-082
`status.yaml` contradiction, split of the AG3-082-prose routing into its own
item, corrected `:48`/`:52` anchors, retraction of the false "already correct"
claim, updated closing sentence). AG3-057 template structure (sections 1–6)
preserved. ARCH-55 English kept for all identifiers/IDs/column names. No
concept files, no `_STORY_INDEX.md`, no AG3-082 files, no production
code/tests edited. `status.yaml` unchanged (already correct).

## Genuine cross-story prerequisites (routed to owners — NOT done here)
These must be fixed by their owners to make the backlog metadata globally
consistent with AG3-083's correct direction. AG3-083 cannot and must not edit
them:
1. **AG3-082 owner** — `stories/AG3-082-kpi-refresh-worker/status.yaml`:
   `depends_on: [AG3-038, AG3-081, AG3-083]`, remove `AG3-083` from `unblocks`.
2. **AG3-082 owner** — `stories/AG3-082-kpi-refresh-worker/story.md`: rewrite
   the "AG3-082 VOR AG3-083" direction prose (lines noted above).
3. **Index/backlog owner** — `var/concept-gap-analysis/_STORY_INDEX.md:89`:
   AG3-083 `depends_on AG3-038, AG3-081` (not `AG3-038, AG3-082`).

Note: items 1–3 are a coupled change (must be applied together with the
already-correct AG3-083 `status.yaml`) to avoid introducing a temporary
ordering cycle.

## Files written
- `stories/AG3-083-kpi-catalog-fact-columns/story.md` (edited: §1 routing block)
- `stories/AG3-083-kpi-catalog-fact-columns/remediation-r3.md` (this report)
- `status.yaml`: **no change** (already correct).
