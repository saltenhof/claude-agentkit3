# AG3-083 — Feasibility / Impact Analysis (READ-ONLY)

> **Codex critical review (job-c53f109b): corrections applied.** Six factual corrections were verified against the repo and applied: rename count (11 not 12), `period_end` table count (4 not 5), drop/rename/rederive/replace framing for non-FK-62 columns, AG3-084 story directory path, Option (c) split caveat sharpened, migration-mechanics claim downgraded from fact to assumption + new skip-logic finding. See each section for details.

**Status:** Go/No-Go decision input. No code written. Every claim carries `file:line` evidence verified by reading the repo on this branch (`main`).
**Author context:** AG3-083 is the LAST open story; story is `draft` / `review_pending` (`stories/AG3-083-kpi-catalog-fact-columns/status.yaml:4-5`), spec-reviewed (review-r1..r4) but never implemented.
**Headline:** The story-as-written assumes it runs **before** AG3-082/AG3-084. Those two stories are **already `completed`** and shipped *on the old column names*, and they reach the renamed identifiers **all the way to the browser**. The rename sweep is therefore far larger and more hard-to-reverse than the story text implies, and the divergence is **not "rename + add" — it is also "DROP"** of columns the shipped code actively writes.

---

## 0. The single most important fact (read this first)

The KPI HTTP edge serializes the **raw Pydantic fact models verbatim** to the wire:

- `src/agentkit/kpi_analytics/http/routes.py:461` — `"rows": [row.model_dump(mode="json") for row in view.rows]` (and `:469` for comparison rows).

There is **no DTO / no field remapping** between the DB column / model field and the JSON the frontend receives. Consequently every model field name (`story_mode`, `started_at`, `guard_id`, `llm_role`, …) is a public wire key, and the frontend types mirror them 1:1 (`frontend/prototype/src/foundation/bff/client.ts`, `WireFactStory`/`WireFactGuardPeriod`/… ~`:251-315`). **Renaming a model field is a breaking wire-contract change that propagates to already-shipped AG3-084/094 frontend code.** This is the crux of "hard-to-reverse."

---

## 1. Scope summary — what AG3-083 actually changes

Per `stories/AG3-083-kpi-catalog-fact-columns/story.md` §2.1:

1. **Catalog population**: register exactly 40 AKTIV KPIs in `KpiCatalog` (story §2.1.1), flip `catalog_status` SKELETON→COMPLETE, replace the skeleton docstring. Current state: 0 registered, `catalog_status: CatalogStatus = CatalogStatus.SKELETON` (`src/agentkit/kpi_analytics/catalog.py:139`; `__init__` registers nothing `:141-142`; skeleton docstring `:1-6`, `:126-137`).
2. **FK-61 typed mapping annex**: per-KPI Source-Event/payload + process point + `[R]`/`[N]` + target `fact_*` column, modelled via the existing `KpiCollectionPoint` fields (`catalog.py:78-92`) plus a new typed target-column mapping (story §2.1.2).
3. **Fact-column ADDITIONS**: bring all five `fact_*` tables up to the FK-62 §62.2 column set (§3, §4).
4. **Fact-column RENAMES**: FK-62 names declared the single truth; story §1/§6 lists the renames (§5 here, §2 of this doc).
5. **Enriched payload targets**: `are_gate_result.total_requirements/covered_requirements` → `fact_story.are_total_requirements/are_covered_requirements`; `integrity_gate_result.blocked_dimensions[]` → `fact_pipeline_period.integrity_gate_block_count/total_count` (story §2.1 pt5).
6. **P50 only**: ensure `fact_pool_period.response_time_p50_ms` exists; `response_time_p95_ms` stays INVENTAR (story §2.1 pt6; FK-62 §62.2.3 line `concept/technical-design/62_kpi_aggregation.md:203`).
7. **Contract tests**: extend (not replace) the AG3-038 family; pin the 40-ID frozenset, identical column sets across the truth-locations, wire keys.

**Not stated by the story but proven below:** the story frames the schema delta as "renames + add missing columns." In reality the shipped schema also contains **columns absent from FK-62 §62.2** (e.g. `period_end`, `token_input_total`, `token_output_total`, `avg_latency_ms`, `stories_completed`, `stories_escalated`, `avg_qa_rounds`, `avg_phase_implementation_ms`, `incidents_recorded`, `patterns_promoted`, `checks_approved`, `agentkit_version`, `agentkit_commit`). Adopting FK-62 "as the single truth" implies **dropping, re-deriving, or replacing** those — some have semantic replacements (e.g. `avg_qa_rounds→qa_round_avg` is a rename/replace; `stories_completed→story_count_closed` is a semantic map), while genuinely absent fields (`token_input_total`, `token_output_total`, `avg_latency_ms`, `agentkit_version`, `agentkit_commit`) are true drops unless FK-62/AC4 is amended. The shipped AG3-082/084 code reads/writes them. See §4 and §5.

---

## 2. Exact RENAME table (cross-checked against FK-62 §62.2)

FK-62 column truth verified in `concept/technical-design/62_kpi_aggregation.md` §62.2.1-§62.2.5 (line refs below). "Current" = today's shipped model field / DDL column.

### 2.1 fact_story (FK-62 §62.2.1, `62_kpi_aggregation.md:107-155`)

