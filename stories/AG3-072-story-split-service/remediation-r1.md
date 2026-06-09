# AG3-072 — Remediation R1 (after hostile Codex review)

Scope of this remediation: **only** `stories/AG3-072-story-split-service/story.md`.
No production code, tests, concept files, other stories' files, or `status.yaml`
were touched. `status.yaml` (`depends_on: [AG3-032, AG3-068]`) was verified against
`var/concept-gap-analysis/_STORY_INDEX.md` line 73 and is already correct — no field
was genuinely wrong, so it was left unchanged.

All cited code anchors were re-verified against the real source before editing.

---

## Must-Fix ERRORs

### MF1 — False `In Progress -> Cancelled` claim + missing admin split-cancel path
**Finding:** Story claimed `In Progress -> Cancelled` is allowed (`story.md:27`, `:80`).
Real code forbids it: `_ALLOWED_TRANSITIONS` only has `Backlog/Approved -> Cancelled`
(`service.py:84-85`); `_check_transition` raises for `In Progress -> Cancelled`
(`service.py:112-122`); `cancel_story` docstring says `In Progress or Done ->
invalid_transition` (`service.py:604`).
**Resolution:**
- Rewrote the Ist-Zustand bullet (§1) to state the truth: the existing `cancel_story()`
  path (Frontend transition guard, `service.py:594-654`) does **not** cover the split,
  with corrected anchors `service.py:84-85`, `:112-122`, `:604`.
- Specified a dedicated **administrative Split-Cancel-Pfad** (`In Progress -> Cancelled`,
  reason `scope_split`) that uses Cancelled semantics but bypasses neither via Closure
  nor via the Frontend `cancel_story()` guard.
- Threaded this through In-Scope item 6 (step 7 of the §54.8 flow) and into AC8.
- Fixed the stale anchor in §6 Hinweise (`service.py:602-649`/`:112` →
  `service.py:594-654` + transition table `:80-89` + `_check_transition` `:97-130`).

### MF2 — FK-54.4 entry preconditions missing as hard contract + negative test
**Finding:** §54.4 preconditions (`scope_explosion`, human approval, valid plan,
no competing admin op; concept `54_...md:133-145`) only appeared in passing; no
fail-closed check / negative test. Formal scenario
`reject-without-scope-explosion-preconditions` (`scenarios.md:36-44`) was uncovered.
**Resolution:**
- Added `FK-54 §54.4` to the autoritative Quell-Konzepte header.
- Added dedicated **In-Scope item 2** "Einstiegsgate (§54.4)" as a fail-closed
  service contract executed before any mutation.
- Added the procedural gate note to the §54.8 flow item.
- Added **AC3** (precondition reject, citing the formal scenario) requiring
  `status=failed` with **no partial mutation**, one negative test per precondition.
- Strengthened the FAIL-CLOSED guardrail reference.

### MF3 — Dependency-rebinding ACs too narrow
**Finding:** AC5 only checked the stale pointer; formal invariants
(`dependency-rebinding/invariants.md:30-44`) also require no_silent_drop,
deterministic_target_selection, no_unjustified_fanout, graph_integrity (no
duplicate edges / no cycles), and mapping-after-successors-created.
**Resolution:**
- Rewrote In-Scope item 7 to enumerate all six formal invariants by id.
- Rewrote **AC6** into a multi-part criterion covering no_stale_cancelled_target,
  no_silent_drop, deterministic_target_selection, no_unjustified_fanout, and
  graph_integrity_preserved, each with a (negative) test obligation.

### MF4 — `split_id` / resume key undefined
**Finding:** AC10 spoke of "the same `split_id`" on a second run, but the CLI only
has `--story --plan --reason` (`54_...md:158-174`); no way to find/pass the id again.
**Resolution:**
- Defined a **deterministic resume key** `(project_key, source_story_id, plan_ref-hash)`
  from which `split_id` is derived (In-Scope item 3).
