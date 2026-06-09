# AG3-078 — Remediation r1 (hostile Codex review)

Scope of this remediation: rewrote `story.md` only (plus one `status.yaml` dependency field).
No production code, tests, or `concept/` files were touched. All resolutions stay strictly
within the AG3-078 cut from `var/concept-gap-analysis/_STORY_INDEX.md:79` (Failure-Corpus
Stufe 2/3) — no scope expansion. Every wrong code anchor was corrected to a verified real
file:line. Identifiers/enum values are English (ARCH-55). The AG3-057 template structure
(sections 1–6) is preserved.

## Must-Fix ERRORs

### 1. Pattern status `confirmed` → `accepted`  (RESOLVED)
- Finding: story demanded `status=confirmed`; FK-41 §41.5.4 prose shows `confirmed`, but the
  code SSOT `core_types/failure_corpus.py:97,103` defines only `PatternStatus.ACCEPTED`.
- Fix: §2.1.2 / AC2 now require the **persisted** status `accepted`; `confirm_pattern` /
  `confirmed_at` / `confirmed_by='human'` are explicitly demoted to action/audit terms, not
  status values. §1 records the real anchor and routes the FK-prose alignment to doc-only
  AG3-103/AG3-104. Guardrail note + sub-agent note reinforce "do not write `confirmed` as
  status".

### 2. `review-checks` adjust/revise path  (RESOLVED)
- Finding: FK-41 §41.6.5 (line 557) requires three human decisions "freigeben, anpassen oder
  verwerfen"; story modeled only `approved`/`rejected`.