| Current (shipped) | FK-62 target | FK-62 evidence | Verified |
|---|---|---|---|
| `story_mode` | `pipeline_mode` | `:112` | verified-in-FK62 |
| `started_at` | `opened_at` | `:113` | verified-in-FK62 |
| `completed_at` | `closed_at` | `:114` | verified-in-FK62 |
| `qa_rounds` | `qa_round_count` | `:119` | verified-in-FK62 |
| `adversarial_findings` | `adversarial_findings_count` | `:128` | verified-in-FK62 |
| `are_gate_status` (str) | `are_gate_passed` (int/bool) | `:139` | verified-in-FK62 (also a **type** change) |

### 2.2 fact_guard_period (FK-62 §62.2.2, `:166-186`)

| Current | FK-62 target | Evidence | Verified |
|---|---|---|---|
| `guard_id` (PK part) | `guard_key` (PK part) | `:169`, `:185` | verified-in-FK62 (**PK rename**) |

### 2.3 fact_pool_period (FK-62 §62.2.3, `:193-217`)

| Current | FK-62 target | Evidence | Verified |
|---|---|---|---|
| `llm_role` (PK part) | `pool_key` (PK part) | `:196`, `:216` | verified-in-FK62 (**PK rename**) |

### 2.4 fact_corpus_period (FK-62 §62.2.5, `:275-288`)

| Current | FK-62 target | Evidence | Verified |
|---|---|---|---|
| `incidents_recorded` | `new_incident_count` | `:281` | verified-in-FK62 |
| `patterns_promoted` | `patterns_total_count` | `:282` | verified-in-FK62 |
| `checks_approved` | `patterns_with_active_check` | `:283` | verified-in-FK62 (semantics shift, not pure rename) |

### 2.5 fact_pipeline_period

No 1:1 rename — the current shipped shape (`stories_completed`/`stories_escalated`/`avg_qa_rounds`/`avg_phase_implementation_ms`) does not map name-for-name onto FK-62 (`story_count`/`story_count_closed`/`qa_round_avg`/…). This is a **shape replacement**, not a rename (see §3/§4).

**Rename count (PK + non-PK, story-mandated and FK-62-confirmed): 11** (6 `fact_story` + 1 `fact_guard_period` + 1 `fact_pool_period` + 3 `fact_corpus_period`). Two of them are **primary-key** renames (`guard_key`, `pool_key`) — the riskiest kind. NOTE: `are_gate_status→are_gate_passed` is the 6th `fact_story` rename (already counted in the 6 above) and **also** carries a type change (str→int/bool); it is ONE rename with a type-change side-effect, not a 12th separate entry.

---

## 3. Exact NEW-COLUMN list (per table, FK-62 subsection)

Columns present in FK-62 §62.2 but **absent** from the shipped models (`src/agentkit/kpi_analytics/fact_store/models.py`). All references into `concept/technical-design/62_kpi_aggregation.md`.

### fact_story (§62.2.1) — ADD
`processing_time_ms` (`:117`), `blocked_ac_count` (`:121`), `blocked_ac_detail_json` (`:122`), `findings_fully_resolved` (`:131`), `findings_partially_resolved` (`:132`), `findings_not_resolved` (`:133`), `adversarial_hit_rate` (`:130`), `final_status` (`:136`), `are_total_requirements` (`:140`), `are_covered_requirements` (`:141`), `increment_count` (`:145`), `phase_exploration_ms` (`:148`), `phase_verify_ms` (`:149`), `computed_at` (`:153`). (`adversarial_tests_created` exists; FK-62 has it as `:129`.)

### fact_guard_period (§62.2.2) — ADD
`period_grain` (`:171`), `violation_rate` (`:176`), `violation_stage_escape` (`:177`), `violation_stage_schema` (`:178`), `violation_stage_template` (`:179`), `escape_detection_count` (`:180`), `computed_at` (`:183`).

### fact_pool_period (§62.2.3) — ADD
`period_grain` (`:198`), `response_time_p50_ms` (`:202`), `verdict_adopted_count` (`:204`), `verdict_total_count` (`:205`), `finding_true_positive_count` (`:206`), `finding_false_positive_count` (`:207`), `quorum_triggered_count` (`:208`), `template_finding_rate_json` (`:211`), `computed_at` (`:214`). (P95 explicitly NOT added, `:203`.)

### fact_pipeline_period (§62.2.4) — ADD (~18; the whole table is effectively new shape)
`period_grain` (`:228`), `story_count` (`:231`), `story_count_closed` (`:232`), `execution_count` (`:233`), `exploration_count` (`:234`), `stage_miss_count` (`:235`), `stage_miss_detail_json` (`:236`), `impact_violation_count` (`:239`), `impact_check_count` (`:240`), `integrity_gate_block_count` (`:241`), `integrity_gate_total_count` (`:242`), `doc_fidelity_conflict_by_level_json` (`:245`), `first_pass_count` (`:248`), `finding_survival_count` (`:249`), `finding_total_count` (`:250`), `effective_check_ids_json` (`:251`), `vectordb_total_hits` (`:254`), `vectordb_above_threshold` (`:255`), `vectordb_classified_conflict` (`:256`), `vectordb_duplicate_detected` (`:257`), `processing_time_avg_ms` (`:260`), `processing_time_variance_ms2` (`:261`), `qa_round_avg` (`:262`), `computed_at` (`:265`).

