# AG3-078 — Remediation r3 (hostile Codex review, round-3)

Scope of this remediation: rewrote `story.md` only, plus one `status.yaml` `depends_on`
change. No production code, tests, `concept/` files, or OTHER stories' files were touched.
All resolutions stay strictly within the AG3-078 functional cut (Failure-Corpus Stufe 2/3).
Code anchors and concept anchors verified against the real source and the concept index
(FK-41 §41.3/§41.6/§41.6.7, FK-69 §69.8/§69.9, FK-03 §3.1). Identifiers/enum values are
English (ARCH-55). The AG3-057 template structure (sections 1–6) is preserved.

The central correction this round: the cross-story OWNERSHIP claims were false. r2 routed
the `story_metrics`/`ProjectionFilter` prerequisites to AG3-081 and the Sonar config field to
AG3-070 as if those stories deliver them. They do not. AG3-078 was therefore
self-contradictory and not buildable. Every routed prerequisite is now stated honestly as a
cross-story action item ("owner story must be EXTENDED to add X — not yet in its scope"),
no AC depends on a field that no story provides, and each such AC is fail-closed gated on
its prerequisite.

## Verification of the ownership contradiction (read of the real stories + code)

- **AG3-081** (`stories/AG3-081-.../story.md`): scope = BC14/BC15 EventTypes + mandatory-
  payload contract, Telemetry-Evidence-Wiring (FK-68 §68.4), typed `phase_state_projection`
  record, guard-invocation counters, reset-purge **delta**. It does **not** touch the
  `story_metrics` schema and does **not** touch `ProjectionFilter`. Its §2.1.7 even leaves
  `fc_check_proposals` untouched and §2.1.5 leaves the `phase_state_projection` field-set to
  AG3-059. → r2's "AG3-081 delivers story_metrics.check_ref / outcome columns /
  ProjectionFilter.check_ref/since_days" is false.
- **AG3-070** (`stories/AG3-070-.../story.md`): AC4 delivers the stanzas
  `orchestrator_guard`/`policy`/`vectordb`/`telemetry`/`governance` only. It does **not**
  deliver a `sonarqube` stanza at all, let alone `accept_frequency_fc_threshold`.
- **AG3-059**: owns `phase_state_projection` (PhaseStateCore), not `story_metrics`.
- **AG3-079**: adversarial runtime; no `story_metrics`/`check_ref`/outcome production in scope.
- **Real code:** `SonarQubeConfig` (`config/models.py:171-180`) lacks the field;
  `StoryMetricsRecord` (`closure/post_merge_finalization/records.py:11-31`) lacks `check_ref`
  / outcome / no-finding fields; `ProjectionFilter` (`projection_accessor.py:119-140`) lacks
  `check_ref`/`since_days`.
- **Concept anchors:** FK-41 §41.6.7 normatively reads `story_metrics` via
  `read_projection(filters={"check_ref": ...}, since_days=...)` (the read contract is
  concept-grounded). But the FK-03 §3.1 `sonarqube` stanza schema contains **no**
  `accept_frequency_fc_threshold` field, and FK-41 §41.10 names the signal without normalizing
  a concrete config field/default → the r2 anchor "FK-03 §3.4.2 default 0.25" was a wrong
  anchor and is removed.

## Must-Fix ERRORs (round-3)

### 1. story_metrics/ProjectionFilter prerequisites falsely routed to AG3-081/AG3-079 (RESOLVED)
- Resolution rule applied: option (b) — explicit cross-story prerequisite. These are
  extensions of a closure-owned model (`story_metrics`) and a telemetry-owned contract
  (`ProjectionFilter`); absorbing them into failure-corpus would create a second operative
  truth (FIX-THE-MODEL violation), so they cannot be option-(a) absorbed.
- §1 Befund 5, §2.1.4, §2.2 now state: **no in-scope story delivers these fields**; they are
  cross-story action items CP2 (`story_metrics` schema, owner story-closure.
  PostMergeFinalization) and CP3 (`ProjectionFilter`, owner telemetry-and-events) that the
  execution-plan/index owner must assign to an owner and have that story EXTENDED. The story
  no longer claims AG3-081/AG3-079 deliver anything they don't.
- AC5 is now fail-closed gated on CP2/CP3: the production read path fails closed if the
  fields are absent (no silent fallback). AG3-078's aggregation/auto-deactivation logic is
  tested against directly-seeded `story_metrics` test rows carrying the CP2 fields, so the
  story stays independently buildable/testable without depending on an unprovided field.
- Outcome population from real runs is split out as CP4 (owner near AG3-079, not in scope).

### 2. Sonar threshold dependency still not genuinely closed (RESOLVED)
- Resolution rule applied: option (b). The `sonarqube` stanza model is owned by the
  `project-config` BC (AG3-070); failure-corpus must not second-copy a config value
  (FIX-THE-MODEL). Absorbing it is therefore disallowed.
