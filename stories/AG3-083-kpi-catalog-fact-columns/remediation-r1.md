# AG3-083 — Remediation r1 (hostile Codex review CHANGES-REQUESTED)

Scope of this remediation: rewrite of `story.md` (+ one `status.yaml` field). No
production code, tests, or `concept/` files were touched. Every ERROR and WARNING
from `review-r1.md` is addressed below with the concrete resolution. All
authoritative facts were re-derived from the real FK sections (FK-60 §60.4,
FK-61 §61.2-§61.12, FK-62 §62.2) and the real `src/agentkit/` code.

## Must-Fix ERRORs

### E1 — FK-61 mapping contract underspecified (was reduced to [R]/[N] + owner)
**Resolved.** New Scope §2.1 #2 + AC3 require, per AKTIV-KPI, the full FK-61
mapping contract: source event/payload (`collection_point.hook_or_event`),
process point (`collection_point.notes`), `[R]`/`[N]` (`collection_point.data_available`),
and a **typed target `fact_*` column** (new §2.1.2, derived from the FK-61
`→ fact_*` column in §61.2-§61.11). AC3 validates all 40 mappings and that each
target column exists in the FK-62 target schema (fail-closed).

### E2 — p95 demanded as target column although FK-62 §62.2.3 marks it INVENTAR
**Resolved.** p95 removed entirely. Scope §2.1 #6 now keeps only the AKTIV P50
column `fact_pool_period.response_time_p50_ms` (FK-60 §60.4.3 `llm_response_time_p50`
AKTIV) and explicitly excludes `response_time_p95_ms` / `llm_response_time_p95`
(both INVENTAR; FK-62 §62.2.3 verbatim "INVENTAR, wird bei Aktivierung ergaenzt").
P95 activation is routed to a separate future concept+code story (Out-of-Scope
§2.2). AC6 asserts the **absence** of the p95 column and any p95 KPI.

### E3 — AC1/AC2 gameable ("count 40 + check status" does not prove the FK-60 set)
**Resolved.** New §2.1.1 pins the exact 40 AKTIV `kpi_id`s (10 domains, balance
7/5/7/1/7/1/2/2/2/6 per FK-60 §60.4.12). AC1 now compares the exact ID frozenset
(not a count) and asserts no INVENTAR id is registered. AC2 validates, per KPI,
name/decision_question/formula_repr/granularity/domain/data-class against FK-60 §60.4.

### E4 — AC4 left "one truth" open; FK-62 is authoritative
**Resolved.** The "FK-62 names OR documented code-reality" alternative is deleted.
Scope §2.1 #3 and AC4 make **FK-62 the binding name/column truth**; all renames
listed in §1 are switched to the FK-62 names (`guard_key`, `pool_key`,
`pipeline_mode`, `opened_at`, `closed_at`, `qa_round_count`,
`adversarial_findings_count`, `are_gate_passed`, corpus columns). Any deviation
would require a FK-62 concept change, not a code-reality override (Guardrail §5
FIX-THE-MODEL).

### E5 — Scope self-contradiction: renames are not "additive-only" but migration was OoS
**Resolved.** New Scope §2.1 #4 takes rename-and-additive migration explicitly
in-scope: renames are coordinated single-truth switches across all five truth
sites; `ADD COLUMN IF NOT EXISTS` (FK-62 §62.4) remains the strategy for new
columns. Out-of-Scope §2.2 now only excludes the DB **versioning strategy**
(`ak3_v<slug>` side-by-side), which is already conform and unchanged here.

### E6 — AG3-082 dependency logically inverted
**Resolved.** AG3-082 (RefreshWorker) computes against the columns AG3-083
defines, so AG3-083 cannot depend on AG3-082. Verified against
`stories/AG3-082-kpi-refresh-worker/status.yaml`: AG3-082 `depends_on:
[AG3-038, AG3-081]` (NOT AG3-083). Corrected `status.yaml` to
`depends_on: [AG3-038, AG3-081]`, `unblocks: [AG3-082]`. AG3-081 is the correct
dependency because AG3-083 consolidates AG3-081's enriched `integrity_gate_result`
/`are_gate_result` payload truth. `story.md` §1 anchor, §2.2 owners and §3 AC
wording were aligned to the new direction. (The `_STORY_INDEX.md` table line for
AG3-083 still shows the old `AG3-082` dependency; per the dedup note "Recompute-
Haelfte in AG3-082" the recompute owner is downstream, so the corrected direction
is consistent with the index's own cut intent. The index is the cut, not a
second runtime truth; the story's `depends_on`/`unblocks` is now self-consistent
and matches AG3-082's actual status.yaml.)

### E7 — Implementation sites wrong/incomplete (missing fact_repository.py + SQLite migration)
**Resolved.** §1 now lists all **five** real truth sites with real file:line
anchors: `kpi_analytics/fact_store/models.py:25-145`,
`state_backend/postgres_schema.sql:809`,
`state_backend/sqlite_store.py:976` (`_ensure_analytics_tables`),
`state_backend/migration/versions/v_3_4_analytics.sql:18`,
`state_backend/store/fact_repository.py:173-331` (`_FACT_STORY_COLUMNS`,
`_FACT_STORY_UPDATE`, `_fact_story_params`, `_row_to_fact_*`). Scope §2.1 #3,
AC4, and the sub-agent notes §6 enumerate the same five sites and require an
identical-column-set contract test across all of them. (Verified that
`postgres_schema.sql` does carry `fact_story` at :809 — the story's original three
sites were real but incomplete; the two added by the reviewer are confirmed.)

## WARNINGs

### W1 — AC5 named no canonical wire keys
**Resolved (fixed in story).** Scope §2.1 #5 and AC5 now nail the canonical wire
keys verbatim from FK-61 §61.12.2: `integrity_gate_result.blocked_dimensions`,
`are_gate_result.total_requirements`, `are_gate_result.covered_requirements`,
plus their target columns via §2.1.2. Consolidated with AG3-081 as the single
payload truth.

### W2 — Docstring line numbers were 4-6, should be 3-5
**Resolved (fixed in story).** §1 corrected to "Modul-Docstring (Z. 3-5)" and the
quote updated to the real English text "The full 40-KPI population is a follow-up
story." (verified at `catalog.py:1-6`). The skeleton/init anchors (`:139`,
`:141-142`) were already correct and retained.

## PASS (no action, retained)
- FK anchors confirmed and kept: FK-60 §60.4, FK-61 §61.12.2, FK-62 §62.2.1-§62.2.5.
- Additional precise anchors added throughout §1/§2 (e.g. FK-62 §62.2.3 p95
  INVENTAR marker, FK-61 §61.9.1/§61.9.2 ARE mappings, FK-62 §62.6 FactStore
  write-owner) to harden against the gameable-AC and underspecified-mapping findings.

## Scope discipline
Stayed strictly within the AG3-083 cut from `_STORY_INDEX.md` (catalog population
+ FK-62 target columns + enriched payload targets + contract tests). No new
capability pulled in: RefreshWorker fill logic → AG3-082; events/payloads →
AG3-081; API/dashboard → AG3-084; p95 activation → separate future story.

## Files written
- `stories/AG3-083-kpi-catalog-fact-columns/story.md` (full rewrite, AG3-057 template structure preserved)
- `stories/AG3-083-kpi-catalog-fact-columns/status.yaml` (`depends_on`/`unblocks` corrected)
- `stories/AG3-083-kpi-catalog-fact-columns/remediation-r1.md` (this report)