### fact_corpus_period (§62.2.5) — ADD
`period_grain` (`:278`), `computed_at` (`:286`).

**New-column count (excluding renames): ~50.**

---

## 4. The truth-locations: current vs target

The story claims **five** truth-locations. Verified reality: there are **four column-bearing files** plus the **mapper layer**, because location #3 carries **no inline DDL** — it delegates to the migration file.

| # | Location | Current column truth | What must change | Notes / divergence flag |
|---|---|---|---|---|
| 1 | `src/agentkit/kpi_analytics/fact_store/models.py:25-120` | Pydantic field names = old set (`story_mode`,`started_at`,`completed_at`,`qa_rounds`,`adversarial_findings`,`are_gate_status`,`guard_id`,`llm_role`,`token_input_total`,`token_output_total`,`avg_latency_ms`,`period_end`,`stories_completed`,`stories_escalated`,`avg_qa_rounds`,`avg_phase_implementation_ms`,`incidents_recorded`,`patterns_promoted`,`checks_approved`,`agentkit_version`,`agentkit_commit`) | Rename fields, add ~50, drop/replace the non-FK62 ones; change `are_gate_passed` type | **The wire-serialized shape** (§0). Editing here breaks the frontend. |
| 2 | `src/agentkit/state_backend/postgres_schema.sql:974-1048` | DDL matches the old model set (TIMESTAMPTZ/BIGINT) | Rename, add, drop columns; PK column renames `:1008` (`guard_id`), `:1023` (`llm_role`) | Carries a long "schema-placement decision" comment `:957-971` asserting columns follow "story §2.1.1 binding spec verbatim" — this is the **OLD** spec, now contradicted by FK-62-as-truth. |
| 3 | `src/agentkit/state_backend/sqlite_store.py:1168-1187` `_ensure_analytics_tables` | **No inline DDL** — calls `MigrationRunner().run(conn)` (`:1185-1187`) | Nothing column-level here; the real SQLite columns live in location #4 | **Divergence vs story:** the story (§1.3, §6) treats this as a column-bearing truth-location. It is not — it is a bootstrap that runs the migration. Editing columns here is a no-op/error. |
| 4 | `src/agentkit/state_backend/migration/versions/v_3_4_analytics.sql:18-118` | The actual SQLite column truth (old set; `guard_id` PK `:52`, `llm_role` PK `:67`, `period_end`, `token_*`, `stories_*`, `incidents_*`, `agentkit_*`) | Rename/add/drop to FK-62 | This is what SQLite tests actually create. **Renames here are NOT additive** — see §7. |
| 5 | `src/agentkit/state_backend/store/_fact_sql.py:41-127` (NOT inline in `fact_repository.py`) + `fact_repository.py` mappers | Column lists `_FACT_*_COLUMNS`/`_UPDATE` (`_fact_sql.py:41-104`) + `_fact_*_params`/`_row_to_fact_*` (`fact_repository.py:193-362`) | Rename every column string + every mapper key + every `row["…"]` access | **Divergence vs story:** story §1.5/§6 points at `fact_repository.py:173-331` for the column lists; they were extracted into the sibling `_fact_sql.py` (see `fact_repository.py:46-64` import block). The mappers (`_fact_*_params`, `_row_to_fact_*`) are still in `fact_repository.py`. So this is **two files**, not one. |

**Net: a rename touches 5 files for the column truth (models, postgres DDL, migration DDL, `_fact_sql`, `fact_repository` mappers), NOT counting consumers/tests.** The story's "five locations" is correct in count but mislabels which file holds the SQLite DDL and where the column lists live.

---

## 5. BACKWARD impact on shipped code (the hard-to-reverse core)

AG3-082 (`status.yaml:4` `status: completed`, `completed: 2026-06-11`) and AG3-084 (shipped routes/dashboard/frontend) consume the **old** names directly. Enumerated, verified call sites:

### 5.1 AG3-082 RefreshWorker + the concrete source adapter

- `src/agentkit/kpi_analytics/aggregation/worker.py:325` — `keys = [(r.project_key, r.llm_role, r.period_start) for r in rows]` → reads `FactPoolPeriod.llm_role`. **Breaks on `llm_role→pool_key`.**
- `worker.py:277` — `guard_weeks.add((project_key, counter.guard_key, counter.week_start))` (this one already uses `guard_key` from the scratchpad model, which FK-62 keeps — OK), but `worker.py:313` builds guard keys from `base.period_start` of `FactGuardPeriod`; the record field `guard_id` is consumed in `analytics_source.py` (below).
- **`src/agentkit/state_backend/store/analytics_source.py`** — the AG3-082-wired `AnalyticsSourcePort` adapter that *recomputes and constructs* every fact record. It uses the OLD field names AND fields **absent from FK-62**:
  - `:177` `llm_role=pool_key`, `:179` `period_end=…`, `:181` `token_input_total=0`, `:182` `token_output_total=0`, `:183` `avg_latency_ms=None` (FactPoolPeriod) — `token_*`/`period_end`/`avg_latency_ms` **do not exist in FK-62 §62.2.3**; under FK-62-as-truth these constructions must be deleted/replaced.
  - `:216-219` `period_end`, `stories_completed`, `stories_escalated`, `avg_qa_rounds` (FactPipelinePeriod) — none exist in FK-62 §62.2.4; whole recompute must be rewritten to the new ~24-column shape.
  - `:243-246` `period_end`, `incidents_recorded`, `patterns_promoted`, `checks_approved` (FactCorpusPeriod) — renamed/dropped per FK-62 §62.2.5.
  - `:269-271` `guard_id=guard_key`, `period_end=…` (FactGuardPeriod) — `guard_id→guard_key`; `period_end` dropped.
  - `:384-393` `story_mode`, `started_at`, `completed_at`, `qa_rounds`, `adversarial_findings`, `agentkit_version`, `agentkit_commit` (FactStory) — every one renamed or dropped.
  - `:319` `max(metrics, key=lambda r: r.completed_at)` and `:156-158`, `:201-205`, `:377-378` read `record.completed_at` from the **runtime** `StoryMetricsRecord` (a *different* model, not the fact model) — these are NOT affected by the fact rename, but the *fact construction* downstream is.
