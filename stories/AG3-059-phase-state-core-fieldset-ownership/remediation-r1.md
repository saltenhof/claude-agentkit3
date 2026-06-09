# AG3-059 — Remediation r1 (hostile Codex review-r1.md)

Scope of this remediation: `story.md` only. `status.yaml` reviewed — no field is
genuinely wrong (see status.yaml note). No production code, tests, or concept files
touched. Every code anchor below was re-verified against the real tree at remediation
time and corrected to `file:line`. Stays strictly within the AG3-059 cut
(PhaseStateCore field-set + RuntimeMetadata strictness + schema ownership + `pause_reason`
field-key); broader runtime-state-machine changes are routed to owners.

## Must-Fix ERRORs

### MF1 — Remote Jenkins/Sonar gate in AC8/DoD (review §AC-Schaerfe ERROR, §Must-Fix 1)
**Finding:** AGENTS.md "Pflicht-Gates vor fertig" (`AGENTS.md:31-45`) mandates Jenkins
green + Sonar green via `scripts/ci/check_remote_gates.ps1` with Sonar targets
`violations=0`, `critical_violations=0`, `security_hotspots=0`. The old AC8 listed only
local tests/ruff/mypy/concept-gates.
**Resolution (in-story):** Split mandatory commands into a local AC9 and a new remote AC10:
AC10 requires `scripts/ci/check_remote_gates.ps1` green (Jenkins SUCCESS, Sonar gate green)
with the three explicit Sonar targets. DoD updated to "AK 1–10 (incl. local AK9 + remote
AK10)". The remote-gate obligation is also added as an authoritative source-concept anchor
(`AGENTS.md "Pflicht-Gates vor fertig"`) and to the §6 hints. The `check_remote_gates.ps1`
script was verified to exist (`scripts/ci/check_remote_gates.ps1`).

### MF2 — §39.3 Dataclass conformance for `PhaseEnvelope`/`RuntimeMetadata` (review §Konzept-Vollstaendigkeit ERROR, §Must-Fix 2)
**Finding:** FK-39 §39.3 (`39_phase_state_persistenz.md:329-339`) normatively defines
`RuntimeMetadata` and `PhaseEnvelope` as frozen **dataclasses** (`@dataclass(frozen=True)`),
not Pydantic models. The real code implements both as Pydantic `BaseModel`
(`runtime.py:29`, `envelope.py:18`). The old story checked only `origin`/`extra="forbid"`
and silently sold §39.3 as done.
**Resolution (in-story — within cut):** This is the §39.2.5/§39.3 RuntimeMetadata-strictness
item (already in scope), so the carrier-form correction belongs in the same cut, not another
story. Ist-Zustand now records the carrier-form drift (Pydantic vs. frozen dataclass) with
real anchors. Scope item 3 retitled "RuntimeMetadata-Strenge + Traegerform (§39.2.5/§39.3)"
and mandates conversion of `RuntimeMetadata`/`PhaseEnvelope` to `@dataclass(frozen=True)`
per §39.3; any deviation must be raised with the §39.3 owner and reconciled in the concept,
no silent Pydantic retention (fail-closed). AC5 now asserts the dataclass carrier-form
(`dataclasses.is_dataclass(...)` + immutability) in addition to frozen/extra strictness.
AC6 + Scope 6 add the dataclass-form test. The "Konform (nicht anfassen)" line was corrected:
the `PhaseEnvelope` persistence boundary stays untouched, but the carrier-form IS in scope.

### MF3 — Existing Core fields `phase`/`status` typing + value-set (review §Konzept-Vollstaendigkeit ERROR, §Must-Fix 3)
**Finding:** §39.2.1 (`39_phase_state_persistenz.md:235-236`) requires `phase` as `Enum`
and `status` from the 5-value set `{IN_PROGRESS, COMPLETED, FAILED, ESCALATED, PAUSED}`.
Real code has `phase: str` (`models.py:438`, only a string validator at `models.py:454-465`)
and `PhaseStatus` with seven values including `PENDING`/`BLOCKED` (`models.py:48-55`).
**Resolution (split — in-story for `phase`, routed for the `status` value-set):**
- `phase` typing IS in this schema-fieldset cut: Scope item 1 now binds `phase` to the
  existing `PhaseName` StrEnum (`phase: PhaseName`, replacing the string + ad-hoc validator).
  New AC3 enumerates the typed Core fields and adds a negative test for a non-`PhaseName`
  value. Ist-Zustand records the `phase: str` divergence with real anchors.
