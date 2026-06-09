# AG3-079 — Remediation of Codex Review R1

**Outcome of R1:** CHANGES-REQUESTED. All five must-fix ERRORs and both WARNINGs resolved in `story.md`. `status.yaml` verified correct (no field wrong). No production code, tests, or `concept/` files touched.

Scope guard: changes stay strictly within the AG3-079 cut from `_STORY_INDEX.md` (Welle 3, line 80: "Echte Schicht-3-Laufzeit statt Passthrough … Telemetrie-Emission + Integrity-Gate-Pflichtnachweis, Gate-Rueckkopplung Layer 3→2", `depends_on: AG3-044, AG3-065`). No scope expansion; the FK-48 §48.2.2 derivation gap is **routed out**, not absorbed.

---

## Must-fix ERRORs

### ERROR 1 — Producer `qa-adversarial` vs. canonical Code-SSOT
**Finding:** Story demanded producer `qa-adversarial`; code SSOT is `ADVERSARIAL_PRODUCER = "verify-system.layer-3-adversarial"` (`qa_artifact_names.py:90`), with `qa-adversarial` marked illustrative (`:83-90`); Integrity-Gate checks the canonical producer (`dimensions.py:557`).
**Resolution:** Every occurrence of producer `qa-adversarial` replaced by the canonical SSOT constant `ADVERSARIAL_PRODUCER` (= `verify-system.layer-3-adversarial`) and stage `ADVERSARIAL_STAGE` (= `qa-layer-adversarial`). §1 documents the FK-vs-code naming relationship (FK name illustrative, code canonical). §2.1.5, AK5, §5 (SSOT), and §6 now mandate using the constants, never a literal. AK5 adds a pin-test for the values.

### ERROR 2 — Mandatory-target derivation falsely claimed done / out-of-scope
**Finding:** FK-48 §48.2.2/§48.2.3 requires derivation from `assertion_weakness` findings with `addressed_part`; real `derive_targets()` keys off `Severity.BLOCKING` and has no `finding_type`/`addressed_part` (`spawn.py:147`, `:71-76`; `Finding` has no such fields, `protocols.py:206-213`).
**Resolution:** Added an explicit **Schnitt-Klarstellung** block and §2.2 entry. The §48.2.2 FK-conformity (`assertion_weakness` finding-typing, `addressed_part`, `extract_mandatory_targets`, Mandatory-Targets prompt section) is declared a Layer-2 finding-typing gap and **routed to its owner: AG3-067** (Mandatory-Target-Rueckkopplung, FK-37/38; `_STORY_INDEX.md` Welle 1) with the Layer-2 finding/stage modelling hanging on **AG3-064** (Stage-Registry Layer 2). AG3-079 consumes the existing `derive_targets` unchanged and keeps only the runtime parts that genuinely belong here: §48.2.3 prompt section, §48.2.4 `mandatory_target_results` field, §48.2.5 feedback (§2.1.5/§2.1.8). The story no longer claims the derivation is "already done in spawn.py".

### ERROR 3 — `llm_call role=adversarial_sparring` missing from Scope/AC/Gate
**Finding:** FK-11 §11.8.2 mandates telemetry `llm_call` with `role=adversarial_sparring`; story only covered the domain event `adversarial_sparring`.
**Resolution:** §2.1.3 now emits **two** telemetry facts: `EventType.LLM_CALL` with `role=adversarial_sparring` (FK-11 §11.8.2) and `EventType.ADVERSARIAL_SPARRING` with `pool` (FK-48 §48.1.6). AC3 and AC7 require both for the fail-closed sparring proof; the Integrity-Gate check (§2.1.7, AK7) counts both. §1 records that `LLM_CALL` already exists at `telemetry/events.py:45`.

