# AG3-099 — Remediation R1 (response to hostile Codex review review-r1.md)

Scope of this remediation: `story.md` + `status.yaml` only (per task constraint).
No production code, tests, concept docs, or other stories' files were touched.
All facts re-verified against FK-70 §70.7-§70.10, FK-68 §68.2.2, FK-91 §66, and the
real code under `src/agentkit/`.

---

## Must-Fix ERRORs

### MF1 — Schema-family count consistent (nine missing, ten total) [ERROR, Konzept + Klarheit]
**Finding:** Story said "acht fehlende" but FK-70 §70.10.2 lists ten families; nine are
actually missing (`dependency_edge` already exists).
**Verified:** FK-70 §70.10.2 (lines 787-797) lists exactly ten families. Code: only
`dependency_edge` (via `story_dependency_repository.py:44`) and `parallelization_config`
are persisted today.
**Resolution:** Reframed everywhere to "neun fehlend + migriertes `dependency_edge` =
zehn Schemafamilien insgesamt". Updated: Quell-Konzept §70.10.2 line, Ist-Zustand bullet
(now "neun"), Scope 2.1 #5, Scope 2.1 #7 (test count), AC6, and `status.yaml` title.
Added an explicit note that `parallelization_config` is not an own §70.10.2 family and its
consolidation is out of the AG3-099 cut (avoids a fabricated eleventh family).

