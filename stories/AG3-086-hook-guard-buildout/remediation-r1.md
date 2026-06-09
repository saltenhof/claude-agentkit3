# AG3-086 — Remediation r1 (hostile Codex review review-r1.md)

**Scope of this remediation:** `stories/AG3-086-hook-guard-buildout/story.md` only.
`status.yaml` was reviewed and left unchanged (no genuinely wrong field — see §"status.yaml" below).
No production code, tests, concept files, or other stories' files were touched. Every code
anchor cited below was verified against the real tree before rewriting.

All findings from `review-r1.md` are addressed (6 must-fix ERRORs + every WARNING).

---

## 1. Konzept-Vollstaendigkeit

### ERROR — CCAG-Regelgeneralisierung verletzt FK-42 (Persistenz als Scope)
**Resolution (in-story).** Scope 6 + AC8 split into proposal vs. persistence. The LLM now
produces **only a proposal/draft**; `approved.yaml` (`learned_from`/`learned_at`) is written
**only after an explicit promote/confirm decision**. Added the negative test "keine Persistenz
ohne Confirm" (AC8) and a positive "Persistenz nach Confirm" test. Anchored to
`FK-42 §42.3` (Default-Schnitt: erste Entscheidung = Einzelfall/Lease), `§42.3.1 F-42-039`
("ohne explizite Bestaetigung werden keine Regeln gespeichert", verified at
`42_ccag_tool_governance_permission_runtime.md:269`), and `§42.4.2` last paragraph
("keine Dauerregel ohne separate Promote-Entscheidung", `:306-308`).

### ERROR — Permission-TTL konzeptionell unvollstaendig (FK-93 1800 vs. Code 600)
**Resolution (in-story).** Scope 5 + AC7 now require a typed config key
`permissions.request_ttl_s` (Default **1800s**, FK-93 §93.5a, verified at
`93_standardwerte_schwellwerte_timeouts.md:64`) instead of the hardcoded
`DEFAULT_TTL_SECONDS = 600` (verified `ccag/requests.py:42`). Confirmed no `permissions.*`
config exists today (grep over `src/agentkit/config` -> 0 matches), so this is a clean new
typed owner. The broader FK-93-defaults reconciliation is correctly routed to doc-only
**AG3-103** (per `_STORY_INDEX.md:144`); AG3-086 fixes only this one value in the typed
config model. Captured in Out-of-Scope and as a cross-story note (§ "Cross-story
prerequisites").

### ERROR — Guard-Signale behauptet, aber nicht akzeptanzscharf (FK-68 integrity_violation)
**Resolution (in-story).** Added Scope 3 telemetry bullet + new **AC5**: every
Prompt-Integrity block emits an `integrity_violation` event with `guard`/`detail`/`stage`,
`stage ∈ {escape_detection, schema_validation, template_integrity}`, with the outward block
message kept opaque (§31.7.3). Anchored to `FK-68 §68.2` governance table (verified
`68_telemetrie_eventing_workflow_metriken.md:368` — the `stage` enum for `prompt_integrity_guard`
is wortgleich in the concept). Accumulation stays out-of-scope (AG3-085).

## 2. AC-Schaerfe

### ERROR — Prompt-Integrity-AC widersprechen FK-31-Modussemantik
**Resolution (in-story).** Scope 3 + AC3 rewritten mode-sharp per FK-31 §31.7.1 (Modusgrenze,
verified `31_...:611-618`) and §31.7.2 (3-stage table, verified `:620-626`):
Stage 1 (escape) both modes; Stage 2 schema **lightweight in `ai_augmented`**
(`role=general`/`skill_proof=null`) vs. **full in `story_execution`** (valid `skill_proof`);
Stage 3 template **only in `story_execution`** with **QA-agents exempt**. Tests required per
mode and per stage, including the QA-agent exemption and the "no Stage 3 in ai_augmented" case.

### WARNING — CCAG-Huellen-AC sprachlich missverstaendlich
**Resolution (in-story).** Reworded Scope 4: "**Fehlt die Huelle, ist der CCAG-Aufruf
unzulaessig und erzeugt einen fail-closed Block**" (matches FK-42 §42.2.4, verified
`42_...:216` "Fehlt diese Huelle, ist der CCAG-Aufruf fail-closed unzulaessig"). AC6 mirrors
the wording.

## 3. Klarheit

