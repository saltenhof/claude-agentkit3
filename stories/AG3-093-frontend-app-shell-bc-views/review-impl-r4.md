# AG3-093 Implementation Review r4 (Codex, sole gate) — OVERALL: REJECT

Job: job-63ebb44e (backend codex, read-only). Date 2026-06-16.

ALL FIVE r3 ERRORs RESOLVED. Only ONE finding remains (ARCH-55, mechanical).

## R3 ERROR verification — all RESOLVED
- E1 RESOLVED: `StoryStatus` approval-only (`storyModel.ts:10`); runtime separate `executionLifecycle`
  (`storyModel.ts:68`). `normalizeSearchSummary` maps approval `status` only (`client.ts:342`);
  `normalizeListSummary` maps `lifecycle_status`→`executionLifecycle` only (`client.ts:352`). Board/sheet
  via `listStories`→search `q=%` (`client.ts:525`); confirmed match-all against real SQL LIKE
  (`story_repository.py:672`).
- E2 RESOLVED: Shell fetches detail+coverage (`Shell.tsx:304/340`); inspector passes spec/evidence/
  coverage-acceptance/are-evidence (`DetailInspector.tsx:67`); tabs render fetched models with empty
  states (`SpecificationTab.tsx:39`, `EvidenceTab.tsx:39`).
- E3 RESOLVED: FlowTab renders only `flowSnapshot`/`flowError`, no story fallback (`FlowTab.tsx:111`);
  hold states preserved (`:39`); `state_reason` rendered (`:224`); Shell surfaces flow failures
  (`Shell.tsx:332`); backend flow carries `state_reason` (`views.py:129`).
- E4 RESOLVED: E2E uses public `BffClient.createStory` (`realBackend.test.ts:111`), public
  approve/reject/cancel + public search read-back (`:175`), negative no-evidence 422 (`:211`); harness
  bypass endpoints REMOVED (`python_harness.py:7`); reconciliation evidence typed+consistency-validated
  (`reconciliation_evidence.py:83`).
- E5 RESOLVED: `shellEdgeCases.test.tsx` renders the real Shell — AC10d (`:93`), AC10e (`:135`),
  AC10h (`:209`); old mini-harness absent.

## ERROR (round 4) — sole remaining
- **ARCH-55** `store/storyModel.ts:1` ("Story-Datenmodell…"), `components/FlowTab.tsx:2`, and other
  productive frontend files: production source COMMENTS/prose are still German. ARCH-55 allows German
  only for UI labels; code comments/prose must be English. FIX: translate all non-UI comments/prose in
  productive frontend source to English; keep German ONLY in rendered UI-label strings/resources.
