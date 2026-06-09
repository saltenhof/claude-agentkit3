# AG3-083 — Remediation r2 (hostile Codex re-review CHANGES-REQUESTED, round 2)

Scope of this remediation: edits to `story.md` only (`status.yaml` already correct
from r1, no change needed). No production code, tests, or `concept/` files were
touched. Every remaining ERROR and inherited WARNING from `review-r2.md` is
addressed below with the concrete resolution. All authoritative facts were
re-derived from the real FK sections (FK-60 §60.4, FK-61 §61.2-§61.12, FK-62
§62.2.3) and the real `src/agentkit/` code.

## Remaining Must-Fix ERRORs

### E1 (r2) — `[N]`-KPI owner rule was factually wrong (blanket "AG3-081 only")
**Resolved.** The blanket claim that all `[N]` KPIs point exclusively to an
AG3-081 EventType/Payload contradicted FK-61. Verified against the real concept:
- `execution_vs_exploration_ratio` — FK-61 §61.2.2: "Kein neues Event noetig.
  `runtime.story_metrics.mode`" (runtime read-model, no AG3-081 event).
- `guard_violation_rate_by_guard` — FK-61 §61.4.3 / §61.12.1: "guard_invocation
  ist bewusst KEIN Event-Typ" (scratchpad counter `guard_invocation_counters`).
- `phase_time_distribution` / `story_predictability` — FK-61 §61.11.2: "Kein
  neues Event" (`phase_state_projection` / `story_metrics`).
- `quorum_trigger_rate`, `llm_call_count_per_story`, `are_gate_result` — FK-61
  §61.3.1/§61.3.2/§61.9.1: existing events.

Fix: New **§2.1.3** defines the five FK-61 source-owner classes (1 existing
event, 2 new AG3-081 event, 3 enriched AG3-081 payload, 4 runtime
metric/read-model/projection, 5 scratchpad counter) with FK-61-anchored
examples for each. Scope §2.1 #2, Scope §2.1 #8 (negative paths), AC3, and
Guardrail §5 (FAIL-CLOSED) were rewritten to test each KPI **against the FK-61
class actually required for that KPI** — the AG3-081 negative test now fires
**only** for class 2/3 KPIs; class 1/4/5 KPIs are checked against their named
FK-61 source; an empty `collection_point.hook_or_event` is always an error.
The wrong "[N] -> AG3-081 only" wording is removed everywhere (grep-verified:
no remaining occurrence of the old blanket rule or `§2.3` anchor).

### E2 (r2) — AG3-082/AG3-083 ordering + p95 not repo-wide consolidated
**Resolved within the AG3-083 cut (cross-file conflicts routed to owners).**
The logically correct direction (reviewer-endorsed: "Wenn AG3-082 gegen
AG3-083-Spalten rechnet, muss AG3-082 von AG3-083 abhaengen") is already
encoded in AG3-083 `status.yaml` (`depends_on: [AG3-038, AG3-081]`,
`unblocks: [AG3-082]`) — unchanged, correct. AG3-082 `status.yaml` is also
already correct (`depends_on: [AG3-038, AG3-081]`).

The remaining contradictions live in two files this story is **not allowed to
edit** (instruction: ONLY AG3-083 story.md/status.yaml). They are explicitly
**routed to their owner** rather than silently left (ZERO DEBT / no silent
inheritance), in a new §1 "Reihenfolge-Konsolidierung (Routing)" block:
- `var/concept-gap-analysis/_STORY_INDEX.md:89` still lists AG3-083 with
  `depends_on AG3-038, AG3-082` (inverted) -> owner: index/backlog maintenance,
  correct to `AG3-038, AG3-081`.
- `stories/AG3-082-kpi-refresh-worker/story.md:52` ("AG3-083 (depends_on
  AG3-082)") and `:48` (lists `response_time_p95_ms` as an AG3-083 target
  column) -> owner: AG3-082; p95 must stay a pure `_percentile` helper (FK-62
  §62.2.3 marks `response_time_p95_ms` INVENTAR), not an AG3-083 persistence
  target.
AG3-083's own truth is self-consistent and p95 stays strictly INVENTAR
(Scope §2.1 #6, AC6). The cross-file fixes are flagged as a WARNING-class
routing item to the responsible owners.

### E3 (r2) — Wrong self-anchor `§2.3`
**Resolved.** Scope §2.1 #4 referenced a non-existent `§2.3`. The story has
only §2.1 and §2.2; the migration/versioning passage lives in §2.1 #4 itself
and Out-of-Scope §2.2. The reference now reads "(Versionierungsstrategie selbst
bleibt Out-of-Scope, §2.2)". Grep-verified: no remaining `§2.3` token.

## Round-1 carry-over status (per review-r2)
- E2/E3/E4/E7 (r1): confirmed still resolved, untouched.
- E1 (r1): now fully resolved by the §2.1.3 class model (was only partial due
  to the `[N]` over-generalisation).
- E5 (r1): now fully resolved — the missing `§2.3` anchor is corrected.
- E6 (r1): AG3-083-side direction confirmed correct; the residual cross-file
  inconsistency is routed (E2/r2 above), not silently kept.

## Scope discipline
Stayed strictly within the AG3-083 cut (catalog population + FK-62 target
columns + enriched payload targets + contract tests). No other story's files,
no concept files, no `_STORY_INDEX.md`, no production code/tests edited. AG3-057
template structure (sections 1-6) preserved. ARCH-55 English kept for all new
identifiers/IDs/column names.

## Files written
- `stories/AG3-083-kpi-catalog-fact-columns/story.md` (edited: §1 routing block,
  §2.1 #2/#4/#8, new §2.1.3, AC3, §5 FAIL-CLOSED)
- `stories/AG3-083-kpi-catalog-fact-columns/remediation-r2.md` (this report)
- `status.yaml`: **no change** (already correct from r1)
