# AG3-097 — Remediation Report (Review-R3, hostile Codex review, 3rd round)

**Scope of edits:** `story.md` (Quell-Konzepte carrier/hook hint, §1 two Ist-Zustand
bullets + Anknuepfungspunkt, §2.1.3 hook bullet + non-reachability bullet, §2.2
Out-of-Scope, AC4, AC6, §5 FAIL-CLOSED, §6 two Hinweise + Cross-Story bullet) and
`status.yaml` (`depends_on` corrected). No production code, tests, or `concept/`
files touched. No other stories' files touched.

**Verification basis (real code/concept re-read before resolving):**
- FK-39 §39.2.1 (Z. 243): `escalation_reason: String|null`, set **only** with
  `status: ESCALATED`, closed value set `{worker_blocked, max_rounds_exceeded,
  preflight_fail, integrity_fail, merge_fail, doc_fidelity_fail, impact_violation,
  design_review_rejected, governance_violation}` — **no `infra_unavailable`**, and
  **no `escalation_class` field at all** (`39_phase_state_persistenz.md:243`).
- FK-25 §25.5.4: the `escalation_class` taxonomy (`domain_gap`/`normative_conflict`/
  `scope_explosion`/`impact_exceeded`/`infra_unavailable`) is **FK-25-own**, and
  §25.5.4 `defers_to_edges` (Z. 23-25) routes the escalation **mechanics**
  (PAUSED/ESCALATED, CLI, Resume) to **FK-35**, not FK-39
  (`25_mandatsgrenzen_feindesign_autonomie.md:23-25/230-231/642-650`).
- AG3-059 (FK-39) scope: §39.2.1 fieldset incl. `escalation_reason` bound to the
  closed §39.2.1 set, valid only with ESCALATED; explicitly out-of-scopes even the
  one extra escalation value (→ AG3-058). It does **not** add `escalation_class` or
  `infra_unavailable` (`AG3-059/story.md:7,36,42,53`).
- AG3-047 (MandateClassification) escalates the **sibling** mandate classes
  (Klasse 1/3/4) today via `HandlerResult.ESCALATED` + free-text `suggested_reaction`,
  not a typed `escalation_class` field (`AG3-047/story.md:157-163`).
- Real escalation path is `HandlerResult(status=ESCALATED, yield_status=PauseReason.
  *.value, errors, suggested_reaction)` via `_escalate` (`exploration/phase.py:701-723`,
  `:746-759`). No PAUSED-with-`escalation_class` path exists. `PhaseState` has no
  `escalation_class`/`escalation_reason` (`models.py:436-479`); `PauseReason` is a
  closed 3-value enum without `infra_unavailable` (`pause_reason.py:46-60`).
- FK-25 §25.5.4 hook (Z. 615-618): "der bestehende Hook-Mechanismus" counts
  `llm_send` per session and blocks the 11th send. Real code: `HookEvent.operation`
  is a closed Literal without `llm_send` (`guard_evaluation.py:28-34`); `llm_send`
  appears only in skill-bundle resources; the real send path is direct
  `HubClient.send(...)` (`multi_llm_hub/client.py:168`).
- AG3-086 scope: WebCallBudgetGuard, skill_usage_check, Prompt-Integrity, CCAG/TTL —
  **no** `*_send`/`llm_send` send-count guard (`AG3-086/story.md:32-47`).
- AG3-095 scope: catalog presence of the `llm-discussion` bundle only; it explicitly
  names the `llm-discussion` Feindesign **transport as AG3-097** (`AG3-095/story.md:73`).

---

## Remaining Must-Fix ERRORs (review-r3 §"Remaining Must-Fix ERRORs")

### ERROR 1 — `infra_unavailable` routing to AG3-059 is not genuine → RESOLVED

- **Finding (review):** AG3-097 claimed AG3-059 delivers `escalation_reason` + an
  escalation class incl. `infra_unavailable` for `status: PAUSED`. That is not what
  FK-39/AG3-059 define.
- **Root cause (confirmed):** AG3-097 had mis-attributed the FK-25 `escalation_class`
  taxonomy to FK-39/AG3-059. FK-39's `escalation_reason` is a different field
  (ESCALATED-only, closed set, no `infra_unavailable`) and FK-39 has no
  `escalation_class` field. The `escalation_class` taxonomy is FK-25-own with FK-35
  mechanics-delegation. **No `_STORY_INDEX.md` story builds the typed
  `escalation_class` Phase-State carrier** (AG3-047 carries siblings as
  `suggested_reaction`; AG3-085 is the FK-35 risk-score, not the carrier).