- Fix: §2.1.3 / AC4 add a third typed decision `CheckApprovalDecision.REVISE`, modeled per
  FK-41 §41.6.7 as a **new check revision** (old proposal -> `rejected`,
  `rejected_reason="superseded_by_revision"`; a fresh `draft` with a new `check_id`, same
  `pattern_ref`; no implementation story). Explicitly NOT a new `CheckStatus` value — the
  5-value lifecycle is preserved (matches §41.6.7 "neue Check-Revision ... nicht als eigener
  Zwischenstatus"). Persistence/validation rules stated.

### 3. Clustering / high severity / favorable checkability testable  (RESOLVED)
- Finding (AC1): "Symptom-Aehnlichkeit" undefined; "hohe Schwere bei 1" blurred the FK rule
  ("produktionsrelevantem oder sicherheitskritischem Impact", §41.5.1:388); "guenstige
  Checkbarkeit" had no proof path before promotion.
- Fix: §2.1.1 / AC1 now specify:
  - **Deterministic cluster key** `(FailureCategory, symptom_signature)` with a fully
    specified `symptom_signature` (lowercase-ASCII normalize, whitespace collapse, tokenize
    on non-word boundaries, stopword-free, sorted tokens, sha256 hex) + tie-breaker (oldest
    `recorded_at` first). No fuzzy threshold, no LLM.
  - **High severity** mapped to `IncidentSeverity in {HIGH, CRITICAL}` (the English 4-step
    scale at `failure_corpus/types.py:47-50`) = production-relevant/security-critical.
  - **Favorable checkability** = `>=2` incidents AND the category's deterministic check-type
    carries `false_positive_risk == LOW` via a named, tested **category→FP-risk matrix**
    (no LLM, no human review pre-promotion).
  - Rule priority defined (HIGH_SEVERITY > REPETITION > FAVORABLE_CHECKABILITY); each rule
    gets an independent boundary test (incl. severity==HIGH@1 → candidate, MEDIUM@1 → none).

### 4. Effectiveness data source not real  (RESOLVED)
- Finding: `StoryMetricsRecord` (`closure/post_merge_finalization/records.py:11-31`) has no
  `check_ref`/outcome/no-finding fields; `ProjectionFilter`
  (`telemetry/projection_accessor.py:119-140`) has no `check_ref`/`since_days`.
- Fix: §2.1.4 / AC5 replace `story_metrics` (closure-owned, must not be extended by
  failure-corpus) with a **failure-corpus-owned `fc_check_outcomes` read-model** (schema-owner
  failure-corpus, analogous to `fc_patterns`/`fc_check_proposals`) carrying `project_key`,
  `check_ref`, `run_id`, `story_id`, `outcome` (English `CheckOutcome` enum), `recorded_at`.
  `ProjectionFilter` is extended with `check_ref`/`since_days` (telemetry-owned contract) so
  the FK-41 §41.6.7 read path is real. Producer of the outcome rows (real verify/closure runs)
  is explicitly routed out to AG3-079/AG3-081; this story owns schema + read + aggregation and
  tests against directly-seeded rows. Guardrail note states `story_metrics` is not used.

### 5. ProjectionAccessor / repository write path for fc_patterns/fc_check_proposals  (RESOLVED)
- Finding: accessor rejects `FC_PATTERNS`/`FC_CHECK_PROPOSALS` fail-closed as externally owned
  (`projection_accessor.py:99-111,271-277,394-403`); repos expose `save()` not the generic
  write contract (`fc_pattern_repository.py:160`, `fc_check_proposal_repository.py:185`).
- Fix: §2.1.5 / AC6 take **ProjectionAccessor-ownership-wiring explicitly into scope**: move
  the three fc_* kinds (incl. the new `fc_check_outcomes`) from `_EXTERNALLY_OWNED_KINDS` to
  `_ACCESSOR_OWNED_KINDS`, register record types in `_build_kind_to_record_type`, wire
  `write_projection`/`read_projection` onto the existing `save/load/list*` ports via
  `ProjectionRepositories` DI (no facade import, AC#7), enforce `project_key` on reads
  (fail-closed, analogous to FC_INCIDENTS), and count them in `purge_run` (FK-69 §69.9). Noted
  that fc_patterns/fc_check_proposals need no dedicated id-allocator (unlike FC_INCIDENTS), so
  the generic `write_projection` path fits. §1 quotes the accessor comment that names this
  story as the producer story.

### 6. `sonarqube.accept_frequency_fc_threshold` config field  (RESOLVED — routed to owner)
- Finding: story reads the field from config; `SonarQubeConfig` (`config/models.py:171-180`)
  does not define it. FK-03 §3.4.2 specifies it (default `0.25`).
- Fix: §1 records the real gap; §2.1.7 keeps the signal **referencing** (not copying) the
  field; §2.2 routes the field addition to its config-model owner **AG3-070** as a **hard
  `depends_on`** (added to `status.yaml`). FK-03 default confirmation routed to doc-only
  AG3-103. AC8 unchanged in intent but now points at the owned config field. This respects the
  cut: AG3-078 is the failure-corpus story, not the config-model story.

### 7. F-41-070 reference example in scope/AC  (RESOLVED)
- Finding: FK-41 §41.6.2:490 requires a permanently documented invariant-sharpening example
  ("muss ... dokumentiert sein"); story had no scope/AC.
- Fix: §2.1.8 / AC9 add the F-41-070 reference example as a durable artifact (canonical
  step-1 prompt/fixture example, referenced in the prompt template) that a concept gate
  verifies is present (not silently deletable).

## WARNINGs

### W1. Legacy export `checks/CHK-{NNNN}/proposal.json`  (ADDRESSED — kept out, owner clarity)
- Finding: FK-41 §41.6.4:524 also names a file export beside `fc_check_proposals`.
- Resolution: The story keeps Schritt 3 on the typed projection write only (the SSOT path).
  The legacy file export is intentionally not adopted — projection persistence via the
  ProjectionAccessor is the single source of truth (CLAUDE.md "kein operatives JSON-Flickwerk
  ohne Owner"; FILE export would be a second operative truth). The FK-prose reconciliation of
  the legacy export sits with the doc-only concept-nachzug AG3-103 (schema/defaults reality).
  No AC was added because adopting the file export would expand scope and reintroduce a
  v2-style file fan-out; this is a deliberate, stated decision rather than a silent omission.

## NIT

### N1. Ist-Zustand glob missing `__init__.py`  (FIXED)
- §1 glob now lists `__init__.py` (confirmed to exist) alongside the other
  `failure_corpus/*.py` files; the core finding "no cli.py" is retained.

## Files written
- `stories/AG3-078-failure-corpus-pattern-check-factory/story.md`  (rewritten)
- `stories/AG3-078-failure-corpus-pattern-check-factory/status.yaml`  (depends_on: +AG3-070)
- `stories/AG3-078-failure-corpus-pattern-check-factory/remediation-r1.md`  (this report)

No other files were modified.
