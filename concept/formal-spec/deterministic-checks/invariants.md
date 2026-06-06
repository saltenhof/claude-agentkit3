---
id: formal.deterministic-checks.invariants
title: Deterministic Checks Invariants
status: active
doc_kind: spec
context: deterministic-checks
spec_kind: invariant-set
version: 1
prose_refs:
  - concept/technical-design/33_deterministische_checks_stage_registry_policy_engine.md
  - concept/technical-design/40_are_integration_anforderungsvollstaendigkeit.md
  - concept/technical-design/41_failure_corpus_pattern_promotion_check_factory.md
---

# Deterministic Checks Invariants

Diese Invarianten definieren den zulaessigen Registry- und
Policy-Prozess.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.deterministic-checks.invariants
schema_version: 1
kind: invariant-set
context: deterministic-checks
invariants:
  - id: deterministic-checks.invariant.stage-plan-derived-from-registry
    scope: process
    rule: stage execution order and applicability must come from the StageRegistry plan, not from ad hoc branching in verify code
  - id: deterministic-checks.invariant.only-applicable-stages-execute
    scope: process
    rule: only stages whose applies_to set contains the current story type may be executed for a given verify gate
  - id: deterministic-checks.invariant.blocking-stage-failure-prevents-pass
    scope: outcome
    rule: a failed blocking stage prevents a PASS outcome from the policy engine
  - id: deterministic-checks.invariant.are-gate-required-only-when-enabled
    scope: process
    rule: the ARE gate stage is mandatory only when the ARE feature is enabled for the project
  - id: deterministic-checks.invariant.failure-corpus-promotions-go-through-registry
    scope: governance
    rule: promoted checks from the Failure Corpus become active only through StageRegistry extension and not through direct verify hardcoding
  - id: deterministic-checks.invariant.sonarqube-gate-sequenced-after-adversarial
    scope: process
    rule: the sonarqube_gate stage is classified as layer 1 deterministic (trust class A, blocking) but the StageExecutionPlan must sequence it after the layer 3 adversarial stage, because every prior remediation changes production code and may introduce new violations
  - id: deterministic-checks.invariant.sonarqube-green-requires-overall-code-zero-issues
    scope: outcome
    rule: the sonarqube_gate is green only when the SonarQube Quality Gate reports OK AND there are zero open non-accepted issues across the whole analyzed overall-code scope, not merely on new code
  - id: deterministic-checks.invariant.sonarqube-gate-read-by-analysis-id
    scope: process
    rule: the gate result is read as a commit-bound attestation by analysisId or ceTaskId and never as a bare projectKey live-read, so a stale green for an outdated commit cannot pass the gate
  - id: deterministic-checks.invariant.ledger-application-single-match-or-fail-closed
    scope: process
    rule: an accepted-exception ledger entry is applied only when exactly one current Sonar issue matches it; zero or more than one match fails the reconciler closed and requires a renewed accept-self-assessment approval (worker plus two goal-oriented LLMs, unanimity; FK-27 27.6b)
  - id: deterministic-checks.invariant.analysis-scope-default-is-baseline-deviation-is-accept-step
    scope: process
    rule: the analysis-scope-hash is decomposed; the project-default scope (sonar.sources plus default exclusions) belongs to world 1 and is checked for baseline equality against the project-expected baseline-hash, while per-scan exclusions beyond the default belong to world 2 and go through the accept-self-assessment step rather than baseline equality
  - id: deterministic-checks.invariant.passed-requires-sonarqube-gate-passed
    scope: outcome
    rule: for APPLICABLE Sonar flows (impl/bugfix with sonarqube.available true and mode not fast) the terminal passed status is reachable only via sonarqube_gate_passed -> policy_evaluated -> passed; the policy engine may aggregate a PASS only after the gate verdict status sonarqube_gate_passed has been reached, and every fail-closed branch (red gate, stale/unreadable attestation, already-failed prior layer, zero/multi-match ledger reconciliation) routes directly into the terminal failed without traversing policy_evaluated, so no PASS trace can bypass the SonarQube green gate
  - id: deterministic-checks.invariant.passed-path-when-sonarqube-not-applicable
    scope: outcome
    rule: when the sonarqube_gate is NOT_APPLICABLE because Sonar is deliberately absent (sonarqube.available false) but mode is not fast, the terminal passed status is reachable without sonarqube_gate_passed via sonarqube_gate_not_applicable -> policy_evaluated -> passed; the Sonar stage is skipped (no Sonar verdict, no fail-closed) but the Policy Engine STILL aggregates over the other layers; this absent-but-non-fast skip must never be conflated with a configured-but-unreachable Sonar, which stays APPLICABLE and fails closed; the mode-fast NOT_APPLICABLE case does NOT use this policy path and is governed separately by fast-mode-terminates-via-tests-green-floor-without-policy
  - id: deterministic-checks.invariant.fast-mode-terminates-via-tests-green-floor-without-policy
    scope: outcome
    rule: under mode fast (story attribute mode per FK-24 24.3.4 / project-level mode_lock fast per 24.3.3) the QA-subflow runs only the Layer-1 tests-green floor; QA Layers 2-4 including the Policy Engine (Layer 4) are OUT per FK-24 24.3.4 and FK-27 27.6a, so the terminal passed status is reached directly via stages_executed -> tests_green_floor_passed -> passed and NEVER through policy_evaluated or any Sonar stage; a failing floor routes into the terminal failed via the existing stages_executed -> failed edge; the closure-side Sanity-Gate (FK-29/FK-35) is a closure concept and is not a QA-subflow state
  - id: deterministic-checks.invariant.sonarqube-gate-applicability-resolved-before-evaluation
    scope: process
    rule: at every one of the three lifecycle gate points the sonarqube_gate applicability is resolved before any green/red evaluation into exactly one of three states; APPLICABLE requires sonarqube.available true AND mode not fast (story attribute mode per FK-24 24.3.4; project-level mode_lock not fast per 24.3.3) AND story_type in implementation or bugfix; NOT_APPLICABLE otherwise; only an APPLICABLE gate is evaluated and may fail closed
  - id: deterministic-checks.invariant.sonarqube-absent-skips-not-applicable
    scope: process
    rule: a deliberately absent Sonar (sonarqube.available false, permitted also for codeproducing projects) makes the gate NOT_APPLICABLE and is skipped without fail-closed, which is strictly distinct from a configured-but-unreachable Sonar (available true, server or branch plugin unreachable, quality gate red, or attestation stale) that stays APPLICABLE and blocks fail-closed; absent is not the same as broken
  - id: deterministic-checks.invariant.sonarqube-fast-mode-not-applicable
    scope: process
    rule: under mode fast (story attribute mode per FK-24 24.3.4; project-level mode_lock fast per 24.3.3) the sonarqube_gate is NOT_APPLICABLE at all three lifecycle gate points; the green-main precondition and integrity-gate dimension 9 are not evaluated and closure uses the sanity gate instead
  - id: deterministic-checks.invariant.sonarqube-reenable-requires-cleanup-green-main
    scope: process
    rule: when a project transitions sonarqube.available false to true or a strict non-fast story starts after fast-mode technical debt accumulated, the existing cleanup remediation worker must establish a green main before the strict story proceeds, after which the green-main precondition applies normally; no new mechanism is introduced
```
<!-- FORMAL-SPEC:END -->
