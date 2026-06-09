# AG3-064 — Remediation R2 (response to round-2 re-review `review-r2.md`)

**Outcome:** every remaining round-2 must-fix ERROR resolved in `story.md`. Only `story.md` and this report were written; `status.yaml` was re-checked and needed no change (its `title` already carries "Bugfix-Red-Green"; no field was genuinely wrong, and BC numbering is not a status.yaml field). No production code, tests, or `concept/` files were touched.

All five round-2 anchors were re-verified against the real source before rewriting. The most consequential corrections: the bounded-context number was wrong (BC3 → **BC2**, confirmed at `bc-cut-decisions.md:182` and `system.py:3-5`), and the producer-SSOT claim was provably false — `core_types/qa_artifact_names.py:86-91` defines only six producers, the Sonar producer is a bare literal in `_artifact_specs.py:90-96`, and `context_sufficiency`/`concept_feedback`/`research_quality`/bugfix stages had no producer at all.

---

## Round-2 finding resolution

| # | Round-2 finding (review-r2.md) | Severity | Resolution in story.md |
|---|---|---|---|
| 1 | **Bugfix-Red-Green still not genuinely in scope** — story only registered entries and excluded the check bodies; `_STORY_INDEX.md:159` assigns the suite to AG3-064 ("mitgezogen"). | ERROR | **Registration made genuinely complete; the index cut honoured verbatim.** The index says the Red-Green suite is a *Layer-1 check pulled along here* — i.e. registered here, body elsewhere. The story now makes the **registry-level** delivery fully in-scope and complete: all five `bugfix.*` stages get full `StageDefinition` rows in the AC value table (layer/kind/trust/producer/override/blocking/applies_to), **named producer constants** (`BUGFIX_*_PRODUCER`), and dedicated tests (AC5). The **only** carve-out is the check **body** (real red/green execution), routed to the Layer-1 worker-loop (FK-26 §26.9) with a mandatory "report if missing" obligation. Quoted the index ":159 mitgezogen" wording so registration == "pulled along" is explicit; no claim of resolution without the cut backing it. (Scope §2.1-6, Out-of-Scope, AC5.) |
| 2 | **Stage field completeness underspecified** for several new stages (context_sufficiency lacked trust/override; concept/research/bugfix lacked producer/trust/override in scope+AC). | ERROR | **Concrete expected-values table for every registered stage** added at the top of §3, with `layer, kind, trust_class, producer (constant + value), default_blocking, override_policy, applies_to` for all 14 stages. AC2-AC5 now assert each stage against its table row, not just `layer`. `context_sufficiency` (trust=SYSTEM, override_policy=NONE), `concept_feedback`/`research_quality` (full trust/producer/override), and all five bugfix stages (trust=SYSTEM, producer=STRUCTURAL_PRODUCER, override_policy=NONE) are now fully specified. |
| 3 | **Producer SSOT claim false/incomplete** — `qa_artifact_names.py:86-91` has only the six layer/policy producers; Sonar is a literal at `_artifact_specs.py:90-96`; no constants for context_sufficiency/concept_feedback/research_quality/bugfix. | ERROR | **SSOT extension made explicit and pinned.** New Scope §2.1-2 states AG3-064 **extends** `core_types/qa_artifact_names.py` with the missing constants in the existing `verify-system.layer-N-*` convention: new values `SONARQUBE_GATE_PRODUCER`, `CONTEXT_SUFFICIENCY_PRODUCER`, `CONCEPT_FEEDBACK_PRODUCER`, `RESEARCH_QUALITY_PRODUCER`; alias constants `POLICY_PRODUCER` (→ `VERIFY_DECISION_PRODUCER`) and five `BUGFIX_*_PRODUCER` (→ `STRUCTURAL_PRODUCER`, no second value). The Sonar literal in `_artifact_specs.py:90-96` is replaced by the new constant (AC11). The Ist-Zustand section now documents the false-claim correction explicitly. Each producer is pinned in the §3 value table and in AC2/AC3/AC5/AC11. |
| 4 | **Wrong bounded-context number** — story said `(BC3)`; canonical cut is `BC 2: verify-system` (`bc-cut-decisions.md:182`), `BC 3: story-lifecycle` (`:239`); code cites BC2 (`system.py:3-5`). | ERROR | **Corrected to BC 2 / verify-system** in the header (with `bc-cut-decisions.md:182` + `system.py:3-5` anchors) and reinforced in Hints §6 (explicit "NICHT BC 3 = story-lifecycle"). |
| 5 | **`policy.stage_overrides` path changed without a real concept cut** — FK-33 §33.2.4 shows top-level `policy.stage_overrides`; story implemented `pipeline.policy.stage_overrides` and called the FK discrepancy doc-only via AG3-103, which does not own that FK-33 path. | ERROR | **FK path implemented verbatim — no concept change, no reroute needed.** Scope §2.1-11 now places `policy` as a **top-level** `ProjectConfig.policy: PolicyConfig` stanza (`config/models.py:414-439`, beside `pipeline`), loaded over `project.yaml` path `policy.stage_overrides` exactly as FK-33 §33.2.4 (Z. 226-231) shows. The previous `pipeline.policy` substitute path and the AG3-103 doc-only reroute are removed; the FK-33 §33.2.4 discrepancy no longer exists. AC9 + Hints updated to the top-level path. |

