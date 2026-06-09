# AG3-091 — Remediation R3 (post hostile Codex review, round 3)

Scope of this remediation: `story.md` + two genuinely-wrong `status.yaml` fields
(`title`, `depends_on`). No production code, tests, concept/formal files, or other
stories' files were touched. All finding evidence was re-verified against the real code,
the FK/§ sources, the formal spec, the prototype, the story index, **and the current
AG3-100 story file** before rewriting. AG3-057 template structure preserved; ARCH-55
English wire-field discipline kept; AC count stays 9.

Only AG3-091 files written:
- `stories/AG3-091-frontend-read-models-execution-input-surface/story.md`
- `stories/AG3-091-frontend-read-models-execution-input-surface/status.yaml`
- `stories/AG3-091-frontend-read-models-execution-input-surface/remediation-r3.md` (this file)

---

## Remaining Must-Fix ERRORs (review-r3.md)

### ERROR 1 — defer-to-AG3-100 route for `next` not genuinely buildable
- **Finding (review-r3.md:10):** AG3-091 routes the missing formal `next`-Reason entity
  to AG3-100, but "current AG3-100 only scopes `GET .../execution-input/next` plus
  Triage-Begruendung and has no FK-72 §72.14.3 / `frontend-contracts.entity.*`
  requirement." Cited AG3-100 story.md:30, :47.
- **Re-verified against the CURRENT AG3-100 story:** the finding is based on a stale read.
  AG3-100 **already owns** the formal `next`-Reason entity explicitly and buildably:
  - AG3-100 §1 Ist-Zustand (`story.md:19`): "**Formale `next`-Reason-Entitaet fehlt
    (FEHLT, §70.8a.2)**" — documents the exact gap as AG3-100's own.
  - AG3-100 §2.1.5 In-Scope (`story.md:34`): "AG3-100 fuehrt die zugehoerige **formale
    Reason-/`next`-Entitaet** in `concept/formal-spec/frontend-contracts/entities.md`
    neu ein (heute fehlend) und bindet die Route per Contract-Test daran (FK-72
    §72.14.3)".
  - AG3-100 AC5 (`story.md:51`): the `next` route is "gebunden an die von AG3-100 neu
    gefuehrte formale `next`-Reason-Entitaet (Contract-Test, FK-72 §72.14.3)".
  The route is therefore genuinely buildable and owner-correct.
- **Resolution (no over-claim — AG3-100 actually delivers it):** AG3-091 §2.2 and
  Cross-Story-Voraussetzung 1 were tightened to cite AG3-100's **exact** owning anchors
  (`AG3-100/story.md:19`, `:34`, `:51`) so a reviewer can verify the prerequisite is real
  without re-deriving it. AG3-091 builds neither the surface nor the `next`-Reason fields
  and does not touch the Formal-Spec for `next`. AG3-100 was **not** edited (no foreign
  file touched); the claim now matches AG3-100's actual scope.

### ERROR 2 — AG3-091 not metadata-consistent as "read-layer only"
- **Finding (review-r3.md:12):** Body excludes `snapshot|next`, but `status.yaml` title
  still said `... + Execution-Input-Surface`, and the story index (`_STORY_INDEX.md:116`)
  still assigns AG3-091 `/execution-input/snapshot|next|limits`. Fix: align
  metadata/index naming to `... + Execution-Limits-Read`; sole `snapshot|next` owner is
  AG3-100.
- **Verified:** `status.yaml:2` title carried `Execution-Input-Surface`; the H1 in
  `story.md:1` already read `Execution-Limits-Read` (r2) — a genuine title/body mismatch.
  `_STORY_INDEX.md:116` is in `var/concept-gap-analysis/` and is **not** an AG3-091 file;
  AG3-100 already records it as Stale-Prosa (`AG3-100/story.md:25`).