- The `PhaseStatus` value-set reduction (`PENDING`/`BLOCKED`) is explicitly carved OUT
  (new Out-of-Scope bullet): it is a runtime state-machine change, not a schema-fieldset/
  ownership change. `PhaseStatus.PENDING`/`BLOCKED` are used productively in four engine
  modules (`composition_root.py`, `control_plane/dispatch.py`, `pipeline_engine/runner.py`,
  `pipeline_engine/engine.py` — verified), so removing them is out of this cut. No story in
  `_STORY_INDEX.md` owns this reduction, so it is reported as a genuine concept/code drift
  for a Wave-0 correctness item or a doc-only concept follow-up (see cross-story below).
  AG3-059 keeps `status: PhaseStatus` typed without altering the value set; AC3 states the
  value set is NOT forced to the 5-value form here.

### MF4 — `PauseReason` lowercase-wire vs. unchanged uppercase enum (review §AC-Schaerfe WARNING, §Must-Fix 4)
**Finding:** The old story said both "Lowercase-StrEnum-Serialisierung" (Scope 2) and
"Bestehende `PauseReason`-Enum bleibt unveraendert" (§6) — self-contradictory. The contract
test `test_enum_wire_values.py:89-93` and the enum itself (`pause_reason.py:58-60`) freeze
UPPERCASE values; AG3-021 (`completed`) chose UPPERCASE normatively and documented the
drift in `pause_reason.py:9-15`. FK-39 is internally inconsistent: §39.2.1 (`:242`) and the
§39.2.2 code block (`:263`) show lowercase wire values, while the FK-39 glossary (`:69`)
shows UPPERCASE.
**Resolution (explicit decision, in-story, testable):** AG3-059 changes only the **field
key** `paused_reason -> pause_reason`; the serialized `PauseReason` **enum value stays
UPPERCASE**. Rationale recorded in Scope item 2: AG3-021's `completed` decision is not
reopened, and the frozen contract test is not bypassed (NO ERROR BYPASSING). AC4 now asserts
the wire format is `{"pause_reason": "AWAITING_DESIGN_REVIEW"}` and that
`test_enum_wire_values.py:89-93` stays green. ARCH-55 guardrail + §6 hint corrected to the
field-key-only semantics. The FK-39-internal lowercase/uppercase inconsistency is reported
as a doc-only concept follow-up (see cross-story below), not flipped in code.

## WARNINGs

### W1 — "vier Konzept-Gates" unscharf (review §Klarheit WARNING)
**Resolution:** AC9 now names the four concrete scripts:
`scripts/ci/check_concept_frontmatter.py`, `scripts/ci/compile_formal_specs.py`,
`scripts/ci/check_architecture_conformance.py`, `scripts/ci/check_concept_code_contracts.py`
(all four verified present in `scripts/ci/`). §6 hint mirrors the concrete list.

### W2 — Re-export bridge not sufficiently bounded (review §Kontext-Sinnhaftigkeit WARNING)
**Finding:** `story_context_manager/__init__.py:6-11` re-exports `PhaseState`/`PhaseStatus`;
many importers = long-term bridge risk.
**Resolution:** Scope item 4 + new AC8 require that no production importer still pulls the
phase-state models from `story_context_manager` after the move; the bridge is kept only as a
**deprecated** transition path for compatible legacy/test imports, with a test/guard proving
no orphaned production import. Real anchor `__init__.py:6-11` cited.

### W3 — `pause_reason` decision (review §AC-Schaerfe WARNING "Wie wollen wir hier vorgehen?")
Same item as MF4. **Decision taken:** field-key rename only, enum value stays UPPERCASE,
FK-39-internal inconsistency routed to a doc-only concept follow-up. See MF4.

