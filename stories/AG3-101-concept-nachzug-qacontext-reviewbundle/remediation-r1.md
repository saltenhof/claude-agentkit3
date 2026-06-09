# AG3-101 — Remediation R1 (hostile Codex review-r1)

Doc-only/concept-alignment story. Every must-fix ERROR and the must-fix list
resolved by aligning the story so the (later) FK prose follows the real code,
without silently mandating code changes. No production code, tests, concept
files, or other stories' files were touched — only `story.md` in this folder.
`status.yaml` was reviewed: no field is genuinely wrong (see Note A).

## Finding -> Resolution

### 1. Konzept-Vollstaendigkeit (ERROR) — §37.1.4 stale `VerifyContext` not in scope
- **Resolution:** Scope and AC expanded from "§37.1.0/§37.1.2" to **all of FK-37 §37.1**, explicitly including the §37.1 head decision blocks and **§37.1.4 (decision rule + pseudocode)**.
- New §1.2 lists every grounded stale location with real anchors: §37.1 `:95,106-107`; §37.1.0 `:117,124`; §37.1.2 `:173,180-181`; **§37.1.4 `:209,218,229-230,266`**.
- AC1 now names §37.1 (head), §37.1.0, §37.1.2, §37.1.4 and FK-38 §38.1.3.
- Quell-Konzepte header updated to "FK-37 §37.1 (gesamter Abschnitt, inkl. §37.1.0/§37.1.2/§37.1.4)".
- Evidence: `37_verify_context_und_qa_bundle.md` lines 95, 106-107, 117, 124, 173, 180-181, 209, 218, 229-230, 266 each carry the old `VerifyContext` enum / two-value set.

