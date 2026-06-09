# AG3-081 — Remediation R3 (after round-3 hostile Codex review `review-r3.md`)

**Scope of this remediation:** story authoring only. Edited files: `story.md`, `status.yaml`, and this `remediation-r3.md`. **No production code, tests, or `concept/` files were touched, and no other story's files were edited.** Both remaining round-3 must-fix ERRORs were resolved by making AG3-081 self-consistent and acyclic within its own cut and routing the foreign-document wording fixes to the correct owner story. The AG3-081 cut is unchanged (BC14/BC15 EventType catalogue + mandatory-payload contract, telemetry-evidence wiring, telemetry-side `phase_state_projection` typing, `guard_invocation_counters` hot-path, reset-purge read-model half, hook-table↔code consistency).

All code anchors were re-verified against the real tree (see "Code-anchor verifications" at the end). No anchor needed correcting in this round.

---

## Round-3 Must-Fix ERROR list (from `review-r3.md` §"Remaining/New Must-Fix ERRORs")

### ERROR 1 — R2 emitter-ownership conflict still repo-wide unresolved
**Finding (review-r3 #1):** AG3-081 acknowledged the AG3-099 wording is wrong and routed it away, but the *fix instruction* asked for the canonical facts to be stated unambiguously: real enum is `EventType` (not `EventTypeId`); AG3-081 owns catalogue + mandatory-payload contract only; generic emitter infra already exists; AG3-099 owns fachliche BC14 emission; and the token "Integrity-Dim-8" must be removed from that (AG3-099) cut.

**Constraint:** AG3-081 may **not** edit `AG3-099/story.md` (foreign story file). The task rule is: make AG3-081 self-consistent and do **not** claim another story delivers something outside its scope; route the foreign-doc wording fix to its owner.

**Resolution (story §2.1.1 Owner-Klarstellung + §2.2 routing line):**
- §2.1.1 now states the canonical enum is **`EventType`** (`telemetry/events.py:18`) and that **`EventTypeId` does not exist anywhere in the code** — the AG3-099 name is factually wrong. The three-level owner split is restated verbindlich and **azyklisch**: (1) generic emitter infra = pre-existing, no story builds it; (2) `EventType` catalogue + mandatory-payload contract = AG3-081 (AG3-081 emits **no** fachliches BC14 event and builds **no** "Emitter-Infrastruktur"); (3) fachliche BC14 emission = AG3-099.
- The §2.1.1 note now spells out that the AG3-099 out-of-scope line is **factually wrong in three points**: (1) enum name; (2) "Emitter-Infrastruktur" (already exists); (3) the "Integrity-Dim-8" token does **not** belong in the AG3-081 cut (collides with the canonical FK-35 dimension `TIMESTAMP_INVERSION`). Added the explicit sentence that **AG3-081 makes no assumption that AG3-099 delivers anything outside AG3-099's scope** and is self-consistent on the pre-existing infrastructure + its own catalogue/contract.
- §2.2 routing line rewritten to enumerate the **exact** corrections the AG3-099 author run must make: (a) `EventTypeId`→`EventType` at `AG3-099 story.md:35`/`:40`; (b) replace the out-of-scope line with the canonical three-way split; (c) **delete the "Integrity-Dim-8" token** from the AG3-099 out-of-scope line. Marked doc-only, no cut/owner change.

This leaves AG3-081 unambiguous and self-consistent; the residual is a pure foreign-document wording correction owned by the AG3-099 author run (cross-story prerequisite, listed below).

### ERROR 2 — `phase_state_projection` ownership split was contradictory
**Finding (review-r3 #2):** AG3-081 said the typed record is "defined/filled at `pipeline_engine.PhaseExecutor`" **but also** routed record filling/write path to AG3-059, while AG3-059 says it owns the Pydantic schema and routes the `phase_state_projection` DB access/write wiring to AG3-081. Recommended fix: make the split explicit and acyclic — AG3-059 owns `PhaseStateCore` schema; AG3-081 owns the projection adapter/wiring and tests that the operational projection is **typed** (not only that `projection_records.py` has no `dict[str, object]`).

**Resolution (story title/BC line, §1 ownership bullet, §1 anknuepfung, §2.1.5, §2.2, AC4, §5, §6, status.yaml):** Established a single, verbindliche, azyklische owner split — **AG3-024 → AG3-059 → AG3-081**:
- **Pydantic schema of the record** (`PhaseStateCore`/`PhaseState`, FK-39 §39.7) = **AG3-059**. AG3-081 **does not define and does not fill** the record type.
- **Write path** (fill + persist `phase_state_projection` rows, FK-69 §69.4) = `pipeline_engine.PhaseExecutor`. ProjectionAccessor stays a fail-closed refusal for `PHASE_STATE_PROJECTION` (`projection_accessor.py:105-111` / `:398-403`) — no ownership migration, no second write-truth.
- **Telemetry-side projection-union adapter + typedness proof** = **AG3-081** (this story): `projection_records.py` union references the AG3-059 record instead of `dict[str, object]`; AC4 now requires a test that the **operative projection surface is typed** (the union resolves to the AG3-059 record), beyond merely asserting no `dict[str, object]` remains.
- §2.1.5 was rewritten from "Der Record-Typ wird daher **beim Pipeline-Owner** definiert/befuellt … Hier wird der typisierte Record-Typ **bereitgestellt**" (which contradicted AG3-059) to "AG3-081 **definiert diesen Typ nicht** und befuellt ihn nicht … referenziert den AG3-059-Record".
- §2.2 out-of-scope line for `phase_state_projection` now puts **both** record definition (schema) and write path out of scope (owners AG3-059 + PhaseExecutor); AG3-081 only re-types the telemetry union.
- The title/BC line, §1 ownership bullet, §1 anknuepfung, §5 guardrail line and §6 hint were all aligned to the same split.
- **status.yaml:** added `AG3-059` to `depends_on` (AG3-081 consumes the AG3-059-owned record → genuine prerequisite; keeps the dependency edge acyclic since AG3-059 depends on AG3-024, not on AG3-081).

---

## WARNINGS
`review-r3.md` raises **two** numbered items, both classified as **ERROR**. The per-dimension scorecard (Konzept-Vollstaendigkeit FAIL, AC-Schaerfe WEAK, Klarheit FAIL, Kontext-Sinnhaftigkeit WEAK) is the summary, not separate findings; the two ERRORs above are the actionable must-fixes and both are resolved. No standalone WARNING was raised in round 3.

---

## Code-anchor verifications applied/re-checked in story.md (round 3)

| Claim in story | Reality (re-verified this round) | Status |
|---|---|---|
| Canonical enum is `EventType` (not `EventTypeId`) | `class EventType(StrEnum)` at `telemetry/events.py:18`; grep `EventTypeId` → no hit in `src/agentkit` | confirmed |
| `are_gate_result` only as payload-pinning, not enum member | `MANDATORY_PAYLOAD_FIELDS_BY_NAME["are_gate_result"]` at `events.py:231`; not in `EventType` enum | confirmed |
| Generic emitter infra exists | `EventEmitter` `emitters.py:19`, `StateBackendEmitter` `storage.py:23` | confirmed |
| `phase_state_projection` is `dict[str, object]` in the union | `projection_records.py:36-37` comment + union `:41-43` (no phase-state record type) | confirmed |
| Accessor fail-closed for `PHASE_STATE_PROJECTION` | externally-owned map `projection_accessor.py:105-111`; refusal `:398-403` | confirmed |
| Write-owner = `pipeline_engine.PhaseExecutor` | `_EXTERNALLY_OWNED_KINDS[PHASE_STATE_PROJECTION]` names it (`:106-108`); purge best-effort `:474-484` | confirmed |
| Schema-owner of `PhaseStateCore` = AG3-059 | `AG3-059 story.md:5` BC line + §2.1.4/§2.2; `_STORY_INDEX.md` Z. 45 | confirmed |
| AG3-103 is the doc-only owner with FK-68 §68.2 in scope | `_STORY_INDEX.md` Z. 144 (doc-only, FK-68 §68.2 listed) | confirmed |
| `run_hook` dispatch + six dedicated branches | `governance/runner.py:536` (run_hook); capability `:575`, review_guard `:589`, budget_event_emitter `:591-592`, self_protection `:605-606`, story_creation_guard `:607-608`, ccag_gatekeeper `:611-612`, generic `evaluate_pre_tool_use` `:614-616` | confirmed (within ±1 line of the stored anchors) |
| `check_all()` runs four rules | `telemetry_contract.py:278-286` (four `RuleResult`s) | confirmed |
| FK-68 §68.4 six proofs | `68_…md` §68.4 table Z. 570-577 (six rows) | confirmed |

## status.yaml change (round 3)
- `depends_on` changed from `[AG3-035, AG3-037]` to `[AG3-035, AG3-037, AG3-059]` (AG3-081 consumes the AG3-059-owned `PhaseStateCore` record for the projection union). No other field changed (`type: implementation`, `size: L`, `phase: review_pending`, `unblocks: [AG3-082, AG3-099]`, `title` remain consistent with `_STORY_INDEX.md`).

## Genuine cross-story prerequisites / hand-offs
1. **AG3-059 (depends_on, now wired):** AG3-081 needs the typed `PhaseStateCore`/`PhaseState` record from AG3-059 to re-type the telemetry projection union. Edge added to AG3-081 `status.yaml`. AG3-059's own `unblocks: []` is in the AG3-059 file (foreign — not edited here); when AG3-059 is authored/updated it should reflect `unblocks: …AG3-081`. **This is a foreign-file follow-up, flagged for the AG3-059 author run, not actioned here.**
2. **AG3-099 wording correction (doc-only, foreign file):** the AG3-099 out-of-scope line must be fixed (`EventTypeId`→`EventType`; "Emitter-Infrastruktur — AG3-081" → canonical three-way split; delete "Integrity-Dim-8"). Owner = **AG3-099 author run**. Routed in AG3-081 §2.2; **not actioned here** (AG3-081 may not edit foreign story files). No AG3-081 cut depends on this beyond the already-existing `unblocks: AG3-099` edge.

## Note (unchanged; flagged, out of "story.md/status.yaml only" scope)
The story **directory name** still contains `…-integrity-dim8` and the `_STORY_INDEX.md` AG3-081 title row (Z. 87) still reads "Integrity-Dim-8-Wiring". Both are outside the "story.md/status.yaml only" edit scope and left untouched; the canonical `story.md` title/text use only "Telemetry-Evidence-Block (FK-68 §68.4)". The `story_id` (AG3-081) is unaffected.
