# AG3-099 — Remediation R4 (response to review-r4.md)

Scope of this remediation: `story.md` only this round. `status.yaml` was
re-checked and is genuinely correct (its title concerns the BC-9 Planning
projection write path and schema families — it carries no `EventTypeId` /
emitter / `Integrity-Dim-8` token), so it needed no change. No production code,
tests, concept docs, or other stories' files were touched. All telemetry facts
re-verified against the REAL code under `src/agentkit/telemetry/`.

---

## Remaining Must-Fix ERROR (review-r4.md)

### MF-R4-1 — Stale `EventTypeId` type name + wrong AG3-081 deliverable framing + stale `Integrity-Dim-8` token [ERROR, Konzept + Klarheit + Kontext]

**Finding (verbatim core):** AG3-099 still used `EventTypeId` (real type is
`EventType`, `events.py:18`) and said AG3-081 delivers "Emitter-Infrastruktur";
the generic emitter infra already exists (`emitters.py:19`, `storage.py:23`).
Canonical split: AG3-081 delivers the `EventType` catalogue / mandatory-payload
contract; the generic emitter infra is pre-existing; AG3-099 owns the fachliche
BC14 emission + its tests. Remove `EventTypeId`, "Emitter-Infrastruktur"
(as an AG3-081 deliverable), and `Integrity-Dim-8` from the dependency wording.
(story.md:42/47/59/64/77)

**Verified against real code (anchors re-checked, not assumed):**
- The telemetry type is `EventType`, a `StrEnum` catalogue
  (`src/agentkit/telemetry/events.py:18` `class EventType(StrEnum)`). There is
  no `EventTypeId` type anywhere in the telemetry code.
- The mandatory-payload contract that AG3-081 owns alongside the catalogue
  values lives in the same module
  (`src/agentkit/telemetry/events.py:173` `MANDATORY_PAYLOAD_FIELDS`,
  with the fail-closed validator `validate_event_payload` at `:257`).
- The generic emitter infrastructure already exists and is pre-existing infra,
  not something AG3-081 or AG3-099 builds:
  `src/agentkit/telemetry/emitters.py:19` (`EventEmitter` Protocol, plus
  `MemoryEmitter`/`NullEmitter`) and
  `src/agentkit/telemetry/storage.py:23` (`StateBackendEmitter`, the persistent
  emitter over the canonical state backend).

**Resolution (edits in `story.md`):** the canonical 3-way split was applied
everywhere the review named it (lines 42/47/59/64/77) plus the source-concept
line 11 that also carried the stale `EventTypeId` token:

1. **`EventTypeId` -> `EventType`** at every occurrence in `story.md`
   (Quell-Konzept §70.10.3 line 11; In-Scope #6 line 42; Out-of-Scope line 47;
   AC7 line 59; DoD precondition line 64; Sub-Agent hint line 77). Zero
   `EventTypeId` tokens remain in `story.md`.

2. **AG3-081's deliverable corrected** to the `EventType` catalogue /
   mandatory-payload contract (anchored to `telemetry/events.py:18`/`:173`),
   NOT "Emitter-Infrastruktur". The Out-of-Scope item (line 47) now reads
   "`EventType`-Katalog-Eintrag + Mandatory-Payload-Contract" and explicitly
   states the generic emitter infrastructure
   (`telemetry/emitters.py:19`, `telemetry/storage.py:23`) is
   **vorhandene, vorbestehende Infra** built by neither AG3-081 nor AG3-099.
   The DoD precondition (line 64) carries the same correction.

3. **AG3-099 owns the fachliche BC14 emission + its tests**, consuming the
   existing `EventType` catalogue + the existing emitter infra. In-Scope #6
   (line 42), AC7 (line 59) and the Sub-Agent hint (line 77) now say AG3-099
   emits over the already-present emitter infrastructure
   (`telemetry/emitters.py:19`/`telemetry/storage.py:23`) and owns the
   emission tests, while only consuming AG3-081's catalogue values.

4. **Stale `Integrity-Dim-8` token removed** from the Out-of-Scope dependency
   wording (line 47). The item now scopes AG3-081 as the eight BC14- (plus
   three BC15-) `EventType` catalogue values, with no `Integrity-Dim-8`
   reference.

The "no second event enum" guardrail is preserved throughout: AG3-099 does not
extend the `EventType` catalogue itself and opens no parallel enum; it is
hard-blocked on AG3-081 if the catalogue values are missing (In-Scope #6 / AC7 /
DoD).

---

## Telemetry anchor re-verification (real file:line)

| Anchor in `story.md` | Real code | Confirmed |
|---|---|---|
| `EventType` catalogue | `telemetry/events.py:18` `class EventType(StrEnum)` | yes |
| Mandatory-payload contract | `telemetry/events.py:173` `MANDATORY_PAYLOAD_FIELDS` | yes |
| Generic emitter protocol | `telemetry/emitters.py:19` `EventEmitter` | yes |
| Persistent emitter | `telemetry/storage.py:23` `StateBackendEmitter` | yes |

No `EventTypeId` type exists in code; the review's correction is accurate and is
now reflected in `story.md`.

---

## R1–R3 carry-over verification (kept intact)

- **10-family framing unchanged:** "neun fehlende plus migriertes
  `dependency_edge` = zehn" persists (Ist-Zustand §1, Scope 2.1 #5, AC6). Not
  touched by R4.
- **Own BC-9 Planning write path unchanged:** Scope 2.1 #5/#5a still build a
  separate, owner-separated BC-9-hosted Planning projection write path; the
  FK-69 `ProjectionAccessor` is explicitly NOT used/extended. Not touched by R4.
- **FK-69 `ProjectionKind` stays 7:** the negative-boundary wording pinning the
  FK-69 contract to exactly seven values
  (`telemetry/projection_accessor.py:56`, contract test
  `tests/contract/telemetry/test_projection_accessor.py:32`) is unchanged.
- **status.yaml R3 title fix retained:** "eigenen BC-9-Planning-Projektions-
  Schreibpfad (nicht der FK-69-ProjectionAccessor)" stays; no R4 edit there.

All R4 edits were isolated to the telemetry/event lines; the resolved R1–R3
content was not altered.

---

## WARNINGs

review-r4.md raised a single blocking ERROR and no separate WARNING items; the
four per-dimension CHANGES-REQUESTED verdicts all trace to that one finding.
Applying the 3-way split resolves all four.

Carry-over non-blocking note (unchanged ownership, from remediation-r3.md):
`_STORY_INDEX.md:135` is the shared cross-story index, owned by the index, not
within AG3-099's edit scope. It summarises the AG3-081 deliverable; if the index
still phrases AG3-081 as delivering "+ Emitter", the index owner should align it
to the catalogue/mandatory-payload framing (generic emitter infra is
pre-existing). Flagged, not silently left; not edited here (would touch another
owner's file).

---

## Files written (AG3-099 only)
- `stories/AG3-099-planning-proposal-rulebook-persistence/story.md`
  (lines 11/42/47/59/64/77: 3-way `EventType` split applied,
  `Integrity-Dim-8` removed).
- `stories/AG3-099-planning-proposal-rulebook-persistence/remediation-r4.md`
  (this file).

No other files touched. `status.yaml` re-verified, genuinely correct, unchanged
(no stale token in its title). AG3-057 template structure preserved. ARCH-55:
all type names, event keys and field names remain English; only German concept
prose retained. Stayed strictly within the AG3-099 cut.