- §1 Befund 3, §2.1.7, §2.2/CP1 now state honestly: the field exists neither in the code
  model nor in the FK-03 §3.1 stanza; it is a **new config field to be added by AG3-070**
  (cross-story prerequisite CP1), not a field AG3-070 already delivers. The wrong anchor
  "FK-03 §3.4.2 (default 0.25)" is removed; FK-03/FK-41 prose alignment is doc-only AG3-103.
- AC8 is fail-closed gated on CP1: the signal reads no story-owned default and fails closed
  if the field is missing; its threshold-comparison logic is tested against an injected
  threshold (buildable without CP1). `depends_on AG3-070` retained as a true build-order edge
  to the config-owner BC (the field lands in AG3-070's model once extended).

### 3. purge_run wording conflicts with FK-69/FK-41 reset semantics (RESOLVED)
- §2.1.5, AC6, Guardrails, and the sub-agent notes now separate the fc_* **read/write**
  accessor wiring from **reset deletion** explicitly:
  - `fc_check_proposals` are **untouched** by a full story reset (FK-41 §41.3.3); `purge_run`
    does not delete them and does not count them in `purged_rows`.
  - `fc_patterns` are **corrected/recomputed, not deleted** on reset (FK-69 §69.9); the
    recompute half is AG3-082; `purge_run` does not delete/count them either.
  - The r2 wording "`purge_run` und das Reset-Purge zaehlen die neuen Kinds mit" is removed.
    `PurgeResult.purged_rows` keeps its "deleted rows" meaning. A test asserts that, after the
    wiring, a reset leaves `fc_check_proposals` untouched and does not purge `fc_patterns`.

## Anchor / framing fixes
- Removed the phantom anchor "FK-03 §3.4.2 default 0.25" for the Sonar field (not present in
  FK-03 §3.1). FK-41 §41.10 kept as the signal's source, with the field flagged as not-yet-
  specified at concept level either (AG3-103 prose nachzug).
- Replaced "routed to owner / harte Dependency / Warning W1" framing with explicit CP1–CP4
  cross-story action items.

## Dependency change (status.yaml)
- **Removed `depends_on: AG3-081`.** It was added in r2 solely on the false premise that
  AG3-081 delivers the `story_metrics`/`ProjectionFilter` extensions. Since AG3-081 delivers
  none of them, this was a false build-order edge; keeping it would perpetuate the
  contradiction. CP2/CP3 have no in-scope owner today and are tracked as cross-story action
  items, not as a depends_on edge.
- **Retained `depends_on: AG3-028`** (failure_corpus top-surface predecessor) and
  **`depends_on: AG3-070`** (config-owner BC of the `SonarQubeConfig` model that must carry
  CP1) — both true build-order edges. Inline comments in status.yaml record the rationale.

## Cross-story prerequisite list (for the orchestrator / execution-plan / index owner)
These cannot be written in AG3-078's files. AG3-078 needs them but no current story delivers
them; an owner story must be extended (or created):

- **CP1 — `sonarqube.accept_frequency_fc_threshold` on `SonarQubeConfig`.** Owner BC:
  `project-config` (currently AG3-070). AG3-070's current AC do NOT add it (and FK-03 §3.1
  does not specify it). Action: extend AG3-070 to deliver the field (validation + default),
  and align FK-03/FK-41 §41.10 prose (doc-only AG3-103). AG3-078 §2.1.7/AC8 fail-closed
  depends on it.
- **CP2 — `story_metrics` schema extension: `check_ref` + check-outcome columns
  (trigger/override/clean-run).** Owner: `story-closure.PostMergeFinalization`
  (`StoryMetricsRecord`, FK-69 §69.8). No current story extends it (NOT AG3-081, NOT AG3-059).
  Action: assign and extend a story-closure owner story. AG3-078 §2.1.4/AC5 read-consumes it.
- **CP3 — `ProjectionFilter` extension: `check_ref: str | None` + `since_days: int | None`.**
  Owner: `telemetry-and-events` (`ProjectionFilter`, `projection_accessor.py:119-140`). No
  current story extends it (NOT AG3-081). Action: assign and extend a telemetry owner story.
  AG3-078 §2.1.4/AC5 read-consumes it.
- **CP4 — outcome population of `story_metrics` from real verify/closure runs** (which stage
  triggered, override = FP). Owner near `AG3-079` (adversarial/verify path) but NOT in its
  current scope. Action: assign and extend the outcome producer. Needed for the production
  effectiveness path; AG3-078 only delivers the aggregation (tested against seeded rows).

## Files written (only AG3-078 files)
- `stories/AG3-078-failure-corpus-pattern-check-factory/story.md`  (rewritten)
- `stories/AG3-078-failure-corpus-pattern-check-factory/status.yaml`  (depends_on: removed AG3-081)
- `stories/AG3-078-failure-corpus-pattern-check-factory/remediation-r3.md`  (this report)

No other files were modified.
