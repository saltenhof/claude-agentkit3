# AG3-082 — Remediation Report (Review r2)

**Scope of change:** `stories/AG3-082-kpi-refresh-worker/story.md` + one genuinely-wrong
`status.yaml` field (`unblocks`). No production code, tests, or `concept/` files touched.
The story stays strictly inside its `_STORY_INDEX.md` cut (line 88: AG3-082 = idempotent
RefreshWorker incl. `_percentile`, depends_on `AG3-038, AG3-081`).

**Authoritative ordering source (decisive for ERRORs 1 + 3):** `var/concept-gap-analysis/_STORY_INDEX.md`
- Line 88: **AG3-082** depends_on `AG3-038, AG3-081`.
- Line 89: **AG3-083** depends_on `AG3-082` — i.e. **AG3-082 comes BEFORE AG3-083**.

This means AG3-082 must NOT take a dependency on AG3-083 (that would invert the index and
create a cycle). The review-r2 ERROR-1 alternative "add AG3-083 as a hard dependency" is
therefore not valid against the index; the correct branch is **remove the p50/p95
persistence obligation from AG3-082**. ERROR 3 follows from the same ordering: the
catch-up materialization needs AG3-083 columns and thus cannot live in AG3-082.

---

## Must-Fix ERRORs (review-r2)

### ERROR 1 — AG3-083 / P50 ordering contradiction → RESOLVED
**Finding:** Story coupled p50/p95 persistence to AG3-083 and "fail-closed on missing
column", implying AG3-083 precedes AG3-082; status.yaml had no AG3-083 link; AG3-083
itself claims to unblock AG3-082.
**Root cause:** Mixed-up ordering vs. the authoritative index (082 → 083).
**Resolution (story.md):**
- §1 Ist-Zustand: percentile bullet now states the index order explicitly (082 before 083)
  and that AG3-082 implements `_percentile` as a **pure function with no persistence**
  (no p50/p95 write side, no AG3-083 dependency, no cycle).
- §2.1 `_percentile` block rewritten: AG3-082 computes/tests the function, **does not
  persist**; persisting into `response_time_p50_ms` is AG3-083 scope; `response_time_p95_ms`
  stays INVENTAR in both stories.
- §2.2 Out of Scope: AG3-083 now owns "column extension **+ percentile persistence**"
  (line 89, depends_on AG3-082).
- **AC9** rewritten: pure-function test only; "no p50/p95 persistence path exists in
  AG3-082; no missing-column fail-closed; no AG3-083 dependency".
- §5 FAIL-CLOSED guardrail and §6 hints aligned (no more p50/p95 column dependency).
- **status.yaml:** `unblocks: []` → `unblocks: [AG3-083]` (genuinely wrong field; the index
  says AG3-082 unblocks AG3-083). `depends_on` left unchanged — already `[AG3-038, AG3-081]`,
  exactly matching index line 88. (The reciprocal drift in AG3-083's own status.yaml —
  `depends_on AG3-081 / unblocks AG3-082` — is outside this story's edit scope and is noted
  for routing below.)

