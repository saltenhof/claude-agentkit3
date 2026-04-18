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
      - command: deterministic-checks.command.evaluate-policy
    expected_end:
      status: deterministic-checks.status.passed
    requires:
      - deterministic-checks.invariant.stage-plan-derived-from-registry
      - deterministic-checks.invariant.blocking-stage-failure-prevents-pass
  - id: deterministic-checks.scenario.are-disabled-skips-are-gate
    start:
      status: deterministic-checks.status.requested
    trace:
      - command: deterministic-checks.command.materialize-stage-plan
      - command: deterministic-checks.command.execute-deterministic-stages
      - command: deterministic-checks.command.evaluate-policy
    expected_end:
      status: deterministic-checks.status.passed
    requires:
      - deterministic-checks.invariant.are-gate-required-only-when-enabled
  - id: deterministic-checks.scenario.failure-corpus-promotion-enters-via-registry
    start:
      status: deterministic-checks.status.requested
    trace:
      - command: deterministic-checks.command.materialize-stage-plan
      - command: deterministic-checks.command.execute-deterministic-stages
      - command: deterministic-checks.command.evaluate-policy
    expected_end:
      status: deterministic-checks.status.passed
    requires:
      - deterministic-checks.invariant.failure-corpus-promotions-go-through-registry
```
<!-- FORMAL-SPEC:END -->
