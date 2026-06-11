# Second-QA Review (adversarial re-review) — AG3-101

- **Story:** AG3-101 — Konzept-Nachzug Enum `VerifyContext` -> `QaContext` und `ContextBundle`/`ReviewBundle` (doc-only)
- **Reviewer:** Fable second-QA (independent adversarial re-review, write authority)
- **Commit reviewed:** `14a931d` (`docs(AG3-101): FK-37/38 concept nachzug VerifyContext -> QaContext -> completed`)
- **Review date:** 2026-06-12
- **Method:** every code anchor in the new FK-37/FK-38 prose was opened in the real current source and checked line-by-line (`core_types/qa_context.py`, `verify_system/routing.py`, `verify_system/contract.py`, `verify_system/llm_evaluator/bundle.py`, `pipeline_engine/phase_executor/models.py`, `implementation/phase.py`, `verify_system/qa_cycle/integration.py`, `concept/_meta/bc-cut-decisions.md`); §37.1 was scanned for internal contradictions, surviving categorical "Exploration never via QA-subflow" prose, live `VerifyContext` usage (word-boundary vs `VerifyContextBundle`), ARCH-55 breaches and scope leakage.

## Findings

| ID | Severity | Location (file:line, pre-fix) | Finding | Action taken |
|----|----------|------------------------------|---------|--------------|
| F1 | Minor | `concept/technical-design/37_verify_context_und_qa_bundle.md:113-114` (Owner-Hinweis) | Representation error: the prose claims the `qa_context.py` module docstring "vermerkt explizit \"Ersetzt den v2-Namen `VerifyContext` (nur zwei Werte)\"" — i.e. presents a **German** sentence as a verbatim docstring quote. The real docstring (`core_types/qa_context.py:6-7`) is English (ARCH-55): "Replaces the v2 name ``VerifyContext`` (only two values) with a four-member StrEnum." A quoted string that does not exist in the code is exactly the "mangelnde Vertretung" failure mode. | **FIXED in-place**: quote now reproduces the English docstring verbatim, with a German paraphrase appended outside the quotes. |
| F2 | Minor | `37_...md:112`, `37_...md:211` (§37.1.2 note), `37_...md:342` (§37.1.5), `38_verify_feedback_und_doctreue_schleife.md:176` (§38.1.3) | Stale anchor: all four citations say `core_types/qa_context.py:15-31`. The file has exactly **30** lines (verified: `(Get-Content ...).Count` = 30); `class QaContext(StrEnum)` spans **15-30** (last enum member `EXPLORATION_REMEDIATION` at line 30). Line 31 does not exist. (The story spec itself carries the same off-by-one in §1/AK1; the FK must anchor to the real file, the spec text was not rewritten.) | **FIXED in-place**: all four occurrences corrected to `core_types/qa_context.py:15-30`. |
| F3 | Minor | `37_...md:315` (§37.1.4 pseudocode comment) and `37_...md:361-362` (§37.1.5) | Internal inconsistency / misrepresentation of `routing.py`: the reduced-path exclusion read "KEIN Adversarial/SonarQube-Gate **(Schicht 3)**", classifying the SonarQube gate as Schicht 3. This contradicts (a) the doc's own Schicht-Zaehlung note (§37.1.5, "`SONARQUBE_GATE` als eigene, nach Adversarial sequenzierte **Layer-1**-Stufe") and (b) `routing.py:37-43` ("SONARQUBE_GATE: **Layer-1** deterministic SonarQube-Green-Gate ... sequenced AFTER the adversarial layer") / `routing.py:53-55`. | **FIXED in-place**: both spots now separate "Adversarial (Schicht 3)" from "SonarQube-Gate-Stufe (nachgelagerte [deterministische] Layer-1-Konvergenzstufe)". |

## Before/after for fixed findings

- **F1** `37_...md` Owner-Hinweis:
  - before: `> vermerkt explizit "Ersetzt den v2-Namen \`VerifyContext\` (nur zwei Werte)").`
  - after: `> vermerkt explizit "Replaces the v2 name \`VerifyContext\` (only two values)", > d. h. das v2-Enum \`VerifyContext\` mit nur zwei Werten ist ersetzt).`
- **F2** (4x, FK-37:112/211/342 + FK-38:176):
  - before: `core_types/qa_context.py:15-31`
  - after: `core_types/qa_context.py:15-30`
