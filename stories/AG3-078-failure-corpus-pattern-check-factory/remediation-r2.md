# AG3-078 — Remediation r2 (hostile Codex review, round-2)

Scope of this remediation: rewrote `story.md` only (plus one `status.yaml` dependency
field). No production code, tests, or `concept/` files were touched. All resolutions stay
strictly within the AG3-078 cut from `var/concept-gap-analysis/_STORY_INDEX.md:79`
(Failure-Corpus Stufe 2/3) — no scope expansion. Code anchors verified against the real
source. Identifiers/enum values are English (ARCH-55). The AG3-057 template structure
(sections 1–6) is preserved.

The central correction this round: round-1 over-corrected its own finding #4 by inventing
a `fc_check_outcomes` read-model that no FK authorizes. Round-2 ERROR #2 is correct — that
table is a second operative truth without a concept owner. It has been removed and replaced
with the concept-normed source `story_metrics` (FK-41 §41.6.7), with the real code gaps
routed to their owner stories.

## Must-Fix ERRORs (round-2)

### 1. `FAVORABLE_CHECKABILITY` not deterministic; `symptom_signature` "stopword-free" undefined  (RESOLVED)
- Finding: story named a "category→FP-risk matrix" without values; `symptom_signature`
  said "Stopword-frei" with no stopword list / no "no stopword removal" rule.
- Verified concept: FK-41 §41.6.3 normalizes the **category→check-type** matrix in the
  concept; FK-41 §41.5.1 only says "Check mit niedriger False-Positive-Gefahr ableitbar"
  (no per-category FP matrix exists in the concept). So the FP risk per check-type is a
  legitimately story-owned, named constant — but it must be fully tabulated.
- Fix (§2.1.1, AC1):
  - `FAVORABLE_CHECKABILITY` is now defined as `len(incidents) >= 2 AND
    CHECK_TYPE_FALSE_POSITIVE_RISK[check_type_for_category(category)] == LOW`, where
    `check_type_for_category` is the **concept-normed FK-41 §41.6.3 matrix** (the same
    constant reused in derive_check step 2), and `CHECK_TYPE_FALSE_POSITIVE_RISK` is a
    named, tested story constant with explicit values: `CHANGED_FILE_POLICY`/
    `SENSITIVE_PATH_GUARD`/`FORBIDDEN_DEPENDENCY` = `LOW`; `ARTIFACT_COMPLETENESS`/
    `TEST_OBLIGATION` = `MEDIUM`; `FIXTURE_REPLAY` = `HIGH`. The full table is written into
    the story and pinned by a test.
  - `symptom_signature` normalization fully specified as a 6-step deterministic pipeline
    (NFKC + ASCII-fold → lowercase → tokenize on `[^a-z0-9]+` → drop empty tokens, **no
    stopword removal, no stopword list exists** → sort tokens, join → sha256, first 16 hex
    chars). The vague "Stopword-frei" is replaced with an explicit "no stopword removal"
    rule + rationale, pinned by a test.

### 2. `fc_check_outcomes` is a read-model outside FK-41/FK-69 authority  (RESOLVED — removed)
- Finding: FK-41/FK-69 name only `fc_incidents`/`fc_patterns`/`fc_check_proposals`;
  `ProjectionKind` (`projection_accessor.py:64-70`) documents exactly 7 tables with no
  outcome kind.
- Verified concept: FK-69 §69.3 lists exactly those tables; FK-41 §41.6.7 explicitly names
  `story_metrics` (Schema-Owner story-closure) as the effectiveness data source, read via
  `read_projection(table="story_metrics", filters={"check_ref": ...}, since_days=...)`.
- Fix (§1 finding 4/5, §2.1.4, §2.1.5, AC5, AC6, Guardrails): the invented
  `fc_check_outcomes` table is removed entirely. `report_effectiveness` reads the canonical
  `story_metrics` source via `Telemetry.read_projection`. `ProjectionKind` stays at 7
  tables; only the two concept-authorized kinds `FC_PATTERNS`/`FC_CHECK_PROPOSALS` are
  wired into the accessor (no new kind). AC6 explicitly asserts no new `ProjectionKind`
  value is introduced.

