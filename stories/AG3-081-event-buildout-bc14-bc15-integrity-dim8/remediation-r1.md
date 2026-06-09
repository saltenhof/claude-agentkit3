# AG3-081 — Remediation R1 (after hostile Codex review `review-r1.md`)

**Scope of this remediation:** story authoring only. Edited files: `story.md`, `status.yaml`, and this `remediation-r1.md`. **No production code, tests, or `concept/` files were touched.** All findings below were resolved inside the story (or explicitly routed to the owner story named in `var/concept-gap-analysis/_STORY_INDEX.md`). Cut/scope kept strictly within the `_STORY_INDEX.md` AG3-081 row (BC14/BC15 EventTypes + emitters/contract, telemetry-evidence wiring, typed `phase_state_projection`, `guard_invocation_counters` hot-path, fc_*/read-model reset-purge half, hook-table↔code consistency).

All code anchors were re-verified against the real tree and corrected where the original story was wrong (see "Code-anchor corrections" at the end).

---

## Must-Fix ERROR list (from review §"Must-Fix ERROR List")

### ERROR 1 — Remove/redefine "Dim 8"
**Finding:** Story called the work "Integrity-Gate-Dim-8", but in the real gate Dimension 8 is `TIMESTAMP_INVERSION` (`governance/integrity_gate/dimensions.py:18`, `_dimension_specs.py`; FK-35 §35.2.4 Z. 274). The label was ambiguous/wrong.
**Resolution:** Eliminated the term "Dim 8" throughout the story. The work is now consistently named **"Telemetry-Evidence-Block (FK-68 §68.4)"** — the six Closure telemetry proofs that the Integrity-Gate checks against the `execution_events` stream. Title (story.md heading + `status.yaml.title`) changed to "…Telemetry-Evidence-Wiring…". A new §1 "Naming-Klarstellung" explicitly contrasts FK-68 §68.4 (this story) vs. FK-35 §35.2.4 `TIMESTAMP_INVERSION` (not this story). The misleading docstring "Dim 8" still present in `telemetry_contract.py:11` is flagged as a code-reality and routed doc-only to **AG3-103** (no new "Dim 8" coined here).
**Quell-Anker:** FK-68 §68.4 (Z. 565-585) is the canonical source for the six proofs; there is no FK-68 "§68.10 Dim 8" — §68.10 is the preflight contract extension. Quell-Konzepte list corrected accordingly.

### ERROR 2 — Reset-purge scope must follow FK-69
**Finding:** Story demanded deleting "the fc_*/read-model rows … completely". FK-69 §69.9 (Z. 365-375) requires: delete `fc_incidents`, recompute/correct `fc_patterns` (patterns are NOT deleted), leave `fc_check_proposals` untouched (FK-41 §41.3).
**Resolution:** §1, §2.1.7, §2.2 and AC6 rewritten to the exact FK-69 §69.9 semantics: `fc_incidents` deleted (already done in `purge_run`), `fc_patterns` recompute/correct → routed to **AG3-082** (recompute half), `fc_check_proposals` untouched (accessor already refuses it fail-closed, `projection_accessor.py:109-110`). AC6 now asserts `fc_check_proposals` stays untouched and that patterns are not deleted.

### ERROR 3 — Wrong Ist-Zustand on reset-purge; existing `purge_run` is the baseline
**Finding:** Story claimed reset-purge "not findable as a central job"; in reality `ProjectionAccessor.purge_run()` exists centrally (`projection_accessor.py:405`) and already purges QA tables, story_metrics, fc_incidents, phase_state_projection (best-effort) and risk_window.
**Resolution:** §1 Ist-Zustand corrected to state the central job exists and what it already covers (with line anchors 405-486, 459-461). The story now works the **delta** to FK-69 §69.9, not a new purge service. §2.1.7 explicitly says "extend/verify the existing `purge_run`, no parallel purge service". The AG3-081 delta is reframed as: the NEW BC14/BC15 events in the run-scoped `execution_events` stream + completeness-verification of `purge_run` against the FK-69 §69.3 table list + the new counter rows.

