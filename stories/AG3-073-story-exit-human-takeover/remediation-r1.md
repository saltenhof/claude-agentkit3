# AG3-073 — Remediation R1 (after hostile Codex review)

Scope: rewrote `story.md` only (and verified `status.yaml`). No production code, tests, or
`concept/` files touched. Stayed strictly within the AG3-073 cut from `_STORY_INDEX.md`
(`exit-story` CLI, reason-enum, four artefacts, `exit_gate`, `exit_class=viability_handoff`
under Cancelled, controlled fallback to `ai_augmented`). No scope expansion.

All code anchors below were verified against the real source before being written into the story.

---

## Must-Fix ERRORs

### ERROR 1 — §58.7 alternative review missing as record/dossier/gate/test obligation
**Was:** Story cited §58.7 but no AC enforced the mandatory check of alternatives
(carry standard contract / reclassify to `integration_stabilization` / story-split).
**Resolved:**
- Added typed `AlternativeReview` model to the `story_exit_record.json` schema (§2.1 #5)
  with `standard_contract_checked` / `reclassification_checked` / `split_checked` (bool)
  plus a non-empty `*_rejection_reason` per alternative.
- New §2.1 #3 makes admissibility a separate context check that consumes `AlternativeReview`
  and fails closed on any missing check or empty rejection reason.
- New AC3 makes it testable (≥3 negative tests, one per missing alternative + one empty-reason test).
- `exit_gate` condition (a) now explicitly includes "passed alternative review" (§2.1 #7, AC7).
- Quell-Konzept line for §58.7 expanded to name the three concrete alternatives.

### ERROR 2 — §58.3 admissibility wrongly reduced to enum validation
**Was:** Story said "Die Enum ist der Owner der Zulaessigkeitspruefung", but §58.3 forbids
exit for normal difficulty / agent uncertainty / usual remediation / split-solvable cases —
none of which enum membership can express.
**Resolved:**
- §2.1 #2 now scopes the enum to **reason-code owner only** ("decides the reason code, not admissibility").
- §2.1 #3 models admissibility separately (the `AlternativeReview` context check), explicitly
  excluding the §58.3 context-prohibitions fail-closed.
- AC2 restated: enum decides only the reason code, not admissibility.
- §58.3 Quell-Konzept line rewritten to call out the context-prohibitions as NOT covered by enum membership.

### ERROR 3 — Human-only / admin path not testable against orchestrator/agent self-decision
**Was:** AC8 ("orchestrator/agent self-decision cannot trigger the exit") named no concrete
API/`principal_type`/`source_component` to reject.
**Resolved:**
- Bound enforcement to the **real** owner: `Principal.HUMAN_CLI` (`principals.py:47`) +
  `PrincipalResolver.resolve(...)` (`principals.py:103`), which derives the principal only from
  attested harness/CLI context (`--ak3-principal-attest`), never from prompt text (FK-55 §55.3a).
- New §2.1 #10 + AC9: service accepts only `Principal.HUMAN_CLI`; a direct service call with
  `Principal.ORCHESTRATOR` or `Principal.WORKER` is fail-closed (one negative test per principal).

### ERROR 4 — Branch-Guard / `ADMIN_SUBCOMMANDS` owner decision left optional ("falls trivial")
**Was:** Story demanded `exit-story` as the single official path but made allowlist inclusion
optional / a follow-up to AG3-087. Contradiction.
**Resolved:**
- New §2.1 #11 makes the allowlist inclusion **hard in scope**: add `exit-story` to
  `ADMIN_SUBCOMMANDS` (`operations.py:168`) and to `_OFFICIAL_ALLOW_PREFIXES`
  (`branch_guard.py:23`). New AC10 tests it.
- The deeper **service-path verdict** (`is_official_service_path` / `ALLOW_VIA_OFFICIAL_SERVICE_PATH`)
  stays AG3-087-owned (it is genuinely a separate, unbuilt mechanism per `_STORY_INDEX.md`
  AG3-087/FK-55). This story only extends the two existing allowlists — no new verdict mechanism.
  Removed all "falls trivial" language.

### ERROR 5 — Teardown owner wrong: `BindingDeleteScope` is not the lock/guard teardown
**Was:** Story sold `BindingDeleteScope` as the teardown path for lock/session/guard regime.
**Resolved (verified against source):**
- `BindingDeleteScope` (`records.py:18`) is **only** the run-scoped binding KEY; corrected everywhere.
- Real owners named: `commit_operation_with_side_effects` (`runtime.py:1233`, atomic op-row +
  INACTIVE locks + binding deletion + deactivation events in one transaction) and
  `Governance.deactivate_locks` (`runner.py:265`, lock-export removal + guard deactivation +
  `restored_to_ai_augmented`). Fallback to `ai_augmented` via `_resolve_operating_mode`
  (`runtime.py:1977`).
- Updated in §1 (Anknuepfungspunkte), §2.1 #4/#8, AC8, §5, §6 (incl. a pitfall note).

---

## WARNINGs

### WARNING (AC-Schärfe) — AC4 "korrektes Schema/Producer" named no schema/envelope/producer owner
**Resolved:** §2.1 #5 now fixes a Pydantic-v2 schema owner per artefact
(`StoryExitRecord` / `ExitManifestSnapshot` / `DeltaQuarantine`) and one Producer-ID
`story_exit_service` (deterministic producer); typed field list given for `StoryExitRecord`.
Notes that an existing artefact-envelope/producer registry, if present, is reused rather than
duplicated. AC5 updated to reference the fixed schema-owner/producer.

---

## NITs

### NIT — basename-only anchors (`operations.py:168` / `branch_guard.py`)
**Resolved:** All anchors throughout the story now use full repo paths and verified line numbers,
e.g. `src/agentkit/governance/principal_capabilities/operations.py:168`,
`src/agentkit/governance/guards/branch_guard.py:23`.

---

## PASS items left intact
The reviewer's verified PASS anchors (`FK-58 §58.2-§58.10`, `FK-59 §59.6.2`, "no exit terms
under src/agentkit", CLI without `exit-story`, `engine.py:751` local variable, Runtime /
StoryStatus / ControlPlaneRecord anchors) were preserved and, where useful, annotated as
"Review-PASS bestaetigt".

---

## Anchor verification log (read from real source this pass)
- `cli/main.py` — no `exit-story` (confirmed).
- `governance/principal_capabilities/operations.py:168` — `ADMIN_SUBCOMMANDS = {"reset-story","split-story","resolve-conflict","cleanup"}` (no `exit-story`).
- `governance/guards/branch_guard.py:23` — `_OFFICIAL_ALLOW_PREFIXES` (no `exit-story`).
- `governance/principal_capabilities/principals.py:47` — `Principal.HUMAN_CLI = "human_cli"`; `:103` `PrincipalResolver.resolve`.
- `control_plane/records.py:18` — `BindingDeleteScope` (run-scoped key only).
- `control_plane/runtime.py:1233` — `commit_operation_with_side_effects` (atomic teardown).
- `control_plane/runtime.py:1977` — `_resolve_operating_mode`.
- `governance/runner.py:265` — `Governance.deactivate_locks`.
- `story_context_manager/story_model.py:46` — `StoryStatus.CANCELLED = "Cancelled"`.
- `pipeline_engine/engine.py:751` — local `terminal_state` PhaseState variable.
- `concept/technical-design/59_story_contract_axes_and_combination_matrix.md:223` — §59.6.2 `exit_class`.

## status.yaml
Checked: `status: draft`, `phase: review_pending`, `depends_on: [AG3-032, AG3-053]`,
`size: L`, `type: implementation` all match `_STORY_INDEX.md` (AG3-073, L, depends_on
AG3-032/AG3-053). No field was wrong; status.yaml left unchanged.
