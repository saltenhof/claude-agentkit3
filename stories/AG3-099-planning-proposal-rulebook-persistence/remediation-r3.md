# AG3-099 — Remediation R3 (response to review-r3.md)

Scope of this remediation: `status.yaml` only this round (`story.md` was already
correct per review-r3.md and needed no change). No production code, tests, concept
docs, or other stories' files were touched. All facts re-verified against the REAL
code under `src/agentkit/` and FK-70 §70.10.2 (via the concept index).

---

## Remaining Must-Fix ERROR (review-r3.md)

### MF-R3-1 — Stale `status.yaml` routing text reintroduces the wrong API name [ERROR, Konzept + Klarheit + Kontext]

**Finding (verbatim core):** R2 is resolved in `story.md`, but not across the
current story package because `status.yaml:2` still titles the persistence path as
`BC-9-Projektions-Schreibpfad (ProjectionAccessor.write_projection)`. That directly
contradicts `story.md:10`, `story.md:35`, and `story.md:76`, which correctly require
an owner-separated, BC-9-hosted Planning projection write path and forbid
extending/using the FK-69 `ProjectionAccessor`.

**Verified against real code (anchors re-checked, not assumed):**
- `ProjectionKind` is an **FK-69** enum with exactly seven values
  (`telemetry/projection_accessor.py:56`): qa_stage_results, qa_findings,
  story_metrics, phase_state_projection, fc_incidents, fc_patterns,
  fc_check_proposals. None are BC14 planning tables.
- The contract test pins exactly seven and matches FK-69 table names
  (`tests/contract/telemetry/test_projection_accessor.py:32`
  `test_projection_kind_has_exactly_seven_values`, `:45`
  `test_projection_kind_values_match_fk69_tables`).
- `build_projection_accessor` builds the FK-69 accessor only
  (`composition_root.py:1419`); no planning projection surface exists in code.
- FK-70 §70.10.2 (concept index, section `70-10-...-015`): the write path runs
  "ausschliesslich ueber `Telemetry.write_projection` (BC 9, konsistent mit dem
  BC-9-Pattern aller anderen fachlichen Projektions-Schreiber)"; Schema-Owner of
  the planning tables is BC 14. `Telemetry.write_projection` is the concept name
  of the BC-9 write pattern — it is NOT the real FK-69 `ProjectionAccessor.write_projection`
  API (which `story.md:10` already pins as the FK-69 read-model boundary).

So the title must not name `ProjectionAccessor.write_projection` as the planning
write path: that API is the pinned FK-69 boundary, and AG3-099 deliberately builds
a separate, owner-separated BC-9 Planning projection write path
(`story.md` Scope 2.1 #5/#5a).

**Resolution (edit in `status.yaml`):**
- `status.yaml:2` title: replaced the wrong, contradicting fragment
  `ueber den BC-9-Projektions-Schreibpfad (ProjectionAccessor.write_projection)`
  with `ueber den eigenen BC-9-Planning-Projektions-Schreibpfad (nicht der
  FK-69-ProjectionAccessor)`. This now matches `story.md:10/35/76`: an
  owner-separated BC-9 Planning write path that does not use/extend the FK-69
  `ProjectionAccessor`. The "neun fehlende plus migriertes dependency_edge = zehn"
  framing is unchanged and stays consistent with the body.

Result: the AG3-099 package is now internally self-consistent. The wrong API name
no longer appears as the persistence *target* anywhere in the story package; the
only remaining mention of `ProjectionAccessor.write_projection` in `story.md:10` is
the correct architecture clarification that it is the FK-69 read-model boundary and
explicitly NOT the planning write path.

---

## R2 carry-over verification (review-r3.md "R2 Verification")

- FK-69 code unchanged and still correctly pinned: `ProjectionKind` = 7 values
  (`projection_accessor.py:56`), `write_projection` FK-69-scoped
  (`projection_accessor.py:249`), `build_projection_accessor` FK-69 composition
  (`composition_root.py:1419`). NOT touched by this remediation.
- `story.md` already correctly scopes Planning as its own enum/records/union/
  repos/DI/top-surface/contract-test path with fail-closed mismatch, FK-69
  seven-value contract unchanged. Confirmed by review-r3.md, re-checked, no edit
  needed.

---

## WARNINGs

review-r3.md raised no separate WARNING items beyond the single blocking ERROR
above; the per-dimension CHANGES-REQUESTED verdicts (Konzept-Vollstaendigkeit,
Klarheit, Kontext-Sinnhaftigkeit) all trace to that one stale `status.yaml` title.
Fixing the title resolves all three.

Carry-over non-blocking note (from remediation-r2.md, unchanged ownership):
`_STORY_INDEX.md:135` is the shared cross-story index. It uses the concept name
`Telemetry.write_projection` (NOT the wrong `ProjectionAccessor.write_projection`)
and still summarizes "acht … Schemafamilien". This is outside AG3-099's two-file
edit scope and owned by the index. Flagged, not silently left — required follow-up
by the index owner: correct line 135 to "neun fehlende plus migriertes
`dependency_edge` = zehn". Not edited here (would touch another owner's file).

---

## status.yaml

Other fields re-verified, all genuinely correct, no change:
- `depends_on: [AG3-098, AG3-081]` and `unblocks: [AG3-100]` match
  `_STORY_INDEX.md:135`.
- `type: implementation`, `size: L`, `phase: review_pending` accurate.
Only the title fragment was genuinely wrong and was corrected.

---

## Files written (AG3-099 only)
- `stories/AG3-099-planning-proposal-rulebook-persistence/status.yaml` (title
  fragment corrected).
- `stories/AG3-099-planning-proposal-rulebook-persistence/remediation-r3.md`
  (this file).

No other files touched. `story.md` unchanged this round (already correct; AG3-057
template structure preserved). ARCH-55: all schema-family names, kind/record/event
keys and field names remain English; only German concept prose retained.
