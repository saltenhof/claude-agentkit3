# AG3-094 Implementation Review r2 (Codex, sole gate) — OVERALL: REJECT

Job: job-5f289d35 (backend codex, read-only). Date 2026-06-16.

R2 was a shallow/partial remediation. E2 + E4 RESOLVED; E1/E3/E5/E6/E7 NOT-RESOLVED;
2 new backend ERRORs (SQLite/Postgres parity drift + CWD hidden-state).

## r1 mapping
- E2 RESOLVED (telemetry→mode-lock: AnalyticsSlot.tsx:925-929, Shell.tsx:529-538/729).
- E4 RESOLVED (useProjectSse.ts:93-105 offline on drop-after-open).
- E1/E3/E5/E6/E7 NOT-RESOLVED (below).

## ERROR (round 2)
- **E1 (AC2/AC5/AC7)** `AnalyticsSlot.tsx:951-953`: guards/pools/pipeline are fetched
  (`:856-861`) then DISCARDED via `void guardsResponse/poolsResponse/pipelineResponse`. Only
  stories/corpus feed rendered UI (`:1009-1023`). `getKpiDesignTokens` dead BFF surface
  (`client.ts:767`). FIX: render the guards/pools/pipeline dimensions where filtered (or remove
  the surface if truly not in the view) + non-empty render assertions.
- **E3 (AC6)** `AnalyticsSlot.tsx:909`: Analytics SSE passes no onOffline/onOnline; Shell only
  passes isOffline/onTelemetryEvent (`Shell.tsx:724`). A dropped Analytics stream can't set Shell
  offline → total-offline locking incomplete. FIX: AnalyticsSlot offline callbacks → useProjectSse
  → Shell setIsOffline(true/false).
- **E5 (AC8)** `AnalyticsSlot.tsx:321`: productive chart option still has raw
  `rgba(255,255,255,0.03)`. FIX: owner-backed `--chart-series-*`/`--ak-*` token.
- **E6 (AC1/AC3/AC4/AC5)** `views.test.tsx:266`: band-toggle test only asserts the mock chart
  still exists (`:281-282`), not helper-series add/remove; Kanban/Graph SSE coverage only checks
  constants (`:459-464`), not real subscriptions/event re-sync; no custom-range period assertion.
  FIX: assert captured chart options after click; custom-range query assertions; real
  Kanban/Graph subscriptions + events via FakeEventSource.
- **E7 (AC10)** `kpiSse.test.ts:255`: E2E proves guards/pools/pipeline/corpus EMPTY (`:255-284`);
  only /kpi/stories seeded non-empty (`:379-392`). SSE event observed (`:395-428`) but NO proof a
  refreshed KPI read/view follows the event. FIX: seed real facts for all consumed dimensions (or
  scope the AC down explicitly) + assert event-driven re-sync changes the read result/view.
- **E8 NEW (AC10/backend parity)** `sqlite_store.py:2714`: SQLite
  `load_execution_event_rows_for_project_global(limit=...)` returns DESC directly, while Postgres
  selects DESC then REVERSES to chronological (`postgres_store.py:1822-1828`). SQLite uses
  `INSERT OR IGNORE` (`:2512`) vs Postgres plain insert (`postgres_store.py:1616-1623`). Cross-backend
  drift in the exact SSE store → would pass local SQLite, break Postgres path on Jenkins. FIX: make
  SQLite match Postgres ordering/limit/dup-key + a cross-backend contract test.
- **E9 NEW (AC10/backend model)** `sqlite_store.py:1973`: global SQLite state for `project=None`
  keyed to `Path.cwd()` (used by global event append/read `:2509/:2717`); harness must
  `os.chdir(_tmp_dir)` (`python_harness.py:46-49`) despite setting `AGENTKIT_STORE_DIR` (`:41`).
  Hidden operational state, not a sound production model. FIX: route global event storage through
  the explicit configured store root (AGENTKIT_STORE_DIR, mirroring per-project dir resolution),
  or fail-closed when no explicit root exists.

## Note
The `_test` harness endpoints are test-only and route through the real FactStore/SSE facade
(`python_harness.py:73-85/122-145/155-159`) — but the CWD store model they rely on (E9) is the problem.