### MF2 — AC6 sharpened to exactly ten round-trips + dependency_edge migration [ERROR, AC-Schaerfe]
**Finding:** AC6 said "Jede der acht Schemafamilien" then listed ten names — not testable.
**Resolution:** AC6 now mandates exactly ten round-trip tests = nine new families
(named) plus one for the migrated `dependency_edge`, with idempotency/revision binding
(§70.11 #8) retained.

### MF3 — EventTypeId scope contradiction resolved (hard precondition, no mixing) [ERROR, AC-Schaerfe]
**Finding:** In-Scope demanded emission as `EventTypeId`; Out-of-Scope deferred the enum +
emitter to AG3-081; AC7 still demanded enum coordination. Real `EventType` enum
(`telemetry/events.py:18-102`) contains none of the eight values (grep: no matches).
**Verified:** `_STORY_INDEX.md:87` — AG3-081 explicitly delivers "Acht BC14- + drei
BC15-EventTypes + Emitter". `depends_on` already lists AG3-081.
**Resolution:** Chose the clean "hard precondition" form (no Mischbetrieb):
- In-Scope #6: AG3-081 delivers the eight enum values + emitter as a hard precondition;
  AG3-099 consumes and emits/tests only, adds nothing to `EventType`, opens no second enum.
- Out-of-Scope AG3-081 bullet: rewritten to "harte Vorbedingung", cross-references
  In-Scope #6.
- AC7: emission tested against AG3-081-provided values; explicit "kein zweiter Enum".
- DoD: added hard-precondition clause (AG3-098 + AG3-081); if AG3-081's enum is missing,
  In-Scope #6 / AC7 is blocked and reported, not bypassed.

### MF4 — Ist-Zustand code anchors corrected to real write lines [ERROR/WARNING, Klarheit]
**Finding:** Anchor `routes.py:108-119 schreibt direkt` was imprecise — those lines only
wire the repos in the constructor.
**Verified:** `routes.py:108-119` = constructor repo wiring. Real writes:
`add_dependency(...)` at `routes.py:259` -> `lifecycle.py:78` (`dep_repo.add(...)`) ->
`story_dependency_repository.py:44` (`facade.save_story_dependency`); and
`config_repository.upsert(...)` at `routes.py:356` -> `parallelization_config_repository.py:27`.
**Resolution:** Ist-Zustand "Schreibpfad weicht ab" bullet + "Kontext-Sinnhaftigkeit"
paragraph + Hinweise bullet now cite these real write anchors; clarified that 108-119 is
only constructor wiring.

### MF5 — Telemetry.write_projection mapped to real ProjectionAccessor.write_projection [WARNING -> resolved]
**Finding:** FK-70 §70.10.2 says `Telemetry.write_projection`; real exported API is
`ProjectionAccessor.write_projection`.
**Verified:** No `Telemetry` class with `write_projection` exists (grep). Real API:
`projection_accessor.py:249` (`write_projection`), `:329` (`read_projection`), exported via
`telemetry/__init__.py:21`.
**Resolution:** Chose "use existing `ProjectionAccessor.write_projection`" (no new facade,
per FIX-THE-MODEL — avoids a second write surface). Mapped explicitly in: Quell-Konzept
§70.10.2 line, Ist-Zustand, Scope 2.1 #5 + #7, AC5, Guardrail-Referenzen, Hinweise.
FK-70 wording kept as the conceptual name with the mapping stated.

---

## WARNINGs

### W1 — FK-91 vs FK-68/FK-70 event-name divergence [WARNING, Konzept]
**Verified:** FK-91 §66 (lines 326-337) uses `planning_proposal_submitted`,
`planning_rulebook_compiled`, `story_became_ready`, etc. FK-68 §68.2.2 (lines 101-108)
lists the eight audit EventTypeIds.
**Resolution:** Quell-Konzept §70.10.3 line now states FK-68/FK-70 are normative for the
BC14 audit EventTypeIds, and FK-91 §66 is a separate API/SSE surface; reconciliation of the
two namespaces is concept work outside this story (see cross-story prerequisite below).
Routed, not silently absorbed — AG3-099 scope stays unchanged.

### W2 — status.yaml unblocks [WARNING, Kontext]
**Verified:** `_STORY_INDEX.md:136` lists AG3-100 `depends_on: AG3-098, AG3-099`.
**Resolution:** `status.yaml` `unblocks:` set to `[AG3-100]` (bidirectional metadata fixed).

---

## Cross-story prerequisites / routed items (NOT fixable inside AG3-099's two files)

1. **AG3-081 (hard precondition, already in `depends_on`):** owns the eight BC14
   `EventTypeId` enum values + emitter (`_STORY_INDEX.md:87`, FK-68 §68.2-§68.10). AG3-099's
   In-Scope #6 / AC7 emission work is blocked until AG3-081 delivers them. This is a genuine
   prerequisite — AG3-081's scope as written does deliver exactly these values, so the
   coupling is correct (no overclaim).

2. **`var/concept-gap-analysis/_STORY_INDEX.md:135` still says "acht fehlenden
   Persistenz-Schemafamilien".** The reviewer flagged this for synchronization, but the
   index is a shared cross-story artifact outside AG3-099's two-file edit scope. NOT edited
   here. Required follow-up: correct line 135 to "neun fehlende plus migriertes
   `dependency_edge` = zehn" by the index owner. Flagging, not silently leaving — per
   WARNING/ZERO-DEBT discipline.

3. **FK-91 ↔ FK-68/FK-70 planning-event namespace reconciliation:** the two concept docs
   carry different planning-event names. This is concept-doc work (a doc-only follow-up,
   cf. Welle-10 concept-Nachzug stories such as AG3-103 which already targets FK-91↔FK-72
   planning-path contradictions). Out of AG3-099's code cut; routed, not absorbed.

---

## Files written (AG3-099 only)
- `stories/AG3-099-planning-proposal-rulebook-persistence/story.md` (rewritten; AG3-057
  template structure preserved: header / Quell-Konzepte / 1 Kontext / 2 Scope /
  3 Akzeptanzkriterien / 4 DoD / 5 Guardrail-Referenzen / 6 Hinweise).
- `stories/AG3-099-planning-proposal-rulebook-persistence/status.yaml` (title count fixed;
  `unblocks: [AG3-100]`).
- `stories/AG3-099-planning-proposal-rulebook-persistence/remediation-r1.md` (this file).

No other files touched. ARCH-55: all schema-family names, event keys, and field names
remain English; only German concept prose retained.
