# AG3-085 — Remediation Report (Review-R1, hostile Codex review)

**Scope of change:** `story.md` rewritten in full (AG3-057 template structure preserved). `status.yaml` checked, no field wrong — left unchanged. No production code, tests, or `concept/` files touched. Story cut/scope from `var/concept-gap-analysis/_STORY_INDEX.md` (Welle 5, AG3-085) respected — no scope expansion.

All anchors below were verified against the real files at the cited line numbers before writing.

---

## Must-Fix ERRORs

### E1 — Rolling-window source: `risk_window` vs FK-35 `execution_events`; forbid in-memory state
**Finding:** Story said consume `risk_window`-Normalisierung and accumulate `current_risk_score`; FK-35 §35.3.1a/§35.3.5 reads `governance_signal` events from `execution_events` and sums `payload.risk_points`, explicitly "kein In-Memory-State".
**Verified:** FK-35 §35.3.5 `current_risk_score(...)` is a SQL `ORDER BY occurred_at DESC LIMIT window_size` query. `telemetry/risk_window/normalized_event.py:6` docstring itself calls the `GovernanceObserver` "out-of-scope" and carries `RiskCategory`, **no `risk_points` field** — so it cannot be the score source.
**Resolution:** Score source is now specified exactly as the FK-35 query against `execution_events` / `event_type == governance_signal` / `payload.risk_points`, read via the existing State-Backend read path (`projection_repositories.py`/`sqlite_store.py`). In-memory rolling buffer explicitly forbidden (Scope 1, AC1 with a test that no in-process state carries the score). The `risk_window`/`RiskCategory` sensor model is explicitly declared **not** the source and **not** consumed; the FK-35↔FK-68 §68.8 overlap is routed as doc-only to **AG3-103**. (Context §1, Scope 1/2.1, AC1, Hinweise.)

### E2 — Cooldown scope wrong/incomplete
**Finding:** Story scoped cooldown to "dieselbe Skopierung" after a measure; FK-35 §35.3.11 scopes by same `signal_type` against the last `governance_adjudication` timestamp.
**Verified:** FK-35 §35.3.11 `should_adjudicate(...)` filters `event_type == governance_adjudication` and `payload LIKE %signal_type%`.
**Resolution:** Cooldown now keyed on `(project_key, story_id, run_id, signal_type)` and based on the last `governance_adjudication` timestamp; other signal types are not blocked; score keeps running (Scope 7, AC5 tests both blocked-same-type and free-other-type).

### E3 — Failure-Corpus handoff overbroad
**Finding:** Story handed "adjudizierte Incidents" to `record_incident`; FK-35 §35.3.9 only severity `medium` or higher; low => telemetry-only.
**Verified:** FK-35 §35.3.9 line 745-746 ("severity: medium oder höher ... in den Failure-Corpus-Eingang").
**Resolution:** Handoff restricted to `severity >= medium`; `low` => no corpus handoff, telemetry only (Scope 8, AC7 tests both cases).

### E4 — AC8 not testable + contradicts event taxonomy
**Finding:** AC8 lumped score/incident/adjudication/measure into one `governance_signal`; FK-91 (Kapitel 35) defines four separate types: `governance_signal`, `governance_adjudication`, `governance_incident_opened`, `governance_measure_applied`. Also the catalog code lacks all four.
**Verified:** `91_api_event_katalog.md:264-267` lists the four distinct types. `telemetry/events.py` `EventType` (read 40-99) has `INTEGRITY_VIOLATION`/`WEB_CALL` etc. but **no** `GOVERNANCE_*`.
**Resolution:** AC8 split by exact event type with required payload fields; event-catalog implementation (the four EventTypes + mandatory payload contracts in `telemetry/events.py`) added to In-Scope (Scope 9), not just producer wiring. Clarified the Observer **consumes** `governance_signal` (produced by AG3-086) and **emits** the other three (Scope 9, AC8).

