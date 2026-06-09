OVERALL: CHANGES-REQUESTED

**Per-Dimension Verdict**
- Konzept-Vollstaendigkeit: FAIL
- AC-Schaerfe: FAIL
- Klarheit/Eindeutigkeit: FAIL
- Kontext-Sinnhaftigkeit: FAIL

**Round-1 Disposition**
- Resolved: persisted pattern status is now `accepted`; `review-checks` has `REVISE`; high severity maps to `HIGH|CRITICAL`; F-41-070 is in scope; the existing top.py anchors are correct.
- Not genuinely resolved: favorable checkability is still underspecified; Sonar config dependency is not real; effectiveness source was replaced with a new table that is not concept-authorized.

**Must-Fix ERRORs**
1. ERROR: `FAVORABLE_CHECKABILITY` still is not deterministic. The story names a “category→FP-risk matrix” but does not define the matrix values ([story.md](T:/codebase/claude-agentkit3/stories/AG3-078-failure-corpus-pattern-check-factory/story.md:45), [story.md](T:/codebase/claude-agentkit3/stories/AG3-078-failure-corpus-pattern-check-factory/story.md:79)). Also `symptom_signature` says “Stopword-frei” without a stopword list or a “no stopword removal” rule ([story.md](T:/codebase/claude-agentkit3/stories/AG3-078-failure-corpus-pattern-check-factory/story.md:41)).
   Fix: list the exact `FailureCategory -> FalsePositiveRisk` mapping and define the token normalization fully.

2. ERROR: `fc_check_outcomes` is a new operative read-model/table outside current FK-41/FK-69 authority. FK-41 names only `fc_incidents`, `fc_patterns`, `fc_check_proposals` as canonical FC tables; FK-69 lists the same FC tables and no `fc_check_outcomes`. Code `ProjectionKind` currently documents exactly 7 tables and has no outcome kind ([projection_accessor.py](T:/codebase/claude-agentkit3/src/agentkit/telemetry/projection_accessor.py:56)).
   Fix: either add an explicit concept/schema-owner change for FK-41/FK-69 in scope, or make AG3-078 depend on the story that authorizes and creates that read-model.

3. ERROR: Sonar threshold dependency is not genuinely closed. AG3-078 says `sonarqube.accept_frequency_fc_threshold` comes from AG3-070 ([story.md](T:/codebase/claude-agentkit3/stories/AG3-078-failure-corpus-pattern-check-factory/story.md:69)), but current `SonarQubeConfig` lacks it ([models.py](T:/codebase/claude-agentkit3/src/agentkit/config/models.py:173)), and AG3-070’s AC do not require adding this Sonar field ([AG3-070 story.md](T:/codebase/claude-agentkit3/stories/AG3-070-config-model-schema-catalog/story.md:29)).
   Fix: update AG3-070 to explicitly deliver the field, or move the field addition into a real config-owner story and depend on that.

4. ERROR: Auto-deactivation predicate is ambiguous. The story says “kein `TRUE_POSITIVE`/`NO_FINDING`-Realfund” ([story.md](T:/codebase/claude-agentkit3/stories/AG3-078-failure-corpus-pattern-check-factory/story.md:57)); `NO_FINDING` is not a real finding. FK-41 requires “90 Tage kein realer Fund UND > 3 False Positives”.
   Fix: define exactly `true_positives_90d == 0 AND false_positives_90d > 3`; `no_findings` may be reported but must not count as a real find.

No approval until these are corrected.