- **Resolution:**
  - `status.yaml` `title` -> `... (Frontend-Read-Models + Execution-Limits-Read)` (the
    one genuinely-wrong metadata field).
  - Added an explicit **Scope-Label (read-layer only)** block at the top of `story.md`
    that names the cut, points to the authoritative story files (AG3-091 §2.2/§6 +
    AG3-100 §2.1.3-5), and records that `_STORY_INDEX.md:116` is overhauled Stale-Prosa.
  - The index is **not** edited (cross-cutting foreign file; AG3-100 already documents the
    reconciliation). No false claim is made — the story is now self-consistent and points
    to where the index discrepancy is owned.

### ERROR 3 — coverage endpoints not bound to formal entities
- **Finding (review-r3.md:14):** AG3-091 claimed all endpoints have existing formal
  entities, but `coverage/.../acceptance` and `.../are-evidence` were only "coverage
  forms"; FK-40 says their payload is `StoryAreLink` + ARE live-status, while
  `frontend-contracts.entities` only has `story_specification`/`story_evidence`, which do
  not model that payload. Fix: name the exact existing entity, or move/add the missing
  formal entity under the correct owner before implementation.
- **Verified (the finding is correct):**
  - `formal.frontend-contracts.entities` has **no** entity modelling the coverage payload.
    `story_specification` (`entities.md:341-367`) carries only the spec-tab `acceptance`
    (list of strings); `story_evidence` (`entities.md:369-394`) carries the QA-cycle
    evidence bundle. Neither models `StoryAreLink` + ARE coverage-status/evidence-paths.
  - FK-40 §40.5b.6 (`40_...:448-452`) fixes the read-API source: both endpoints consume
    "**ausschliesslich `StoryAreLink` plus ARE-Live-Status**", read-only.
  - FK-40 §40.10 (`40_...:527-544`) catalogs both endpoints as `requirements_coverage`-BC
    read-endpoints, payload anchor `StoryAreLink`, "offizieller Eintrag im API-Katalog
    liegt in FK-91"; FK-91 §91.1a (`91_...:127-128`) lists them.
  - FK-72 §72.14.3 (`72_...:445-458`) rule: a **new endpoint** requires both a FK-91
    catalog entry **and** a `formal.frontend-contracts.*` entity in the **same** change.
- **Resolution (owner-correct: AG3-091 owns it, because AG3-091 introduces the
  endpoints):** Unlike the `next`-Reason case (which belongs to AG3-100 because AG3-100
  owns the snapshot/next surface), AG3-091 is the story that introduces the two coverage
  read-endpoints. Per FK-72 §72.14.3 the missing coverage formal entity is therefore
  AG3-091's own deliverable. Changes:
  - §1 Coverage bullet (`story.md`): states the formal-entity gap explicitly, names the
    FK-40 §40.5b.6 source, and that AG3-091 introduces the entity itself.
  - §2.1 item 2 coverage sub-bullet + item 5 (Vertragsbindung): rewritten — existing
    bindings listed precisely (`execution_limits`/`project_mode_lock`/`story_counters`/
    `story_flow_snapshot`), coverage declared as the **one** owned Formal-Spec addition,
    reads `StoryAreLink` from AG3-077.
  - AC5: coverage endpoints read `StoryAreLink` + ARE-live-status (FK-40 §40.5b.6), no
    mutation, AG3-091 introduces the coverage entity + Contract-Test, no second coverage
    truth beside AG3-077's path.
  - AC8: replaced the false "all endpoints have an existing entity / no spec gap silently
    filled" with the precise split (4 existing bindings + 1 explicit owned coverage-entity
    addition; `next`-Reason stays AG3-100).
  - §5 CONTRACT guardrail: corrected from "fuehrt keine Formal-Spec-Ergaenzung durch" to
    "fuehrt genau eine Formal-Spec-Ergaenzung durch (Coverage-Entitaet)"; `next` stays
    AG3-100.
  - §6: added a coverage hint; corrected the blanket "Concept-/Formal-Dateien NICHT
    anfassen" to "Formal-Spec nur fuer die eigene Coverage-Entitaet ergaenzen (FK-72
    §72.14.3); `next`-Reason bleibt AG3-100; FK-Technical-Design-/Domain-Prosa NICHT
    veraendern."
  - Out-of-Scope + Cross-Story-Voraussetzung 2: `StoryAreLink` write-paths/ARE
    dock-points routed to **AG3-077** (owner, `_STORY_INDEX.md:78`) as a read-source
    dependency; explicitly noted the coverage **entity** is NOT an AG3-077 case but
    AG3-091's own (it owns the endpoints).

