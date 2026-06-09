# AG3-091 — Remediation R2 (post hostile Codex review, round 2)

Scope of this remediation: `story.md` + one genuinely-wrong `status.yaml` field.
No production code, tests, concept files, or other stories' files were touched.
All finding evidence was re-verified against the real code, the FK/§ sources, the
formal spec, the prototype, and the story index before rewriting. AG3-057 template
structure preserved; ARCH-55 English wire-field discipline kept.

Both remaining must-fix ERRORs from `review-r2.md` are resolved by **one** consistent
cut decision: the living Execution-Input double-surface (`snapshot`/`next`) and its
single deterministic selector are **fully owned by AG3-100** (execution-planning BC
author, `_STORY_INDEX.md:136`, FK-70 §70.8a.3). AG3-091 stops building them and is
narrowed to the genuine frontend-read-layer: `execution-input/limits` (read-only) plus
the pure read-models (`mode-lock`, `stories/counters`, `stories/{id}/flow`,
`coverage/...`). Removing `snapshot`/`next` from AG3-091 eliminates ERROR 1 (no
`next` reason fields here at all) and ERROR 2 (no duplicate selector/endpoint
ownership) at the same time.

---

## Remaining Must-Fix ERRORs (review-r2.md)

### ERROR 1 — `execution-input/next` reason fields without a formal entity
- **Finding (review-r2.md:12-13):** AG3-091 still planned to ship typed `next` reason
  fields, but `formal.frontend-contracts.entities` has no `execution_input_next`/reason
  entity; binding only the returned story to `story_summary`/snapshot does not satisfy
  FK-72 §72.14.3 for the full `next` response payload. Reviewer's accepted fixes:
  either depend on the AG3-100 formal entity before implementing `next`, or
  remove/defer `next` reason fields from AG3-091.
- **Verified:** `formal.frontend-contracts.entities` contains only
  `execution_input_snapshot` (`entities.md:669-706`), `execution_input_stack`
  (`entities.md:708-726`), `execution_limits` (`entities.md:728-753`) — no
  `execution_input_next`/reason entity. FK-72 §72.14.3 (`72_frontend_architektur.md:445-458`)
  mandates an Entity/Command per new endpoint. FK-91 §91.1a lists `next`
  (`91_api_event_katalog.md:115`) bound to FK-70 §70.8a.2.
- **Resolution (defer route chosen, cleaner than dependency-on-spec route):** AG3-091
  no longer ships `next` (or its reason fields) at all. `next` is moved entirely to its
  real owner AG3-100, which also carries the formal reason-entity addition. AG3-091
  contains **zero** endpoints without an existing formal entity (`execution_limits`,
  `project_mode_lock`, `story_counters`, `phase-state-projection`/`coverage` forms all
  exist). New AC8 asserts no AG3-091 endpoint lacks a formal binding and that no
  Formal-Spec gap is silently filled. The missing reason-entity is routed to AG3-100 as
  a cross-story prerequisite (§2.2, §6, Cross-Story-Voraussetzung 1) — AG3-091 does not
  touch the Formal-Spec.

### ERROR 2 — AG3-091 and AG3-100 both own `snapshot`/`next` + the same single selector
- **Finding (review-r2.md:14-15):** Both stories owned the same `snapshot`/`next`
  endpoints and the same "one deterministic selector," violating the single-owner /
  single-selector rule (FK-70 §70.8a.3, "Doppel-Implementierung unzulaessig"). Not
  buildable with duplicate ownership. Reviewer's fix: one story owns the
  selector/endpoints, the other explicitly consumes/reuses it, with status dependencies
  aligned.
- **Verified:** `_STORY_INDEX.md:136` assigns AG3-100 "lebende Execution-Input-Doppel-
  Surface (snapshot/next)" + the single selector + `evaluate_scheduling`. AG3-100's own
  story (`AG3-100/story.md` §2.1.3-5, §3.3-5) builds exactly one deterministic selector
  and both surface variants. FK-70 §70.8a.3 (`70_...:701-718`) requires both variants to
  derive from one selector. AG3-100 is the execution-planning BC author; FK-70 §70.8a is
  its core domain. The previous AG3-091 wording had it building the same selector +
  endpoints — a true duplicate-ownership conflict.
