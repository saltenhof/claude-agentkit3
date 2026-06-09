# AG3-081 — Remediation R2 (after round-2 hostile Codex review `review-r2.md`)

**Scope of this remediation:** story authoring only. Edited files: `story.md`, `status.yaml`, and this `remediation-r2.md`. **No production code, tests, or `concept/` files were touched.** Every round-2 must-fix ERROR was resolved inside the story or correctly routed to the owner story named in `var/concept-gap-analysis/_STORY_INDEX.md`. Cut/scope kept strictly within the AG3-081 row (BC14/BC15 EventTypes + mandatory-payload contract, telemetry-evidence wiring, typed `phase_state_projection`, `guard_invocation_counters` hot-path, reset-purge read-model half, hook-table↔code consistency).

All code anchors were re-verified against the real tree and corrected where the R1 story was still wrong (see "Code-anchor corrections" at the end).

---

## Round-2 Must-Fix ERROR list (from `review-r2.md` §"Not genuinely resolved / new blocker")

### ERROR 1 — Guard-counter hot path did not cover "every guard hook"
**Finding:** Story placed the UPSERT at `evaluate_pre_tool_use` and claimed all PreToolUse guards flow through it. Real code bypasses that path for six dedicated branches before the generic fallback: capability enforcement (`runner.py:575`), `review_guard` (`:590`), `budget_event_emitter` (`:592`), `self_protection` (`:606`), `story_creation_guard` (`:608`), `ccag_gatekeeper` (`:612`); only the remainder falls through to `evaluate_pre_tool_use` (`:616`). FK-61 §61.4.3 (verified Z. 203-204: "Jeder Guard-Hook fuehrt am Ende ein einzelnes UPSERT aus") requires every guard hook to increment the counter.
**Resolution:** Re-anchored the hot path from the generic `evaluate_pre_tool_use` to the **common module-level dispatch `governance/runner.py:run_hook` (Z. 536)**, which is the single point all pre-hook branches return through. Added a new §1 Ist-Zustand bullet ("Guard-Dispatch-Topologie") enumerating all six dedicated early-return branches + the generic fallback with verified line anchors, and stating that placing the UPSERT only at `evaluate_pre_tool_use` misses six guard paths. §2.1.6 rewritten: a common counting wrapper at `run_hook` increments `invocations` for every `phase=="pre"` branch result and `blocks` when the verdict is a BLOCK, `guard_key` derived from `hook_id`. AC5 now requires tests for **both** the generic path AND at least two dedicated branches (e.g. `review_guard` + `self_protection`), plus a BLOCK→`blocks+1` test. §6 hint re-pointed to `run_hook` over all branches.

### ERROR 2 — "Emitter" ownership conflict not genuinely resolved repo-wide
**Finding:** AG3-081 routed fachliche planning emitters to AG3-099, but AG3-099 still says the `EventTypeId` enum entry **plus** "Emitter-Infrastruktur" are AG3-081 (`AG3-099 story.md:40`/`:35`) while also saying AG3-099 emits the eight BC14 events — a circular/unclear owner.
**Resolution:** Verified the generic emitter infrastructure **already exists** (`EventEmitter` protocol `telemetry/emitters.py:19`, `StateBackendEmitter` `telemetry/storage.py:23`, `MemoryEmitter`/`NullEmitter`) — neither story builds it. Added an explicit three-level owner split to §2.1.1: (1) generic emitter infrastructure = pre-existing, no story owns its construction; (2) EventType catalogue + mandatory-payload contract = AG3-081 (canonical enum owner); (3) fachliche BC14 emission = AG3-099. This makes the cut acyclic and unambiguous. The inaccurate AG3-099 wording ("Emitter-Infrastruktur — AG3-081"; also the wrong name `EventTypeId` vs. the real `EventType`) is flagged as a story-doc-only wording mismatch and routed to the **AG3-099 author run** in §2.2 (AG3-081 may not edit foreign story files; the cut itself does not change).

