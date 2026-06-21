# AG3-093 Implementation Review r2 (Codex, sole gate) — OVERALL: REJECT

Job: job-8712c630 (backend codex, read-only). Date 2026-06-15.

R2 fixed the surface (project-scoped URLs, KPI telemetry, Kanban validate, slice
imports, search dispatch, CSS tokens) but left the deeper wiring. 4/10 r1 items
RESOLVED; 6 ERROR remain/new.

## r1 mapping
- ERROR1 RESOLVED (project-scoped URL paths) — but NEW data-shape mismatch (see E1 below).
- ERROR2 NOT-RESOLVED (read-models still not consumed).
- ERROR3 RESOLVED (detail fetch + KPI telemetry).
- ERROR4 NOT-RESOLVED (e2e readback bypasses public path).
- ERROR5 RESOLVED for Kanban — but NEW Sheet invalid-local-status (see E6).
- ERROR6 NOT-RESOLVED (fail-open reads).
- ERROR7 NOT-RESOLVED (hollow tests).
- MAJOR8 RESOLVED. MAJOR9 RESOLVED (dispatch). MAJOR10 RESOLVED.

## ERROR (round 2)
- **E1 — AC9/AC14 response-shape mismatch** `client.ts:68` + `Shell.tsx:48`:
  `StoryListItem`/`toStory()` read `id/type/size/status`, real models expose
  `story_id/story_type/story_size/lifecycle_status` (`src/agentkit/story/models.py:65-73`).
  Search returns `story_id/repos/change_impact/concept_quality` from
  `story_to_wire_summary` (`src/agentkit/story_context_manager/wire_adapter.py:44`).
  Real backend data maps to undefined/broken UI. Fix: normalize list/search responses
  like detail is adapted; tests use REAL backend-shaped payloads.
- **E2 — AC9** `Shell.tsx:136`: initial/project reload fetch only `listStories` +
  `getExecutionLimits`; `getStoryCounters`/`getModeLock`/`getStoryFlow`/
  `getCoverageAcceptance`/`getCoverageAreEvidence` NOT wired. Counters/mode still local
  (`Shell.tsx:329-330`); Flow renders from local Story (`DetailInspector.tsx:36`).
- **E3 — AC14** `realBackend.test.ts:153`: persistence proof reads via `/_test/story-status`
  (`python_harness.py:80` → `story_context_manager.service.StoryService`), NOT the public
  `GET /v1/projects/{key}/stories/{id}` (`app.py:1176` → `agentkit.backend.story.service.StoryService.get_story`).
  Test admits seeded stories not visible via public getStoryDetail (`realBackend.test.ts:188`).
  Proves internal service write/read, not the UI-required public BFF read path. Fix: assert
  persisted status through `BffClient.getStoryDetail`/`listStories` against the real app, with
  seeding that populates the PUBLIC read model (investigate the two-StoryService split).
- **E4 — AC10/FAIL-CLOSED** `Shell.tsx:138/177/224`: `getExecutionLimits` `.catch(()=>null)`,
  `listProjects` silent default fallback, `searchStories` silent clear. Required reads fail open.
- **E5 — AC10h** `Shell.tsx:163`: project metadata reduced to names, discards `status` →
  archived projects can't disable mutating UI; no draft-loss warning (`:453`); no disabled
  state (`:523`).
- **E6 — AC8** `StorySheet.tsx:216`: inline status edit writes local draft before validating;
  unsupported transition leaves `endpoint=null` (`:235`), no error/revert → local-only invalid
  draft. Fix: share Kanban transition matrix, validate before draft, failure pill.
- **E7 — AC4/AC7/AC10** `edgeCases.test.tsx:102`: hollow tests remain — AC10a only tests
  BffClient ("DI won't work easily" `:103`), AC10e local counter (`:232`), AC10h local boolean
  (`:341`), AC10i local string (`:362`). `shell.test.tsx:197` never asserts `searchStories`
  called. `views.test.tsx:242/247` only import Execution views. Fix: render real components +
  assert visible behavior after real events for every AC10a-10i and AC4 interaction.