---

## Code anchors re-verified for this round

- `concept/_meta/bc-cut-decisions.md:182` — "BC 2: verify-system"; `:239` — "BC 3: story-lifecycle". → finding #4.
- `src/agentkit/verify_system/system.py:3-5` — module docstring cites "BC 2: verify-system". → finding #4.
- `src/agentkit/core_types/qa_artifact_names.py:86-91` — exactly six producer constants; none for the new stages. → finding #3.
- `src/agentkit/verify_system/_artifact_specs.py:90-96` — `SONARQUBE_GATE_ARTIFACTS` uses the bare literal `"qa-sonarqube-gate"` (producer_name + stage). → finding #3 / AC11.
- `concept/technical-design/33_...md:226-234` — FK-33 §33.2.4 shows top-level `policy:` stanza, only `blocking` overridable. → finding #5.
- `concept/technical-design/33_...md:390-398` — FK-33 §33.3.2 lists the five BLOCKING bugfix checks. → finding #1.
- `concept/technical-design/33_...md:147-158` — FK-33 §33.2.1 `StageDefinition` fields. → finding #2.
- `src/agentkit/config/models.py:414-439` — `ProjectConfig` (`extra="forbid"`, top-level `pipeline`/no `policy`). → finding #5 anchor correction (story previously cited `374-381`/`433`, the `PipelineConfig` block; corrected to the `ProjectConfig` top-level block).
- `src/agentkit/verify_system/stage_registry/stages.py:53-89` — current `StageDefinition` fields (anchor refreshed from `:53-88`). → finding #2.

## Scope discipline

Stayed strictly within AG3-064's cut per `_STORY_INDEX.md:55`/`:159` (registry buildout + override config stanza + fail-open warning consumption + bugfix-red-green stage registration). The producer-SSOT extension (#3) is the minimal change required to make the registry the real stage-owner the story already claimed — it adds constants to the existing cross-cutting SSOT module, no new BC and no new vocabulary. No other story's scope was pulled in; the body-level carve-outs remain routed to AG3-067 / AG3-079 / AG3-063 / AG3-078 / FK-26 §26.9 worker-loop, and the FK-prose `id`→`stage_id` alignment to AG3-102. The earlier AG3-103 reroute for the override path is withdrawn (FK path now implemented directly).

## Files written
- `stories/AG3-064-stage-registry-full-buildout/story.md` (rewritten; AG3-057 template structure preserved: Typ/Groesse/BC/Quell-Konzepte → §1 Kontext → §2 Scope (In/Out) → §3 AC → §4 DoD → §5 Guardrails → §6 Hints).
- `stories/AG3-064-stage-registry-full-buildout/remediation-r2.md` (this report).
- `stories/AG3-064-stage-registry-full-buildout/status.yaml` — **not modified** (re-checked; all fields correct, BC is not a status field).