### 2. AC-Schaerfe (ERROR) — AC2 temporally contradicts the AG3-067 dependency
- **Resolution (per reviewer's preferred option):** Dependency on AG3-067 **kept**; AC2 reformulated to **re-ground against the post-AG3-067 real `ReviewBundle`**.
- New §1.3 ("Code-vs-FK-Drift-Robustheit") states the conflict explicitly: AG3-067 (§2.1.3 / AC5) adds typed `arch_references`/`evidence_manifest` to `ReviewBundle`, so the current 8-field state is not the post-AG3-067 reality.
- AC2 now requires: if those fields are typed after AG3-067 → document them as **present**; if still missing → mark as AG3-067 code-need; never assert a state untrue at execution time.
- The enum part (§2.1.1/§2.1.2) is declared independent of AG3-067 and grounded against the Ist-Code.

### 3. Klarheit (ERROR) — `VerifyContext` enum not separated from valid `VerifyContextBundle`
- **Resolution:** New dedicated §1.1 "Scharfe Symbolabgrenzung" separates the exact old enum/discriminator symbol `VerifyContext` (the only replacement target) from the still-valid public contract type `VerifyContextBundle`.
- Evidence: `contract.py:136` `class VerifyContextBundle(BaseModel)`; `system.py:478-487` `run_qa_subflow(self, ctx: VerifyContextBundle, ..., qa_context: QaContext, ...)` — two separate parameters.
- Substring deletion explicitly **forbidden**; matching must use a word boundary so `VerifyContextBundle` is never a hit. Reflected in §2.1.1, §2.2 (added as Out-of-Scope), AC1 ("mit Wortgrenze geprueft"), AC3 (new), Guardrails §5, and Sub-Agent note "Symbol-Disziplin".
- Story title `VerifyContext` -> `QaContext` left intact: it refers to the enum being replaced, which is accurate.

### 4. Kontext-Sinnhaftigkeit (ERROR) — not robust against code-vs-FK drift; ReviewBundle bound to pre-AG3-067 line
- **Resolution:** Added an explicit **Re-Grounding-Pflicht** as a binding execution step:
  - §1.3 (rationale), §2.1.6 (the obligation), §2.1.3 (ReviewBundle scope now defers to the execution-time field set), AC2 (asserts neither stale "implemented" nor stale "open"), DoD (execution + commit only after AG3-067, so the ReviewBundle part is grounded against real code).
- Wording mirrors the reviewer's fix: "vor FK-Aenderung realen `ReviewBundle`/`build_review_bundle` erneut pruefen; FK folgt exakt diesem Feldset; offene Felder nur dann an AG3-067/Follow-up spiegeln, wenn nach AG3-067 weiterhin fehlend."

## Must-Fix List (review-r1)
1. **FK-37 §37.1.4 stale `VerifyContext` in scope/AC** — DONE (§1.2, §2.1.1, AC1).
2. **`VerifyContext` exactly separated from valid `VerifyContextBundle`, no blanket substring deletion** — DONE (§1.1, §2.2, AC1/AC3, §6).
3. **AG3-067 dependency resolved with AC2 (re-ground after AG3-067)** — DONE (dependency kept; §1.3, §2.1.6, AC2, DoD).

## Anchor corrections (wrong -> real file:line)
- `implementation/phase.py:320,433` -> **`:320,434`** — `QaContext.IMPLEMENTATION_INITIAL` is at line **434** (320 = `IMPLEMENTATION_REMEDIATION`, confirmed). Off-by-one fixed in §1 Ist-Zustand.
- `bc-cut-decisions.md Z. 84-101` re-expressed as `bc-cut-decisions.md:84-101` (consistent file:line form; range confirmed: §QA-Subflow-Vertrag at 84, QaContext values at 100-101).
- Added precise grounding anchors that were previously missing: `contract.py:136`, `system.py:478-487`, and the full §37.1.4 line set.
- Verified unchanged-correct anchors: `qa_context.py:15-31`, `story_context_manager/models.py:136`, `bundle.py:44-69`, `_verify_context_for()` at `:637-640`, FK-38 §38.1.3 `38_...:176`.

## ARCH-55
All identifiers/enum values kept English (`QaContext`, the four UPPER_SNAKE values, `VerifyContextBundle`, `ReviewBundle`). No German keys introduced. Concept prose (German) unchanged in tone; AG3-057 section structure (1 Kontext / 2 Scope / 3 AC / 4 DoD / 5 Guardrails / 6 Hinweise) preserved.

## Self-consistency
- Story claims AG3-067 delivers only what AG3-067's scope actually delivers: typed `arch_references`/`evidence_manifest` on `ReviewBundle`, ContextSufficiencyBuilder, Section-aware Packing, Ebene-4 `feedback_fidelity`, Mandatory-Target-Rueckkopplung (verified against `stories/AG3-067-.../story.md` §2.1, AC5). No over-claim.
- No code change is mandated by AG3-101 itself; all pure code-needs routed to AG3-067 (and §37.1.3 to AG3-069).

## Note A — status.yaml
Reviewed, left unchanged. `depends_on: [AG3-067]` is correct and intentionally retained (finding #2 resolution). `unblocks: []` is correct — AG3-101 unblocks no story (AG3-067 unblocks AG3-101, not vice versa; confirmed in `AG3-067/status.yaml`). Title refers to the enum rename and is accurate. No genuinely-wrong field found, so per the doc-only constraint status.yaml was not edited.

## Cross-story prerequisite (genuine)
- **AG3-067** is a genuine prerequisite for the **ReviewBundle part (§2.1.3)** of the later FK execution: it adds the typed `arch_references`/`evidence_manifest` fields. The FK ReviewBundle prose must be (re-)grounded against the post-AG3-067 code; therefore execution/commit of AG3-101's bundle changes must follow AG3-067 (DoD). The enum part (§2.1.1/§2.1.2/§38.1.3) has no cross-story prerequisite and can be grounded against current Ist-Code.

## Files written (this story only)
- `stories/AG3-101-concept-nachzug-qacontext-reviewbundle/story.md` (rewritten)
- `stories/AG3-101-concept-nachzug-qacontext-reviewbundle/remediation-r1.md` (this file)
- `status.yaml`: not modified (Note A).