- **Resolution (honest, self-consistent):**
  1. Removed every claim that AG3-059 (or any story) supplies `escalation_class`/
     `infra_unavailable`. Quell-Konzepte hint, §1 carrier bullet, §1 Anknuepfungspunkt,
     §2.1.3 non-reachability bullet, §2.2, AC4, §5, §6 corrected to state the FK-25/
     FK-35 ownership and the closed FK-39 set (with real `file:line`/§-anchors).
  2. Confined AG3-097's deliverable to the buildable signal: the typed
     `FineDesignEvaluatorUnavailableError` carrying the FK-25 triple as typed payload
     (`escalation_class="infra_unavailable"`, `escalation_reason="Multi-LLM-Quorum
     nicht erreichbar"`, desired `status: PAUSED`).
  3. Escalation at the call boundary now uses the **existing** `_escalate` ESCALATED
     path (`exploration/phase.py:701-723`) — the **same** path AG3-047 uses for the
     sibling mandate classes — carrying the triple in `errors`/`suggested_reaction`.
     No new Phase-State field, no new `PauseReason` value.
  4. Routed the typed FK-35 `escalation_class` PAUSED/Resume carrier as a **reported
     open gap with no current owner** (§2.2) — not falsely assigned to AG3-059.
  5. `status.yaml` `depends_on`: removed **AG3-059** (it delivers nothing AG3-097
     consumes for this).
- **Why not build in-story:** introducing a typed `escalation_class` field / new
  `PauseReason` value would be a second operative truth beside the (unscheduled)
  FK-35 owner — a FIX-THE-MODEL / SINGLE-SOURCE-OF-TRUTH violation and outside the
  AG3-097 cut.

### ERROR 2 — Hook send-count routing to AG3-086/AG3-095 is not genuine → RESOLVED

- **Finding (review):** AG3-097 routed the real-time 11th-send hook block to
  AG3-086/AG3-095; neither scopes `llm_send`/`*_send` send-count enforcement.
  status.yaml also did not list AG3-095 despite the text calling it a prerequisite.
- **Root cause (confirmed):** the `*_send`-PostToolUse send-count guard is FK-30 hook
  infrastructure, but **no `_STORY_INDEX.md` story scopes it** — AG3-086 builds other
  guards; AG3-095 owns only catalog presence and points the transport at AG3-097.
- **Resolution:**
  1. Routed the real-time 11th-send hook block as a **reported open FK-30 gap with no
     current owner** (Quell-Konzepte hint, §1 hook bullet, §2.1.3, §2.2, AC6, §5, §6),
     with anchors proving AG3-086/AG3-095 do not deliver it.
  2. Kept AG3-097's buildable bound: adapter-side max-10-sends-per-LLM in the
     fine-design loop (`FineDesignSubprocess`, `fine_design.py:143-198`) terminating
     as `max_rounds_exceeded`. AC6 unchanged in intent, sharpened in wording.
  3. `status.yaml` `depends_on`: removed **AG3-086** (does not deliver the guard);
     **added AG3-095** as a genuine consume-dependency — AG3-097's hub transport wires
     against the `llm-discussion` bundle whose catalog presence AG3-095 owns. This
     also resolves the status.yaml↔text inconsistency the review flagged.

---

## Per-Dimension impact

- **Konzept-Vollstaendigkeit:** the two FK-25 §25.5.4 obligations whose carriers/
  surfaces AG3-097 cannot own are now honestly recorded as **open gaps with no current
  story-owner** (FK-35 `escalation_class` carrier; FK-30 `*_send` hook), grounded in
  real anchors — no false attribution to AG3-059/AG3-086.
- **AC-Schaerfe:** AC4 asserts the typed-error-payload + existing-ESCALATED-path
  behavior (no invented field, no foreign-story carrier claim); AC6 asserts the
  adapter-side round bound with the hook block correctly marked owner-less.
- **Klarheit/Eindeutigkeit:** every "buildable here vs. owned elsewhere vs. open gap"
  boundary is explicit with real `file:line`/§-anchors; FK-39 vs FK-25/FK-35 carrier
  distinction stated precisely.
- **Kontext-Sinnhaftigkeit:** §1 now records both missing surfaces as belegt
  Ist-Zustand with real anchors and the correct (no-)ownership, so the gaps are
  grounded, not asserted.

## status.yaml change

- `depends_on` before: `[AG3-031, AG3-047, AG3-059, AG3-065, AG3-086]`
- `depends_on` after:  `[AG3-031, AG3-047, AG3-065, AG3-095]`
- Rationale: AG3-059 and AG3-086 were R2 mis-additions supporting the false routing
  and are removed; the genuine `_STORY_INDEX.md:128` set is `[AG3-031, AG3-047,
  AG3-065]`, plus **AG3-095** (catalog presence of the `llm-discussion` bundle the
  AG3-097 hub transport consumes — a real consume-dependency named in the story text).
  `story_id`/`type`/`size: M` unchanged and match the index.

## Scope discipline

- Stayed strictly within the AG3-097 cut (FK-56 §56.7a/§56.10 + FK-25 §25.5.2/§25.5.4/
  §25.5.5/§25.10). No other story's scope is claimed to deliver something it does not
  own. The two non-buildable surfaces are reported as open, owner-less gaps rather
  than mis-attributed.
- R1/R2-resolved items left intact except the two specifically-flagged mis-routings.

## Files written

- `stories/AG3-097-free-mode-multi-llm-finedesign/story.md` (edited — both ERROR areas)
- `stories/AG3-097-free-mode-multi-llm-finedesign/status.yaml` (`depends_on` corrected)
- `stories/AG3-097-free-mode-multi-llm-finedesign/remediation-r3.md` (this report)
