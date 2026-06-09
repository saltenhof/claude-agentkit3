# AG3-093 — Remediation r2 (response to hostile Codex review `review-r2.md`)

Scope of this remediation: **only** `stories/AG3-093-frontend-app-shell-bc-views/story.md`
was changed. `status.yaml` was re-examined and left unchanged (see "status.yaml decision").
No production code, tests, concept files, or other stories' files were touched. Prototype
`frontend/prototype/` and `src/agentkit/` were read as normative functional source / anchor
verification only. All anchors below were re-verified against the live files.

---

## ERROR (the single remaining must-fix)

### MF — AG3-091 falsely claimed as owner of `story_telemetry_summary` (review §"Remaining Must-Fix ERROR")

**Finding (confirmed true):** AG3-093 declared AG3-091 as owner of `story_telemetry_summary`
and made AC9 require the KPI-tab to read it from an AG3-091 read-model. Verification:

- AG3-091's actual scope (`stories/AG3-091-.../story.md:31-41`, §2.1) and its index row
  (`_STORY_INDEX.md:116`) list `mode-lock`, `stories/counters`, `stories/{id}/flow`,
  `coverage/...` and `execution-input/limits` — **not** `story_telemetry_summary` and
  **not** `story_detail`. (The `execution-input/snapshot|next` double-surface is even
  routed away from AG3-091 to AG3-100 in AG3-091 §2.2.)
- `story_telemetry_summary` is formally nested under `story_detail.telemetry`
  (`concept/formal-spec/frontend-contracts/entities.md:324`-`:327`, re-verified: line 324
  `- name: telemetry`, line 327 `target: frontend-contracts.entity.story_telemetry_summary`).
- It is delivered by the story-detail endpoint `GET /v1/stories/{id}`
  (`91_api_event_katalog.md:118`, re-verified), which is the **story_context_manager /
  story-service** surface — not an AG3-091 frontend-read-model endpoint.
- The real adapter returns `"telemetry": None` today
  (`src/agentkit/story_context_manager/http/routes.py:144`, re-verified).
- FK-72 §72.14.2 (`72_frontend_architektur.md:439`-`:443`) is explicit that this KPI-tab
  aggregate is produced from `kpi-and-dashboard` projections, embedded in `story_detail`.

So the owner claim was false. Per the review's two allowed fixes, this remediation takes
**both halves correctly**: it (a) removes the false AG3-091 attribution and (b) re-points the
story to consume only a read-model that genuinely exists, routing the still-missing telemetry
*value* to its real owners — **without** claiming any story delivers something outside its scope.

**Resolution — five edits, all in `story.md`:**

1. **§1 Kontext (line 22):** rewritten — splits the read-model sources honestly. AG3-091
   delivers the view read-models (`mode-lock`/`counters`/`flow`/`coverage`/`execution-input/limits`);
   `story_telemetry_summary` is stated to live under `story_detail.telemetry`, served by
   `GET /v1/stories/{id}`, currently `"telemetry": None` in real code, with the liefer-owner
   named as the `story_detail` producer (AG3-014) sourcing from `kpi-and-dashboard` (AG3-084),
   **explicitly not AG3-091**. Anchors: `entities.md:324`-`:327`, `91_api_event_katalog.md:118`,
   `routes.py:144`, `72_frontend_architektur.md:439`-`:443` / `:499`-`:501`.

2. **§2.1 item 8 (line 42, BFF-Anbindung):** rewritten — the inspector (incl. KPI-tab) now
   consumes the `story_detail` read-model (`GET /v1/stories/{id}`); the KPI-tab reads the
   embedded `story_detail.telemetry → story_telemetry_summary`; explicit Abgrenzung that
   AG3-093 builds no own telemetry endpoint / KPI aggregation and that the telemetry payload
   delivery is a routed cross-story prerequisite to AG3-014/AG3-084 (§7).

3. **§2.2 Out-of-Scope (line 49):** the AG3-091 row no longer lists `story_telemetry_summary`.
   It now lists exactly AG3-091's true scope (`mode-lock`/`counters`/`flow`/`coverage`/`limits`,
   anchored to `_STORY_INDEX.md:116` and AG3-091 §2.1) plus an explicit "Klarstellung
   (Codex-Review r2)" that AG3-091 does **not** own `story_telemetry_summary`/`story_detail`,
   and that snapshot/next is AG3-100's.

4. **§3 AC9 (line 65):** the KPI-tab AC now reads `story_detail.telemetry`'s
   `story_telemetry_summary` (test against a mocked `story_detail` response that includes the
   `telemetry` aggregate), plus a negative check that AG3-093 builds no own telemetry/KPI
   aggregation endpoint. The view read-models stay attributed to AG3-091.