---

## status.yaml — changes
- `title`: `... (Frontend-Read-Models + Execution-Input-Surface)` ->
  `... (Frontend-Read-Models + Execution-Limits-Read)` (ERROR 2 — title/body mismatch).
- `depends_on`: added `AG3-077` (coverage endpoints genuinely consume AG3-077's
  `StoryAreLink` + ARE-live-status; previously the dependency was undeclared while the
  story claimed to read that source). Now `[AG3-090, AG3-098, AG3-100, AG3-077]`.
- `status: draft` / `phase: review_pending` unchanged (still under review).

## Code-/concept-anchor re-verification (no stale file:line)
- `service.py:109-117` project_detail aggregation (`mode_lock`/`story_counters`) — confirmed.
- `service.py:124` `derive_mode_lock`, `:156` `compute_story_counters` — confirmed.
- `views.py:44-56` `ProjectModeLock` (no `holder_count`) — confirmed.
- `execution_planning/http/routes.py:39-52` — confirmed: only dependency-graph/
  dependencies/dependency-detail/next-ready/config regexes; no `execution-input/*` route.
- `entities.md:93-110` project_mode_lock, `:116` story_counters, `:341-367`
  story_specification, `:369-394` story_evidence, `:554-651` story_flow_snapshot,
  `:728-753` execution_limits, `:669-726` snapshot/stack — confirmed; **no** coverage
  entity and **no** `next`-Reason entity exist (both gaps real).
- FK-40 `:448-452` (§40.5b.6 read-API source), `:527-544` (§40.10 catalog) — confirmed.
- FK-72 `:445-458` (§72.14.3 endpoint+entity rule) — confirmed.
- FK-91 `:127-128` (coverage), `:134` (limits GET) — confirmed.
- AG3-100 `story.md:19/:34/:51` (owns the `next`-Reason entity) — confirmed (current file).
- `_STORY_INDEX.md:78` AG3-077 (StoryAreLink owner), `:116` AG3-091 stale prosa,
  `:136` AG3-100 — confirmed.

## Routing correctness check (no false claims about other stories)
- `next`-Reason entity + snapshot/next surface -> **AG3-100**: verified that AG3-100's
  own current story explicitly scopes it (§1/§2.1.5/AC5). No over-claim.
- `StoryAreLink` write-paths + ARE-live-status -> **AG3-077**: verified that AG3-077's
  index scope (`_STORY_INDEX.md:78`) covers exactly these write-paths/dock-points. The
  coverage **formal entity** is explicitly NOT attributed to AG3-077 — it is AG3-091's own
  (AG3-091 owns the coverage read-endpoints). No story is claimed to deliver something
  outside its scope.

## Template-Treue
AG3-057 template preserved: Title/Scope-Label/Meta/Quell-Konzepte -> §1 Kontext/
Ist-Zustand (belegt) -> §2 Scope (2.1 In Scope / 2.2 Out-of-Scope mit Owner) -> §3
Akzeptanzkriterien -> §4 DoD -> §5 Guardrail-Referenzen -> §6 Hinweise + Cross-Story-
Voraussetzungen. AC count stays 9 (no AC added/removed; AC5/AC8 content corrected). DoD
"AK 1-9" unchanged. ARCH-55 English wire-field discipline kept.