### ERROR 2 — `sync_state.schema_version` has no writer/seed owner → RESOLVED (read-only here, seed routed)
**Finding:** AG3-082 fail-closes on missing/mismatched `schema_version`, but no story
seeds `(project_key, "schema_version")`. Migration only creates the table
(`v_3_4_analytics.sql:97-104`); repository exposes only `get_sync_state`
(`fact_repository.py:421-430`) + `upsert_sync_state` (`:560`).
**Root cause:** Seed responsibility is a schema/migration concern, not a worker concern.
**Resolution (story.md):** AG3-082 is scoped to **READ ONLY**, fail-closed; it does **not**
seed (no hidden worker-side migration). The seed/writer is assigned to the schema/migration
owner **AG3-038** (owns `sync_state` + `schema_version`-cursor + migration strategy,
`AG3-038/story.md:22`; status `completed`; the `upsert_sync_state` writer port already
exists). The missing per-project seed is an AG3-038 follow-up gap, mirrored to the PO as
**WARNING W2** (it cannot be created inside the AG3-082 cut without expanding scope into a
completed story's schema layer).
- §1 Ist-Zustand: new sentence documenting the missing seed + the AG3-038 ownership.
- §2.1.6 rewritten: "schema_version — READ ONLY, fail-closed, no worker seeding".
- §2.2: new Out-of-Scope entry "schema_version seed/writer = AG3-038".
- **AC10** rewritten: worker reads fail-closed and does not seed; test proves
  fail-closed-on-missing-seed instead of self-seeding.
- §6 W2 WARNING (routed to PO).

### ERROR 3 — Dashboard catch-up materialization routed to stories that do not own it → RESOLVED (honest gap to PO)
**Finding:** FK-62 §62.3.7 requires dashboard sync to materialize non-closed stories;
AG3-082 excludes it and routed it to AG3-083/AG3-084, but both stories explicitly exclude
RefreshWorker/fill logic.
**Root cause:** False routing; the materialization needs AG3-083 columns
(`fact_story.final_status` + trend columns) which land **after** AG3-082, so it cannot live
in AG3-082 (cycle), and AG3-083/084 do not own fill logic — i.e. it has **no current owner**.
**Resolution (story.md):** §2.2 and §6 W1 now state plainly: the open-story materialization
has **no unambiguous owner in the current cut**; the column prerequisite is AG3-083 (after
AG3-082); AG3-083/AG3-084 both exclude RefreshWorker/fill logic; therefore it needs its own
follow-up unit with a status dependency. This is flagged as **WARNING W1 to the PO** (not
silently pushed onto AG3-083/AG3-084). The `RefreshTrigger.DASHBOARD` plumbing remains in
AG3-082 and is idempotent but does not materialize open stories.

### ERROR 4 — Anchor defect in prerequisite reference → RESOLVED
**Finding:** §1 said AG3-081 prerequisite is "siehe §2.3, AK11" (wrong AC — AC11 is FactStore
ports; the ordering gate is AC12) and the AG3-081 path was abbreviated with `...`.
**Resolution (story.md):** §1 now reads "siehe §2.3 und AK12" and uses the exact anchor
`stories/AG3-081-event-buildout-bc14-bc15-integrity-dim8/status.yaml:4-5`
(verified: line 4 `status: draft`, line 5 `phase: review_pending`).

---

## WARNINGs (per CLAUDE.md SEVERITY-SEMANTIK — actively mirrored to PO, not silently dropped)

- **W1 — Dashboard catch-up materialization (FK-62 §62.3.7):** no owner in the current cut;
  question to PO = create a dedicated follow-up story with a status dependency on AG3-083
  (which supplies `final_status` + trend columns)? Documented in §2.2 and §6 W1.
- **W2 — `sync_state.schema_version` per-project seed:** owner AG3-038 (completed); question
  to PO = schedule an AG3-038 follow-up so AG3-082 does not remain permanently fail-closed
  after implementation? Documented in §2.2 and §6 W2.
- **Residual cross-story drift (routing note, not an AG3-082 defect):** AG3-083's own
  `status.yaml` currently reads `depends_on: [AG3-038, AG3-081]` + `unblocks: [AG3-082]`,
  which is the inverse of the authoritative `_STORY_INDEX.md` ordering (083 depends_on 082).
  Fixing AG3-083's status.yaml is outside this story's edit scope; routed to the AG3-083
  owner / PO for reconciliation with the index.

---

## Code-anchor re-verification (all confirmed against real files)

- `fact_pool_period` has only `avg_latency_ms`, no p50/p95: `kpi_analytics/fact_store/models.py:72-87`,
  `state_backend/postgres_schema.sql:849-859` (confirmed).
- `sync_state` table (no seed): `state_backend/postgres_schema.sql:889-896` and
  `state_backend/migration/versions/v_3_4_analytics.sql:97-104` (confirmed — table only, no seed row).
- `get_sync_state` read port: `state_backend/store/fact_repository.py:421-430`;
  `upsert_sync_state` writer port: `:560` (confirmed — writer exists, seed call missing).
- AG3-038 owns sync_state + schema_version-cursor + migration strategy:
  `stories/AG3-038-analytics-schema-fact-tables/story.md:22`; status `completed` (confirmed).
- AG3-081 prerequisite anchor:
  `stories/AG3-081-event-buildout-bc14-bc15-integrity-dim8/status.yaml:4-5` (confirmed).
- Index ordering: `var/concept-gap-analysis/_STORY_INDEX.md:88` (AG3-082 deps AG3-038/AG3-081),
  `:89` (AG3-083 deps AG3-082) (confirmed — decisive for ERROR 1 + 3).

---

## ARCH-55 / template

- AG3-057 template structure preserved (Header / §1 Kontext / §2 Scope / §3 AC / §4 DoD /
  §5 Guardrails / §6 Hinweise).
- All new/changed identifiers stay English (`RefreshTrigger`, `EXPECTED_SCHEMA_VERSION`,
  `response_time_p50_ms`, `final_status`, port names). AC13 (ARCH-55) unchanged.

---

## Files written
- `stories/AG3-082-kpi-refresh-worker/story.md` (rewritten — ERRORs 1-4 + W1/W2)
- `stories/AG3-082-kpi-refresh-worker/status.yaml` (`unblocks: []` → `unblocks: [AG3-083]`)
- `stories/AG3-082-kpi-refresh-worker/remediation-r2.md` (this report)

No production code, tests, or `concept/` files were touched.
