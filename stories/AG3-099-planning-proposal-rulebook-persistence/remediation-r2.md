# AG3-099 — Remediation R2 (response to review-r2.md)

Scope of this remediation: `story.md` only (per task constraint). `status.yaml`
needed no field change (re-verified). No production code, tests, concept docs, or
other stories' files were touched. All facts re-verified against the REAL code
under `src/agentkit/` and FK-70 §70.7-§70.10 (via concept index).

---

## Remaining Must-Fix ERROR (review-r2.md)

### MF-R2-1 — AG3-099 not buildable against the real ProjectionAccessor contract [ERROR, Konzept + AC-Schaerfe + Kontext]

**Finding (verbatim core):** The story said the ten BC14 schema families are
created as `ProjectionKind` + `ProjectionRecord` and written via
`ProjectionAccessor.write_projection`, but the real code pins `ProjectionKind`
to exactly seven FK-69 values and a contract test enforces exactly seven;
`write_projection` only maps accessor-owned FK-69 kinds, not planning records.
The story must explicitly scope the BC-9 projection registry/accessor expansion
or split needed for BC14-owned planning tables (record union/registry, schema
adapters, `ProjectionRepositories`, contract-test handling) instead of an
implicit "add ProjectionKind values" that breaks the pinned FK-69 contract.

**Verified against real code (anchors re-checked, not assumed):**
- `ProjectionKind` is an **FK-69** enum with exactly seven values
  (`telemetry/projection_accessor.py:56-71`): qa_stage_results, qa_findings,
  story_metrics, phase_state_projection, fc_incidents, fc_patterns,
  fc_check_proposals. None are BC14 planning tables.
- Contract test pins exactly seven (`tests/contract/telemetry/test_projection_accessor.py:32`
  `test_projection_kind_has_exactly_seven_values`, and `:45`
  `test_projection_kind_values_match_fk69_tables`).
- `write_projection` (`projection_accessor.py:249`) only handles
  `_ACCESSOR_OWNED_KINDS` (`:85`) and the lazy `_build_kind_to_record_type`
  map (`:190`); everything else is fail-closed via
  `ProjectionKindNotAccessorOwnedError`. No planning kinds/records.
- `ProjectionRecord` union (`telemetry/projection_records.py:41`) =
  QAStageResultRecord | QAFindingRecord | StoryMetricsRecord | Incident — all
  FK-69, no planning records.
- `ProjectionRepositories` DI bundle
  (`state_backend/store/projection_repositories.py:240`) bundles only FK-69
  repos (qa_*, story_metrics, phase_state_projection, qa_layer_batch,
  fc_incidents, risk_window).
- `build_projection_accessor` (`composition_root.py:1419`) builds the FK-69
  accessor only; no planning projection surface exists in code.
- `_STORY_INDEX.md:87` (AG3-081) covers FK-69 §69.3/§69.9/§69.14 read-models +
  a typed `phase_state_projection`-Record + Reset-Purge chain + the eight BC14
  EventType enum values + emitter — it does **NOT** own the BC14 *planning*
  projection registry/accessor expansion. `_STORY_INDEX.md:135` assigns "die …
  Persistenz-Schemafamilien über `Telemetry.write_projection`" to **AG3-099**.
  So this expansion is genuinely AG3-099's own work — it cannot be routed away.

**Design decision (FIX THE MODEL, stays inside the AG3-099 cut):**
Two options were considered:
- (A) extend the FK-69 `ProjectionKind`/`ProjectionRecord`/`ProjectionRepositories`
  and rewrite the pinned contract test to N values. Rejected: FK-69 §69.3 is
  normative for **FK-69 read-models**; the ten BC14 planning tables are not
  FK-69 read-models. Folding them into the FK-69 enum breaks a pinned foreign
  contract and conflates two BC vocabularies (NO ERROR BYPASSING, FIX THE MODEL).
- (B, chosen) AG3-099 builds its **own BC-9-hosted Planning projection write
  path** following the same BC-9 DI pattern (as FK-70 §70.10.2 actually requires:
  "konsistent mit dem BC-9-Pattern aller anderen fachlichen Projektions-Schreiber"),
  but owner-separated: a Planning kind-enum (ten BC14 families), typed per-family
  records + a Planning record union with fail-closed type-mismatch, thin
  schema/repository adapters + a Planning DI bundle wired in the composition root
  (analogous to `build_projection_accessor`), a Planning write/read top-surface,
  and its **own** contract test pinning the ten Planning families. The existing
  FK-69 contract test stays unchanged at exactly seven.