### ERROR 3 — Telemetry-Evidence scope overstated existing contract rules
**Finding:** FK-68 §68.4 (verified Z. 570-577) requires six proofs including "kein `integrity_violation`" and "`web_call` ≤ Budget". The story claimed the existing finished `TelemetryContract` rules would be wired for all six, but real `check_all()` (`telemetry_contract.py:278-286`) runs only four: agent pairing, review coverage, preflight balance, llm role coverage.
**Resolution:** §1 Ist-Zustand corrected to state the existing contract implements four of six rules (with the exact `check_all()` anchor and the names of the two missing rules). §2.1.4 split into two explicit parts: (a) **extend** `TelemetryContract` with two new rules `check_no_integrity_violation` and `check_web_call_within_budget`, added into `check_all()` at the same pattern; (b) wire the full six-rule `check_all()` into the Closure integrity path. AC3 now requires `check_all()` to aggregate six rules (plus a positive test asserting six `RuleResult`s) and keeps the six named negative tests. ZERO DEBT guardrail reference updated to call out the two added rules.

### ERROR 4 — `status.yaml` dependency metadata was false
**Finding:** AG3-081 had `unblocks: []`, but AG3-082 (`AG3-082 status.yaml:8`) and AG3-099 (`AG3-099 status.yaml:8`) both `depends_on: AG3-081`; `_STORY_INDEX.md` confirms both edges (Z. 88, Z. 135).
**Resolution:** Set `status.yaml` `unblocks` to `[AG3-082, AG3-099]`.

---

## WARNINGS
`review-r2.md` lists four numbered items, all classified as **ERROR** (the per-dimension FAILs are the summary scorecard, not separate findings). No standalone WARNING was raised in round 2. The R1 PASS-with-note anchors that were retained remain valid (re-verified below).

---

## Code-anchor corrections / verifications applied in story.md (round 2)

| Claim in R1 story | Reality (re-verified) | Fix in R2 rewrite |
|---|---|---|
| Counter hot path at `governance/guard_evaluation.py:evaluate_pre_tool_use` (Z. 85) "covers every guard" | That is only the **generic fallback**; six dedicated branches bypass it (`runner.py:575/590/592/606/608/612`), generic at `:616` | Re-anchored to `governance/runner.py:run_hook` (Z. 536) over **all** branches; enumerated the six dedicated paths |
| "die bestehenden, fertigen Contract-Regeln … alle sechs" | `check_all()` (`telemetry_contract.py:278-286`) runs only **four** rules; no `integrity_violation`/`web_call`-budget rule exists | Story now requires adding two rules before wiring; six-rule `check_all()` |
| Emitter ownership routed to AG3-099 only as prose | Generic emitter infra already exists (`emitters.py:19`, `storage.py:23`); enum is `EventType` not `EventTypeId` | Added three-level owner split; routed AG3-099 wording mismatch to AG3-099 author run |
| `unblocks: []` | AG3-082 + AG3-099 depend on AG3-081 (`_STORY_INDEX.md` Z. 88/135; both status.yaml Z. 8) | `unblocks: [AG3-082, AG3-099]` |
| FK-68 §68.4 six proofs | Confirmed at FK-68 §68.4 Z. 570-577 (table of six) | Re-anchored body to Z. 570-577 |
| FK-61 "Jeder Guard-Hook" | Confirmed at FK-61 §61.4.3 Z. 203-204 | Quell-Konzepte line tightened |

## status.yaml change (round 2)
- `unblocks` changed from `[]` to `[AG3-082, AG3-099]`. No other field is wrong (`type: implementation`, `size: L`, `depends_on: [AG3-035, AG3-037]`, `phase: review_pending`, `title` all consistent with `_STORY_INDEX.md`).

## Note (unchanged; flagged)
The story **directory name** still contains `…-integrity-dim8` and the `_STORY_INDEX.md` AG3-081 title row still reads "Integrity-Dim-8-Wiring". Both are outside "story.md/status.yaml only" scope and were left untouched in R1 for the same reason. The `story_id` (AG3-081) is unaffected.