- `tests/unit/state_backend/store/test_analytics_source.py` asserts the recomputed records by old field names (`stories_completed`, `stories_escalated`, `avg_qa_rounds`, `llm_role`, `guard_id` — per the test scan).

### 5.2 AG3-084 KPI API + DashboardService + top facade

- `src/agentkit/kpi_analytics/http/routes.py:461`,`:469` — dumps fact models to wire (the §0 finding). Every renamed field changes the public JSON.
- `src/agentkit/kpi_analytics/top.py:72` — `or fact.guard_id == kpi_filter.entity_filter.guard` → entity filter on `guard_id`. **Breaks on rename.**
- `top.py:80` — `or fact.llm_role == kpi_filter.entity_filter.pool`. **Breaks on rename.**
- `top.py:329`,`:337` — error messages referencing `guard_id`/`llm_role` columns (cosmetic but part of the contract surface).
- `src/agentkit/kpi_analytics/dashboard/service.py:189` `fact.completed_at`, `:197` `fact.are_gate_status`, `:201` `fact.qa_rounds`, `:203` `fact.completed_at`, `:206` sort by `completed_at`. **All renamed fields.**
- `fact_repository.py` read path: `list_fact_guards` orders by `guard_id` (`:501`), `list_fact_pool` orders by `llm_role` (`:513`); `_row_to_fact_*` read `row["guard_id"]` (`:320`), `row["llm_role"]` (`:329`), `row["started_at"]` (`:286`), `row["completed_at"]` (`:287`), `row["qa_rounds"]` (`:288`), `row["are_gate_status"]` (`:298`), etc. **All renamed.**

### 5.3 Frontend (AG3-084/094) — reaches the browser

The frontend wire types mirror the raw column names and the UI binds them directly (from the frontend scan; representative, verified by file path):
- `frontend/prototype/src/foundation/bff/client.ts` — `WireFactStory` (`story_mode`,`started_at`,`completed_at`,`qa_rounds`,`adversarial_findings`,`are_gate_status`,`agentkit_version`,`agentkit_commit`), `WireFactGuardPeriod` (`guard_id`,`period_end`), `WireFactPoolPeriod` (`llm_role`,`period_end`,`token_input_total`,`token_output_total`,`avg_latency_ms`), `WireFactPipelinePeriod` (`stories_completed`,`stories_escalated`,`avg_qa_rounds`,`period_end`), `WireFactCorpusPeriod` (`incidents_recorded`,`patterns_promoted`,`checks_approved`,`period_end`) (~`:251-315`).
- `frontend/prototype/src/contexts/kpi_analytics/AnalyticsSlot.tsx` — direct field reads & UI bindings: `r.qa_rounds` (~`:139`,`:177`), `r.adversarial_findings` (~`:145`), `r.started_at` (~`:174`), `r.guard_id` (~`:782-785`), `r.llm_role` (~`:813-816`), `r.token_input_total + r.token_output_total` (~`:819`), `r.stories_completed`/`r.stories_escalated` (~`:849`,`:852`), `r.incidents_recorded`/`r.patterns_promoted`/`r.checks_approved` (~`:733-735`).
- Frontend tests pinning the shapes: `__tests__/realShapes.fixture.ts` (~`:207-308`), `__tests__/views.test.tsx`, `__tests__/e2e/kpiSse.test.ts`.

> Note: exact frontend line numbers are from the read-only frontend scan; the file paths and identifiers are confirmed present. Treat the line numbers as "approximately at" pending a direct re-read during implementation.

### 5.4 Verdict on how much green code AG3-083 forces to change

A full FK-62 rename sweep is **NOT** confined to the five schema-truth files. It forces edits to, at minimum:
- **Backend production:** `aggregation/worker.py`, `state_backend/store/analytics_source.py` (heavy rewrite — also has columns FK-62 deletes), `kpi_analytics/top.py`, `kpi_analytics/dashboard/service.py`, `fact_repository.py` read mappers — i.e. **the entire shipped AG3-082 recompute path and AG3-084 read path.**
- **Frontend production:** `client.ts` wire types + `AnalyticsSlot.tsx` bindings.
- **Tests:** the contract schema test + the full kpi_analytics/state_backend test suites + frontend KPI tests (§6).