### ERROR 4 — Sandbox/result path contradiction (`{epoch}`)
**Finding:** Story mixed `_temp/adversarial/{story_id}/` and `_temp/adversarial/{story_id}/{epoch}/`; AC5 read `…/{story_id}/result.json` (no epoch). Code SSOT uses `{epoch}` (`spawn.py:196-205`).
**Resolution:** Canonicalised on the code form **with `{epoch}`** everywhere: header source-concept note, §1, §2.1.5 (`_temp/adversarial/{story_id}/{epoch}/result.json`), AK2, and §6. §6 notes the FK prose without `{epoch}` is the simplified rendering; `spawn.py:196-205` is the SSOT.

### ERROR 5 — Wrong Ist-Zustand anchors
**Finding:** `extract_mandatory_targets` does not exist in `spawn.py` (only `derive_targets`); story claimed `_dimension_specs.py` had "no adversarial hit" although it carries `NO_ADVERSARIAL`/`ADVERSARIAL_STAGE`/`ADVERSARIAL_PRODUCER`.
**Resolution:** §1 fully rewritten with verified anchors: `derive_targets` at `spawn.py:127-160` (not `extract_mandatory_targets`); the Adversarial **envelope** gate is **present** (Dim 6 `NO_ADVERSARIAL`, `_dimension_specs.py:37`, check at `dimensions.py:531-565`, producer check `:557`); what is **missing** is the sparring/telemetry proof. `extract_mandatory_targets` is now only named as the FK-spec term to be built by the owner story (§2.2), never as existing code. All other anchors re-verified against the real files and corrected to file:line.

---

## WARNINGs

### WARNING A — AC8 half-testable (no data model / write location / mapping)
**Finding:** "sets the Layer-2 finding to ≥ `partially_resolved`" named no model, write location, or mapping.
**Resolution:** §2.1.8 + AK8 now specify: mapping `target_id == AdversarialTarget.finding_id == f"{finding.layer}.{finding.check}"` (`spawn.py:149`) onto `FindingKey = (layer, check)` (`finding_resolution.py:39`); status field `FindingResolutionStatus.PARTIALLY_RESOLVED` (`finding_resolution.py:71`); written into the existing Resolution/RemediationFeedback model the loop already consumes (`serialize_resolution_map`, FK-34 §34.9) — no new artifact, no new status automaton. Both the unmet and the met (TESTED+PASS / justified UNRESOLVABLE) cases are testable.

### WARNING B — Pool-boundary fallback collides with `depends_on: AG3-065`
**Finding:** "if transport not real yet, keep testable at the pool boundary" contradicted the hard dependency on AG3-065.
**Resolution:** Fallback removed. §2.2 and §6 now treat **AG3-065 as a hard precondition**: AG3-079 consumes the AG3-065 transport surface, builds no second pool adapter and no fallback, and may only start once AG3-065 is available. The LLM/worker boundary remains the single permitted mock boundary in tests (consistent with the MOCKS guardrail), which is the legitimate test seam rather than a production fallback.

---

## Other review notes addressed
- **AC4 sharpness (ERROR under "AC-Schaerfe"):** AC4 split into three concrete deterministic paths over **sandbox-created** tests (valid+pass → `tests/`; valid+fail → `tests/adversarial_quarantine/`; invalid/dry-run-fail/duplicate → stays in sandbox), with an explicit dedup criterion (module-qualified test-name collision against `tests/`). The wording no longer conflates pre-existing repo tests with sandbox-generated tests.

## Files written
- `stories/AG3-079-adversarial-runtime/story.md` — full rewrite (AG3-057 template structure preserved: title, Typ/Groesse/BC/Quell-Konzepte, §1 Kontext, §2 Scope (In/Out-with-owner), §3 Akzeptanzkriterien, §4 DoD, §5 Guardrails, §6 Sub-Agent-Hinweise).
- `stories/AG3-079-adversarial-runtime/remediation-r1.md` — this report.

## Files NOT touched
- `status.yaml` — reviewed; all fields correct (`story_id`, `type=implementation`, `depends_on: [AG3-044, AG3-065]` per `_STORY_INDEX.md`, `phase: review_pending`). No change needed.
- No production code, tests, or `concept/` files modified.
