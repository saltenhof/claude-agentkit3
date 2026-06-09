# AG3-100 — Remediation R1 (hostile Codex review)

Scope of this remediation: `story.md` only (status.yaml verified, no field genuinely wrong → untouched). No production code, tests, concept/formal files, or other stories' files were modified. All review claims were re-verified against the real code/concept before fixing.

## Must-Fix (ERRORs)

### 1. §70.11 Invariant #10 fehlte in Scope/AC/Tests — RESOLVED (taken in-story)
- **Finding:** Title/Index assign AG3-100 the §70.11 invariants, but #10 (optional Human-Review must not be silently treated as a blocking Human-Gate) appeared only in the Ist-Zustand, not in Scope/AC/tests (review §Konzept-Vollstaendigkeit; FK-70 `70_...:845-846`; gap `gap-fk-58-70.md:458`).
- **Resolution:** #10 added to the authoritative source list, to §1 Ist-Zustand (explicit gap), to Scope §2.1.7, to AC7 (negative test: optional review open → story stays READY; only a declared-blocking Human-Gate holds), to the test list §2.1.8, and to the FAIL-CLOSED/DoD guardrails. The optional-vs-blocking Human-Gate classification is consumed from AG3-098 (out-of-scope owner noted in §2.2), so the AG3-100 cut stays a pure enforcement/consumption layer.

### 2. Duplicate owner with AG3-091 — RESOLVED (owner cut documented)
- **Finding:** Both stories appeared to scope `execution-input/snapshot|next` (review §Kontext-Sinnhaftigkeit; index `_STORY_INDEX.md:116` vs `:136`).
- **Verification:** AG3-091's story.md is **already narrowed** — it explicitly excludes snapshot/next + the single selector + the reason-entity and routes them to AG3-100 (`AG3-091 story.md:5`, `:25`, §2.2 `:44`, §6 `:74`, cross-story prereq `:83`); AG3-091 keeps only `limits` + the other read-models.
- **Resolution:** Added an explicit "Owner-Schnitt gegen AG3-091" block in §1 plus notes in §2.2 and §6: AG3-100 owns snapshot/next + the one selector + the formal `next`-reason-entity; AG3-091 owns only `limits` and consumes the surface. The stale index-row prose (`_STORY_INDEX.md:116`) is flagged as superseded by the narrowed story file; the authoritative boundary is the story files. No claim is made that AG3-091 delivers anything outside its narrowed scope. (Index file not edited — shared/other-owner file.)

### 3. Wrong/conflicting wire field names — RESOLVED (snake_case per formal spec)
- **Finding:** Story used CamelCase `eligibleReady`/`totalReady`/`globalSlotsLeft`; formal contract defines snake_case `eligible_ready`/`total_ready`/`global_slots_left` (`entities.md:685`/`:694`/`:699`); AG3-091 excludes CamelCase as UI-prototype form.
- **Resolution:** All occurrences switched to snake_case bound to `frontend-contracts.entity.execution_input_snapshot` (`entities.md:669-706`) — in the source-concept header, Scope §2.1.4, AC4 (now requires a contract-test against the formal entity), and the ARCH-55 guardrail (CamelCase explicitly named as UI-only, not the wire shape).

## Cross-cutting (also ERROR-class, raised by review claim re reason-entity)

### Formal `next`-reason-entity ownership — RESOLVED (scoped to AG3-100)
- **Finding/verification:** No `next`/reason/triage entity exists in `formal.frontend-contracts.entities` (`entities.md:669-753` has only `execution_input_snapshot`/`execution_input_stack`/`execution_limits`). AG3-091 explicitly designates AG3-100 as the owner that introduces it (`AG3-091 story.md:44`, `:83`).
- **Resolution:** AG3-100 now explicitly scopes introducing the formal `next`-reason-entity (Scope §2.1.5) and binding `/execution-input/next` to it via contract-test (AC5, FK-72 §72.14.3). This closes the duplicate-owner cut self-consistently — AG3-091 is not claimed to deliver it. (The actual `entities.md` edit happens at implementation time, which is out of remediation scope; this remediation only authorizes/cuts it.)

