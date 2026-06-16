# AG3-094 Implementation Review r1 (Codex, sole gate) — OVERALL: REJECT

Job: job-c71c9718 (backend codex, read-only). Date 2026-06-16.

Substantial R1 but real gaps: only the stories KPI dimension wired, dead dimension
methods, weak offline handling, loose hex, mocked-ECharts hollow tests, hollow AC10 E2E.

## ERROR
1. **AC2/AC5/AC7** `AnalyticsSlot.tsx:722`: Analytics fetches ONLY `getKpiStories()`. The
   `/kpi/guards|pools|pipeline|corpus|design-tokens` BFF methods are dead surface
   (`client.ts:743/749/755/761/767`). Guard/pool filters wrongly sent to `/kpi/stories`
   (`:659-660/722`) — backend has guard only on `/kpi/guards`, guard+pool invalid
   (`kpiSse.test.ts:203-230`). `failure_corpus` re-fetch has no funnel state wired. FIX:
   fetch+render all required KPI dimensions, route endpoint-specific filters to their
   dimension, make guard/pool endpoint-scoped, implement the corpus funnel + its re-fetch.
2. **AC5** `AnalyticsSlot.tsx:749`: `telemetry` events only call `fetchKpiData()`, never
   refresh mode-lock; Shell subscribes only stories/phases/planning (`Shell.tsx:527-565`),
   mode loaded only via `loadProjectData()`. FIX: wire telemetry events to refresh the
   mode-lock-dependent UI (Shell-level telemetry subscription or a mode-lock refresh cb).
3. **AC6** `Shell.tsx:665/687/699`: total-offline does NOT disable mutating UI (only
   archived does); Kanban/Sheet still call mutations; Analytics passes no onOffline/onOnline
   (`AnalyticsSlot.tsx:740-756`). FIX: global shell offline state → `projectArchived ||
   isOffline` on ALL mutating controls (Kanban, Sheet, Story button, limits steppers).
4. **AC6** `useProjectSse.ts:102`: offline only fires before the first open (`if (!wasOpen)`);
   a drop AFTER a prior open never sets "Verbindung verloren". FIX: set offline on `error`
   for established streams too, clear on `open`, keep reconnect re-sync on every reopen.
5. **AC8** `AnalyticsSlot.tsx:31/33/261` + rgba consts `:39-44`: loose chart hex fallbacks
   (`#48e7ff`, `#f0f0f0`) remain in the productive view. FIX: all chart colors from token
   CSS vars / owner-backed values; remove hardcoded color literals.
6. **AC1/AC3/AC4/AC5** `views.test.tsx:18`: ECharts is mocked and the feature tests don't
   assert (band test never clicks `band-toggle` / inspects options `:213-225`); NO EventSource
   tests for per-view topic subscription, reconnect re-sync, event-triggered updates, or
   no-periodic-refetch. FIX: real option-level tests (overlay, band, custom range, dataZoom,
   tooltip formatter) + EventSource lifecycle/topic/event tests per view.
7. **AC10** `kpiSse.test.ts:105`: the "real E2E" creates only a project, asserts mostly EMPTY
   KPI responses (`:131-201`) and probes only SSE headers (`:265-310`). No UI render, no KPI
   facts created, no KPI-producing DB write/read cycle, no SSE event emitted/observed, no
   re-sync-updates-view proof. FIX: persist KPI-producing data, render frontend/BFF calls,
   deliver a real SSE event, assert cards/charts/funnel update after re-fetch.

## NON-BLOCKING (not an AG3-094 defect)
- `.mcp.json` modified: PRE-EXISTING since session start (already `M` before this story; on
  the never-commit list). Not touched by AG3-094; never committed. Leave as-is.
