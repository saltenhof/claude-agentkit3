# AG3-064 — Remediation R1 (response to hostile Codex review `review-r1.md`)

**Outcome:** every must-fix ERROR resolved in `story.md`; every WARNING either fixed in the story or routed to its owner story. Only `story.md`, `status.yaml`, and this report were written. No production code, tests, or `concept/` files were touched.

All code anchors in `review-r1.md` were re-verified against the real source. The most consequential correction: `TrustClass` lives in `verify_system/protocols.py:173-186` (values A/B/C), **not** `policy_engine/trust.py` (which only imports + weights it). The old story.md cited the wrong file in three places — all corrected.

---

## Section 1 — Konzept-Vollstaendigkeit

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 1 | Bugfix-Red-Green out of scope (story.md:43); index `_STORY_INDEX.md:159` assigns it to AG3-064; FK-33:390-398 lists the 5 bugfix checks. | ERROR | **Brought into scope.** New Scope §5 + AC5 register `bugfix.reproducer_manifest`/`red_evidence`/`green_evidence`/`suite_evidence`/`red_green_consistency` as Layer-1 `StageDefinition`s (`applies_to={BUGFIX}`, BLOCKING). The **check-body** (real red/green execution) is bounded out as Layer-1/Worker-loop (FK-26 §26.9) and must be *reported*, not silently dropped — staying within the index cut (registry buildout only). |
| 2 | Trust-Class validation missing; FK-33:501-505 forbids any stage with `trust_class "C"` as `blocking:true`; story only required the field. | ERROR | **Reject path added.** Scope §9 + AC8: fail-closed validation at registry construction AND after `stage_overrides` application; two tests (definition + override). |
| 3 | §33.2.3 Stage-ID = `artifact_kind`/filename not covered; code uses `doc_fidelity.json`/`decision.json` (`qa_artifact_names.py:36,60-66`). | ERROR | **Migration/compat rule specified.** Scope §12 + AC11: `stage.id` IS the `artifact_kind`; canonical reference is `ArtifactRecord(kind = stage.id)`; legacy filenames stay export-only (§33.2.3 Z.215-219). |
| 4 | concept/research too coarse; FK-33:940-959 names `concept.structure/completeness/sparring/vectordb`, `research.structure/sources/assessment`; story only had `concept_feedback`/`research_quality`. | WARNING | **Fixed in story + routed.** Scope §4 keeps the two aggregating registry stages here (so `stages_for` is fail-closed non-empty); the fine subchecks are Layer-1 check-*bodies*, explicitly Out of Scope and routed to the concept/research check story (AG3-078 / dedicated check story) with a "must report if missing" obligation. |

## Section 2 — AC-Schaerfe

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 5 | AC2 tested only `layer` (story.md:48); FK-33:147-158 wants kind/blocking/trust_class/producer/execution_policy/override_policy. | ERROR | **Per-field value table.** AC2 now asserts each stage against an expected-values table for `layer/kind/trust_class/producer/blocking/applies_to`; AC3 (context_sufficiency) likewise. |
| 6 | AC5 only `_LAYER_NAME_TO_NUMBER`; code also has `_SYSTEM_LAYER_NAME_TO_NUMBER` and `_KIND_TO_LAYER_NUMBER` (`system.py`). | ERROR | **All mapping sources addressed.** Scope §6 + AC6: all three SSOTs (`engine.py:382-391`, `system.py:1458-1466`, `system.py:1518-1524`) replaced by registry knowledge; inventory part of acceptance. |
| 7 | AC7 no testable PolicyWarning contract; `decide()` takes only `LayerResult` (`engine.py:190-198`); `VerifyDecision` has no warning field (80-106). | ERROR | **Contract defined.** Scope §11 + AC10: new `PolicyWarning(stage_id, detail, source_artifact)` + `VerifyDecision.warnings`; four tests (missing/sufficient/partial/malformed). |
| 8 | AC1 "blocking without breaking severity" unclear. | WARNING | **Invariant fixed.** Scope §1 + AC1: `default_blocking = severity == BLOCKING`; `effective_blocking` after override. |