**Resolution (edits in `story.md`):**
- Quell-Konzept §70.10.2 line: added the architecture clarification that the
  real `ProjectionAccessor.write_projection` is the FK-69 read-model boundary
  (pinned to 7 by contract test), is NOT the planning write path, and that
  AG3-099 builds an owner-separated BC-9 planning projection write path.
- Ist-Zustand §1: replaced the "target API = `ProjectionAccessor.write_projection`"
  framing with a new "Kein BC-9-Planning-Schreibpfad vorhanden (FEHLT)" bullet
  that cites the seven-value pin (`:56`), the contract test (`:32`),
  `_ACCESSOR_OWNED_KINDS` (`:85`), `_build_kind_to_record_type` (`:190`), the
  record union (`projection_records.py:41`) and the repo bundle
  (`projection_repositories.py:240`) — and states the FK-69-contract-breaking
  consequence explicitly.
- Kontext-Sinnhaftigkeit: rewritten to state the planning write path is
  deliberately separate from the FK-69 accessor and why (FIX THE MODEL).
- Scope 2.1 #5: reframed onto the BC-9 Planning projection write path + explicit
  negative boundary ("FK-69 `ProjectionAccessor` NOT used/extended").
- Scope 2.1 **#5a (new)**: enumerates the concrete buildable expansion inside the
  AG3-099 cut — Planning kind-enum, typed records + Planning record union with
  Kind->Record mapping + fail-closed mismatch, thin schema/repository adapters +
  Planning DI bundle wired in the composition root, Planning write/read
  top-surface, and a dedicated Planning contract test; explicitly keeps the FK-69
  contract test unchanged at seven.
- Scope 2.1 #7 (tests): round-trip + new Planning contract-test now target the
  Planning write path, not `ProjectionAccessor.write_projection`.
- AC5: now requires the dedicated Planning projection write path to exist
  (enum+union+DI bundle+composition-root wiring+top-surface) plus the Planning
  contract test, and that the FK-69 contract test stays green at seven.
- AC6: round-trips run over the Planning projection write path.
- Guardrail-Referenzen (FIX THE MODEL): rewritten to the owner-separated path;
  no FK-69-accessor misuse.
- Hinweise: explicit "do NOT extend the FK-69 ProjectionKind/ProjectionRecord/
  ProjectionRepositories" with the real anchors, build the parallel Planning
  pendant via the composition-root pattern.

Result: AG3-099 is now buildable against the real code without breaking the
pinned FK-69 §69.3 seven-table contract, and the persistence work stays entirely
within AG3-099's cut (per `_STORY_INDEX.md:135`).

---

## Non-blocking note (review-r2.md)

`_STORY_INDEX.md:135` still summarizes "acht fehlenden … Schemafamilien". This is
a shared cross-story index outside AG3-099's two-file edit scope (already routed
in remediation-r1.md item #2). The R2 review itself classifies it non-blocking and
confirms the current `story.md`/`status.yaml` are internally corrected. NOT edited
here (would touch another owner's file); flagged, not silently left — required
follow-up: index owner corrects line 135 to "neun fehlende plus migriertes
`dependency_edge` = zehn".

---

## status.yaml

Re-verified; no field is genuinely wrong. `depends_on: [AG3-098, AG3-081]` and
`unblocks: [AG3-100]` match `_STORY_INDEX.md`. Title still accurately reflects the
"neun fehlend + migriertes dependency_edge = zehn" framing and the BC-9 write
path. No edit needed.

---

## Files written (AG3-099 only)
- `stories/AG3-099-planning-proposal-rulebook-persistence/story.md` (rewritten
  sections; AG3-057 template structure preserved: header / Quell-Konzepte /
  1 Kontext / 2 Scope / 3 Akzeptanzkriterien / 4 DoD / 5 Guardrail-Referenzen /
  6 Hinweise).
- `stories/AG3-099-planning-proposal-rulebook-persistence/remediation-r2.md`
  (this file).

No other files touched. ARCH-55: all schema-family names, kind/record/event keys
and field names remain English; only German concept prose retained.
