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
    rule: an accepted-exception ledger entry is applied only when exactly one current Sonar issue matches it; zero or more than one match fails the reconciler closed and requires renewed six-eyes approval
  - id: deterministic-checks.invariant.passed-requires-sonarqube-gate-passed
    scope: outcome
    rule: for Sonar-required flows (impl/bugfix) the terminal passed status is reachable only via sonarqube_gate_passed -> policy_evaluated -> passed; the policy engine may aggregate a PASS only after the gate verdict status sonarqube_gate_passed has been reached, and every fail-closed branch (red gate, stale/unreadable attestation, already-failed prior layer, zero/multi-match ledger reconciliation) routes directly into the terminal failed without traversing policy_evaluated, so no PASS trace can bypass the SonarQube green gate
```
<!-- FORMAL-SPEC:END -->