## Corrected / verified code anchors (review §Kontext-Sinnhaftigkeit PASS retained)
All anchors the review confirmed as real were kept and re-checked against the tree:
`PhaseState` at `models.py:436-452` (with `paused_reason` at `:442`), `RuntimeMetadata` at
`runtime.py:29-51` (review cited `:46`/`:29`; the story now uses the class-def line `:29`
plus the field range), `PhaseEnvelope` at `envelope.py:18`, `store.py:30-37`, `AttemptRecord`
at `phase_executor/records.py:26` (importer of `PhaseName` from `story_context_manager.models`
at `records.py:15`), `PhaseStatus` at `models.py:48-55`, `PauseReason` at `pause_reason.py:58-60`
(+ drift note `:9-15`), contract test `test_enum_wire_values.py:89-93`, FK-39 §39.2.1 table
`:235-247`, FK-39 §39.3 dataclass code block `:329-339`, `__init__.py:6-11`. The old
`runtime.py:46-51` anchor was widened to `runtime.py:29-51` to include the class definition.

## status.yaml
Reviewed; no field is genuinely wrong. `depends_on: [AG3-024]` matches the `_STORY_INDEX.md`
master row (line 45). `phase: review_pending` correctly reflects the running review cycle;
`status: draft` is correct for a not-yet-authorized story. No edit made (per instruction:
only touch status.yaml if a field is genuinely wrong).

## Genuine cross-story prerequisites / follow-up units
1. **AG3-058 — `escalation_reason` value `IMPLEMENTATION_REQUIRED_AFTER_EXPLORATION`.**
   Stays Out-of-Scope with owner AG3-058 (FK-24 terminality; `_STORY_INDEX.md:44`, AG3-058
   depends on AG3-057). AG3-059 only sets up the §39.2.1 value range; AG3-058 decides the
   extra value. Not a blocker for AG3-059.
2. **AG3-081 — `phase_state_projection` DB-access layer / telemetry write-path.**
   Stays Out-of-Scope with owner AG3-081 (`_STORY_INDEX.md:87`, "typisierter
   `phase_state_projection`-Record"). AG3-059 delivers the Pydantic schema (owner), AG3-081
   the projection write-path. Clean ownership split, no scope overlap.
3. **AG3-089 — schema-version migration / `migrate_*`.** Stays Out-of-Scope with owner
   AG3-089 (`_STORY_INDEX.md:105`, `migrate_config`/`migrate_3_to_4`). AG3-059 adds only the
   `schema_version` field + constant.
4. **doc-only concept follow-up — FK-39 §39.2.1/§39.2.2 vs. glossary `pause_reason` case
   drift.** FK-39 §39.2.1 (`:242`) and the §39.2.2 code block (`:263`) show lowercase wire
   values; the FK-39 glossary (`:69`) and the AG3-021-frozen contract use UPPERCASE. Code is
   authoritative via the frozen contract test; this is FK-prose-vs-contract drift. Belongs in
   the doc-only concept follow-up for the FK-39 owner, NOT in the AG3-059 code cut.
5. **concept/code drift OR Wave-0 correctness item — `PhaseStatus` value set.** §39.2.1
   (`:236`) lists five status values; the engine uses seven (`PENDING`/`BLOCKED`). No
   `_STORY_INDEX.md` story owns this reduction today. Either the engine states are legitimate
   and FK-39 must adopt them (doc-only nachzug), or they must be removed (a new Wave-0
   correctness item alongside AG3-058..060). Reported here; explicitly out of the AG3-059
   schema-fieldset/ownership cut.

Note on cut fidelity: the §39.3 dataclass carrier-form (MF2) and `phase`-enum typing (MF3a)
are kept **inside** AG3-059 because they are the RuntimeMetadata-strictness and Core-field
items already in this cut. The `PhaseStatus` value-set (MF3b) and the FK-39 case drift (MF4)
are routed out because they are runtime-state-machine / doc-only concerns, not schema-fieldset
or ownership concerns, and no other story falsely claims to deliver them.
