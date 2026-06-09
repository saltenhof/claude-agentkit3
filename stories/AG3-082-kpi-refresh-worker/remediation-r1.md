# AG3-082 — Remediation Report (Review r1)

**Scope of change:** `stories/AG3-082-kpi-refresh-worker/story.md` only. `status.yaml` left
unchanged (all fields already correct: `type: implementation`, `depends_on: [AG3-038, AG3-081]`,
`phase: review_pending`). No production code, tests, or `concept/` files touched.

The story stays strictly inside its `_STORY_INDEX.md` cut: AG3-082 = **Recompute-half** of the
reset-purge chain + RefreshWorker/percentile. AG3-081 = Schema/Read-Model-purge-half + hot-path
write. AG3-083 = column sets / KPI catalog. AG3-071 = reset trigger. No scope was expanded beyond
the FactStore transaction/delete/replace ports, which the review itself demanded as in-scope.

---

## Must-fix ERRORs

### E1 — `sync_analytics` trigger contract vs FK-62
**Finding:** FK-62 §62.3.2 specifies `sync_analytics(trigger, project_key, hint_story_id, client)`
with an explicit trigger; the story only had `sync_analytics(project_key, hint_story_id=None)`.
**Resolved:** §2.1.1 now defines the worker signature as
`sync_analytics(trigger, project_key, hint_story_id=None)` with a typed `RefreshTrigger` StrEnum
(`CLOSURE`/`DASHBOARD`/`RESET`, ARCH-55 English values). §2.1.2 documents how
`KpiAnalytics.refresh_analytics(project_key, hint_story_id)` maps onto it without information loss:
the facade is the Closure adapter (`trigger=RefreshTrigger.CLOSURE`), while Dashboard/Reset triggers
are set by their own callers. AC1 asserts the typed trigger; AC5 asserts the `CLOSURE` mapping.

### E2 — ProjectionAccessor / FactStore ownership as a testable AC
**Finding:** FK-62 §62.6.1/§62.6.2 mandate runtime-read only via `ProjectionAccessor` and write only
via `FactStore`; the story only mentioned FactStore guardrail-style.
**Resolved:** Added source-concept refs to §62.6.1/§62.6.2 in the header, a guardrail entry, and a
dedicated **AC6**: an import/architecture-conformance test proving the worker module holds no direct
`runtime.*` DB connection and no `state_backend.store` facade import for writes (mirrors the existing
AC8 boundary in `fact_store/repository.py`).

### E3 — `guard_invocation_counters` drain incomplete (delete processed rows)
**Finding:** FK-62 §62.2.6 requires transferring AND deleting processed scratchpad rows; old AC7 only
required draining into `fact_guard_period`.
**Resolved:** §2.1.5 now states the drain transfers idempotently AND deletes processed rows in the
same transaction, and that reset removes the affected story's scratchpad rows. **AC8** asserts both
(counter in `fact_guard_period`, scratchpad rows gone; reset removes them).