### 3. Sonar threshold dependency not genuinely closed  (RESOLVED — routed to owner as AC-extension)
- Finding: AG3-078 reads `sonarqube.accept_frequency_fc_threshold` from config, but
  `SonarQubeConfig` (`config/models.py:171-180`) lacks it and AG3-070's AC do not require
  adding it.
- Verified: AG3-070 AC4 enumerates `orchestrator_guard`/`policy`/`vectordb`/`telemetry`/
  `governance` stanzas only — the Sonar field is not in its delivered set. AG3-070 is the
  config-model owner per `_STORY_INDEX.md:66`. I may only edit AG3-078 files, so the field
  add cannot be written into AG3-070 here.
- Fix (§2.2 / Warning W1, AC8, sub-agent note): kept the hard `depends_on AG3-070` and made
  the story state explicitly that AG3-070 must extend its AC to deliver
  `sonarqube.accept_frequency_fc_threshold` before the signal can read it (a Warning routed
  to the owner per SEVERITY-SEMANTIK — actively mirrored, not silently dropped). AG3-078
  references the field, never second-copies it. FK-03 default confirmation stays doc-only
  AG3-103. (Cross-story action item below for the AG3-070 owner.)

### 4. Auto-deactivation predicate ambiguous  (RESOLVED)
- Finding: r1 wrote "kein `TRUE_POSITIVE`/`NO_FINDING`-Realfund"; `no_findings` is not a
  real find. FK-41 requires "90 Tage kein realer Fund UND > 3 False Positives".
- Verified concept: FK-41 §41.6.7 table — "90 Tage kein realer Fund UND > 3 False
  Positives"; FK-93 §93.11 — period 90d, FP threshold "> 3 (mehr als 3)".
- Fix (§2.1.4, AC5, sub-agent note): auto-deactivation is now exactly
  `true_positives_90d == 0 AND false_positives_90d > 3` → `RETIRED`. `no_findings` is
  reported but explicitly never counts as a real find and never enters the predicate.
  `risk_level == CRITICAL` remains exempt. Boundary tests specified: `tp==0,fp==3` not
  deactivated; `tp==0,fp>3` deactivated; `tp>0,fp>3` not deactivated.

## WARNINGs

### W1. AG3-070 AC must explicitly deliver `sonarqube.accept_frequency_fc_threshold`  (ROUTED to owner)
- This is the WARNING half of ERROR #3. Per SEVERITY-SEMANTIK a Warning must be actively
  mirrored to the owner, not left lying. Routed to AG3-070 (config-model owner) as a
  required AC extension; recorded in §2.2 of the story and in the cross-story action item
  below. depends_on AG3-070 retained.

## Dependency change (status.yaml)
- Added hard `depends_on: AG3-081`. Rationale: the effectiveness read path needs the
  `story_metrics` schema extension (`check_ref` + outcome columns) and the `ProjectionFilter`
  extension (`check_ref`/`since_days`); both are owned by story-closure / telemetry-and-events
  and are produced/wired in AG3-081 (Read-Model/Event-Vollausbau, FK-69 §69.3/§69.9/§69.14).
  AG3-078 read-consumes only. (AG3-028 and AG3-070 retained.)

## Cross-story action items (cannot be written in AG3-078 files; for the owners)
- **AG3-070 (config-model owner):** extend AC to deliver
  `sonarqube.accept_frequency_fc_threshold` on `SonarQubeConfig` (FK-03 §3.4.2 default
  `0.25`). AG3-078 §2.1.7 depends on it.
- **AG3-081 (read-model/event owner):** extend `story_metrics`/`StoryMetricsRecord` with
  `check_ref` + check-outcome columns and `ProjectionFilter` with `check_ref`/`since_days`.
  AG3-079 produces the outcome rows. AG3-078 §2.1.4 read-consumes both.

## Files written
- `stories/AG3-078-failure-corpus-pattern-check-factory/story.md`  (rewritten)
- `stories/AG3-078-failure-corpus-pattern-check-factory/status.yaml`  (depends_on: +AG3-081)
- `stories/AG3-078-failure-corpus-pattern-check-factory/remediation-r2.md`  (this report)

No other files were modified.