### ERROR 4 — `phase_state_projection` ownership conflict
**Finding:** Story demanded "write/read ownership via ProjectionAccessor", but the code marks `PHASE_STATE_PROJECTION` as externally owned by `pipeline_engine.PhaseExecutor` and refuses accessor ownership fail-closed (`projection_accessor.py:105-111`, `:398-403`).
**Resolution:** §1 documents the real ownership (PhaseExecutor, FK-69 §69.4, accessor fail-closed refusal). §2.1.5 + AC4 now keep write-ownership at `pipeline_engine.PhaseExecutor` and require the typed frozen record to be defined **at the pipeline owner**, with the telemetry-side union (`projection_records.py:36-37`) merely referencing it instead of `dict[str, object]`. **No ownership migration** is requested. The field-set/ownership home is routed to **AG3-059** (PhaseStateCore field-set + ownership) in §2.2 — this story only provides the typed record type and flips the union; AG3-059 stays in `_STORY_INDEX.md` (Welle 0). AC4 asserts the accessor refusal is unchanged.

### ERROR 5 — AC5 must cover all four FK-61 flush triggers
**Finding:** Scope named Closure/Week-Rollover/Housekeeping/Reset but AC5 tested only Closure/Reset; FK-61 §61.4.3 (Z. 219-229) requires all four.
**Resolution:** AC5 rewritten to require all four flush triggers wired and each individually tested: (1) Closure, (2) Week-Rollover, (3) Housekeeping (>24h without update), (4) full story-reset. §2.1.6 matches. The `fact_guard_period` drain itself remains routed to **AG3-082**.

### ERROR 6 — "Emitter" vs AG3-099 out-of-scope conflict
**Finding:** Scope 2.1.1 demanded "Enum-Member + Emitter" while Out-of-Scope said the planning emitters are AG3-099.
**Resolution:** Removed "Emitter" from the in-scope BC14/BC15 deliverable. §2.1.1/§2.1.2 now deliver **Enum-Member + Mandatory-Payload-Contract (catalogue + contract) only**; the fachliche planning emitters are explicitly **AG3-099** (§2.2). Title changed from "…+ Emitter" framing to catalogue/contract framing. No emitter work remains in this story's scope.

### ERROR 7 — AC3/AC5 must make every required proof and every affected hook testable
**Finding (AC3):** "Dim 8" claimed six proofs but a negative test for only three classes — not complete or unambiguously testable.
**Resolution (AC3):** AC3 now requires **one concrete, named negative test per proof class** (six): agent-pairing, llm-role-coverage, review-compliance, integrity_violation-present, web_call-over-budget, preflight-balance — each asserting Closure blocks.
**Finding (AC5):** "Jeder Guard-Hook" was not operationalised — no hook files/registry paths named.
**Resolution (AC5):** The "every guard hook" requirement is operationalised against the **single deterministic dispatch point** all PreToolUse guards flow through: `governance/guard_evaluation.py:evaluate_pre_tool_use` (line 85), invoked via `governance/runner.py:run_hook` (line 536) and CLI `governance/hookruntime.py`. Placing the UPSERT there guarantees "every guard" is counted without per-guard scattering; AC5 names this path and requires a test with two distinct guards → two counts and a block → blocks+1. §2.1.6 + §6 hints match.

---

## WARNINGS (from review §1 and §2)

