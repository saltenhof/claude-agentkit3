# AG3-088 — Remediation R1 (hostile Codex review `review-r1.md`)

**Scope of edits:** `story.md` only (and this report). `status.yaml` was inspected and left
unchanged — no field was wrong (`type: implementation`, `status: draft`, `phase: review_pending`,
`depends_on: AG3-001/AG3-006/AG3-070` all match `_STORY_INDEX.md:104`). No production code, tests,
or `concept/` files were touched. Scope held strictly to the `_STORY_INDEX.md:104` cut (Installer as
`FlowDefinition` with the FK-50 §50.2-§50.4 checkpoint set + dry-run/verify modes + register/verify CLI);
no scope expansion.

All code anchors below were re-verified against the real source before being written into `story.md`.

---

## Must-Fix ERRORs

### ERROR 1 — CP10c omitted (FK-50 §50.3 CP10c, `concept/...50...md:421-433`)
**Resolved.** Added `cp_10c_are_scope_validation` as an in-scope checkpoint under `branch_are_enabled`
(story §2.1.1 node list, §2.1.2 CP10c). Defined the result/status behaviour: `are_scope` + full
`are.module_scope_map` check, delta-only resolution, interactive vs. agentic mode, agentic
`PENDING_SELECTION` mapped onto `CheckpointResult` status `SKIPPED` / `reason="pending_selection"`
(no status neologism; PENDING_SELECTION metadata travels in `detail`/handler payload), resolved/mapped
items -> `UPDATED`/`PASS`, idempotent skip. Added AC8 with three tests (missing mapping, resolved
mapping, idempotent skip) plus the `are_disabled` skip path. Routed the ARE-API scope source +
`resolve_pending_scope_mapping()` producer to owner story **AG3-077** in §2.2 (CP10c only consumes).

### ERROR 2 — Reserved CP3/CP4 not specified as flow nodes (`concept/...50...md:136-139, 174-178, 224-236`)
**Resolved.** Added explicit `cp_03_reserved` and `cp_04_reserved` no-op `step` nodes to the node list
(§2.1.1) and §2.1.2 with deterministic `CheckpointResult` semantics: status `SKIPPED`,
`reason="reserved"`, no action. Added AC5 asserting this deterministically and listed both IDs in AC3.

### ERROR 3 — CP8 incomplete (missing `PromptRuntime.update_binding`, `concept/...50...md:304-318, 595-619`)
**Resolved.** Expanded CP8 in §2.1.2 to cover both `Skills.bind_skill(...)` and the prompt-bundle binding
preservation/transfer via `PromptRuntime.update_binding(bundle_id, version)`
(verified at `src/agentkit/prompt_runtime/runtime.py:206`, class `PromptRuntime` at `runtime.py:134`).
Added AC6 asserting both calls, and a test entry in §2.1.5.

### ERROR 4 — Non-existent status `UPGRADED` (FK-50 status set is `PASS/CREATED/UPDATED/SKIPPED/FAILED`)
**Resolved.** Replaced every `UPGRADED` with `UPDATED` across the story (idempotent re-run wording in
§2.1.3, AC11, §2.1.5 tests). Verified the code vocabulary: `CheckpointStatus` =
`PASS/CREATED/UPDATED/SKIPPED/FAILED` at `src/agentkit/installer/registration.py:43-50` (no `UPGRADED`).

### ERROR 5 — Dry-run result semantics underspecified (`story.md` old `:54`)
**Resolved.** Added an explicit **Dry-Run-Result-Contract per CP** in §2.1.3: handler reports the
*planned* status the real register run would produce (`CREATED`/`UPDATED`/`PASS`/`SKIPPED` with the same
`reason` as register, e.g. `vectordb_disabled`/`not_applicable`/`reserved`), plus a stable plan token
`reason="planned_no_mutation"` for would-create/would-update outcomes and a plan marker in `detail` so a
consumer can hard-distinguish "planned, not executed" from a real mutation result. Reflected in AC10 and
a dedicated test in §2.1.5.

