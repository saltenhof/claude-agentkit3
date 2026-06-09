# AG3-086 — Remediation r3 (hostile Codex review review-r3.md)

**Scope of this remediation:** `stories/AG3-086-hook-guard-buildout/story.md` (+ a genuinely
wrong field in `status.yaml`). No production code, tests, concept files, or other stories'
files were touched. Every code/concept anchor cited below was verified against the real tree
before rewriting.

review-r3.md carries exactly **one** remaining must-fix ERROR (the round-2 budget/fail-closed
items are confirmed resolved). It is resolved below.

---

## ERROR 1 — `integrity_violation` fix not buildable against the real telemetry contract

**Finding (review-r3.md).** The story requires `skill_usage_check` and `WebCallBudgetGuard`
block events to emit `integrity_violation` **without** `stage`, but the real contract pins
`stage` as mandatory for **every** `integrity_violation`
(`MANDATORY_PAYLOAD_FIELDS[EventType.INTEGRITY_VIOLATION] = ("stage",)`), and the contract
test locks that in. AC9 requires contract tests green — so the story asks for no-stage
budget/skill events while the shared contract still demands stage. Not buildable as written.

**Verification (real tree + concepts).**
- Code/contract is exactly as the finding says:
  - `src/agentkit/telemetry/events.py:173` (`MANDATORY_PAYLOAD_FIELDS` map start), `:180`
    (`EventType.INTEGRITY_VIOLATION: ("stage",)`), `:257` (`validate_event_payload`, fixed-tuple
    presence check).
  - `tests/contract/telemetry/test_event_catalog.py:114`
    (`_EXPECTED_MANDATORY_FIELDS[INTEGRITY_VIOLATION] = ("stage",)`), asserted `:150`
    (`dict(MANDATORY_PAYLOAD_FIELDS) == _EXPECTED_MANDATORY_FIELDS`).
- The concept disagrees with the unconditional pinning:
  - **FK-61 §61.12.2** (KPI doc, the authoritative source the `events.py` map comment cites)
    lists the enriched `integrity_violation` field as `stage` **"(fuer prompt_integrity_guard)"**,
    i.e. **conditional**, not unconditional.
  - **FK-68 §68.2** (event model): only `project_key/story_id/run_id/event_id/event_type/
    occurred_at/source_component/severity` are universally mandatory; everything else is
    event-specific detail payload. **FK-68 §68.3.1** lists "Guard-Hooks (inkl. SkillUsageCheck)
    | `agentkit.governance.guard_system` | PreToolUse | Blockade (exit 2) | `integrity_violation`"
    — every guard block emits `integrity_violation`, and only prompt_integrity carries `stage`.
  - So the **concept** already wants `stage` conditional; the **code** over-pins it. The story's
    field semantics were right; the missing piece was an explicit contract-migration scope/AC so
    AC9 is achievable.