- **F3a** `37_...md` §37.1.4 pseudocode:
  - before: `# KEIN Structural (Schicht 1), KEIN Adversarial/SonarQube-Gate (Schicht 3).`
  - after: `# KEIN Structural (Schicht 1), KEIN Adversarial (Schicht 3), / # KEINE SonarQube-Gate-Stufe (nachgelagerte Layer-1-Konvergenzstufe, §37.1.5).`
- **F3b** `37_...md` §37.1.5:
  - before: `**ohne** Structural (Schicht 1) und **ohne** Adversarial/SonarQube-Gate (Schicht 3) — gemaess`
  - after: `**ohne** Structural (Schicht 1), **ohne** Adversarial (Schicht 3) und **ohne** die SonarQube-Gate-Stufe (nachgelagerte deterministische Layer-1-Konvergenzstufe, s. Hinweis unten) — gemaess`

## Verified clean (adversarially checked, no defect)

1. **§37.1.7 ReviewBundle representation (AK2):** opened `verify_system/llm_evaluator/bundle.py` and counted the fields myself. `class ReviewBundle` at `bundle.py:34`, field block `:55-66` = exactly **12 fields**: `story_id: str`, `story_brief_excerpt: str`, `acceptance_criteria: list[str]`, `diff_summary: str`, `diff_content: str`, `concept_excerpt: str = ""`, `concept_refs: list[str]`, `arch_references: str = ""`, `evidence_manifest: BundleManifest | dict[str, object] | str | None = None`, `packing_protocol: dict[str, tuple[str, ...]] = Field(default_factory=dict)`, `previous_findings: list[Finding] | None`, `qa_cycle_round: int`. The §37.1.7 table matches **exactly** in count, names, types, defaults and order; `frozen=True, extra="forbid"` claim matches `bundle.py:53`. Anchors `:34-66`, `:62-63` (arch_references/evidence_manifest), `:110-182` (`build_review_bundle`) all land correctly. Mapping claims (`story_spec` -> `story_brief_excerpt`, `handover` -> `diff_content`) match the `build_review_bundle` docstring/body (`:125-128`, `:171-174`). The "present, filled post-AG3-067, no open code need" classification is correct — no false open-need and no false done-claim.
2. **Routing fidelity (AK7):** `routing.py:56-76` verified — `_IMPLEMENTATION_LAYERS = (STRUCTURAL, LLM_EVALUATOR, ADVERSARIAL, SONARQUBE_GATE, POLICY)`, `_EXPLORATION_LAYERS = (LLM_EVALUATOR, POLICY)`, `_ROUTING_TABLE` `:71-76`. The §37.1.0 table, §37.1.2 table, §37.1.4 invariant and §37.1.5 mirror this exactly; **no** "all four values => full 4-layer QA" generalization exists anywhere in §37.1. Anchors `routing.py:12-14,65-68,74-75` and `:37-49` verified line-accurate.
3. **Eligibility (AK8):** no surviving categorical "Exploration nie/nicht via QA-Subflow" statement. Remaining "nie"/"nicht via" hits at `37_...md:162`, `:178`, `:364` are explicit supersession narration ("fruehere Aussage ... ueberholt/nicht mehr zutreffend"); `:404` and `:723` are unrelated. Both trigger/depth tables (§37.1.0, §37.1.2) cover all four `QaContext` contexts with the correct per-context depth. The `mode` argument (§37.1.1, BB2-057) and the impl-internal trigger logic are preserved intact.
4. **Symbol discipline (AK1/AK3):** word-boundary scan — every remaining `VerifyContext` token in FK-37 (`:106-107`, Owner-Hinweis quote, `:116`, `:206`) and FK-38 (`:176`) is pure supersession narration ("abgeloest/ersetzt/loest ab/nicht das abgeloeste"), never live/normative usage. `VerifyContextBundle` verified at `contract.py:136` (class definition lands on that exact line) and is correctly classified in the Owner-Hinweis as the separate, valid `ctx` run-context carrier — not a replacement target.
5. **Authoritative contract:** `bc-cut-decisions.md:84-101` = "QA-Subflow-Vertrag" heading (84) + `run_qa_subflow(..., qa_context: QaContext, ...)` (94) + the four QaContext values (100-101); `:76-79` = "Output-QA wird interner Subflow innerhalb produktiver Phasen (Exploration und Implementation)". Both anchors land as claimed.
6. **Payload/phase anchors:** `ImplementationPayload.verify_context: QaContext | None = None` verified at `pipeline_engine/phase_executor/models.py:144`; FK-37 correctly defers the payload model to FK-39 §39.2.3 (`39_phase_state_persistenz.md:292`) and cites no stale path. `_verify_context_for` (`implementation/phase.py:731-734`) maps only to `IMPLEMENTATION_INITIAL`/`IMPLEMENTATION_REMEDIATION`, consistent with the FK prose (FK-37 cites no phase.py lines, so nothing to fix). Cross-refs FK-33 §33.8.3 (`33_...:918`) and FK-29 §29.1.1 (`29_...:188`) exist.
7. **Scope (AK6 / out-of-scope discipline):** §37.2/§37.3 are only referenced with Owner AG3-067, §37.1.3 untouched (Owner AG3-069); nothing is falsely described as done. `git show 14a931d --stat` touched only `concept/technical-design/37_*.md`, `concept/technical-design/38_*.md` and the story `status.yaml` — **no** `src/` or `tests/` file. My fixes are likewise doc-only (FK-37, FK-38, this commentary file).
8. **ARCH-55 (AK5):** all identifiers/enum values/field names in the new prose are English; no German keys introduced.