### ERROR 6 — `.mcp.json` contradiction (scope CP10 mutates `.mcp.json` vs. note "NICHT anfassen")
**Resolved (coherent fix per review, FK-50 §50.3 in scope).** Clarified in §6 and AC9 that two different
files are meant: CP10 mutates the **target-project `.mcp.json`** in `register` mode (FK-50 §50.3 CP10,
`concept/...50...md:365-383`) — in scope — while the **AK3 repo's own `.mcp.json`** (the dev MCP config in
this repo root; confirmed the only `.mcp.json` in the repo) is never touched. `dry_run`/`verify` leave even
the target `.mcp.json` unchanged. Removed the blanket "`.mcp.json` NICHT anfassen" wording and replaced it
with the precise two-file distinction. AC9 tests target-`.mcp.json` immutability under dry_run/verify.

### ERROR 7 — Grep-based God-function AC not test-sharp (old AC1, `story.md:49`)
**Resolved.** Rewrote AC1 to a measurable structural criterion: `install_agentkit` is either removed or a
**thin facade** delegating exclusively to `CheckpointEngine.run(...)` with no remaining imperative
checkpoint-ordering logic; the test asserts flow execution through the engine and delegation (not grep
wording). Mirrored in Guardrail §5 ("KEINE MONOLITHISCHE WORKFLOW-DATEI"). Confirmed the current God
function exists at `src/agentkit/installer/runner.py:1014`.

### ERROR 8 — False code-location claim for `Governance.register_hooks` (old `story.md:24`)
**Resolved.** Corrected every reference: data models (`HookDefinition` etc.) live in
`governance/hook_registration.py`, but the **method** `register_hooks` is at
`src/agentkit/governance/runner.py:193` (verified). Updated §1 anchor list, §2.1.2 CP9, AC7, and §6.

---

## WARNINGs

### WARNING — `_STORY_INDEX.md:104` row omits CP10c while claiming §50.2-§50.4 coverage
**Addressed in-story + routed to the planning-source owner.** The substance of the gap is now closed in
`story.md` (CP10c is fully in scope: node, result contract, AC, tests). The `_STORY_INDEX.md` row itself is
the planning source and is **outside this remediation's permitted write set** (instruction: edit only this
story's `story.md`/`status.yaml`/`remediation-r1.md`). Routed as an explicit follow-up to the **owner of
`var/concept-gap-analysis/_STORY_INDEX.md`** (the planning/PO maintainer of this backlog): update the
AG3-088 row's Scope cell to name `CP10a/10b/10c/10d` (and reserved CP3/CP4) so the planning source stops
re-seeding the same concept gap. This is a one-line index edit; no story scope change is implied.

---

## PASS evidence re-verified (review's "PASS evidence" block)
- FK anchors exist: §50.2 (`...50...md:114`), §50.3 (`:130`), §50.3.1 (`:150`), §50.4 (`:567`). ✔
- God function `install_agentkit` at `src/agentkit/installer/runner.py:1014`. ✔
- `FlowDefinition` at `src/agentkit/process/language/model.py:175`; `FlowLevel.COMPONENT` at `model.py:40`;
  `NodeKind.STEP/BRANCH` at `model.py:46`/`:49`. ✔
- CLI lacks `register-project`/`verify-project` (`src/agentkit/cli/main.py:38-160`). ✔
- Additional anchors corrected to real source while remediating: CP7 idempotent digest compare at
  `runner.py:1335`; CP5 at `runner.py:1076-1079`; CP6/`_resolve_skill_profile` at `runner.py:674`;
  CP8 `bind_skill` at `runner.py:882` and `Skills.bind_skill` at `skills/top.py:361`;
  `CheckpointResult` at `installer/registration.py:123-173` (was wrongly cited as `43-179`);
  `CheckpointStatus` at `registration.py:43-50`; `RuntimeProfile` at `registration.py:33`.

---

## Files written
- `stories/AG3-088-checkpoint-engine-installer/story.md` (rewritten; template/structure of AG3-057 kept)
- `stories/AG3-088-checkpoint-engine-installer/remediation-r1.md` (this report)
- `status.yaml`: **not modified** (no field was wrong)
