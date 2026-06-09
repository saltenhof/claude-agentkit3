# AG3-097 — Remediation Report (Review-R2, hostile Codex review, 2nd round)

**Scope of edits:** `story.md` rewritten in the two affected areas (Quell-Konzepte
carrier-hint, §1 Ist-Zustand, §2.1.3 escalation + hook bullets, §2.2 Out-of-Scope,
AC4, AC6, AC7, §5 FAIL-CLOSED, §6 Hinweise + Beleg). `status.yaml`: `depends_on`
corrected (AG3-059 + AG3-086 added). No production code, tests, or `concept/` files
touched. No other stories' files touched.

**Verification basis:** every R2 anchor was checked against the real code/concept
before resolving. All cited anchors proved **accurate**:
- `PhaseState` has `status`/`paused_reason`/`errors`, **no** `escalation_class`/`escalation_reason` — confirmed `story_context_manager/models.py:436-479`.
- `PauseReason` is a closed 3-value enum (`AWAITING_DESIGN_REVIEW`/`AWAITING_DESIGN_CHALLENGE`/`GOVERNANCE_INCIDENT`), **no** `infra_unavailable` — confirmed `core_types/pause_reason.py:46-60`.
- Exploration escalation today returns `HandlerResult(status=ESCALATED, yield_status=PauseReason....value, errors=..., suggested_reaction=...)`, **not** `PAUSED`+infra fields — confirmed `exploration/phase.py:701-723`, `:751-755`.
- `HookEvent.operation` is a closed Literal `{bash_command,file_write,file_edit,file_read,unknown_tool}`, **no** `llm_send` — confirmed `governance/guard_evaluation.py:28-34`.
- `llm_send` appears in the repo **only** in skill-bundle resources, not as a runtime guard — confirmed `resources/skill_bundles/llm-discussion-core/4.0.0/SKILL.md:5/58` + `create-userstory-core/.../SKILL.md`.
- Real send path is direct `HubClient.send(...)` — confirmed `multi_llm_hub/client.py:168` (would bypass a harness hook).

**Concept basis (FK-25 §25.5.4, fetched via concept MCP):** the FK explicitly defers
escalation **mechanics** (PAUSED/ESCALATED, CLI, Resume) to **FK-35** and the
Phase-State carrier (`PauseReason`-enum, `escalation_reason`) to **FK-39**
(`defers_to_edges: FK-35|escalation-mechanics`, FK-39 phase-state-persistence).
The FK-25 triple is therefore a **consumer** of the FK-39 field set, not an FK-25-own
carrier. The hook bullet says "der **bestehende** Hook-Mechanismus" — i.e. it assumes
hook infrastructure that FK-30 owns, not something FK-25/AG3-097 introduces.

---

## Remaining Must-Fix ERROR list (review §"Remaining Must-Fix ERRORs")

### ERROR 1 — `infra_unavailable` escalation specified against non-existent fields

- **Finding:** Story required exact `status: PAUSED` + `escalation_class` + `escalation_reason` on a Phase-State carrier that does not exist; `PauseReason` is a closed 3-value enum with no `infra_unavailable`.
- **Root cause (not symptom):** the escalation carrier (`escalation_reason` + escalation class incl. an `infra_unavailable` value at PhaseStateCore) is **FK-39-owned and delivered by AG3-059** (FK-39 §39.2.1; `_STORY_INDEX.md:45`), which is **not** in the AG3-097 cut. AG3-097 was specifying fields it cannot build.
- **Resolution:**
  1. **Routed the carrier to its owner as a hard dependency.** `status.yaml` `depends_on` now includes **AG3-059**. New §2.2 Out-of-Scope bullet names AG3-059 as the FK-39 carrier owner.
  2. **Confined AG3-097's own deliverable to what it can build:** the typed unavailability **signal** at the fine-design boundary — `FineDesignEvaluatorUnavailableError` (`fine_design.py:41`) carrying the FK-25 triple as **typed payload** (`escalation_class="infra_unavailable"`, `escalation_reason="Multi-LLM-Quorum nicht erreichbar"`, desired `status: PAUSED`).
  3. **Defined the mapping path:** the exploration-phase-handler (`exploration/phase.py:701-723`) maps the error payload onto the AG3-059-delivered carrier. Until AG3-059 is merged, AG3-097 escalates via the **existing** ESCALATED path (`HandlerResult.errors`/`suggested_reaction`) carrying the triple as payload — explicitly **never** an invented Phase-State field (FIX-THE-MODEL, no shadow field).
  4. AC4 rewritten accordingly (test = error with exact triple payload + mapping via AG3-059 carrier, no invented field). §1 Ist-Zustand gained a belegt bullet documenting the missing carrier with real `file:line` anchors. §5 FAIL-CLOSED and §6 Hinweise updated.