## WARNINGs

### 4. Existing start-path not framed as migration context — RESOLVED
- **Finding:** A fail-closed `PreStartGuard` already consumes `assess_readiness` in `control_plane.dispatch`; `PipelineEngine` itself calls no planning surface. Story only said "PipelineEngine not wired", risking a second admission layer.
- **Verification:** `PreStartGuard` at `dispatch.py:95-120`, port `SchedulingAdmissionReader` `:77-93`, fires before fresh setup start `:277-287`, reads `assess_readiness` `:599-635` (call `:626`), factory `:640-650`. Confirmed exact.
- **Resolution:** §1 now describes the existing admission path as the migration point; Scope §2.1.2 and AC2 require migrating that one Tor-2 path from `assess_readiness` to `evaluate_scheduling` with a test proving no second parallel admission/scheduling truth; §6 spells out the anchors and the no-cycle constraint. FAIL-CLOSED/SSOT guardrails updated.

### 5. Mandatory remote gates missing from AC8/DoD — RESOLVED
- **Finding:** AC8 listed only local tests/ruff/mypy/concept-gates; AGENTS.md requires Jenkins + Sonar via `scripts/ci/check_remote_gates.ps1` before "done" with strict Sonar target (`AGENTS.md:31-43`).
- **Resolution:** AC8 extended with remote gates via `scripts/ci/check_remote_gates.ps1` (Jenkins green + Sonar strict `violations=0`/`critical_violations=0`/`security_hotspots=0`); DoD §4 and §6 updated to require remote gates before "fertig".

## Code-anchor corrections (review noted weak/missing anchors)
All anchors verified and made file:line-precise in the rewrite:
- `execution_planning/__init__.py:14-31` (only `assess_readiness` exported, no `evaluate_scheduling`).
- `execution_planning/http/routes.py:39-52`, `:125-157` (dependency-graph/dependencies/next-ready/config only).
- `control_plane/dispatch.py:77-93`/`:95-120`/`:277-287`/`:599-635`/`:626`/`:640-650` (PreStartGuard + assess_readiness wiring).
- `execution_planning/dependency_graph.py:48-59` (`has_cycle`), `lifecycle.py:72-78` (`add_dependency` rejects cycles, no quarantine).
- `concept/technical-design/20_...:760-773` (FK-20 §20.8.2), `70_...:820-846` (§70.11 incl. #10), `entities.md:669-706` (snapshot wire-shape).

## Self-consistency / cut discipline
- Story stays strictly within the AG3-100 cut: enforcement/consumption layer over AG3-098 (domain) + AG3-099 (persistence/revision); owns snapshot/next + single selector + formal `next`-reason-entity + invariant enforcement. No domain types redefined; no `limits` read-model pulled in.
- AG3-057 template structure preserved (sections 1–6: Kontext/Ist-Zustand, Scope In/Out, Akzeptanzkriterien, Definition of Done, Guardrail-Referenzen, Hinweise fuer den Sub-Agent).
- ARCH-55: API paths/fields English; wire fields snake_case per formal spec.

## Genuine cross-story prerequisites (other owners)
1. **AG3-098** (depends_on) — Planning domain model incl. the optional-vs-blocking Human-Gate classification that invariant #10 enforces, plus Feasibility/Scheduling/Wave/Budget. AG3-100 consumes, does not define.
2. **AG3-099** (depends_on) — Proposal/persistence/revision model that revision-bound idempotency (#8) relies on.
3. **AG3-091** (already narrowed, consumer) — read-layer consumer of the snapshot/next surface; owns only `limits`. No action needed on AG3-091; boundary documented on both sides.
4. **Real cap values** (`llm_pool_cap`/`ci_capacity_cap`) — AG3-070/Pool-BC; AG3-100 consumes typed budgets only.