### E4 — Dirty-set matrix + atomic rollback tests too vague
**Finding:** AC1 "delta-driven" was not testable; FK-60/FK-62 name concrete dirty sets and sources.
**Resolved:** §2.1.4 adds the full five-row dirty-set matrix (each set's tuple type + source events)
verbatim from FK-62 §62.3.4, including the corpus special case. **AC2** turns it into a per-source
testable matrix (five targeted asserts). AC3 (idempotency) splits cleanly; AC4 (atomicity) is below.

### E5 — Read-model-purge scope contradiction
**Finding:** In Scope said "purges the FK-69 read-models" while Out of Scope assigned the read-model
purge path to AG3-081.
**Resolved:** §2.1.3 now says `purge_story_analytics` **calls** the AG3-081-provided FK-69 read-model
purge port (does NOT implement it). §2.2 keeps the port *implementation* with AG3-081 and cites the
`_STORY_INDEX.md` "Reset-Purge-Kette" split (schema/read-model half = AG3-081, recompute half =
AG3-082). **AC7** asserts the port is *called*, not implemented.

### E6 — P50/P95 / AG3-083 column conflict
**Finding:** Story fed `_percentile` into `response_time_p50_ms`/p95, but FK-62 §62.2.3 marks p95 as
INVENTAR and AG3-083 (after AG3-082) owns column extension.
**Resolved:** The `_percentile` block now separates computation from persistence: AG3-082 fully
implements and tests `_percentile`, but writes only to existing columns; p50/p95 target columns are
owned by AG3-083 and `response_time_p95_ms` is noted as today's INVENTAR. If a target column is
missing, the worker reports the dependency fail-closed instead of writing to a non-existent field.
**AC9** encodes this; §2.2 keeps the column set with AG3-083.

### E7 — FactStore/Repository transaction/delete/replace ports not in scope
**Finding:** Story required "write only via FactStore" but the real `FactStore`/`FactRepository`
(`store.py:87-109`, `repository.py:83-105`) only have read + single-row upsert — no
transaction/delete/replace-slice API.
**Resolved:** §2.1.7 explicitly takes the port extension into scope (transaction bracket,
`delete_fact_story`, `replace_<table>_period` for the four period tables), owned by FactStore (no
second write path). **AC11** asserts the ports exist and are used (replace-slice + delete + rollback).

---

## WARNINGs

### W1 — Dashboard catch-up / survivorship bias (FK-62 §62.3.7)
**Finding:** Materialization of unclosed `RUNNING/ESCALATED/PAUSED` stories on dashboard sync was
missing; FK-62 §62.3.7 requires it.
**Resolved (routed, not silently dropped):** §6 documents it as **deliberately out of scope** here,
because it depends on `fact_story.final_status` and trend-KPI columns that **AG3-083** introduces
(`_STORY_INDEX.md`: column sets = AG3-083). The `RefreshTrigger.DASHBOARD` path exists and is
idempotent in AG3-082 but does not yet materialize open stories; that follow-up is explicitly routed
to AG3-083/AG3-084 (dashboard live view). No FK-60↔FK-62 concept conflict was found — both agree on
the trigger model; only the column prerequisite forces the deferral.

### W2 — AC8 `schema_version` had no expected value / key contract
**Finding:** Old AC8 required fail-closed on unknown `schema_version` but named no expected value or
storage/key contract.
**Resolved:** §2.1.6 fixes the contract: key `(project_key, "schema_version")` in `sync_state`,
`value_int`, compared against a named `EXPECTED_SCHEMA_VERSION` constant (initial value `1`, since the
current FK-62 schema is the first version). **AC10** asserts fail-closed for both missing and
mismatched versions.

### W3 — "atomic transaction per refresh unit" undefined
**Finding:** The transaction unit was undefined (whole project refresh incl. cursor vs per dirty
slice).
**Resolved:** §2.1.1 defines it as **one atomic transaction per `sync_analytics` call**, spanning all
slices + the cursor update (FK-62 §62.3.2/§62.3.7: cursor update is the last step inside the same
transaction). **AC4** makes atomicity concrete: failure injected **after** `replace_*_period` and
**before** `update_sync_cursor`; assert no fact change visible AND `last_event_id` unchanged.

### W4 — Story claimed AG3-081 "delivers"; AG3-081 is draft/review_pending
**Finding:** §1 claimed AG3-081 supplies hot-path/purge, but AG3-081 is `draft/review_pending`.
**Resolved:** §1 now states AG3-081 is currently `draft/review_pending`
(`stories/AG3-081-.../status.yaml:4-5`) and that AG3-082 requires **AG3-081 completed** before
implementation/release. New §2.3 (Voraussetzung/ordering) and **AC12** (ordering gate) encode the
prerequisite; the wording no longer asserts AG3-081 is already delivered.

---

## Code-anchor corrections (review flagged wrong/loose anchors)

All anchors were re-verified against the real files and corrected to file:line:

- `top.py` paths: was loose `top.py:74-103`/`:101`/`:59`. Now precise:
  SKIPPED `top.py:93-99`, `NotImplementedError` `top.py:101-103`, constructor slot `top.py:59`,
  facade range `top.py:55-103` (verified in `src/agentkit/kpi_analytics/top.py`).
- `sync_state` table: was `postgres_schema.sql:889`. Now `postgres_schema.sql:889-896` (verified).
- `fact_pool_period`/`avg_latency_ms`: now `models.py:72-87` and `postgres_schema.sql:849-859`
  (verified; only `avg_latency_ms`, no p50/p95 columns — confirms E6).
- `guard_invocation_counters`: anchored to `postgres_schema.sql:902-909` (verified, runtime schema).
- FactStore/Repository read+upsert-only: anchored to `store.py:34/87-109` and
  `repository.py:34/83-105` (verified — confirms E7).

---

## Other adjustments

- Acceptance criteria renumbered to AK1–AK14 (was AK1–10); DoD and mandatory-commands AC updated
  accordingly.
- Header source-concepts list refined to the precise FK-62 sub-sections actually cited
  (§62.3.1/§62.3.2 trigger, §62.3.4 dirty sets, §62.2.6 drain, §62.4.3 schema_version,
  §62.6.1/§62.6.2 ownership) plus FK-60 §60.3.5/§60.3.6.
- ARCH-55 reinforced: `RefreshTrigger` enum values, dirty-set names, `EXPECTED_SCHEMA_VERSION`,
  and all new ports are English.

---

## Files written
- `stories/AG3-082-kpi-refresh-worker/story.md` (rewritten)
- `stories/AG3-082-kpi-refresh-worker/remediation-r1.md` (this report)
- `status.yaml` — **not modified** (no field was wrong)

No production code, tests, or `concept/` files were touched.
