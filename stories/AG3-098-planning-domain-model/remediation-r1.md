# AG3-098 — Remediation Report (Review R1)

**Review:** `review-r1.md` (OVERALL: CHANGES-REQUESTED)
**Scope of remediation:** `story.md` + `status.yaml` only. No production code, tests, or `concept/` files touched.
**Cut/scope guard:** stayed strictly within the `_STORY_INDEX.md` AG3-098 slice (FK-70 §70.4-§70.6, BlockingCondition / Feasibility-vs-Scheduling / PlanDerivation / Wave / Human-External-Gates). New §70.4.1 and §70.6.2a items fall inside the indexed §70.4-§70.6 range and were absorbed in-scope (in-memory model only); all runtime/persistence concerns were routed to the index-named owners AG3-099 / AG3-100.

---

## Must-Fix ERRORs

### ERROR 1 — §70.4.1 `PlannedStory` coverage missing
**Finding:** Story omitted §70.4.1; `StoryRefForPlanning` (`entities.py:54`) lacks the mandatory planning fields.
**Resolution:** Added §70.4.1 to the authoritative source list. Added **Scope 1** (in-scope): `StoryRefForPlanning` is lifted to / superseded by a `PlannedStory` read-model carrying the full §70.4.1 field set (`project_key`, `story_id`, `story_type`, `story_size`, `participating_repos`, `human_touchpoints`, `external_prerequisites`, `planning_status`). New **AC1** asserts presence/typing of all fields and AG3-054 backward-compat (default fill). Population from authoritative persistence explicitly routed to AG3-099 (Out of Scope), since repo caps and gates need these fields here — in-scope is the cleaner fix as the reviewer noted.

### ERROR 2 — §70.6.2a Re-Plan-Trigger coverage missing
**Finding:** §70.6.2a is inside the indexed range and mandates event-driven re-evaluation; story named AG3-099/100 for persistence/runtime but not this trigger contract.
**Resolution:** Added §70.6.2a to the source list. Added **Scope 10**: a typed `RePlanTrigger` StrEnum (five trigger classes: `story_done`, `blocker_or_gate_changed`, `capacity_budget_changed`, `rulebook_or_policy_changed`, `conflict_or_contract_reevaluated`) plus a pure classification function — **model + pure classification only**. The runtime/event-driven, debounced enforcement (emission, revision, anti-thrashing) is explicitly assigned to AG3-099 (events/persistence) and AG3-100 (runtime enforcement) in Out of Scope. New **AC10** tests each class and asserts the runtime enforcement is provably absent.