5. **§7 Geroutete Cross-Story-Voraussetzung (new first bullet):** the `story_detail.telemetry`
   (`story_telemetry_summary`) payload is routed to its genuine owners — the `story_detail`
   producer **AG3-014** (owner of the `story_detail` wire-composition,
   `stories/AG3-014-.../story.md:386`) sourcing from **AG3-084** kpi-and-dashboard rollups
   (`_STORY_INDEX.md:90`) — with an explicit note that AG3-091 is deliberately NOT named (its
   scope excludes it) and that the prior attribution was the r2 error. The bullet states the
   story stays **internally self-consistent**: AG3-093 only consumes an already-existing
   read-model field (`story_detail` exists in real code; AG3-014 is `completed`) whose
   `telemetry` value the producer must still populate.

**No false cross-story claim made:** AG3-014 owns `story_detail` composition (verified scope +
`runtime.py` wire-composition line 386) and is the correct producer of the `telemetry` sub-field;
AG3-084 owns the KPI rollups that feed it (verified index row 90). Neither is claimed to deliver
anything beyond its own scope; the routing only asks the existing owners to populate a field they
already own the shape of.

---

## status.yaml decision (no change)

`depends_on: [AG3-090, AG3-091, AG3-092]` is correct and was left unchanged:

- **AG3-091 stays** — it genuinely owns the other view read-models AG3-093 consumes
  (`mode-lock`/`counters`/`flow`/`coverage`/`limits`). The r2 ERROR was about a *false extra*
  claim, not about AG3-091 being a non-dependency.
- **AG3-014 is NOT added as a new hard dependency** — it is `completed`
  (`stories/AG3-014-.../status.yaml:4`) and the `story_detail` endpoint already ships in real
  code (`routes.py:127-149`). The inspector's read-model source therefore already exists; only
  the nullable `telemetry` sub-field is unfilled. That is a non-blocking functional prerequisite
  (the field is `required: false` in the formal entity), correctly handled as a §7 routing note
  rather than a build-blocking `depends_on`.
- **AG3-084 is NOT added** for the same reason — softer, value-only prerequisite behind a
  nullable field; routed in §7.

`unblocks: [AG3-094, AG3-105]` unchanged (still correct).

---

## Round-1/earlier recheck

All r1-resolved items remain intact and were not regressed: Analytics container-only split from
AG3-094, ECharts naming, Hub prototype-placeholder decision, FK-72 §72.14.6 edge-case split with
honest SSE routing, remote gates in AC13, no-UI-BC framing, `unblocks` for AG3-094/AG3-105. None
of these were touched by the r2 edits (the five edits are localized to the telemetry-owner claim).

---

## Anchors added / re-verified (file:line, all checked against live files)

- `concept/formal-spec/frontend-contracts/entities.md:324`-`:327` — `story_detail.telemetry ->
  story_telemetry_summary` (verified: 324 `- name: telemetry`, 327 target line).
- `concept/technical-design/91_api_event_katalog.md:118` — `GET /v1/stories/{story_id}` story
  detail (with Telemetriebezug).
- `src/agentkit/story_context_manager/http/routes.py:144` — `"telemetry": None` (verified).
- `concept/technical-design/72_frontend_architektur.md:439`-`:443` — KPI-tab read-model from
  kpi-and-dashboard projections; `:499`-`:501` — schema = `story_telemetry_summary`, frontend
  synthesis no longer allowed.
- `stories/AG3-014-story-service-backend/story.md:386` — `runtime.py` story_detail wire-composition.
- `_STORY_INDEX.md:90` (AG3-084 dashboard-backend / KPI rollups), `:116` (AG3-091 true scope).
- AG3-091 §2.1 (`stories/AG3-091-.../story.md:31-41`) and §2.2 (snapshot/next → AG3-100).

---

## AG3-057 template structure preserved

Sections 1–7 kept (Kontext / Scope[2.1+2.2] / Akzeptanzkriterien / DoD / Guardrail-Referenzen /
Hinweise / Entscheidungen+geroutete Voraussetzungen). AC count unchanged (1–13); DoD "AK 1–13"
unchanged. ARCH-55: all edits English in code/identifier/wire terms, German prose only.

---

## Confirmation

Only `stories/AG3-093-frontend-app-shell-bc-views/story.md` was written (plus this
`remediation-r2.md`). `status.yaml` examined and left unchanged (no genuinely-wrong field). No
production code, tests, concept files, or other stories' files were modified.