- **Why not build it in-story:** introducing `escalation_class`/`escalation_reason` on `PhaseState` or a new `PauseReason` value would create a **second operative truth** beside the FK-39 owner (AG3-059) — a direct CLAUDE.md FIX-THE-MODEL / SINGLE-SOURCE-OF-TRUTH violation and outside the AG3-097 cut.

### ERROR 2 — Hook-send enforcement relies on a non-existent production hook surface

- **Finding:** Story claimed enforcement via "bestehende Send-Count-Sensorik" blocking the 11th send; no such guard/operation exists (`HookEvent.operation` has no `llm_send`; `llm_send` only in skill resources; real path is direct `HubClient.send`).
- **Root cause (not symptom):** the `*_send`-PostToolUse send-count guard is **FK-30-owned hook/guard infrastructure**, delivered by **AG3-086** (Hook-/Guard-Vollausbau, FK-30 §30.5.1/§30.10; `_STORY_INDEX.md:97`) on the AK3 side, and **AG3-095** (`llm-discussion` bundle) on the harness/skill side. Not in the AG3-097 cut.
- **Resolution:**
  1. **Routed the hook surface to its owners as a hard dependency.** `status.yaml` `depends_on` now includes **AG3-086** (AG3-095 was already in scope as the skill owner; named in §2.2). New §2.2 Out-of-Scope bullet names AG3-086 (AK3) + AG3-095 (skill).
  2. **Changed AG3-097 to enforce the 10-round bound in the fine-design adapter** (the buildable surface): the concrete Hub implementation + bounded loop (`FineDesignSubprocess`, `fine_design.py:143-198`) send no more than 10x per LLM and terminate as `max_rounds_exceeded`. No harness hook needed for this.
  3. **Explicit cross-story dependency for hook enforcement:** the real-time 11th-send hook block is marked Out-of-Scope with its owners; AG3-097 does not pretend to deliver it.
  4. AC6 rewritten (test = max 10 sends per LLM from the implementation, no 11th send; the hook block is explicitly NOT this cut). §1 Ist-Zustand gained a belegt bullet with real `file:line` anchors. §5 and §6 updated.

---

## Per-Dimension impact

- **Konzept-Vollstaendigkeit:** the two FK-25 §25.5.4 obligations whose carriers AG3-097 cannot own are now correctly attributed to their FK-39/FK-30 owners (AG3-059/AG3-086) with hard dependencies — the story no longer claims to deliver what its cut does not contain, and the FK obligations are fully accounted for across owners.
- **AC-Schaerfe:** AC4 and AC6 now assert testable, buildable behavior (typed error payload; adapter-side round bound) instead of behavior against non-existent fields/hooks.
- **Klarheit/Eindeutigkeit:** every "buildable here vs. owned elsewhere" boundary is stated explicitly with real anchors; stale lettered cross-ref ("Punkt 3d") fixed.
- **Kontext-Sinnhaftigkeit:** §1 now records the missing carriers as belegt Ist-Zustand with real `file:line`, so the gap is grounded, not asserted.

---

## status.yaml change

- `depends_on` was **genuinely wrong** (missing the two owners the resolution depends on). Changed:
  - before: `[AG3-031, AG3-047, AG3-065]`
  - after: `[AG3-031, AG3-047, AG3-059, AG3-065, AG3-086]`
- Rationale: AG3-059 is the FK-39 escalation-carrier owner (ERROR 1); AG3-086 is the FK-30 hook/guard send-count owner (ERROR 2). Both are now hard consumed-not-built dependencies. All other fields (`story_id`/`type`/`size: M`) match `_STORY_INDEX.md` and are unchanged.

## Scope discipline (per `_STORY_INDEX.md`)

- Stayed strictly within AG3-097's cut (FK-56 §56.7a/§56.10 + FK-25 §25.5.2/§25.5.4/§25.5.5/§25.10).
- Both R2 ERRORs were resolved by **routing the non-buildable carrier/surface to its real owner** (AG3-059 for the FK-39 phase-state escalation carrier; AG3-086 + AG3-095 for the FK-30 hook send-count surface) and confining AG3-097's own deliverable to the buildable signal (typed `FineDesignEvaluatorUnavailableError` payload) and the buildable bound (adapter-side 10-round limit). No other story's scope was claimed to deliver something it does not own — the owners assigned match exactly their `_STORY_INDEX.md` rows.
- R1-resolved items (R1-E1/E2/E4/E5/E6 per review-r2.md) left intact.

## Files written

- `stories/AG3-097-free-mode-multi-llm-finedesign/story.md` (edited — two ERROR areas)
- `stories/AG3-097-free-mode-multi-llm-finedesign/status.yaml` (`depends_on` corrected)
- `stories/AG3-097-free-mode-multi-llm-finedesign/remediation-r2.md` (this report)