### ERROR 3 — blocker-class → `PlanningStatus` mapping not precise
**Finding:** AC2 said "each blocker class maps to the correct `BLOCKED_*`" but FK has six blocker classes and only four `BLOCKED_*` statuses (no `BLOCKED_INTERNAL`/`BLOCKED_CONTRACT`).
**Resolution:** Added an explicit mapping table in **Scope 3** (no FK change — FK status model is treated as correct, mapping is the fix):
`blocked_internal_dependency`→`UNSTARTED` (pure graph state, §70.6.1 #1), `blocked_external`→`BLOCKED_EXTERNAL`, `blocked_human`→`BLOCKED_HUMAN`, `blocked_capacity`→`BLOCKED_CAPACITY`, `blocked_conflict`→`BLOCKED_CONFLICT`, `blocked_contract`→`BLOCKED_CONFLICT` (protected contract surface is a conflict state per §70.6.1 #5). Added a deterministic multi-blocker priority order. **AC3** rewritten to require a test per class plus a multi-blocker priority test.

### ERROR 4 — AC8 omits mandatory remote gates
**Finding:** Story only listed pytest/mypy/ruff/concept-gates/coverage; AGENTS.md requires Jenkins, Sonar, and `scripts/ci/check_remote_gates.ps1`.
**Resolution:** Split the old AC8 into **AC11 (local gates)** and a new **AC12 (remote gates)**: `scripts/ci/check_remote_gates.ps1` green (Jenkins `http://localhost:9900/job/claude-agentkit3/` + Sonar `http://192.168.0.20:9901`) with the strict Sonar targets `violations=0`, `critical_violations=0`, `security_hotspots=0` (per AGENTS.md). DoD updated to "AK 1–12".

### ERROR 5 — `status.yaml unblocks` empty
**Finding:** `unblocks: []` but the index has AG3-091, AG3-099, AG3-100 depending on AG3-098.
**Resolution:** `status.yaml` `unblocks` now lists `AG3-091`, `AG3-099`, `AG3-100` (confirmed against `_STORY_INDEX.md` lines 116/135/136).

### ERROR 6 — SchedulingHint vs Rulebook out-of-scope contradiction
**Finding:** Story required project-local hints to narrow `recommended_batch` while Rulebook compile is out-of-scope to AG3-099.
**Resolution:** Added **Scope 6**: a non-persistent in-memory `SchedulingHint` value type that may only *narrow* `recommended_batch` (never release). Explicitly distinguished from a compiled Rulebook / `rulebook_revision` write path, which stays assigned to AG3-099. **AC5** now references `SchedulingHint` (not Rulebook) and keeps the "cannot heal a feasibility violation" test.

### ERROR 7 — false `critical_path` Ist-Zustand claim; owner/projection undefined
**Finding:** "Grep `critical_path ...` ohne Treffer" is false; `critical_path` exists at `story_model.py:207` and `story_repository.py:403`.
**Resolution:** Rewrote the Ist-Zustand bullet to "no `PlanDerivation` output in `execution_planning`" and explicitly noted the existing `critical_path` read-model field/DB column as a downstream **projection, not the calculation owner**. Added an explicit **Owner/Projection rule** in §1 and reinforced it in **Scope 8** and **AC8**: the calculation owner is the pure PlanDerivation in the BC; `story_model.py:207` / `story_repository.py:403` are projections only — no second source of truth.

### ERROR 8 — typed-edge preservation / soft-dependency filtering
**Finding:** `DependencyGraph` discards edge kind (only predecessor IDs) and `compute_readiness` treats every predecessor as blocking, conflicting with `soft_story_dependency` (§70.4.2) and AC6.
**Resolution:** Added a dedicated Ist-Zustand bullet (ABWEICHEND) citing the real anchors: kind discarded in `dependency_graph.py:17-25` (`self._predecessors[...].add(edge.depends_on_story_id)` at `:25`), all-predecessors-blocking in `readiness.py:97-101`. Added **Scope 5**: the graph/feasibility layer must consume typed edges and treat only hard edges (per §70.6.1) as blocking; `soft_story_dependency` must not block feasibility; `has_cycle` stays unchanged. **AC6** now requires a mixed hard/soft test and a regression test that the kind is not discarded.

---

## WARNINGs

### WARNING (AC8) — "vier Konzept-Gates" not a testable command set
**Finding:** "vier Konzept-Gates" is not a concrete command set.
**Resolution (fixed in story):** Replaced with the exact gate commands in **AC11**: `scripts/ci/check_concept_frontmatter.py` and `scripts/ci/compile_formal_specs.py` (the two concept gates AGENTS.md names), plus pytest/mypy (default + `--platform linux`)/ruff/coverage. The vague "vier Konzept-Gates" wording was removed everywhere it appeared.

---

## Corrected code anchors (verified against real files)

| Old/claimed anchor | Corrected anchor | Note |
|---|---|---|
| `entities.py:25-41` StoryDependency | `entities.py:25-41` | verified correct |
| `kind ... aus core_types` | `core_types/dependency.py:15-41` | path/lines made precise |
| `StoryRefForPlanning` | `entities.py:54-64` | added; was implicit |
| `WaveStory.blocked_by` | `entities.py:77` | added precise line |
| `practical_parallelism` collapse | `readiness.py:44-47` | added precise lines |
| `critical_path` "no hits" (false) | `story_model.py:207`, `story_repository.py:403` | corrected to projection, BC has none |
| edge-kind discard | `dependency_graph.py:17-25` (`:25`) | newly cited |
| all-predecessors-blocking | `readiness.py:97-101` | newly cited |
| `lifecycle.py` services | `lifecycle.py:43-124` | added precise lines |

---

## Files written
- `stories/AG3-098-planning-domain-model/story.md` (rewritten; AG3-057 template structure preserved)
- `stories/AG3-098-planning-domain-model/status.yaml` (`unblocks` populated)
- `stories/AG3-098-planning-domain-model/remediation-r1.md` (this report)

No production code, tests, or `concept/` files were modified. ARCH-55 respected: all new identifiers, enum values, fields, and wire keys in the story are English.