**Routing decision (the load-bearing part of this remediation).**
The canonical owner of the `EventType` catalogue + Mandatory-Payload-Contract
(`MANDATORY_PAYLOAD_FIELDS`, `MANDATORY_PAYLOAD_FIELDS_BY_NAME`, `validate_event_payload`,
`tests/contract/telemetry/test_event_catalog.py`) is **AG3-081** — confirmed in
`_STORY_INDEX.md:87` ("Event-Vollausbau … angereicherte Event-Payloads … Hook-Tabelle↔Code-
Konsistenz") and in `AG3-081/story.md §2.1` ("EventType-Katalog + Mandatory-Payload-Contract …
— **AG3-081** (diese Story). Das ist der kanonische Enum-Owner."). AG3-081 already reconciles a
sibling event's payload contract owner-based (`are_gate_result`, AG3-081 §2.1.3).

**Crucial honesty check (per the prompt's warning):** AG3-081's *written, approved* scope does
**not** currently list the `integrity_violation` `stage`-conditionality. I did **not** claim
AG3-081 already delivers it, and I did **not** edit AG3-081's files. AG3-081 is APPROVE
(`AG3-081/review-r4.md` OVERALL APPROVE) but still `status: draft` / `phase: review_pending`,
i.e. in the same pre-implementation wave as AG3-086.

So the change cannot be silently dumped onto a foreign owner's files, nor can AG3-086 pretend
the contract is already conditional. The model-true resolution:

- AG3-086 is the **producer** story that *introduces the need* (first non-prompt-integrity
  `integrity_violation` emitters). The contract migration is intrinsic to AG3-086's deliverable
  being buildable.
- The canonical map definition stays with the **AG3-081** owner; AG3-086 performs the one
  `integrity_violation` entry's migration **in coordination with AG3-081** and records the real
  dependency via `depends_on: AG3-081`. No second validator/contract path is created
  (SINGLE SOURCE OF TRUTH).

**Resolution (in-story).**
- **Source-concept head:** added an `FK-61 §61.12.2` bullet stating `stage` is "fuer
  prompt_integrity_guard" (conditional), contrasted with the real unconditional pinning
  (`events.py:180`) and the contract-test lock (`test_event_catalog.py:114`), concluding the
  new emitters are not buildable without a contract migration.
- **Ist-Zustand:** new fifth gap bullet documenting the contract-vs-concept mismatch with exact
  anchors (`events.py:173/:180/:257`, `test_event_catalog.py:114/:150`) and the AC9 conflict.
- **Scope 0 (new):** "`integrity_violation`-Payload-Vertrag konzeptkonform auf bedingtes `stage`
  migrieren" — `guard`/`detail` always mandatory; `stage` valid/required only for
  `guard="prompt_integrity_guard"`; touches `MANDATORY_PAYLOAD_FIELDS`,
  `validate_event_payload` (conditional check instead of fixed tuple), and the contract test.
  Explicit owner-clarification: AG3-081 is the canonical contract owner; AG3-086 is the
  producer that triggers it; `depends_on: AG3-081`; no second contract path; no false claim
  that AG3-081 already lists it. ARCH-55 note.
- **AC0 (new):** conditional contract is testable — skill/budget event without `stage`
  validates green; prompt_integrity event without `stage` fails closed; contract test green
  against the new conditional expectation.
- **AC2b / AC5b sharpened:** now state "**without** `stage`" and "setzt AC0 voraus", citing
  FK-61 §61.12.2.
- **AC5 sharpened:** prompt_integrity event carries `guard`+`detail` (always) **plus** `stage`
  (conditional, AC0).
- **Scope 2 / Scope 1 telemetry bullets:** add the AC0 precondition note (else
  `validate_event_payload` rejects the stage-less event).
- **Scope 3 telemetry bullet:** `guard`/`detail` always mandatory; `stage` conditional
  (FK-61 §61.12.2).
- **Scope 7 test list, DoD (AK 0–9), Out-of-Scope, Guardrails (FIX-THE-MODEL/SSOT), Sub-Agent
  hints, "done"-evidence:** all extended with the conditional-contract migration + tests and
  the AG3-081 ownership/coordination note.

## status.yaml

`depends_on` extended with **AG3-081** — a genuinely missing, real dependency (AG3-086 now
requires the conditional `integrity_violation` contract whose canonical owner is AG3-081).
All other fields (`status: draft`, `phase: review_pending`, `type/size/title`,
`AG3-013`/`AG3-080`) remain correct.

## Routing check (no false delegation)

- **AG3-081** (`_STORY_INDEX.md:87`, `AG3-081/story.md §2.1`): canonical Mandatory-Payload-
  Contract owner. The `integrity_violation` field migration is coordinated with it
  (depends_on), but AG3-086 does **not** claim AG3-081 already delivers the `stage`-condition
  (it does not list it). The map definition stays at the owner; AG3-086 supplies the
  producer-driven reconciliation + producers.
- **AG3-085** (`:96`): consumes governance signals (incl. `integrity_violation`); does not own
  the payload contract. Unchanged (consume-only Out-of-Scope).
- **AG3-103** (`:144`): doc-only FK-93/FK-68 §68.2 prose reconciliation — unrelated to the
  code-level payload contract change.
- **AG3-080**: `health_monitor` only — untouched.

## Template / language

AG3-057 section structure (head → 1 Kontext/Ist-Zustand → 2 Scope (In/Out) → 3 AC → 4 DoD →
5 Guardrails → 6 Sub-Agent hints) is preserved; the new Scope 0 / AC0 slot into the existing
ordered lists. ARCH-55: all new identifiers/values are English (`integrity_violation`, `guard`,
`detail`, `stage`, `prompt_integrity_guard`, `web_call_budget_guard`, `skill_usage_check`,
`escape_detection`, `schema_validation`, `template_integrity`); German remains only in prose.

## Must-fix checklist (review-r3.md)

1. `integrity_violation` fix buildable against the real telemetry contract — **done**:
   Scope 0 + AC0 migrate the payload contract (`MANDATORY_PAYLOAD_FIELDS`,
   `validate_event_payload`, `test_event_catalog.py`) to conditional `stage`
   (`guard`/`detail` mandatory; `stage` only for `prompt_integrity_guard`), coordinated with the
   canonical owner AG3-081 (`depends_on` added). AC2b/AC5b/AC5 + tests/DoD/guardrails/hints
   aligned; AC9 (contract tests green) is now achievable.

Only `stories/AG3-086-hook-guard-buildout/story.md` and `status.yaml` were written (+ this
`remediation-r3.md`). No other files touched.