- Made In-Scope item 5 (CLI) explicit: exactly `--story/--plan/--reason`, **no**
  `--split-id` option; the resume key follows from `--story` + `--plan`.
- Rewrote **AC11** accordingly (resume finds the same record; no double creation /
  rebinding / second cancel; CLI takes no `split_id`).

### MF5 — Guard-AC conflates branch-guard with backend service path
**Finding:** AC9 mixed the branch-guard allowlist with the `ALLOW_VIA_OFFICIAL_SERVICE_PATH`
verdict, which is AG3-087 (Out of Scope). Real branch guard only allows command
prefixes (`branch_guard.py:23-27`).
**Resolution:**
- Split In-Scope item 9 to cover **only** the existing branch-guard command-prefix
  path (`_OFFICIAL_ALLOW_PREFIXES`, `branch_guard.py:23-27`); explicitly excludes the
  AG3-087 service-path verdict.
- Rewrote **AC10** to test only the prefix path and explicitly **not** the AG3-087 verdict.
- Clarified the AG3-087 Out-of-Scope entry: this story does not model it and does
  **not** depend on it (clean boundary, not a blocker).

---

## WARNINGs

### W1 — `story_lineage` missing from the plan model
**Finding:** `formal.story-split.entities:36-42` lists `story_lineage` as a split-plan
attribute; the story plan structure omitted it.
**Resolution:** Chose the "deterministically derived" normalization (the option the
review allowed): added `story_lineage` to the plan model (In-Scope item 4 and the
§54.7 header line) and stated it is derived deterministically from `source_story_id`
+ `successors[].story_id` and materialized via `split_from`/`split_successors`.
AC7 updated to reflect the deterministic derivation.

### W2 — Idempotency not testably specified
Resolved together with MF4 (resume key + AC11). The second run is now defined and testable.

---

## Anchor corrections (wrong → verified file:line)
- `service.py:602-649` / `In Progress → Cancelled ist erlaubt, service.py:112`
  → `service.py:594-654` (cancel path), `:84-85` (allowed transitions),
  `:97-130`/`:112-122` (`_check_transition` blocks it), `:604` (docstring).
- `service.py:384` Backlog creation → `service.py:378-384` (matches the review's
  verified anchor for backlog creation).
- `branch_guard.py:26` → `branch_guard.py:23-27` (`_OFFICIAL_ALLOW_PREFIXES` tuple).

---

## Cross-story prerequisites (genuine)
- **AG3-032** and **AG3-068** — existing hard `depends_on` (story creation/backend
  + VektorDB reindex owner). Unchanged; correct per `_STORY_INDEX.md`.
- **AG3-087** (FK-55 service-path verdict) — explicitly **NOT** a prerequisite. This
  story is self-contained via the existing branch-guard command prefix; AG3-087 may
  later add the `ALLOW_VIA_OFFICIAL_SERVICE_PATH` verdict as an additional anchor.
- **AG3-074** (FK-59 `terminal_state`/`exit_class`) — soft boundary only: this story
  sets `StoryStatus.CANCELLED` and mirrors the `exit_class=scope_split` mapping to
  AG3-074 rather than duplicating that axis. Not a blocking dependency.

No new cross-story prerequisite was introduced by this remediation.

---

## ARCH-55 / template compliance
- All new identifiers, wire keys, and CLI options remain English
  (`split_id`, `story_lineage`, `scope_split`, `_OFFICIAL_ALLOW_PREFIXES`, etc.).
  German remains only in fachliche Prosa, as permitted.
- AG3-057 template structure preserved: §Quell-Konzepte, §1 Kontext/Ist-Zustand,
  §2 Scope (In/Out), §3 Akzeptanzkriterien, §4 Definition of Done,
  §5 Guardrail-Referenzen, §6 Hinweise fuer den Sub-Agent — all intact; only
  content edited within sections, no sections added or removed.
