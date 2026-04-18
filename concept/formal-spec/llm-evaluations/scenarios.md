---
id: formal.llm-evaluations.scenarios
title: LLM Evaluations Scenarios
status: active
doc_kind: spec
context: llm-evaluations
spec_kind: scenario-set
version: 1
prose_refs:
  - concept/technical-design/34_llm_bewertungen_adversarial_testing_runtime.md
---

# LLM Evaluations Scenarios

Diese Traces pruefen die regulaeren Ausgaenge von Layer 2 und Layer 3.

<!-- FORMAL-SPEC:BEGIN -->
```yaml
object: formal.llm-evaluations.scenarios
schema_version: 1
kind: scenario-set
context: llm-evaluations
scenarios:
  - id: llm-evaluations.scenario.layer2-pass-adversarial-pass
    start:
      status: llm-evaluations.status.pending
    trace:
      - command: llm-evaluations.command.run-layer2-reviews
      - command: llm-evaluations.command.aggregate-layer2-results
      - command: llm-evaluations.command.run-adversarial
    expected_end:
      status: llm-evaluations.status.completed
    requires:
      - llm-evaluations.invariant.layer2_requires_three_verdict_sources
      - llm-evaluations.invariant.adversarial_requires_sparring_and_test_execution
  - id: llm-evaluations.scenario.layer2-blocking-fail
    start:
      status: llm-evaluations.status.pending
    trace:
      - command: llm-evaluations.command.run-layer2-reviews
      - command: llm-evaluations.command.aggregate-layer2-results
    expected_end:
      status: llm-evaluations.status.failed
    requires:
      - llm-evaluations.invariant.layer2_fail_is_blocking
  - id: llm-evaluations.scenario.remediation-round-carries-findings
    start:
      status: llm-evaluations.status.pending
    trace:
      - command: llm-evaluations.command.rerun-layer2-remediation
    expected_end:
      status: llm-evaluations.status.failed
    requires:
      - llm-evaluations.invariant.remediation_round_requires_resolution_tracking
```
<!-- FORMAL-SPEC:END -->