## Residual observations (left as-is, with reason)

- **O1** (`37_...md:97-99`, §37.1.0 table): `verify_context` is framed as the ImplementationPayload field while the table also keys the `EXPLORATION_*` rows under the `verify_context` column; in code the exploration contexts travel as the `qa_context` **parameter** of `run_qa_subflow` (`qa_cycle/integration.py:32-43`), `ExplorationPayload` carries no such field. Left as-is: the story spec (AK8/§2.1.1) mandates exactly this table shape, the head Entscheidung already states the field lives on `ImplementationPayload`, and the payload model is normatively FK-39's scope — no contradiction with code, only a framing nuance.
- **O2** (`38_...md:205`): "Danach laufen alle vier QA-Subflow-Schichten vollstaendig von vorne" — true for the implementation-scoped remediation loop this section describes (`PhaseMemory.implementation.qa_feedback_rounds`); outside AG3-101's FK-38 scope (only `:176`). Left as-is.
- **O3** (`concept/_meta/bc-cut-decisions.md:92`): the authoritative contract pseudocode shows `ctx: StoryContext` while the real signature is `ctx: VerifyContextBundle` (`verify_system/system.py`). Drift inside the meta doc itself, outside FK-37/FK-38 and outside this story's lane — flagged for the orchestrator, not edited.
- **O4** (story spec `story.md` §1): cites `story_context_manager/models.py:136` for `ImplementationPayload.verify_context`; the model actually lives at `pipeline_engine/phase_executor/models.py:144` (no `verify_context` in story_context_manager). The FK prose carries no such anchor, so no concept fix needed; the spec text was not rewritten (spec ≠ deliverable).

## Gate evidence (post-fix)

- `check_concept_frontmatter.py` -> `[concept-frontmatter] OK: 88 docs, all lints passed.` (exit 0)
- `compile_formal_specs.py` -> `[formal-spec] OK: 186 documents, 1558 ids, 1913 references, 128 scenarios, 437 prose links` (exit 0)
- `check_architecture_conformance.py` -> `[architecture-conformance] OK: no architecture contract violations` (exit 0)
- `check_concept_code_contracts.py` -> `[concept-code-contracts] OK: no truth-boundary contract violations` (exit 0)
- `src`/`tests`: untouched by AG3-101 and by this review. (The working tree currently carries unrelated `src/agentkit/story_context_manager/*` + test changes from the concurrent AG3-074 worker — not part of 14a931d and not touched here.)

## Verdict

POST-FIX STATE: **clean** — 3 Minor findings (F1 quote fidelity, F2 off-by-one anchors, F3 SonarQube-gate layer classification), all FIXED in-place and re-gated green; no Major or Blocker findings; residual-open: O3 (`bc-cut-decisions.md:92` `ctx: StoryContext` drift, orchestrator decision) and O4 (story-spec anchor nit, informational only). Nothing blocking remains for AG3-101.