This is a **breaking change to two already-completed, green stories and the live wire contract.** That is the definition of hard-to-reverse.

---

## 6. Test blast radius

### MUST-UPDATE (golden / exact-column / wire assertions — fail immediately on rename)

- `tests/contract/state_backend/test_analytics_schema.py:53-108` — `_REQUIRED_COLUMNS` dict pins the **old** mandatory column set per table (`fact_story`→`started_at`,`qa_rounds`,`agentkit_version`,`agentkit_commit` `:59-62`; `fact_guard_period`→`guard_id`,`period_end` `:65-68`; `fact_pool_period`→`llm_role`,`period_end`,`token_input_total`,`token_output_total` `:74-79`; `fact_pipeline_period`→`stories_completed`,`stories_escalated` `:85-86`; `fact_corpus_period`→`incidents_recorded`,`patterns_promoted`,`checks_approved` `:92-94`). Consumed by parametrized `test_analytics_table_exists_with_mandatory_columns:125-138` and the PK test `test_fact_story_primary_key_is_project_key_story_id:142-160`. The Postgres roundtrip `test_postgres_five_fact_tables_roundtrip_via_factstore:163-234` instantiates `FactStory(...started_at=,qa_rounds=,agentkit_version=,agentkit_commit=...)`.
- `tests/unit/state_backend/migration/test_migration_runner.py` — expects table set `:38-42` and an INSERT with the **old** corpus column list (`incidents_recorded, patterns_promoted, checks_approved`) `:61-85`.
- `tests/unit/kpi_analytics/fact_store/test_models.py` — constructs every fact model by old field names (`:29-133`); model is `frozen, extra="forbid"` (`models.py:22`) so any rename breaks construction.
- Frontend: `realShapes.fixture.ts`, `views.test.tsx`, `e2e/kpiSse.test.ts` pin the old wire keys.

### WILL-BREAK on construction / assertion (transitive)

- `tests/unit/kpi_analytics/fact_store/test_store.py` (helpers `_story()`/guard/pool/corpus build old fields).
- `tests/contract/kpi_analytics/test_ag3_084_contracts.py` (`_make_facts()` and comparison tests use old fields).
- `tests/integration/kpi_analytics/test_fact_store_roundtrip.py:55-131` (full five-table roundtrip incl. `are_gate_status`, `guard_id`, `llm_role`, `token_*`, `stories_*`, `agentkit_*`).
- `tests/integration/kpi_analytics/test_kpi_endpoints.py` (asserts wire JSON, e.g. `body["rows"][0]["guard_id"]`).
- `tests/integration/kpi_analytics/aggregation/test_refresh_worker.py` and `test_productive_wiring.py` (factory helpers).
- `tests/unit/state_backend/store/test_analytics_source.py` (asserts recomputed records by old fields).
- `tests/unit/kpi_analytics/test_top.py`, `tests/unit/kpi_analytics/dashboard/test_service.py` (read `FactStory` old fields).
- `tests/unit/kpi_analytics/test_catalog.py:116-170` — pins `CatalogStatus.SKELETON` and the skeleton behaviour; **must flip to COMPLETE/40** once populated (this is an intended, not accidental, break).

> Caveat: the test scan also surfaced many `started_at`/`completed_at` hits in closure/envelope/telemetry tests (e.g. `tests/unit/closure/*`, `tests/unit/artifacts/test_envelope.py`). Those are **unrelated** models (artifact envelopes, story metrics) and are NOT in the fact-table blast radius. Do not "fix" them.

**Test files in the real fact blast radius: ~12 backend + 3 frontend.** None of these will "break silently" at runtime — Pydantic `extra="forbid"` + the contract schema test fail loudly; the dangerous silent case is the **frontend** (TypeScript will surface missing keys only if the types are updated; a stale wire key just renders `undefined`).

---

## 7. Postgres parity & migration mechanics