### WARNING — Mandatory payloads from FK-68 not hard-listed; ARE conflict undecided
**Resolution:** Added two explicit tables to §2.1.1 (eight BC14 events) and §2.1.2 (three BC15 events) listing the exact FK-68 §68.2.2 mandatory fields per event (e.g. `dependency_recorded` → `story_id`, `depends_on_id`; `are_gate_result` → `story_id`, `result`). The FK-68-vs-FK-61 ARE conflict (`MANDATORY_PAYLOAD_FIELDS_BY_NAME["are_gate_result"]` carries `covered`/`required`/`coverage_ratio` from FK-61 §61.12.2 at `events.py:231`) is now owner-decided in §2.1.3: the `telemetry`-BC owns the SSOT; the FK-68 catalogue is canonical (`story_id`, `result` mandatory), the FK-61 metric fields stay **optional/enriched**. The doc-side FK-61 prose alignment is routed to **AG3-103** (already covers FK-68 §68.2 in `_STORY_INDEX.md`). AC2 makes this testable (one mandatory set per event-name; a contract test proves the metric fields are optional).

### WARNING — AC2 "single documented truth" not testable
**Resolution:** AC2 now names the concrete target location (`MANDATORY_PAYLOAD_FIELDS_BY_NAME` + Enum-contract in `telemetry/events.py`) and requires a contract test proving exactly one mandatory set per event-name and no second string-map path.

### PASS-with-note (review §4) — anchors exist
No action required; the confirmed-correct anchors (FK-68 §68.2/§68.4, FK-69 §69.3/§69.9, FK-61 §61.4.3, and the EventType/BC15/TelemetryContract/ProjectionRecord/GuardCounter Ist-Zustand claims) were retained and tightened.

---

## Code-anchor corrections applied in story.md

| Claim in original story | Reality (verified) | Fix in rewrite |
|---|---|---|
| `events.py:230` for `are_gate_result` pinning | `MANDATORY_PAYLOAD_FIELDS_BY_NAME` map at `events.py:229`; `are_gate_result` key at `events.py:231` | Cited `events.py:231` (key) and `:229` (map / `validate_event_payload`) |
| `GuardInvocationCounter` in `fact_store/models.py:148` | Real path `kpi_analytics/fact_store/models.py:148` (no top-level `fact_store/`) | Corrected to `kpi_analytics/fact_store/models.py:148` |
| `postgres_schema.sql:902` (table) / Z. 898-901 (comment) | Confirmed: table at `:902`, follow-up comment Z. 898-901 | Kept; added `state_backend/` prefix |
| Reset-purge "not findable as central job" | `ProjectionAccessor.purge_run()` at `projection_accessor.py:405-486` | Rewritten to cite the existing job and work the delta |
| "Schreib-/Lese-Ownership ueber ProjectionAccessor" for phase_state | Externally owned by PhaseExecutor; accessor refuses (`projection_accessor.py:105-111`, `:398-403`) | Ownership kept at PhaseExecutor; anchors added |
| FK-68 §68.10 used for the six proofs | The six proofs are FK-68 **§68.4** (Z. 565-585); §68.10 is the preflight contract extension | Quell-Konzepte + body re-anchored to §68.4 |
| Integrity "Dim 8" | FK-35 §35.2.4 Dim 8 = `TIMESTAMP_INVERSION` (`dimensions.py:18`) | Renamed to "Telemetry-Evidence-Block (FK-68 §68.4)"; FK-35 cross-ref added |
| Guard hot-path "in `governance/guards/`" (per-guard) | Single dispatch `governance/guard_evaluation.py:evaluate_pre_tool_use:85` via `runner.py:run_hook:536` | AC5/§2.1.6/§6 point the UPSERT at the central dispatch |

## status.yaml change
- `title` updated to drop the ambiguous "Integrity-Dim-8-Wiring" → "Telemetry-Evidence-Wiring, Reset-Purge-Delta" (matches the corrected story.md heading). No other field was wrong (`type: implementation`, `size: L`, `depends_on: [AG3-035, AG3-037]`, `phase: review_pending` all consistent with `_STORY_INDEX.md`).

## Note (not changed; flagged)
The story **directory name** still contains `…-integrity-dim8`. Renaming it is out of scope for "story.md/status.yaml only" and would break the path references in `review-r1.md` and `_STORY_INDEX.md`. The `story_id` (AG3-081) is unaffected. If a rename is desired, it should be a separate, explicit task.