- **Resolution:** AG3-100 is named the **sole owner** of the selector and both
  endpoints; AG3-091 becomes an explicit **consumer/read-layer** (Frontend/Skill) and
  builds neither. Single-owner restored. Status dependency aligned: `status.yaml`
  `depends_on` gains `AG3-100` (AG3-091 now genuinely consumes AG3-100's surface; the
  previous `[AG3-090, AG3-098]` no longer reflected the real dependency on the surface
  owner). New AC6 proves AG3-091 creates neither `snapshot`/`next` nor a second triage
  selector. §1, §2.1.3, §2.2, §5, §6 all state the cut and warn the implementer to stop
  and report if it looks like AG3-091 must build snapshot/next.

---

## Code-anchor re-verification (no stale file:line)
- `service.py:124-153` `derive_mode_lock` — confirmed (real impl read).
- `service.py:156-217` `compute_story_counters` — confirmed.
- `service.py:109-117` `project_detail` aggregation — confirmed.
- `execution_planning/http/routes.py:39-52` — confirmed: only
  `dependency-graph`/`dependencies`/`next-ready`/`config` regexes; **no**
  `execution-input/*` route exists in code (consistent with AG3-100 still being unbuilt).
- `views.py:44-95` (`ProjectModeLock` `:44-56`, counters models) — referenced as before.
- `entities.md:669-753` (snapshot/stack/limits), `93-110` (project_mode_lock),
  `invariants.md:108-122` (mode_lock_derived), `91_api_event_katalog.md:114-115`
  (snapshot/next), `:127-128` (coverage), `:134` (limits GET) — confirmed.

## status.yaml — change
Changed: `depends_on` now `[AG3-090, AG3-098, AG3-100]`. Rationale: with `snapshot`/`next`
deferred to AG3-100 and AG3-091 reduced to consuming that surface, the dependency on the
surface owner (AG3-100) is now genuine; omitting it left the story claiming to consume an
artifact with no declared upstream owner. `status: draft` / `phase: review_pending` remain
correct (story still under review, not merged). No other field changed.

## Template-Treue
AG3-057 template preserved: Title/Meta/Quell-Konzepte -> §1 Kontext/Ist-Zustand (belegt)
-> §2 Scope (2.1 In Scope / 2.2 Out-of-Scope mit Owner) -> §3 Akzeptanzkriterien ->
§4 DoD -> §5 Guardrail-Referenzen -> §6 Hinweise + Cross-Story-Voraussetzungen.
AC count reduced 13 -> 9 (the four snapshot/next/triage ACs removed with their scope);
DoD adjusted to "AK 1-9".

## Routing correctness check (no false claims about other stories)
AG3-100's own story (`AG3-100/story.md` §2.1.3-5, §3.3-5, §6) **does** deliver the single
selector + snapshot + next + the machine-readable triage reason. Routing the formal
reason-entity and the surface to AG3-100 therefore matches AG3-100's actual scope — no
over-claim. The doc-only FK-70 §70.8a.5 path-name alignment remains a Welle-10
(AG3-101..104 class) doc-only follow-up, outside AG3-091's code cut.

## Genuine cross-story prerequisites (routed to owners)
1. **Execution-Input double-surface (snapshot/next) + single selector + formal reason
   entity** — Owner **AG3-100** (`_STORY_INDEX.md:136`; FK-70 §70.8a.3; FK-72 §72.14.3).
2. **Doc-only FK-70 §70.8a.5 prose alignment** (`ready-set`/`execution-plan` ->
   project-scoped `next-ready` etc.) — Welle-10 doc-only, outside the AG3-091 code cut.