### E5 — `StructuredEvaluator` is not a ready `governance_adjudication` transport
**Finding:** AC3 assumed a fake evaluator stands in for `governance_adjudication`, but target interface undefined; real `evaluate` takes `ReviewerRole`/`ReviewBundle`/previous findings/QA round and validates CheckResult arrays.
**Verified:** `structured_evaluator.py:299` signature `evaluate(role: ReviewerRole, bundle: ReviewBundle, previous_findings, qa_cycle_round)`; `:126` `ReviewerRole` = only `qa_review`/`semantic_review`/`doc_fidelity`; `:352` `_parse_response` validates a CheckResult JSON array.
**Resolution:** Defined a dedicated, narrow `GovernanceAdjudicator` port in the `governance` BC that materializes the FK-35 §35.3.7 adjudication prompt, sends via the existing LLM-pool transport (owner AG3-065, added to Out-of-Scope deps), and validates against the dedicated `GovernanceAdjudicationVerdict` schema. Explicitly forbids abusing the CheckResult `ReviewerRole`/`evaluate(...)` path and forbids smuggling a value into `ReviewerRole`. Fake only at the LLM boundary (Scope 4/5, AC3, Guardrails, Hinweise).

### E6 — Config keys conflict with FK-93
**Finding:** Story proposed `governance.observer.window_size` etc.; FK-93 §93.5 requires `governance.window_size`, `governance.risk_threshold`, `governance.cooldown_s`.
**Verified:** `93_standardwerte...md:54-58`.
**Resolution:** Keys corrected to the exact FK-93 §93.5 paths everywhere (Scope 1, AC9, Hinweise). No concept-change story needed.

### E7 — Separate governance incident candidate from Failure-Corpus incident candidate
**Finding:** `IncidentCandidate` ambiguous; FK-35 candidate has score/event fields, real `failure_corpus.IncidentCandidate` requires `category`/`severity`/`phase`/`role`/`model`/`symptom`/`evidence`.
**Verified:** FK-35 §35.3.6 candidate fields (lines 654-665); `failure_corpus/incident.py:62` model with required fields at `:95-104`.
**Resolution:** Introduced a distinct `GovernanceIncidentCandidate` (FK-35 fields) plus an explicit mapper to `failure_corpus.incident.IncidentCandidate` filling the mandatory fields (Scope 3/8, AC7, Hinweise).

### E8 — False Ist-Zustand claims + wrong symbol/file names
**Findings & verification:**
- `governance_observer/__init__.py` is **0 bytes** (`wc -c` = 0), not "1 Zeile mit future-annotations". Corrected.
- Grep claim "0 produktive Treffer" is false-as-written: hits exist in `risk_window/normalized_event.py`, `state_backend/store/projection_repositories.py`, `state_backend/sqlite_store.py`. Reworded to "no productive Observer implementation" and the three sensor/persistence hits are named.
- `HookIdentifier` -> real `HookId` (`hook_registration.py:36`). Corrected.
- `HookEvent` lives in `governance/guard_evaluation.py:38`, not in `runner.py`/`hook_registration.py`. Corrected.
**Resolution:** All four corrected in Context §1 with exact file:line anchors. Also added the explicit note that `EventType` lacks the `GOVERNANCE_*` types today (drives Scope 9). Also flagged the `StructuredEvaluator` mis-description from finding 4.3 here and resolved via E5.

---

## WARNINGs

### W1 — AC10 "vier Konzept-Gates" unnamed
**Finding:** AC10 said "vier Konzept-Gates" without naming the commands.
**Resolution (fixed in story):** AC10 now names them: `concept-coverage`, `concept-anchors`, `concept-language` (ARCH-55), `concept-no-orphan` (run via the repo gate runners). Kept generic-but-named to match the AG3-057 template's "vier Konzept-Gates" convention without inventing exact CLI flags that are not anchorable. If the exact gate command names differ in the toolchain, that is a doc/tooling alignment owned by the gate-runner story, not this story's logic — noted here per SEVERITY-SEMANTIK (no silent drop).

### W2 — "unbekannte Signalart fail-closed behandeln (loggen...)" contradictory
**Finding:** Logging is not fail-closed.
**Resolution (fixed in story):** Behavior redefined as a **hard reject (Exception)** for unknown signal types — no silent default, no mere logging — in Scope 2, AC9, and Guardrails (FAIL-CLOSED). Test added in Scope 10.

---

## status.yaml
Checked: `depends_on: [AG3-037, AG3-078, AG3-065]` matches `_STORY_INDEX.md` AG3-085 exactly; `type: implementation`, `size: L`, `status: draft`, `phase: review_pending` are all consistent with a story under review. No field wrong -> left unchanged.

## Files written
- `stories/AG3-085-governance-observation-risk-score/story.md` (rewritten)
- `stories/AG3-085-governance-observation-risk-score/remediation-r1.md` (this report)
- `status.yaml`: not modified (no wrong field)

No production code, tests, or `concept/` files were touched.
