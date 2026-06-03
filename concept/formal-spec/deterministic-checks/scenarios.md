---
id: formal.deterministic-checks.scenarios
title: Deterministic Checks Scenarios
status: active
doc_kind: spec
context: deterministic-checks
spec_kind: scenario-set
version: 1
prose_refs:
  - concept/technical-design/33_deterministische_checks_stage_registry_policy_engine.md
  - concept/technical-design/40_are_integration_anforderungsvollstaendigkeit.md
  - concept/technical-design/41_failure_corpus_pattern_promotion_check_factory.md
---

# Deterministic Checks Scenarios

Diese Traces pruefen die Registry- und Policy-Semantik.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.deterministic-checks.scenarios
schema_version: 1
kind: scenario-set
context: deterministic-checks
scenarios:
  - id: deterministic-checks.scenario.impl-story-happy-path
    start:
      status: deterministic-checks.status.requested
    trace:
      - command: deterministic-checks.command.materialize-stage-plan
      - command: deterministic-checks.command.execute-deterministic-stages
      # APPLICABLE case (sonarqube.available true AND mode not fast, FK-33
      # §33.6.5): the SonarQube-Green-Gate is mandatory for impl/bugfix before
      # policy evaluation (FK-27 §27.6a, FK-33 §33.6.3); the gate is sequenced
      # after the adversarial layer and read as a commit-bound attestation. The
      # NOT_APPLICABLE variants are the available-false-skip and fast-sanity
      # scenarios below.
      - command: deterministic-checks.command.read-attestation
      - command: deterministic-checks.command.run-sonarqube-gate
      - command: deterministic-checks.command.evaluate-policy
    expected_end:
      status: deterministic-checks.status.passed
    requires:
      - deterministic-checks.invariant.stage-plan-derived-from-registry
      - deterministic-checks.invariant.sonarqube-gate-sequenced-after-adversarial
      - deterministic-checks.invariant.sonarqube-green-requires-overall-code-zero-issues
      - deterministic-checks.invariant.sonarqube-gate-read-by-analysis-id
      - deterministic-checks.invariant.blocking-stage-failure-prevents-pass
      - deterministic-checks.invariant.passed-requires-sonarqube-gate-passed
  - id: deterministic-checks.scenario.are-disabled-skips-are-gate
    start:
      status: deterministic-checks.status.requested
    trace:
      - command: deterministic-checks.command.materialize-stage-plan
      - command: deterministic-checks.command.execute-deterministic-stages
      # APPLICABLE case (FK-33 §33.6.5): the SonarQube-Green-Gate stays
      # mandatory for impl/bugfix before policy even when the ARE gate is
      # disabled (FK-27 §27.6a, FK-33 §33.6.3).
      - command: deterministic-checks.command.read-attestation
      - command: deterministic-checks.command.run-sonarqube-gate
      - command: deterministic-checks.command.evaluate-policy
    expected_end:
      status: deterministic-checks.status.passed
    requires:
      - deterministic-checks.invariant.are-gate-required-only-when-enabled
      - deterministic-checks.invariant.sonarqube-gate-sequenced-after-adversarial
  - id: deterministic-checks.scenario.failure-corpus-promotion-enters-via-registry
    start:
      status: deterministic-checks.status.requested
    trace:
      - command: deterministic-checks.command.materialize-stage-plan
      - command: deterministic-checks.command.execute-deterministic-stages
      # APPLICABLE case (FK-33 §33.6.5): the SonarQube-Green-Gate remains
      # mandatory for impl/bugfix before policy (FK-27 §27.6a, FK-33 §33.6.3).
      - command: deterministic-checks.command.read-attestation
      - command: deterministic-checks.command.run-sonarqube-gate
      - command: deterministic-checks.command.evaluate-policy
    expected_end:
      status: deterministic-checks.status.passed
    requires:
      - deterministic-checks.invariant.failure-corpus-promotions-go-through-registry
      - deterministic-checks.invariant.sonarqube-gate-sequenced-after-adversarial
  - id: deterministic-checks.scenario.sonarqube-not-applicable-absent-skips-to-policy
    start:
      status: deterministic-checks.status.requested
    trace:
      - command: deterministic-checks.command.materialize-stage-plan
      - command: deterministic-checks.command.execute-deterministic-stages
      # NOT_APPLICABLE — deliberately absent Sonar (sonarqube.available false,
      # FK-33 §33.6.5): the gate is resolved NOT_APPLICABLE before any
      # attestation read, so no read-attestation/run-sonarqube-gate runs. The
      # plan proceeds straight to policy aggregation via
      # sonarqube_gate_not_applicable WITHOUT a Sonar verdict and WITHOUT
      # fail-closed. Absent is not broken: a configured-but-unreachable Sonar
      # (available true) would stay APPLICABLE and fail closed instead.
      - command: deterministic-checks.command.evaluate-policy
    expected_end:
      status: deterministic-checks.status.passed
    requires:
      - deterministic-checks.invariant.sonarqube-gate-applicability-resolved-before-evaluation
      - deterministic-checks.invariant.sonarqube-absent-skips-not-applicable
      - deterministic-checks.invariant.passed-path-when-sonarqube-not-applicable
      - deterministic-checks.invariant.blocking-stage-failure-prevents-pass
  - id: deterministic-checks.scenario.sonarqube-not-applicable-fast-mode-tests-green-floor
    start:
      status: deterministic-checks.status.requested
    trace:
      - command: deterministic-checks.command.materialize-stage-plan
      - command: deterministic-checks.command.execute-deterministic-stages
      # NOT_APPLICABLE — mode fast (story attribute mode per FK-24 §24.3.4 /
      # project-level mode_lock fast per §24.3.3, FK-33 §33.6.5): QA Layers 2-4
      # including the Policy Engine (Layer 4) are OUT (FK-24 §24.3.4, FK-27
      # §27.6a). Only the Layer-1 tests-green floor runs; the terminal `passed`
      # is reached DIRECTLY from tests_green_floor_passed and does NOT route
      # through evaluate-policy / policy_evaluated or any Sonar stage. A failing
      # floor reuses the existing fail-closed edge stages_executed -> failed.
      - command: deterministic-checks.command.run-tests-green-floor
    expected_end:
      status: deterministic-checks.status.passed
    requires:
      - deterministic-checks.invariant.sonarqube-gate-applicability-resolved-before-evaluation
      - deterministic-checks.invariant.sonarqube-fast-mode-not-applicable
      - deterministic-checks.invariant.fast-mode-terminates-via-tests-green-floor-without-policy
  - id: deterministic-checks.scenario.sonarqube-gate-branch-green-passes
    start:
      status: deterministic-checks.status.stages_executed
    trace:
      - command: deterministic-checks.command.read-attestation
      - command: deterministic-checks.command.run-sonarqube-gate
      - command: deterministic-checks.command.evaluate-policy
    expected_end:
      status: deterministic-checks.status.passed
    requires:
      - deterministic-checks.invariant.sonarqube-gate-sequenced-after-adversarial
      - deterministic-checks.invariant.sonarqube-green-requires-overall-code-zero-issues
      - deterministic-checks.invariant.sonarqube-gate-read-by-analysis-id
  - id: deterministic-checks.scenario.sonarqube-gate-branch-red-fails-into-remediation
    start:
      status: deterministic-checks.status.stages_executed
    trace:
      # Even the red path reads the commit-bound attestation first; the gate
      # then yields a red verdict that fails closed DIRECTLY into the terminal
      # `failed` (attestation_read -> failed), never through the policy
      # aggregator. There is no green-capable shortcut that skips
      # attestation_read.
      - command: deterministic-checks.command.read-attestation
      - command: deterministic-checks.command.run-sonarqube-gate
    expected_end:
      status: deterministic-checks.status.failed
    requires:
      - deterministic-checks.invariant.sonarqube-gate-read-by-analysis-id
      - deterministic-checks.invariant.sonarqube-green-requires-overall-code-zero-issues
      - deterministic-checks.invariant.blocking-stage-failure-prevents-pass
  - id: deterministic-checks.scenario.exception-ledger-zero-match-fails-closed
    start:
      status: deterministic-checks.status.stages_executed
    trace:
      # Fail-closed: a zero-match ledger reconciliation routes directly into
      # the terminal `failed` (stages_executed -> failed) and never reaches
      # the policy aggregator. The aggregator can only emit a PASS from
      # sonarqube_gate_passed (APPLICABLE) or sonarqube_gate_not_applicable
      # (sonarqube.available false); fast mode terminates via the tests-green
      # floor without the aggregator.
      - command: deterministic-checks.command.apply-exception-ledger
    expected_end:
      status: deterministic-checks.status.failed
    requires:
      - deterministic-checks.invariant.ledger-application-single-match-or-fail-closed
      - deterministic-checks.invariant.passed-requires-sonarqube-gate-passed
  - id: deterministic-checks.scenario.exception-ledger-multi-match-fails-closed
    start:
      status: deterministic-checks.status.stages_executed
    trace:
      # Same fail-closed route for a multi-match reconciliation.
      - command: deterministic-checks.command.apply-exception-ledger
    expected_end:
      status: deterministic-checks.status.failed
    requires:
      - deterministic-checks.invariant.ledger-application-single-match-or-fail-closed
      - deterministic-checks.invariant.passed-requires-sonarqube-gate-passed
  - id: deterministic-checks.scenario.main-drift-at-closure-triggers-remediation
    start:
      status: deterministic-checks.status.stages_executed
    trace:
      # Stale/drifted attestation: it is still read first (by analysisId), the
      # gate detects the drift and fails closed DIRECTLY into the terminal
      # `failed` (attestation_read -> failed), never through the policy
      # aggregator.
      - command: deterministic-checks.command.read-attestation
      - command: deterministic-checks.command.run-sonarqube-gate
    expected_end:
      status: deterministic-checks.status.failed
    requires:
      - deterministic-checks.invariant.sonarqube-gate-read-by-analysis-id
      - deterministic-checks.invariant.blocking-stage-failure-prevents-pass
```
<!-- FORMAL-SPEC:END -->
