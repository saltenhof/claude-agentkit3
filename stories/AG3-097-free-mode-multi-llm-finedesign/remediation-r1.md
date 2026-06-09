# AG3-097 — Remediation Report (Review-R1, hostile Codex review)

**Scope of edits:** `story.md` rewritten. `status.yaml` reviewed — no field wrong, unchanged. No production code, tests, or `concept/` files touched.

**Verification basis:** every review anchor was checked against the real code/concept before resolving.
All cited code anchors in the review proved **accurate** (`guard_evaluation.py:96-105`,
`fine_design.py:102`, `change_frame.py:270/277`, `runtime.py:28-29`, `PROJECT_STRUCTURE.md:120`,
`client.py:92-109` no stats, `routes.py:96/112` no stats). Wrong/imprecise anchors in the **old story**
were corrected to real file:line (see WARNING/NIT items below).

---

## Must-Fix ERROR list (review §"Must-Fix ERROR List")

### ERROR 1 — German Change-Frame code field → English wire-key
- **Finding:** AC6 demanded German wire-field `feindesign_entscheidungen`; conflicts with ARCH-55 and AC7.
- **Resolution:** Single English wire-key chosen: **`fine_design_decisions`** (Scope 2.1 §4, AC9/AC10).
  Sub-fields reuse the already-English `FineDesignDecision` keys (`decision_id/question/decision/rationale/normative_basis/llm_responses`, present in `fine_design.py:56-83`). `feindesign_entscheidungen` now appears **only** as the FK concept name in prose/comments. Code key is English. German-key doc-only nachzug explicitly routed to **AG3-102** (per `_STORY_INDEX.md` Welle 10).

### ERROR 2 — ChatGPT + second LLM mandatory ("Qwen optional" was wrong)
- **Finding:** Story made the second LLM optional; FK-25 §25.5.2 requires ChatGPT **plus** a second advisor (Qwen preferred, else Gemini/Grok).
- **Resolution:** Scope 2.1 §3 and **AC3** now require **ChatGPT mandatory AND a second advisor mandatory** (Qwen preferred, Gemini/Grok fallback). Fake-Hub test: missing ChatGPT **or** missing any second advisor → deterministic abort. Verified against FK-25 §25.5.2 lines 549-560.

### ERROR 3 — `infra_unavailable` / `PAUSED` / exact escalation_reason missing
- **Finding:** Story said only "deterministischer Abbruch (fail-closed)"; FK-25 §25.5.4 mandates the typed escalation triple.
- **Resolution:** Scope 2.1 §3 (non-reachability bullet) and **AC4** now demand **exactly** `status: PAUSED`, `escalation_class: "infra_unavailable"`, `escalation_reason: "Multi-LLM-Quorum nicht erreichbar"`, mapped via the existing `FineDesignEvaluatorUnavailableError` (`fine_design.py:41`) at the exploration-phase-handler boundary. Verified against FK-25 §25.5.4 lines 642-650.

### ERROR 4 — AC1 not testable enough (typed fail-closed reaction)
- **Finding:** "kein Integrity-Gate, kein FAIL-Code" did not define what the call returns/throws.
- **Resolution:** **AC1** now specifies a typed **`IntegrityGateNotApplicableError`** raised **before** `integrity_gate_started`, with the test asserting the exception **plus** no `integrity_gate_started`/`integrity_gate_result` events **plus** no Closure-FAIL-codes. Anchored to the real entry point `IntegrityGate.evaluate` (`integrity_gate/__init__.py:151`), which today takes no `operating_mode`.

### ERROR 5 — `llm_session_stats` adapter gap
- **Finding:** Story claimed `llm_session_stats` is an existing consumable AK3 transport; AK3 `HubClient` (`client.py:92-109`) and BFF routes (`routes.py:96-122`) have no stats API.
- **Resolution:** Taken **into scope** as a minimal **read-only** `session_stats` consumption surface (HubClient method + BFF GET route + typed Pydantic response model) — Scope 2.1 §3 (session_stats bullet) and **AC5**. Decision rationale (recorded for the PO): `_STORY_INDEX.md` assigns the **Verify-LLM dialogue transport** to AG3-065, **not** a fine-design stats adapter; the stats consumption is specific to this story's FK-25 §25.5.4 post-hoc verification, is small and read-only, and the FK explicitly requires this endpoint be consumed here. Out-of-scope note for AG3-065 clarified so the boundary is unambiguous (this story does **not** build the DialogueRunner/Verify transport).

