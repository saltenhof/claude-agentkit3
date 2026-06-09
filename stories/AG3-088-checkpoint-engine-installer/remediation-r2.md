# AG3-088 — Remediation R2 (hostile Codex review `review-r2.md`)

**Scope of edits:** `story.md` only (and this report). `status.yaml` was inspected and left
unchanged — no field is wrong (`type: implementation`, `status: draft`, `phase: review_pending`,
`depends_on: AG3-001/AG3-006/AG3-070` all match `_STORY_INDEX.md:104`). No production code, tests,
`concept/` files, or other stories' files were touched. AG3-057 template/section structure kept.
Scope held strictly to the `_STORY_INDEX.md:104` cut.

`review-r2.md` confirmed all eight R1 ERRORs are genuinely resolved and listed **two remaining
must-fix ERRORs and no WARNINGs**. Both are about how the FK-50 CP-dependency graph is mapped onto
the FlowDefinition node order — squarely inside the AG3-088 cut, so both are fixed **in-story**; no
routing to another owner was needed (and none is claimed). All concept anchors below were
re-verified against the real source before being written into `story.md`.

---

## Remaining Must-Fix ERRORs

### ERROR 1 — CP10b ordered before its declared dependency CP11
**Source of truth:** FK-50 §50.3 CP10b "Abhängigkeiten: CP 11 (Git-Hooks müssen konfiguriert
sein)" (`concept/.../50_installer_checkpoint_engine_bootstrap.md:416`). The previous node list put
`cp_10b_concept_validation_hook` inside `branch_vectordb_enabled` **before**
`cp_11_git_hooks_and_claude`, violating the dependency.

**Resolved.** Modelled the explicit two-step hook path the review asked for:
- §2.1.1 node list: the `branch_vectordb_enabled` branch is now **two-stage** — `cp_10a_...` runs
  before `cp_11_git_hooks_and_claude`, and a **second** `branch_vectordb_enabled` after CP11 routes
  `cp_10b_concept_validation_hook`. Added a normative "Abhaengigkeits-/Reihenfolge-Modellierung"
  block spelling out that CP11 creates/configures the hook substrate (`core.hooksPath`,
  `tools/hooks/` skeleton) and CP10b then registers the path-based concept-dispatch logic into the
  already-existing hook.
- §2.1.2 CP10b text: "nur `features.vectordb: true`, **nach CP11 modelliert**, weil CP10b die
  konfigurierten Git-Hooks aus CP11 voraussetzt (`...50...md:416`)".
- AC2 now asserts the two-stage vectordb branch (CP10a before CP11, CP10b after CP11), and the new
  AC9(b) asserts the edge `cp_10b` **after** `cp_11`.
- §2.1 test list + §6 sub-agent hint carry the ordering invariant as a flow-edge assertion.

### ERROR 2 — CP10c can run without its CP10 ARE-MCP dependency
**Source of truth:** FK-50 §50.3 CP10c "Abhängigkeiten: CP 5 (Pipeline-Config), CP 10 (ARE
MCP-Server)" (`...50...md:431`); CP10 registers "Auch ARE-MCP-Server wenn `features.are: true`"
(`...50...md:383`); FK-03 binds `are.mcp_server` to `features.are` only, **not** `features.vectordb`
(`03_konfigurationsmodell_schemas_versionierung.md:343`). The previous story branched CP10 solely on
`features.vectordb` while CP10c branched on `features.are`, so in an ARE-only profile
(`are: true, vectordb: false`) CP10c had no registered ARE-MCP server upstream.

**Resolved.** Defined the fail-closed feature invariant the review proposed (ARE implies the
required MCP registration path before CP10c):
- §2.1.1 node list: lifted `cp_10_mcp_registration` **out** of the pure-VectorDB branch into a
  shared node that runs when `features.vectordb: true` **OR** `features.are: true`, placed **before**
  `cp_10a`/`cp_10c`. When both features are off -> `SKIPPED`/`reason="vectordb_disabled"`.
- §2.1.2 CP10 text rewritten: CP10 is the common precondition for CP10a/CP10b (VectorDB) and CP10c
  (ARE); registers the Story-Knowledge-Base MCP server at `features.vectordb: true` and the **ARE-MCP
  server at `features.are: true` independent of VectorDB** (FK-03 `:343`, FK-50 `:431`).
- §2.1.2 CP10c text: added "Abhaengigkeit: CP5 + CP10/ARE-MCP (`...50...md:431`)" and a fail-closed
  rule — CP10c runs only after CP10 registered the ARE-MCP server; a missing ARE-MCP server as a hard
  precondition is `FAILED`.
- New AC9(a)/(c): CP10 lies before CP10a/CP10c; CP10 registers the ARE-MCP server in an ARE-only
  profile without VectorDB, and yields `SKIPPED`/`reason="vectordb_disabled"` only when both features
  are off (dedicated test).

---

## WARNINGs
None in `review-r2.md`. (The R1 `_STORY_INDEX.md` planning-source WARNING was already addressed and
routed in R1; it is outside this remediation's permitted write set and was not re-touched.)

---

## Knock-on edits (consistency, same fixes)
- Inserted a new AC9 (CP-dependency ordering), so the trailing criteria were renumbered: old
  AC9 (`.mcp.json`) -> AC10; old AC10 (dry-run) -> AC11; old AC11 (verify) -> AC12; old AC12 (CLI)
  -> AC13; old AC13 (mandatory commands) -> AC14. DoD updated "AK 1–13" -> "AK 1–14".
- AC10 (`.mcp.json`) clarified that CP10's MCP entry is Story-Knowledge-Base at vectordb / ARE-MCP at
  are, matching the reworked CP10.

## Anchors re-verified for this round
- FK-50 CP10b dependency on CP11: `...50...md:416`. ✔
- FK-50 CP10c dependency on CP5 + CP10 (ARE MCP): `...50...md:431`. ✔
- FK-50 CP10 also registers ARE-MCP at `features.are: true`: `...50...md:383`. ✔
- FK-03 validator: `are.mcp_server` required iff `features.are`, not `features.vectordb`:
  `03_konfigurationsmodell_schemas_versionierung.md:341-344`. ✔
- `_STORY_INDEX.md:104` AG3-088 cut + `depends_on` unchanged. ✔

## ARCH-55 / template
All new node IDs, reasons, and CLI tokens stay English; concept prose remains German per the
established story style. AG3-057 section structure (§1 Kontext, §2 Scope, §3 AC, §4 DoD,
§5 Guardrails, §6 Hints) preserved.

## Files written
- `stories/AG3-088-checkpoint-engine-installer/story.md` (edited; both ERRORs fixed in-scope)
- `stories/AG3-088-checkpoint-engine-installer/remediation-r2.md` (this report)
- `status.yaml`: **not modified** (no field was wrong)
