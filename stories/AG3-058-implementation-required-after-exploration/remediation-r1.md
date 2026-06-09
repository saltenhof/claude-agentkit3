# AG3-058 — Remediation R1 (hostile Codex review-r1)

Review verdict: CHANGES-REQUESTED. All 5 Must-Fix ERRORs + both WARNINGs resolved in-story.
Only `story.md` and `status.yaml` of AG3-058 were touched. No production code, tests, concept
files, or other stories' files were modified.

---

## Must-Fix 1 (ERROR, Kontext-Sinnhaftigkeit FAIL) — false `story_done` / "Grep ohne Treffer" claim

**Finding:** Ist-Zustand claimed the follow-state flags `implementation_required`/`closure_allowed`/`story_done`
"existieren nicht (Grep ohne Treffer)". But `story_done` exists as a code anchor: the closure helper
`_transition_story_done` (`closure/phase.py:1082`, called at `:331`).

**Resolution:** Rewrote the Ist-Zustand bullet (story.md §1):
- `implementation_required`/`closure_allowed` **fehlen komplett** am autoritativen Zustandsmodell
  (`StoryContext`, `story_context_manager/models.py:310` — verified: no such fields).
- `story_done` is **not** a persisted follow-state field; the string exists only as a closure
  helper name (`_transition_story_done`, `closure/phase.py:1082`, called `:331`) that only triggers
  the `complete_story` service call and carries no typed terminality follow-state.
Verified anchors against real code: `closure/phase.py:331` and `:1082`, `models.py:310`.

## Must-Fix 2 (ERROR, AC-Schaerfe) — `core_types` constants claim for `worker-manifest.json`/`protocol.md`

**Finding:** §6 hint claimed these names are pulled from existing `core_types` artifact constants.
In reality they are private (`_PROTOCOL_FILE`/`_WORKER_MANIFEST_FILE`, `artifact_checks.py:34-35`);
`core_types/__init__.py` exports only QA-layer names (`qa_artifact_names.py`), not the worker-handover names.

**Resolution (chose consolidation, FIX-THE-MODEL — not removal):**
- Added new Scope item **2.1.8**: consolidate/export the canonical worker-handover filenames
  (`protocol.md`/`worker-manifest.json`) into `core_types` (`qa_artifact_names.py` or neighbouring
  foundation module), re-point the existing private constants in `artifact_checks.py` onto the new SSOT,
  and have the gate consume the same SSOT — no new literal. FK-27 §27.4.1 stays the semantic owner.
- Rewrote the §6 hint to state the true Ist-Zustand (names not yet in `core_types`) and to require
  doing 2.1.8 first before the gate references them.
Verified: `core_types/__init__.py` (no handover names in `__all__`), `artifact_checks.py:34-36`.

## Must-Fix 3 (WARNING, Konzept-Vollstaendigkeit) — FK-24 §24.9 rendered too strictly

**Finding:** Story implied FK-24 mandates `exploration-summary.md` directly; FK-24 §24.9.1 actually
allows `exploration-summary.md` **OR** a defined exploration section in `protocol.md`.

**Resolution:** Reworded the Quell-Konzept bullet for §24.9 (story.md §1 references): FK-24 §24.9.1 permits
the alternative; AG3-058 deliberately picks the stricter dedicated `exploration-summary.md` per the
**index decision** (`_STORY_INDEX.md:44`), explicitly NOT because FK-24 only allows that file.
Verified anchor: `24_story_type_mode_terminalitaet.md:520-527` (the OR-alternative) and `_STORY_INDEX.md:44`.

## Must-Fix 4 (WARNING, Klarheit) — AG3-059 dependency / PhaseStateCore `escalation_reason` owner order

**Finding:** AG3-058 had no `depends_on: AG3-059`, though AG3-059 owns PhaseStateCore + the
`escalation_reason` field/range and explicitly delegates the extra value to AG3-058
(`AG3-059 story.md:7,30,40`).

**Resolution:**
- `status.yaml`: added `AG3-059` to `depends_on` (genuine field/transport prerequisite).
- story.md: added FK-39 §39.2.1 (Owner AG3-059) to Quell-Konzepte; expanded the
  Kontext-Sinnhaftigkeit paragraph with the explicit owner split (AG3-059 owns the field +
  §39.2.1 base range; AG3-058 only decides/sets the value); added an Out-of-Scope bullet for the
  PhaseStateCore field/transport with owner AG3-059 and a fallback (dedicated typed code if AG3-059
  not yet landed — one decision, no double path); refined the §6 hint accordingly.
Verified anchors: `AG3-059 story.md:7,30,40`.

## Must-Fix 5 (ERROR, AC-Schaerfe) — AC2 must rest on independent system evidence, not worker self-report

**Finding:** AC2/Scope did not pin "code/file changes" to Trust-A/B system evidence. Existing verify
code forbids blocking decisions on Trust-C worker self-report (`system_evidence.py:1-23`,
FK-33 §33.5.1/§33.5.2). `worker-manifest.json` must not count as proof of real changes.

**Resolution:**
- Scope item 2.1.2 rewritten: the blocking "real code/file changes" assertion must rest **only** on
  independent system/Trust-B evidence (system `git` diff / `ChangeEvidence` via `ChangeEvidencePort`,
  `system_evidence.py`), never on `worker-manifest.json` (Trust-C `WORKER_ASSERTION`). Manifest/protocol
  count only as mandatory-artifact/schema presence; a manifest claiming changes without a confirming
  system diff is FAIL-CLOSED, not PASS.
- AC2 rewritten with three tests: (i) exploration-only -> FAIL; (ii) manifest+protocol present but
  system diff shows no change -> FAIL (manifest alone insufficient); (iii) mandatory artifacts +
  confirming system diff -> PASS.
- Added a dedicated §6 hint reinforcing the Trust separation.
Verified anchor: `system_evidence.py:1-23` (FK-33 §33.5 Trust-A/B-only rule + absent fail-closed default).

## NIT (positive anchors confirmed real)

No change required. Spot-verified: `closure/gates.py:58` (FindingResolutionVerdict dataclass),
`closure/phase.py:16` (canonical sequence), FK-24 §§24.5.2/24.7.1/24.8.2/24.9/24.12/24.14 exist.
Tightened a couple of anchors in the text to file:line where the original was a range only.

---

## Genuine cross-story prerequisite

- **AG3-059** (PhaseStateCore-Feldsatz + `escalation_reason` field/range) is now a hard
  `depends_on`. AG3-058 only sets the value `IMPLEMENTATION_REQUIRED_AFTER_EXPLORATION`; the typed
  `escalation_reason` field and its persistence/wire transport are delivered by AG3-059
  (`AG3-059 story.md:40` explicitly delegates the value back to AG3-058). Documented fallback in
  Out-of-Scope: if AG3-059 is not yet landed, AG3-058 carries the reason as a dedicated typed
  Closure/Verify error code (single decision, no double path) — so the story stays self-consistent
  either way.

## Files written (AG3-058 only)

- `stories/AG3-058-implementation-required-after-exploration/story.md`
- `stories/AG3-058-implementation-required-after-exploration/status.yaml` (added `depends_on: AG3-059`)
- `stories/AG3-058-implementation-required-after-exploration/remediation-r1.md` (this file)

AG3-057 template structure (Typ/Groesse/BC/Quell-Konzepte/§1 Kontext/§2 Scope/§3 AK/§4 DoD/
§5 Guardrails/§6 Hinweise) preserved; all field names/enum values stay English (ARCH-55).
