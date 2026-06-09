# AG3-093 — Remediation r1 (response to hostile Codex review `review-r1.md`)

Scope of this remediation: **only** `stories/AG3-093-frontend-app-shell-bc-views/story.md` and
`.../status.yaml` were changed. No production code, tests, concept files, or other stories'
files were touched. Prototype `frontend/prototype/` and `src/agentkit/` were read as the
normative functional source / anchor verification only.

All anchors below were re-verified against the live files (not trusted from the original draft).

---

## ERRORS (must-fix)

### MF1 — AG3-091 not modelled as hard dependency (review §2 / Must-Fix 1)
**Finding:** AC6/Scope require real BFF read-models (owned by AG3-091), but `status.yaml`
listed only AG3-090/AG3-092.
**Resolution:**
- `status.yaml` `depends_on` now includes **AG3-091** (between AG3-090 and AG3-092).
- §2.2 Out-of-Scope row for read-models now tags AG3-091 as `depends_on` and enumerates the
  owned read-models (`mode-lock`, `stories/counters`, `stories/{id}/flow`, `coverage/...`,
  `story_telemetry_summary`, `execution-input/snapshot|next|limits`) — matching AG3-091's actual
  scope (verified in `stories/AG3-091-frontend-read-models-execution-input-surface/story.md`).
- The reverse-link (`AG3-091.unblocks += AG3-093`) and the index `depends_on` cell are **routed**
  to the owner (see Cross-Story Prerequisites) — those files are outside the AG3-093 cut and were
  not edited.

### MF2 — Analytics double-ownership with AG3-094 (review §1 / Must-Fix 2)
**Finding:** AG3-093 claimed Analytics "1:1 incl. Overview/Timeseries" (`story.md:39`,`:57`) while
also declaring Charts/SSE out-of-scope to AG3-094 (`:49`); AG3-094 owns exactly that ECharts/SSE
work; the prototype `AnalyticsView.tsx` has real ECharts chart mechanics.
**Resolution:**
- §2.1.6 split: AG3-093 now delivers **only the Analytics slice structure + mount slot**
  (`contexts/kpi_analytics/`, nav entry, `#analytics` routing, `MainView` dispatch `App.tsx:782`-`:784`,
  empty slice container). The 1:1 charts/timeseries + SSE are explicitly AG3-094's on that slot.
- §2.1.3 `kpi_analytics/` bullet reworded ("KPI-Tab + Analytics-Slot/Slice-Container", not
  "Analytics-Hauptsicht").