### ERROR — Prompt-Integrity-Ist-Claim "Grep -> 0 Treffer" falsch
**Resolution (in-story).** Ist-Zustand bullet corrected. The false "0 Treffer for
`AGENTKIT-SUBAGENT-V1|skill_proof`" is removed. New claim: there is **no production guard and
no `prompt_integrity` HookIdentifier** (grep `prompt_integrity|PromptIntegrity` over
`src/agentkit/` -> 0), **but the spawn header already exists as a resource/skill contract** and
must be **consumed**, not invented — verified at
`resources/skill_bundles/execute-userstory-core/4.0.0/SKILL.md:57-62` (header schema),
`:64-69` (story_execution binding), `:71` ("The governance hook blocks non-conformant spawns"),
`:151-153` (concrete spawn example). Scope 3 + AC4 now reference this contract as the Stage-2
source format.

### WARNING — FK-Verweis WebCallBudget nennt falsches `FK-30 §30.10`
**Resolution (in-story).** Source anchors corrected. WebCallBudget now cites
`FK-30 §30.5.1` (guard table, verified `30_...:564`), `FK-30 §30.5.1a` (the
`WebCallBudgetGuard` class spec, verified `:568-587`) and `FK-68 §68.6`/`§68.6.0`.
`§30.10` is now correctly identified as the **Worker-Health-Monitor** (verified `30_...:912`,
FK-49) and appears **only** in Out-of-Scope as AG3-080's owner.

## 4. Kontext-Sinnhaftigkeit

### ERROR — WebCallBudget-Ist-Zustand materiell falsch, Duplicate-Owner offen
**Resolution (in-story).** This was the biggest correction. The old "only the observational
half exists / emitter stays unchanged observational" claim was **false** and is replaced.
Verified real state: `BudgetEventEmitter` **already blocks** (double role) —
`budget_event_emitter.py:51-54` (`name = "budget_event_emitter"`), `:112` (over_budget),
`:132-149` (`GuardVerdict.block`), wired as a **PreToolUse** dispatch in
`runner.py:591-594` and `:913-987`, with the double role documented at `base.py:21-23`.
Meanwhile the `budget` HookIdentifier (`hook_registration.py:53`) has **no** blocking class.
Scope 1 + new **AC1b** now make the **migration explicit**: remove/neutralise the block in
`BudgetEventEmitter` (keep it observational, still emitting `web_call`), introduce
`WebCallBudgetGuard` as the **sole** block owner, consolidate the `budget` vs.
`budget_event_emitter` dispatch, and a negative test against double-block / wrong owner.
Counter/event production stays with the emitter (Out-of-Scope).

---

## Must-Fix checklist (from review-r1.md)

1. WebCallBudget Ist-Zustand + migration scope incl. existing `budget_event_emitter` block path — **done** (Scope 1, AC1b, §1 Ist-Zustand bullet 1).
2. Prompt-Integrity mode-sharp + QA-template exception — **done** (Scope 3, AC3).
3. False "0 Treffer" corrected + resource header as existing anchor — **done** (Ist-Zustand bullet 3, Scope 3, AC4).
4. CCAG rule-generalisation with confirm/promote barrier — **done** (Scope 6, AC8).
5. Permission-TTL `permissions.request_ttl_s` Default 1800 — **done** (Scope 5, AC7; reconciliation routed to AG3-103).
6. Event-emission/telemetry AC for the new guards — **done** (Scope 3 telemetry, AC5).

---

## status.yaml

Left unchanged. `status: draft` / `phase: review_pending` correctly reflect a story still in
review (DoD says "zunaechst nur autorisiert/reviewt"). `depends_on: [AG3-013, AG3-080]` matches
`_STORY_INDEX.md:97`. `type/size/title` are correct. No field is genuinely wrong, so per the
remediation constraint it was not edited.

---

## Cross-story prerequisites (genuine)

- **AG3-103 (doc-only, FK-93 defaults reconciliation):** AG3-086 sets the Permission-Request-TTL
  to the FK-93 §93.5a value (1800s) in the typed config model for the path it builds. The
  authoritative per-value reconciliation FK-93↔Code (which side wins for every other threshold)
  is AG3-103's owner per `_STORY_INDEX.md:144`. This is a documentation follow-up, not a blocker
  for AG3-086 — AG3-086 stays FK-93-conformant for its own value either way.
- **AG3-085 (FK-35 §35.3, Governance-Observation):** Consumes the `integrity_violation` /
  budget signals that AG3-086's guards emit. Direction is consume-only; AG3-086 does not depend
  on AG3-085 to ship. Already reflected in Out-of-Scope.
- **AG3-102 (doc-only, ccag namespace):** The `ccag/` -> `ccag_permission_runtime/` rename is a
  concept-text follow-up; not required for AG3-086's behaviour. Already reflected in Out-of-Scope.

No prerequisite **blocks** AG3-086 from being authorised/implemented within its own cut. The
depends_on (AG3-013 for the CCAG runtime, AG3-080 for the `health_monitor` boundary it disclaims)
is unchanged and consistent with the index.
