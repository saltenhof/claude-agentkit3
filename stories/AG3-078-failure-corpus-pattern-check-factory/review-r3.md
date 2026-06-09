OVERALL CHANGES-REQUESTED

**Per-Dimension Verdict**
- Konzept-Vollstaendigkeit: FAIL. Effectiveness and Sonar prerequisites are still routed to stories that do not deliver them.
- AC-Schaerfe: FAIL. AC5/AC8 depend on unavailable fields; AC6 conflicts with reset semantics.
- Klarheit/Eindeutigkeit: FAIL. The story states concrete owners, but the referenced real stories contradict those ownership claims.
- Kontext-Sinnhaftigkeit: FAIL. The replacement for `fc_check_outcomes` is conceptually right, but the dependency cut is not executable.

**Round-2 ERROR Disposition**
- R2 #1 resolved: `FAVORABLE_CHECKABILITY` now has an explicit FP-risk table and `symptom_signature` says no stopword removal.
- R2 #2 partly resolved: `fc_check_outcomes` is removed, but its replacement path is falsely routed.
- R2 #3 not resolved: Sonar config field still has no real delivering owner.
- R2 #4 resolved: auto-deactivation is now `true_positives_90d == 0 AND false_positives_90d > 3`; `no_findings` is excluded.

**Must-Fix ERRORs**
1. ERROR: `story_metrics`/`ProjectionFilter` prerequisites are routed to AG3-081/AG3-079, but those stories do not deliver them.
Evidence: AG3-078 claims AG3-081 delivers `story_metrics.check_ref`, outcome columns, and `ProjectionFilter.check_ref/since_days` ([story.md](T:/codebase/claude-agentkit3/stories/AG3-078-failure-corpus-pattern-check-factory/story.md:75)). Current AG3-081 only covers events, telemetry evidence, counters, and reset-purge delta; targeted search found no `check_ref`, `since_days`, `ProjectionFilter`, or outcome schema scope. AG3-079 also has no `story_metrics`/`check_ref` outcome production. Real code confirms `StoryMetricsRecord` lacks these fields and `ProjectionFilter` lacks `check_ref/since_days`.
Fix: add/update a real owner story to deliver the `story_metrics` schema fields, read filters, repository/read support, and outcome emission, then make AG3-078 depend on that actual story. Do not claim AG3-081/AG3-079 deliver it unless their stories are updated.

2. ERROR: Sonar threshold dependency is still not genuinely closed.
Evidence: AG3-078 says AG3-070 must extend its AC for `sonarqube.accept_frequency_fc_threshold` ([story.md](T:/codebase/claude-agentkit3/stories/AG3-078-failure-corpus-pattern-check-factory/story.md:90)), but current AG3-070 AC4 lists only `orchestrator_guard`/`policy`/`vectordb`/`telemetry`/`governance`, not Sonar. Real `SonarQubeConfig` still lacks the field.
Fix: update AG3-070 to explicitly deliver `accept_frequency_fc_threshold` with validation/default/tests, or create a separate config-owner story and add it to AG3-078 `depends_on`. A warning inside AG3-078 is not enough because AC8 needs the field.

3. ERROR: `purge_run` wording conflicts with FK-69/FK-41 reset semantics.
Evidence: AG3-078 says `purge_run` counts `FC_PATTERNS`/`FC_CHECK_PROPOSALS` after wiring ([story.md](T:/codebase/claude-agentkit3/stories/AG3-078-failure-corpus-pattern-check-factory/story.md:80), [story.md](T:/codebase/claude-agentkit3/stories/AG3-078-failure-corpus-pattern-check-factory/story.md:106)). FK-69 requires `fc_patterns` be corrected/recomputed and `fc_check_proposals` remain untouched; FK-41 states full story reset does not touch `fc_check_proposals`. Current `PurgeResult.purged_rows` means deleted rows.
Fix: keep read/write wiring separate from reset deletion. `purge_run` must not delete or “purged_rows”-count `fc_check_proposals`; pattern recompute/correction belongs to the reset/recompute owner path.