### ERROR 6 — Non-existent `frozen`/`frozen_at` invariant
- **Finding:** Story demanded "frozen/frozen_at-Invariante wahren"; code explicitly does **not** enforce such an invariant (`change_frame.py:277-280`).
- **Resolution:** Removed. Scope 2.1 §4, **AC9**, and §6 now say the **existing freeze behavior is not changed** and explicitly note no `frozen`/`frozen_at` consistency invariant exists or is to be introduced.

---

## Additional review findings (non-"Must-Fix" but addressed)

### §1 ERROR (concept completeness, 2nd LLM) — same as ERROR 2; resolved.
### §2 ERROR (AC6/AC7 ARCH-55 contradiction) — same as ERROR 1; resolved (AC9 = field, AC10 = ARCH-55).
### §3 ERROR (German field + English key, no English target named) — same as ERROR 1; concrete target `fine_design_decisions` named in Scope 2.1 §4.
### §4 ERROR (session_stats transport claim) — same as ERROR 5; resolved.
### §4 ERROR (frozen invariant) — same as ERROR 6; resolved.

### WARNING — Session-release check not covered by an AC (FK-25 §25.5.4, line 631)
- **Resolution:** New **AC8** + Scope 2.1 §3 (release bullet): non-released session → Telemetry **WARNING** per SEVERITY-Semantik; correct release → no warning.

### WARNING — AC5 conflated hook-enforcement and subprocess result
- **Resolution:** Split into two ACs: **AC6** (hook blocks the **11th** send per `session_id`, only `session_id` needed, no response parsing — FK-25 §25.5.4 line 613) and **AC7** (subprocess terminates at round 10 as `max_rounds_exceeded`, existing `fine_design.py:194` behavior).

### WARNING — "minimal als benannte Surface + melden" = scope-flight on the resolver namespace
- **Resolution:** Resolver namespace made a **MUST** (Scope 2.1 §2, **AC2**): the named `operating_mode_resolver` surface is a binding deliverable; the "melden statt liefern" escape clause was deleted. FK-prose doc-only nachzug routed to AG3-102. Stayed within this story's cut (no split needed — it is a consolidation onto a named owner, no behavior change).

### NIT — sloppy gap refs "FK-46-56", "FK-13-25"
- **Resolution:** Corrected to **`FK-56`** (§1 bullet 1) and **`FK-25`** (§1 bullet 3) respectively. All §1 anchors re-verified to real file:line.

### PASS-Teilbefund (review §4) — Ist-Zustand anchors exist
- Re-verified and **tightened** in §1 with exact lines: `guard_evaluation.py:96-105` / `:85`, `fine_design.py:102/38/143/56-83/41`, `change_frame.py:270/277-280/283/298-305/308/316`, `runtime.py:29`, `PROJECT_STRUCTURE.md:120`, `integrity_gate/__init__.py:151`, `client.py:92-109`, `routes.py:96-102/112-122`.

---

## Scope discipline (per `_STORY_INDEX.md`)
- Stayed strictly within AG3-097's cut (FK-56 §56.7a/§56.10 + FK-25 §25.5.2/§25.5.4/§25.10).
- The only scope addition (read-only `session_stats` consumption surface) is required by the in-scope FK-25 §25.5.4 verification and is **not** owned by any other story; the Verify transport remains explicitly AG3-065.
- Out-of-scope items kept with their owners: AG3-065 (verify transport), AG3-095 (llm-discussion skill), AG3-102 (FK-56-namespace / German-key doc-only nachzug), free-mode/Prompt-Integrity (harness, no Python scope).

## status.yaml
- Reviewed: `story_id`, `type`, `size: M`, `depends_on: [AG3-031, AG3-047, AG3-065]` all match `_STORY_INDEX.md`. **No field wrong → unchanged.**

## Files written
- `stories/AG3-097-free-mode-multi-llm-finedesign/story.md` (rewritten)
- `stories/AG3-097-free-mode-multi-llm-finedesign/remediation-r1.md` (this report)
- `status.yaml`: **not** modified (no wrong field).
