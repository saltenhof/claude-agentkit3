# AG3-093 Implementation Review r1 (Codex, sole gate) — OVERALL: REJECT

Job: job-c895d3f3 (backend codex, read-only). Date 2026-06-15.

R1 was a structural re-organization of the monolith with self-stubbed tests;
NOT wired to the real backend. 7 ERROR + 3 MAJOR.

## ERROR
1. **AC9/AC14** `frontend/prototype/src/foundation/bff/client.ts:75` — BFF client calls
   bare `/v1/stories/{id}` and mutation paths. Real router only exposes
   `/v1/projects/{project_key}/stories/...` (`src/agentkit/control_plane_http/app.py:83`, `:597`).
   These 404 against the real BFF. Fix: project-scoped URLs in all story client methods.
2. **AC9** `app_shell/layout/Shell.tsx:16` — imports `STORY_FIXTURES as initialStories`,
   inits all view state from fixtures (`:71`); counters/mode computed locally (`:172`).
   No initial GETs for `mode-lock`, `stories/counters`, `stories/{id}/flow`, `coverage/...`,
   `execution-input/limits` despite real routes at `read_model_routes.py:68`.
3. **AC9** `Shell.tsx:134` — story detail fetched only to catch 404; success discarded.
   `DetailInspector` still gets fixture `Story` (`:431`). `KpiTab` reads `story.telemetry`
   (`contexts/kpi_analytics/KpiTab.tsx:5`), not fetched `story_detail.telemetry`.
4. **AC14** `__tests__/e2e/realBackend.test.ts:20` — all E2E skipped unless `BACKEND_BASE_URL`;
   instantiate only `BffClient` (`:28`), not UI nor `ControlPlaneApplication`, via broken bare endpoints.
5. **AC8** `app_shell/board/Kanban.tsx:157` — optimistic status change before validating
   transition; unsupported drops return "local-only" (`:170`) leaving invalid states
   (Backlog→Done) in UI without backend mutation or revert.
6. **AC10/FAIL-CLOSED** `Shell.tsx:147` — non-404 detail fetch errors "silently ignored
   for the prototype" = fail-open. Surface error pill/state.
7. **AC4/AC7/AC10/AC13** `__tests__/edgeCases.test.tsx:84` — edge tests are self-stubbed
   structural asserts (local request-id `:85`, local project-switch var `:117`, local
   last-write-wins `:130`). `views.test.tsx:24` only renders the analytics slot. No real
   interaction tests for Graph/Kanban/Sheet/Execution-Input/Limits, shell keyboard/outside/search,
   AC10 behaviors.

## MAJOR
8. **AC2** `DetailInspector.tsx:6` — FlowTab imported from `components/FlowTab`, not
   `contexts/pipeline_engine`. Execution-Input/Limits imported from generic `components`
   (`Shell.tsx:28`). Move/wrap into owning BC slices.
9. **AC7** `Shell.tsx:94` — global search is a local fixture filter over `storyState`,
   not a BFF/cross-BC dispatch.
10. **AC11** `styles.css:2073` — literal font sizes (`:2468`, `:2475`, `:2553`, …) and
    ad-hoc hex outside token definitions (`:110`, `:259`). Replace with AG3-092 tokens.
