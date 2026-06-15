# AG3-093 Implementation Review r3 (Codex, sole gate) — OVERALL: REJECT

Job: job-dfabfe0f (backend codex, read-only). Date 2026-06-15.

R3 (Opus) resolved E5 (archived-project UI) + E6 (Sheet validate-before-draft), and the
architectural adjudication landed FAVORABLY. 5 ERROR remain, now sharper.

## Architecture adjudication (ACCEPTED by Codex — do NOT re-litigate)
- Two-StoryService split is real: public detail/list = `agentkit.story.service` (`app.py:1176`,
  runtime `lifecycle_status`); search + mutations = `story_context_manager` (`wire_adapter.py:44`,
  approval status). Exposing approval status on public detail/list is a foreign-owner backend
  concern → does NOT block AG3-093.
- AC14-via-public-`searchStories` is ACCEPTED in principle: search is a public BFF read path and
  can satisfy "real DB write → real DB read → back into the view" for approval status — IF the UI
  status views actually use that path.

## ERROR (round 3)
- **E1 — AC9/AC14** `Shell.tsx:135`, `client.ts:269/322`, `realShapes.fixture.ts:62`,
  `storyModel.ts:10`: board/sheet initial data comes from `listStories`, whose public status is
  runtime `lifecycle_status='defined'`, NOT the approval union `Backlog|Approved|...`.
  `normalizeStorySummary`/`listItemToStory` cast that into UI `Story.status` → type lie that
  smuggles the two-service split into UI state. FIX: source board/sheet status from the
  approval-bearing public path (`searchStories`), OR type runtime lifecycle separately and never
  feed it into `Story.status`.
- **E2 — AC9** `Shell.tsx:289`, `DetailInspector.tsx:35`, `SpecificationTab.tsx:6`,
  `EvidenceTab.tsx:15`, `client.ts:470/475`: `getStoryDetail` is fetched but spec/evidence tabs
  ignore `storyDetail.spec`/`.evidence` (render local Story + fallback prose); coverage
  read-models exist only in client/tests, never consumed. FIX: store + pass
  detail/spec/evidence/coverage into the owning tabs, render fail-closed.
- **E3 — AC9/AC10f** `FlowTab.tsx:51/64/105`, `Shell.tsx:313/318`: fetched flow hold states
  collapsed to `active`, `state_reason` discarded, local `selectStoryFlow(story)` fallback when no
  snapshot; Shell suppresses 404 flow failures. FIX: model hold states (paused/escalated/failed) +
  render `state_reason`; remove local fallback for required read-model; surface failures as pill.
- **E4 — AC14** `realBackend.test.ts:123/166`, `python_harness.py:7`: e2e creates via test-only
  `/_test/seed-story`, not `BffClient.createStory`/public `POST /v1/projects/{key}/stories`. FIX:
  prove ≥1 create→approve/reject/cancel→public read-back through the PUBLIC create path, OR
  explicitly record the public-create blocker as an out-of-scope backend conflict (don't test around it).
- **E5 — AC4/AC7/AC10** `edgeCases.test.tsx:219/232/407`, `helpers/lastRequestWinsHarness.tsx:37`:
  hollow tests remain — AC10d only a BffClient 404 assert (not Shell visible inspector-close+pill);
  AC10e a mini harness duplicating Shell logic (not real Shell); AC10h tests StorySheet draft, not
  the real project-switch warning/inspector-close/view-preservation. FIX: render real `Shell` with
  controlled transport, assert visible behavior after real UI events.

## RESOLVED at r3
- E5(r2 archived-project) RESOLVED; E6(r2 Sheet validate) RESOLVED; r2 E1 field-name normalization
  partially (URLs/field-names ok) but lifecycle-vs-approval cast remains (see E1 above).
