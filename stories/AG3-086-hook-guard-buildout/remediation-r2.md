# AG3-086 — Remediation r2 (hostile Codex review review-r2.md)

**Scope of this remediation:** `stories/AG3-086-hook-guard-buildout/story.md` only.
`status.yaml` was reviewed and left unchanged (no genuinely wrong field — see §"status.yaml").
No production code, tests, concept files, or other stories' files were touched. Every code
and concept anchor cited below was verified against the real tree before rewriting.

Both remaining must-fix ERRORs from `review-r2.md` are resolved. Both fixes stay strictly
inside the AG3-086 cut (confirmed against `_STORY_INDEX.md:96-97`) — neither is routed to
another story, because both belong to the guards AG3-086 builds.

---

## ERROR 1 — `integrity_violation` not covered for all new guards (FK-68 §68.3.1 / FK-30 §30.7.3)

**Verification.** FK-68 §68.3.1 (`68_telemetrie_eventing_workflow_metriken.md:447`) lists the
row "Guard-Hooks (inkl. SkillUsageCheck) | `agentkit.governance.guard_system` | PreToolUse |
Blockade (exit 2) | `integrity_violation`" — so **every** guard block path emits
`integrity_violation`, not only Prompt-Integrity. §68.2 (`:368`) confirms `integrity_violation`
= "Ein Guard wurde verletzt" and scopes the `stage` field to "bei prompt_integrity_guard"
only. FK-30 §30.7.3 (`30_hook_adapter_guard_enforcement.md:784`) writes blockade details as
`integrity_violation` into `execution_events`. Round-1 had only added this for Prompt-Integrity.

**Resolution (in-story).**
- **Scope 2** (`skill_usage_check`): new telemetry bullet — every block emits
  `integrity_violation` with `guard="skill_usage_check"` and `detail`, **no** `stage` (stage is
  prompt_integrity-specific). Anchored to §68.3.1:447 + §30.7.3:784.
- **Scope 1** (`WebCallBudgetGuard`): new telemetry bullet — every block path (hard-limit
  **and** unresolved story type) emits `integrity_violation` with `guard="web_call_budget_guard"`,
  explicitly distinguished from the observational `web_call` counter event (which stays with the
  emitter, FK-30 §30.5.1a).
- **Scope 3** (Prompt-Integrity): `guard` value pinned to `"prompt_integrity_guard"` and `stage`
  explicitly marked prompt_integrity-specific (§68.2).
- **New AC2b** (skill_usage `integrity_violation`) and **new AC5b** (WebCallBudgetGuard
  `integrity_violation` for both block paths). **AC5** sharpened (`guard` value + stage scope).
- **Source-concept list (story head):** the old line conflated `(guard/detail/stage)` "bei
  Guard-Blockade" — corrected into a dedicated FK-68 §68.2/§68.3.1 bullet stating `stage` is
  prompt_integrity-only and that §68.3.1 lists guards incl. `SkillUsageCheck`.
- **Sub-agent hints:** added a dedicated bullet "`integrity_violation` is mandatory for ALL new
  guard block paths, not only Prompt-Integrity", with the `stage`-only-for-prompt-integrity
  caveat and the do-not-confuse-with-`web_call` note.
- **DoD** + **Scope-7 test list** + **"done"-evidence list** extended with the per-guard
  `integrity_violation` tests.

No exemption was claimed for any block path; all three new guards now emit the event.

## ERROR 2 — Budget migration can silently drop the fail-closed unresolved-story-type block

**Verification.** `runner.py:960-968` blocks fail-closed when the story type cannot be resolved
for a web tool call ("must NOT downgrade it to non-research"). Existing tests pin this:
`tests/integration/governance/test_budget_event_emitter_dispatch.py:252-268`
(`test_unresolved_story_type_fails_closed_deny`) and
`tests/unit/telemetry/hooks/test_budget_event_emitter.py:81-91`
(same name, asserts no silent allow, no `web_call` event). Round-1's migration removed the
emitter block but never said who owns this case afterwards → potential fail-open regression.

**Resolution (in-story).** Since `WebCallBudgetGuard` becomes the **sole** block owner and
§68.6.0 makes blocking a Governance responsibility, the unresolved-type fail-closed decision is
migrated **to `WebCallBudgetGuard`** (in-cut; the index entry AG3-086 explicitly owns the
blocking `WebCallBudgetGuard`). Concretely:
- **Scope 1:** new bullet "Fail-closed bei unaufloesbarem Story-Typ wandert mit zum
  Governance-Owner (kein fail-open-Regress)" citing `runner.py:960-968` + both tests; the
  migration bullet now explicitly says the fail-closed branch `:960-968` is consolidated, not
  deleted, and the emitter produces **no** verdict for this case either.
- **New AC1c:** unresolved story type on a web tool call blocks fail-closed under
  `WebCallBudgetGuard` (no downgrade, no allow); migration test proves owner changes,
  behavior holds, emitter no longer verdicts.
- **Scope 7 test list, DoD, Guardrail FAIL-CLOSED, sub-agent hints, "done"-evidence** all
  updated to mandate the "unresolved story type -> block now from the Governance owner" test
  and to forbid deleting `runner.py:960-968`.

This is the FIX-THE-MODEL move: the block currently sits at the wrong owner (telemetry); it
moves to the right owner (governance) without behavioral loss. Not routed elsewhere — AG3-085
only *consumes* governance signals (index `:96`), it does not own this block.

---

## Routing check (no false delegation)

- **AG3-085** (`_STORY_INDEX.md:96`): observation / risk-score / adjudication / `governance_signal`
  — consumes signals, does not emit `integrity_violation` and does not own the budget block.
  Correctly left as consume-only in Out-of-Scope.
- **AG3-103** (`:144`): doc-only FK-93 defaults reconciliation — unrelated to these two findings.
- **AG3-080**: `health_monitor` only — untouched.
Both r2 findings belong to guards AG3-086 itself builds (`WebCallBudgetGuard`,
`skill_usage_check`), so both are fixed in-story; nothing is delegated.

## status.yaml

Left unchanged. The two findings are AC-scope / telemetry-completeness issues, not metadata.
`status: draft` / `phase: review_pending`, `depends_on: [AG3-013, AG3-080]`, `type/size/title`
remain correct (consistent with `_STORY_INDEX.md:97`). No field is genuinely wrong.

## Template / language

AG3-057 section structure (head → 1 Kontext/Ist-Zustand → 2 Scope (In/Out) → 3 AC → 4 DoD →
5 Guardrails → 6 Sub-Agent hints) is preserved. ARCH-55: all new identifiers/values are English
(`integrity_violation`, `guard="skill_usage_check"`, `guard="web_call_budget_guard"`,
`guard="prompt_integrity_guard"`, `story_type`, `web_call`); German remains only in prose.

## Must-fix checklist (review-r2.md)

1. `integrity_violation` for all new guards (skill_usage_check + WebCallBudgetGuard block paths)
   — **done** (Scope 1 + 2 telemetry bullets, AC2b, AC5b, AC5 sharpened, head bullet, hints).
2. Unresolved-story-type fail-closed block migrated to `WebCallBudgetGuard` (no fail-open
   regression), with migration test — **done** (Scope 1 bullet, AC1c, test list, FAIL-CLOSED,
   hints).

Only `stories/AG3-086-hook-guard-buildout/story.md` was written (+ this `remediation-r2.md`).
`status.yaml` and all other files untouched.