- **Not additive.** FK-62 §62.4.1 only blesses `ADD COLUMN IF NOT EXISTS` for *new* KPIs (`62_kpi_aggregation.md:586`, idempotent `_ensure_column` `:592-606`). The ~50 new columns can ride that path. The **renames cannot** — there is no `RENAME COLUMN IF NOT EXISTS` idempotency primitive that is symmetric across SQLite and Postgres, and the **PK renames** (`guard_id→guard_key`, `llm_role→pool_key`) touch the primary key, which SQLite cannot `ALTER` in place at all.
- **Two DDL dialects + one mapper must move together** or parity breaks: `postgres_schema.sql` (TIMESTAMPTZ/BIGINT, `:974-1048`), `v_3_4_analytics.sql` (TEXT/INTEGER, `:18-118`), and the `_fact_sql.py` column strings + `fact_repository.py` mappers. The schema-versioning model is **side-by-side per `ak3_v<slug>`** (`postgres_schema.sql:957-971`), so each version owns an isolated table set.
- **Migration mechanics — OPEN QUESTION / assumption, not established fact.** Both backends create the tables via `CREATE TABLE IF NOT EXISTS` at bootstrap (`postgres_schema.sql:974`, `v_3_4_analytics.sql:18`, run from `sqlite_store._ensure_analytics_tables:1185`). The statement "there is no shipped production analytics dataset to migrate" is **NOT verifiable from the repo** — it is an assumption that must be explicitly confirmed before choosing a migration strategy. **(OPEN QUESTION: confirm whether any CI/CD, staging, or production environment has a live DB with version 3.4 already recorded in `schema_versions`.)** Assuming the data is disposable/recomputable (FK-62 glossary "rollup" `:54-60`), the clean path is: replace the DDL outright and bump the schema version — not in-place `RENAME`.
- **Migration-skip mechanics finding (`migration_runner.py:127`).** `MigrationRunner.run()` skips versions already present in `schema_versions` (`if version in already: continue`). Consequence: **rewriting `v_3_4_analytics.sql` in place will NOT re-apply on any DB that already recorded version `3.4`**. A DB bootstrapped on the old schema will continue running the old column set. The correct approach is either: (a) create a **new version file** (e.g. `v_3_5_analytics_rename.sql`) added to the `_MIGRATIONS` registry (`migration_runner.py:40-43`), or (b) an explicit re-apply strategy that deletes the `3.4` entry from `schema_versions` first. This is a concrete mechanics requirement, not just a naming preference. **(OPEN QUESTION: which strategy — new version vs. re-apply — is preferred given the analytics tables' rollup-disposable nature?)**
- The historic Jenkins parity break is the risk if one of the 5 files drifts; the contract test `test_analytics_schema.py` is the guard, but its `_REQUIRED_COLUMNS` must be rewritten in the same change or it will pass against a stale set.
- `EXPECTED_SCHEMA_VERSION = 1` in `aggregation/worker.py:56` and the `schema_version` cursor (`models.py:133`, FK-62 §62.4.3) — if the version is bumped, the worker's expected value and the seed must move together or the worker fails closed (`worker.py:360-371` `SchemaVersionError`).

---

## 8. Ordering contradiction (082 ↔ 083)

**Four sources, three of them contradict the story's own claim:**

| Source | Says | Evidence |
|---|---|---|
| AG3-083 `status.yaml` | `depends_on: [AG3-038, AG3-081]`, `unblocks: [AG3-082]` (083 BEFORE 082) | `stories/AG3-083-kpi-catalog-fact-columns/status.yaml:8-12` |
| AG3-082 `status.yaml` | `unblocks: [AG3-083]` (082 BEFORE 083 — opposite) | `stories/AG3-082-kpi-refresh-worker/status.yaml:12-13` |
| `_STORY_INDEX.md` | AG3-083 `depends_on AG3-038, AG3-082` (082 BEFORE 083 — opposite) | `var/concept-gap-analysis/_STORY_INDEX.md:89` |
| AG3-082 `story.md` prose | "AG3-082 VOR AG3-083" throughout | (story prose, per AG3-083 story §1 pt2.3) |

The AG3-083 story (§1 pt2) argues the *fachlich correct* direction is **082 depends_on 083** (worker fills columns 083 defines) and asks the three external sources be corrected by their owners.

**Resolution given current reality (the decisive point the story could not know):** **082 and 084 are already `completed`.** So the "083 before 082" intent is **moot** — 082 already shipped a working recompute path *against the old columns*, and 084 shipped an API/frontend *against the old wire shape*. The dependency-direction debate no longer governs *sequencing* (nothing is left to sequence); it only matters for **bookkeeping consistency**. Concretely:
- The metadata cleanup (083 status `unblocks` 082 vs 082 status `unblocks` 083 vs index) is now **cosmetic** — neither story is waiting on the other.
- What actually matters: **AG3-083, if it does the rename, is no longer "defining columns for a future worker" — it is rewriting a live, green worker + live API + live frontend.** The rename-strategy decision (§10) supersedes the ordering decision. Recommendation: stop treating this as an ordering fix; treat it as a **breaking-change-management** decision. If the renames proceed, AG3-083 owns the edits to 082's `analytics_source.py`/`worker.py` and 084's `routes`/`top`/`dashboard`/frontend in the *same* PR (a "083 sweeps 082+084" change), because splitting them re-introduces the parity/drift risk the story warns about.

---

## 9. Risk & effort assessment

**Size (full FK-62 rename sweep, option (a)):**
- Schema-truth files: **5** (models, postgres DDL, migration DDL, `_fact_sql`, `fact_repository` mappers).
- Renames: **11** (2 are PK renames).
- New columns: **~50**.
- Dropped/replaced columns from shipped code: **~12** (`period_end`×4, `token_input_total`, `token_output_total`, `avg_latency_ms`, `stories_completed`, `stories_escalated`, `avg_qa_rounds`, `avg_phase_implementation_ms`, `agentkit_version`, `agentkit_commit`). NOTE: `period_end` exists on the four period tables (guard/pool/pipeline/corpus) only — `fact_story` has no `period_end` in either the current model (`models.py:38-53`) or FK-62 §62.2.1 (`62_kpi_aggregation.md:107-155`).
- Shipped-code production edits: **≥5 backend modules** (worker, analytics_source [heavy], top, dashboard service, repository) **+2 frontend** (client.ts, AnalyticsSlot.tsx).
- Test edits: **~12 backend + 3 frontend**, incl. a golden column contract.
- Catalog: 40 KPI definitions + typed FK-61 mapping annex + ~4 new negative tests.

**Top risks (ranked):**
1. **Wire-contract break to the browser** (§0/§5.3) — silent on the frontend if types aren't updated; user-visible KPI breakage. HIGHEST.
2. **`analytics_source.py` is not a rename — it's a rewrite**: it constructs columns FK-62 deletes (`token_*`, `period_end`, `stories_*`, `agentkit_*`) and lacks the ~50 new ones. The recompute logic for the new pipeline/pool/guard/corpus columns is **AG3-082 territory** (story §2.2 puts fill-logic out of scope) yet the *shape* change forces touching it. **Scope collision with a completed story.**
3. **Cross-backend parity / PK rename** (§7) — historically breaks Jenkins; mitigated only by replacing DDL wholesale + bumping schema version + rewriting `_REQUIRED_COLUMNS` atomically.
4. **`are_gate_status`(str)→`are_gate_passed`(int/bool)** — type change, not just a name; dashboard service `:197` treats it as a string (`fact.are_gate_status or "UNKNOWN"`). Semantic break.
5. **Corpus rename is a semantics shift** (`checks_approved`→`patterns_with_active_check`, `patterns_promoted`→`patterns_total_count`) — recompute meaning changes, not just labels.

**QA-round likelihood:** HIGH (≥2-3 rounds) for option (a). The change is broad (public interfaces + core state model + wire contract → CLAUDE.md "Operations: nicht nur ein schmaler Ausschnitt"), spans Python + SQL + TypeScript, and hits the Jenkins-sensitive Postgres parity path. Coverage ≥85% must hold while a recompute path is rewritten.

---

## 10. Options & recommendation

### Option (a) — Full FK-62 rename sweep as specified
Do exactly what the story says: FK-62 is the single truth; rename all 11, add ~50, drop/rename/rederive/replace the ~12 non-FK62 columns (some are renames/semantic maps, some are true drops — see §1 and §9), and ripple through 082/084/frontend in one PR.
- **Pro:** ends the divergence; one consistent truth; satisfies FIX-THE-MODEL / SINGLE-SOURCE-OF-TRUTH; story-as-written is honoured; no parallel column set.
- **Con:** largest blast radius; rewrites two completed green stories + the live wire contract + frontend; high QA-round risk; forces `analytics_source.py` recompute rewrite that overlaps AG3-082's out-of-scope fill-logic.
- **Blast radius:** maximal (5 schema files + 5 backend modules + 2 frontend + ~15 tests).
- **Reversibility:** LOW (breaking wire change; would need a coordinated revert across BE+FE).

### Option (b) — Additive-only now; defer renames to a dedicated coordinated story
Populate the 40-KPI catalog + FK-61 mapping annex now; **ADD** the ~50 missing columns (clean `ADD COLUMN IF NOT EXISTS`, FK-62 §62.4 path); **DEFER** the 11 renames (and the ~12 drops/renames/rederives) to a separate, explicitly-scoped "schema-rename + wire-contract migration" story that owns BE+FE+tests together.
- **Pro:** unblocks the catalog (the genuinely new value) immediately; additive columns are low-risk and parity-safe; does NOT break 082/084/frontend; isolates the dangerous rename into one reviewable, owner-clear change; aligns with ZERO-DEBT severity (rename is a real WARNING that must be surfaced, not silently inherited).
- **Con:** temporarily keeps two naming conventions (old shipped names + FK-62 new names co-existing as the "truth divergence" the story wanted to kill) → tension with SINGLE-SOURCE-OF-TRUTH; the FK-61 mapping annex (§2.1.2) references FK-62 target names that won't all exist yet under old names (the mapping must point at *real* columns → either map to current names or only to added-new ones); the story AC4 ("FK-62 names as single truth, all renames done") would **not** be met, so the story spec must be amended.
- **Blast radius:** moderate (catalog + additive DDL across 4 files + new tests); zero shipped-code breakage.
- **Reversibility:** HIGH (additive columns are droppable; no wire break).

### Option (c) — Split into two stories: (c1) catalog population, (c2) schema migration
Carve AG3-083 into 083a (40-KPI catalog + FK-61 typed mapping + contract tests, **no schema change**) and 083b (the FK-62 column reconciliation incl. renames/drops/adds + the BE/FE/test sweep).
- **Pro:** cleanest ownership; 083a is small, safe, and finishes "the last story's catalog half" immediately; 083b can be sized/reviewed as the genuinely hard-to-reverse change it is, with explicit BE+FE+test scope and a schema-version bump.
- **Con:** introduces a new story (needs user consent / backlog edit); 083a's FK-61 mapping must point at columns that exist *today* or be marked pending 083b (fail-closed AC tension); two reviews instead of one.
- **Blast radius:** 083a tiny; 083b = option (a) blast radius but isolated and intentional.
- **Reversibility:** 083a HIGH; 083b LOW (same as (a) but consciously owned).

> **IMPORTANT CAVEAT (verified against story.md:95 and FK-61 §61):** 083a (catalog + FK-61 mapping, no schema change) **CANNOT fully satisfy AC3** (`story.md:95` requires each KPI's target fact column to resolve in the FK-62 schema — "Jede genannte Ziel-Spalte MUSS im FK-62-Sollschema existieren — sonst Test rot"; FK-61 §61 makes the target column part of the collection-point contract). A split is defensible **only** with an explicit story/spec amendment that accepts temporary mapping-to-current-columns (or pending-marker placeholders) as a **SURFACED WARNING** under ZERO-DEBT severity semantics — i.e. an explicit, tracked open item that must be resolved by 083b, not a silent deferral. Treating 083a as "concept-faithful completion" without such an amendment is incorrect.

### Recommended path

**Option (c) is the safest, with Option (b) as the pragmatic fallback if a new story is undesirable.** Rationale tied to the guardrails and the proven reality:
- The catalog population (the actual new capability, FK-60 §60.4) is independent of the schema rename and carries **none** of the hard-to-reverse risk. Ship it.
- The rename is, today, **not** "defining future columns" — it is a **breaking change to live, green code and a live wire contract** (§0, §5). Per CLAUDE.md SEVERITY-SEMANTIK this is a WARNING-class fact that must be **mirrored to the user with "how do we proceed,"** which is exactly what this analysis does — not silently executed inside a story that thought it was running first.
- Option (a) is *technically* the FIX-THE-MODEL ideal, but executing it blind (as the story text implies) would knowingly break two completed stories and the frontend in one sweep, with HIGH QA-round and Jenkins-parity risk, while overstepping AG3-082's out-of-scope recompute logic.

### OPEN QUESTIONS the user must answer before any code

1. **Rename now or defer?** Given 082/084 already shipped on the old names and the wire contract is live to the browser, do we (a) do the full breaking sweep in AG3-083, (b) additive-only + defer renames, or (c) split? *(This is the Go/No-Go pivot.)*
2. **Who owns the cross-story edits?** If renames proceed, AG3-083 must edit AG3-082's `analytics_source.py`/`worker.py` and AG3-084's `routes`/`top`/`dashboard`/frontend. Is AG3-083 authorised to modify completed stories' code and the frontend, or does that need new stories / consent? (CLAUDE.md: no editing other stories' artifacts without ownership.)
3. **Drop vs keep the non-FK62 columns?** `token_input_total`/`token_output_total`/`avg_latency_ms`/`period_end`/`stories_*`/`avg_*`/`agentkit_version`/`agentkit_commit` are written by shipped code but absent from FK-62 §62.2. Are these to be **dropped** (FK-62 is truth) or is FK-62 to be **amended** to retain some (e.g. `agentkit_version`/`agentkit_commit` provenance, `period_end`)? A concept decision is required either way (CLAUDE.md: amend the concept, not the code).
4. **Schema-version strategy:** bump `EXPECTED_SCHEMA_VERSION` (worker.py:56) + `schema_version` seed + a new `v_3_5_*` migration (required if any DB already has version `3.4` recorded — see §7 migration-skip finding), or rewrite `v_3_4` in place with an explicit re-apply step? **Confirm whether analytics tables are truly bootstrap-only / no prod data to preserve** — this is an assumption in the doc, not a verified fact. If any environment has a live DB with `3.4` recorded, rewriting the file in place silently does nothing.
5. **`are_gate_status`→`are_gate_passed` type change:** confirm the int/bool semantics and how `dashboard/service.py:197` (`or "UNKNOWN"`) and the wire/frontend should represent it.
6. **Story-spec amendment:** AC4 currently demands "FK-62 names as the single truth, all renames done." Options (b)/(c) cannot satisfy that as written — confirm the spec may be amended (and who owns the `_STORY_INDEX.md` / AG3-082 metadata cleanup the story flagged).

---

### Evidence index (primary files read)
- Concepts: `concept/technical-design/62_kpi_aggregation.md` (FK-62 §62.2/§62.4/§62.6); story-cited FK-60 §60.4 / FK-61 ranges (catalog IDs verified against story §2.1.1; FK-60/61 prose not exhaustively re-derived here — see OPEN QUESTION on amendments).
- Truth-locations: `kpi_analytics/fact_store/models.py`, `state_backend/postgres_schema.sql:957-1077`, `state_backend/sqlite_store.py:1168-1187`, `state_backend/migration/versions/v_3_4_analytics.sql`, `state_backend/store/_fact_sql.py`, `state_backend/store/fact_repository.py`.
- Catalog: `kpi_analytics/catalog.py`.
- Shipped consumers: `kpi_analytics/aggregation/worker.py`, `kpi_analytics/aggregation/source_port.py`, `kpi_analytics/aggregation/models.py`, `state_backend/store/analytics_source.py`, `kpi_analytics/http/routes.py`, `kpi_analytics/top.py`, `kpi_analytics/dashboard/service.py`; frontend `foundation/bff/client.ts`, `contexts/kpi_analytics/AnalyticsSlot.tsx` (via read-only scan).
- Ordering: `stories/AG3-083-kpi-catalog-fact-columns/status.yaml`, `stories/AG3-082-kpi-refresh-worker/status.yaml`, `var/concept-gap-analysis/_STORY_INDEX.md:88-90`. AG3-084 story dir (for status/contracts): `stories/AG3-084-dashboard-backend-kpi-endpoints/`.
- Tests: `tests/contract/state_backend/test_analytics_schema.py` (verified directly); kpi_analytics/state_backend test families (via read-only scan).