- AC4 drops "Analytics" from the 1:1 view list; new **AC5** asserts only the slot/structure with a
  **negative check** (no `echarts`/`echarts-for-react` import, no `selectKpiDailySeries`/
  `selectProjectKpiStats` call in AG3-093's production Analytics view).
- §2.2 states "Keine Doppel-Ownership: the 1:1 chart/timeseries/SSE ACs live only in AG3-094".

### MF2b — Wrong chart library named (Chart.js) — ARCH-55 / Concept-as-Code
**Finding (corollary of MF2):** the draft and review both wrote "Charts (Chart.js)". The
normative source `frontend/prototype/src/components/AnalyticsView.tsx:15` imports
`echarts-for-react` (`:16` `import type { EChartsOption } from 'echarts'`) — the truth is **ECharts**.
AG3-094 already corrected this for itself.
**Resolution:** §2.2 now carries an explicit "Hinweis Chart-Lib" note: ECharts is the truth
(prototype = Concept-as-Code, FK-72 §72.13.4); the "Chart.js" mention in `_STORY_INDEX.md:119`
refers to the old stdlib QA-dashboard and is routed to the doc-only story **AG3-103**. AG3-093
builds no chart engine regardless.

### MF3 — Hub not decision-ready (review §1 / Must-Fix 3)
**Finding:** FK-72 §72.5 lists Hub as one of five top views; FK-72 §72.14.2 only defers its
*productive contract*. The draft posed Hub as an open question (`:50`,`:84`) instead of a concrete AC.
**Resolution:**
- New in-scope item **§2.1.11**: Hub is **decided** — ported as nav entry + `foundation/multi_llm_hub/`
  skeleton at **prototype state** (`LlmHubView` `App.tsx:1472`, fixtures `:175`-`:345`), with **no**
  real sessions, **no** `/v1/events/hub` SSE, **no** real backend.
- New **AC6**: Hub reachable/routable (`#hub`), prototype-state render smoke-test + negative check
  (no `/v1/events/hub` subscription).
- §2.2 Hub row reworded from "falls ueberhaupt" to the firm decision.
- §7 lists it under "Entschieden", no longer an open question.

### MF4 — Edge-case AC did not fully cover FK-72 §72.14.6 (review §2 / Must-Fix 4)
**Finding:** old AC7 tested only mutation-fail, stale-selected, empty-state; §72.14.6 also requires
last-request-wins, invalid-transition revert, sheet `validation_failed` draft, paused/escalated/failed
flow-state, project-switch, archived-project-disable, reconnect/offline.
**Resolution:** old AC7 expanded into **AC10 (10a–10i)**, each individually testable and anchored to the
named `formal.frontend-contracts.invariant.*`:
10a optimistic-revert+pill, 10b kanban invalid_transition revert, 10c sheet validation_failed draft,
10d stale-selected, 10e last-request-wins, 10f escalated/paused/failed flow-state, 10g empty-states,
10h project-switch (local part) + archived-project-disable, 10i limits last_writer_wins.
The **SSE-dependent** subset (reconnect re-sync, total-offline disable indicator, SSE subscription
teardown on project-switch) is correctly bounded out to **AG3-094** (which has its own AC6 for it),
because AG3-093 builds no SSE consumer.

### MF5 — Mandatory gates incomplete (review §2 / Must-Fix 5)
**Finding:** old AC9 named only local tests/lint/concept-gates; AGENTS.md requires Jenkins green,
Sonar green, and `scripts/ci/check_remote_gates.ps1` (which hard-fails on red, `:75`-`:83`).
**Resolution:** AC9 → **AC13**, now lists the exact commands incl. **Pflicht-Remote-Gates**:
`scripts/ci/check_remote_gates.ps1` green = Jenkins green (`http://localhost:9900/job/claude-agentkit3/`)
**and** Sonar Quality-Gate `OK` strict `violations=0`/`critical_violations=0`/`security_hotspots=0`
(`http://192.168.0.20:9901`), with the hard-fail anchor `check_remote_gates.ps1:75`-`:83` (verified).

### MF6 — Wrong ownership term ("Bounded Context frontend") (review §3 / Must-Fix 6)
**Finding:** header called `frontend` a "Bounded Context"; FK-72 §72.3 (Z.56) is explicit: no UI-BC,
no cockpit aggregator; cross-BC views are shell composers.
**Resolution:** header field renamed **"Modul / Layer: `frontend` — kein UI-BC"** and restructured
into (a) App-Shell R-bracket (FK-72 §72.4), (b) BC-aligned slices under `contexts/<bc>/` (BC-ownership
in the slice), (c) cross-BC composers (Inspector/Board/Sheet) composed in the shell but not a BC.

### MF7 — Open points contradicted already-set scope (review §3, second ERROR)
**Finding:** scope demanded the own layouter from `graph.ts` (`:32`,`:39`) yet an open point asked
whether to replace it (`:85`); Hub likewise open (`:84`).
**Resolution:** §7 restructured into "Entschieden":
- **Graph-Layouter DECIDED:** keep + port the own `graph.ts` layouter 1:1 (FK-72 has no layout contract;
  prototype = Soll). dagre/elk swap is explicitly out of this story's cut. §2.1.6 already states "eigener
  Layouter aus `graph.ts`" — now consistent.
- **Hub DECIDED:** see MF3.

### MF8 — `unblocks` inconsistent (review §4 / Must-Fix 7)
**Finding:** `status.yaml` had `unblocks: []` though AG3-094 (`depends_on: AG3-093`) and AG3-105 build
on AG3-093 per the index.
**Resolution:** `status.yaml` `unblocks` now lists **AG3-094** and **AG3-105** (both verified: AG3-094
`status.yaml:8-11` has `depends_on: AG3-093`; AG3-105 index row `_STORY_INDEX.md:120` `depends_on AG3-093`).

---

## WARNING

### W1 — Index source under-declared (review §4)
**Finding:** index row names only FK-72 §72.1-§72.10, but the story makes §72.13/§72.14 normative.
**Resolution:** The story genuinely **requires** §72.13 (prototype-as-truth mandate) and §72.14
(data contracts / status-mutation / edge-cases) — removing them would gut the story (no Concept-as-Code
basis, no status-dispatch/edge-case ACs). Therefore the story keeps its sources, and the index-row
widening to `FK-72 §72.1-§72.14` is **routed** to the index owner (see Cross-Story Prerequisites;
recorded in §7). The index file is not an AG3-093 artifact and was not edited. This warning is hereby
mirrored to the commissioner per the SEVERITY-SEMANTIK rule.

---

## Anchor corrections / additions (file:line, all re-verified)

- Header + sources now cite live FK-72 line ranges: §72.3 Z.56, §72.4 Z.96-117, §72.5 Z.121-137,
  §72.14.2 Z.428-434, §72.14.4 Z.460-481, §72.14.6 Z.503-595.
- Prototype anchors added/verified in §2.1.6, §2.1.11, AC5/AC6/AC7/AC9/AC12 and §6:
  `App.tsx` `App` :406, `viewFromLocationHash` :84, hash-sync :492-:503, keyboard :505-:535,
  outside-pointer :537-:550, resize :552-:577, `MainView` :709 (analytics dispatch :782-:784,
  hub dispatch :786-:788), graph ReactFlow block :790-:831, `Kanban` :853, `StorySheet` :1034 +
  `SheetCell` :1376, `LlmHubView` :1472 (+ fixtures :175-:345), `DetailInspector` :1715,
  tabs :1782/:1860/:1966, `KpiTab` heuristic :1966-:2071 (phase-split comment :1970-:1972),
  `ViewMode` :76.
- src anchor: `scripts/ci/check_remote_gates.ps1:75`-`:83` (hard-fail block) verified.
- Fixed two stray `App.tsx:1966`-§ placeholders to the real range `:1966`-`:2071`.

---

## AG3-057 template structure preserved

Sections 1–7 kept (Kontext / Scope[2.1+2.2] / Akzeptanzkriterien / DoD / Guardrail-Referenzen /
Hinweise / [Entscheidungen+geroutete Voraussetzungen]). DoD updated "AK 1–9" → "AK 1–13".

---

## Cross-Story prerequisites (genuine, routed — NOT editable from AG3-093)

These require an edit in another owner's file and are listed for the orchestrator/PO to action.
They do **not** block AG3-093 internal self-consistency.

1. **AG3-091** (`stories/AG3-091-.../status.yaml`): add `AG3-093` to `unblocks` (currently `[]`).
   AG3-093 now correctly declares `depends_on: AG3-091`; the reverse link must be made symmetric by
   the AG3-091 owner.
2. **`var/concept-gap-analysis/_STORY_INDEX.md:118`** (AG3-093 row): widen FK source from
   `FK-72 §72.1-§72.10` to `FK-72 §72.1-§72.14`; add `AG3-091` to the `depends_on` cell. (Index owner.)
3. **`_STORY_INDEX.md:119`** (AG3-094 row + line referenced by W1): the "Chart.js" wording is
   already routed to doc-only **AG3-103** by AG3-094 §7 — no new action; noted for completeness.

No claim is made that any other story delivers something outside its own scope: AG3-094 explicitly
owns Analytics charts/timeseries/SSE (its §2.1.1-§2.1.4, AC1-AC7); AG3-091 explicitly owns the
read-models/execution-input surface (its §2 + verified anchors); AG3-105 is the Task-Management UI
that builds on this shell.