## Section 3 — Klarheit/Eindeutigkeit

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 9 | `id` vs `stage_id` unresolved (FK-33:149 `id`; `stages.py:82` `stage_id`). | ERROR | **Decided.** Scope §1: field stays `stage_id` (existing SSOT, the `artifact_kind`); `@property id` alias for §33.2.1 fidelity; FK-prose alignment is doc-only → **AG3-102**. |
| 10 | `doc_fidelity_impl` collides with `doc_fidelity` (`qa_artifact_names.py`, `engine.py:387`). | ERROR | **Canonical ID + legacy alias rule.** Scope §12 + AC11: canonical stage-ID `doc_fidelity_impl` mapped onto the existing `DOC_FIDELITY_*` producer/export; layer-name `doc_fidelity` retained — no break. |
| 11 | Wrong TrustClass anchor (story said `policy_engine/trust.py`; real `verify_system/protocols.py:173-186`). | ERROR | **Anchor corrected** everywhere (Context §, Scope §1/§9, Hints). Explicit note that `trust.py:12` only imports/weights it. |
| 12 | Producer-IDs ambiguous (FK-33:164-176 `qa-*`; code `verify-system.layer-*` in `qa_artifact_names.py:79-91`). | WARNING | **Existing producer SSOT reused.** Scope §2 + Hints: reuse `core_types/qa_artifact_names.py` producer constants; FK `qa-*` prose is doc-only → **AG3-102**. No new producer vocabulary. |

## Section 4 — Kontext-Sinnhaftigkeit

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 13 | `policy` as blocking stage breaks flow; VerifySystem skips `QALayerKind.POLICY` (`system.py:596-598`), calls `decide()` after (650); blocking `policy` → `_missing_stage_findings` sees a traversed stage without LayerResult (`engine.py:328-351`). | ERROR | **`policy` exempted.** Scope §8 + AC7: `policy` stage excluded from the missing-stage check (it produces the aggregate itself, has no upstream LayerResult); stays registered for owner completeness. |
| 14 | Missing-stage check is layer-based (`engine.py:394-401`); a `structural` result masks a missing `sonarqube_gate` (both layer 1). | ERROR | **Stage-ID/Producer based.** Scope §7 + AC7: check against produced stage-/artifact-set (`ArtifactRecord(kind=stage.id)`/producer), not layer number; explicit `structural`-doesn't-mask-`sonarqube_gate` test. |
| 15 | "Registry replaces engine layer table" incomplete — beyond `_LAYER_NAME_TO_NUMBER` also `system.py:1504-1524`. | ERROR | Same fix as #6 — all three layer truths inventoried and replaced. |
| 16 | Config-owner for `policy.stage_overrides` unspecified; `ProjectConfig` forbids extra fields (`config/models.py:433`); `PipelineConfig` has no policy field (374-381). | WARNING | **Owner specified.** Scope §10 + AC9: new `PolicyConfig`/`StageOverride` (`blocking` only, `extra="forbid"`) at `PipelineConfig.policy`, YAML path `pipeline.policy.stage_overrides`, loader tests + unknown-stage fail-closed; FK top-level-`policy:` prose alignment doc-only → **AG3-103**. |

---

## Must-Fix ERROR checklist (review-r1.md bottom block)

1. Bugfix-Red-Green scope → **resolved** (#1, Scope §5/AC5; bodies routed).
2. Trust-C/blocking fail-closed → **resolved** (#2, Scope §9/AC8).
3. artifact_kind/filename migration §33.2.3 → **resolved** (#3, Scope §12/AC11).
4. AC for ALL stage fields → **resolved** (#5, AC2/AC3 value tables).
5. PolicyWarning contract + input path → **resolved** (#7, Scope §11/AC10).
6. id/stage_id, doc_fidelity_impl/doc_fidelity, Producer-SSOT → **resolved** (#9/#10/#12).
7. `policy` self-missing + layer-based missing-stage check → **resolved** (#13/#14, Scope §7+§8/AC7).
8. All layer-mapping SSOTs (not just `_LAYER_NAME_TO_NUMBER`) → **resolved** (#6/#15, Scope §6/AC6).

## WARNING disposition

- #4 concept/research granularity → fixed in story + routed to concept/research check story (AG3-078/dedicated).
- #8 blocking-vs-severity invariant → fixed (AC1).
- #12 producer ambiguity → reuse existing SSOT; FK prose → AG3-102 (doc-only).
- #16 override config owner → fixed (PolicyConfig); FK prose → AG3-103 (doc-only).

## Scope discipline (per `_STORY_INDEX.md`)

Stayed strictly within AG3-064's cut: registry buildout + override config stanza + fail-open warning consumption. Routed outward without expansion: builder → AG3-067, adversarial runtime → AG3-079, conformance logic → AG3-063, config-version/feature-matrix → AG3-070, FK-prose alignment → AG3-102/103, concept/research + bugfix check-*bodies* → respective Layer-1 check stories. No other story's scope was pulled in.

## Files written
- `stories/AG3-064-stage-registry-full-buildout/story.md` (rewritten, AG3-057 template structure preserved)
- `stories/AG3-064-stage-registry-full-buildout/status.yaml` (title widened to include Bugfix-Red-Green; all other fields already correct)
- `stories/AG3-064-stage-registry-full-buildout/remediation-r1.md` (this report)
